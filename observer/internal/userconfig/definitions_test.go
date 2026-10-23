package userconfig

import (
	"errors"
	"fmt"
	"os/exec"
	"reflect"
	"strings"
	"testing"
	"unicode"
)

func ptr(n int) *int { return &n }

func upper(s string) string {
	r := []rune(s)
	r[0] = unicode.ToUpper(r[0])
	return string(r)
}

const v1Description = "Sends anonymous usage counts about Splunk Observability Studio itself to Splunk. Turning this off does not change what Splunk Observability Studio collects from your agents or shows you locally."

func assertV1Definitions(t *testing.T, defs []Definition) {
	t.Helper()
	if len(defs) != 1 {
		t.Fatalf("got %d definitions, want 1", len(defs))
	}
	d := defs[0]
	want := Definition{
		Path:        "telemetry.enabled",
		Section:     "telemetry",
		Type:        TypeBool,
		Label:       "Send anonymous usage data",
		Description: v1Description,
		Default:     true,
		FailSafe:    false,
		Apply:       ApplyLive,
	}
	if !reflect.DeepEqual(d, want) {
		t.Fatalf("definition = %#v, want %#v", d, want)
	}
}

func TestTableV1(t *testing.T) {
	defs := Definitions()
	assertV1Definitions(t, defs)
	for _, d := range defs {
		if d.Path == "version" || strings.Contains(d.Path, "port") {
			t.Errorf("unexpected definition %q", d.Path)
		}
	}
}

func TestTableSelfTest(t *testing.T) {
	defs := table()
	secs := sections()
	for _, d := range defs {
		v := d.view()
		if err := d.checkAny(v.Default); err != nil {
			t.Errorf("%s: Default fails check: %v", d.path(), err)
		}
		if err := d.checkAny(v.FailSafe); err != nil {
			t.Errorf("%s: FailSafe fails check: %v", d.path(), err)
		}
	}
	for _, s := range secs {
		if len(defsIn(s, defs)) == 0 {
			t.Errorf("section %q has no definitions", s.name)
		}
	}
	seen := map[string]bool{}
	for _, d := range defs {
		if seen[d.path()] {
			t.Errorf("duplicate path %q", d.path())
		}
		seen[d.path()] = true
	}

	settingsType := reflect.TypeOf(Settings{})
	if settingsType.NumField() != len(secs) {
		t.Fatalf("Settings has %d fields, want one per section (%d)", settingsType.NumField(), len(secs))
	}
	var s Settings
	sv := reflect.ValueOf(&s).Elem()
	kinds := map[Type]reflect.Kind{TypeBool: reflect.Bool, TypeInt: reflect.Int, TypeString: reflect.String}
	for _, sec := range secs {
		f, ok := settingsType.FieldByName(upper(sec.name))
		if !ok {
			t.Fatalf("Settings has no field %q", upper(sec.name))
		}
		if f.Type.Name() != upper(sec.name)+"Settings" {
			t.Errorf("Settings.%s has type %s, want %sSettings", f.Name, f.Type.Name(), upper(sec.name))
		}
		in := defsIn(sec, defs)
		if f.Type.NumField() != len(in) {
			t.Errorf("%s has %d fields, want %d", f.Type.Name(), f.Type.NumField(), len(in))
		}
		for _, d := range in {
			name := upper(defName(d))
			df, ok := f.Type.FieldByName(name)
			if !ok {
				t.Errorf("%s has no field %q for %s", f.Type.Name(), name, d.path())
				continue
			}
			if df.Type.Kind() != kinds[d.typ()] {
				t.Errorf("%s.%s has kind %s, want %s", f.Type.Name(), name, df.Type.Kind(), kinds[d.typ()])
			}
			wantAddr := sv.FieldByName(f.Name).FieldByName(name).Addr().Pointer()
			gotAddr := reflect.ValueOf(fieldPointer(d, &s)).Pointer()
			if gotAddr != wantAddr {
				t.Errorf("%s: Field does not return the address of %s.%s", d.path(), f.Name, name)
			}
		}
	}

	if !DefaultSettings().Telemetry.Enabled {
		t.Error("DefaultSettings().Telemetry.Enabled = false, want true")
	}
	if FailSafeSettings().Telemetry.Enabled {
		t.Error("FailSafeSettings().Telemetry.Enabled = true, want false")
	}
}

func fieldPointer(d def, s *Settings) any {
	switch d := d.(type) {
	case *definition[bool]:
		return d.spec.Field(s)
	case *definition[int]:
		return d.spec.Field(s)
	case *definition[string]:
		return d.spec.Field(s)
	}
	panic(fmt.Sprintf("unexpected definition type %T", d))
}

func TestCheckConstraints(t *testing.T) {
	sec := newSection("t")
	n := newDefinition(sec, "n", defSpec[int]{Label: "n", Description: "n.", Apply: ApplyLive, Min: ptr(1), Max: ptr(10)})
	e := newDefinition(sec, "e", defSpec[int]{Label: "e", Description: "e.", Apply: ApplyLive, Enum: []int{1, 2, 4}})
	s := newDefinition(sec, "s", defSpec[string]{Label: "s", Description: "s.", Apply: ApplyLive, Enum: []string{"low", "high"}})
	v := newDefinition(sec, "v", defSpec[string]{Label: "v", Description: "v.", Apply: ApplyLive, Validate: func(s string) error {
		if s == "" {
			return errors.New("must not be empty")
		}
		return nil
	}})
	b := newDefinition(sec, "b", defSpec[bool]{Label: "b", Description: "b.", Apply: ApplyLive})

	cases := []struct {
		name string
		err  error
		want string
	}{
		{"n=1", n.check(1), ""},
		{"n=10", n.check(10), ""},
		{"n=0", n.check(0), "userconfig: invalid value: t.n: 0 is less than 1"},
		{"n=11", n.check(11), "userconfig: invalid value: t.n: 11 is greater than 10"},
		{"e=3", e.check(3), "userconfig: invalid value: t.e: 3 is not one of 1, 2, 4"},
		{"s=mid", s.check("mid"), `userconfig: invalid value: t.s: "mid" is not one of "low", "high"`},
		{"v=empty", v.check(""), "userconfig: invalid value: t.v: must not be empty"},
		{"v=x", v.check("x"), ""},
		{"b=true", b.check(true), ""},
		{"b=false", b.check(false), ""},
	}
	for _, tc := range cases {
		if tc.want == "" {
			if tc.err != nil {
				t.Errorf("%s: got %v, want nil", tc.name, tc.err)
			}
			continue
		}
		if tc.err == nil {
			t.Errorf("%s: got nil, want %q", tc.name, tc.want)
			continue
		}
		if tc.err.Error() != tc.want {
			t.Errorf("%s: got %q, want %q", tc.name, tc.err.Error(), tc.want)
		}
		if !errors.Is(tc.err, ErrInvalidValue) || errors.Is(tc.err, ErrUnknownKey) {
			t.Errorf("%s: wrong sentinel for %v", tc.name, tc.err)
		}
		var ive *invalidValueError
		if !errors.As(tc.err, &ive) {
			t.Errorf("%s: not an *invalidValueError", tc.name)
			continue
		}
		if want := tc.want[strings.Index(tc.want, ive.path+": ")+len(ive.path)+2:]; ive.reason != want {
			t.Errorf("%s: reason %q, want %q", tc.name, ive.reason, want)
		}
	}
}

func TestCheckOrder(t *testing.T) {
	calls := 0
	o := newDefinition(newSection("t"), "o", defSpec[int]{
		Label: "o", Description: "o.", Apply: ApplyLive,
		Enum: []int{5, 50}, Max: ptr(20),
		Validate: func(int) error { calls++; return nil },
	})
	if err := o.check(30); err == nil || !strings.HasSuffix(err.Error(), "30 is not one of 5, 50") {
		t.Errorf("check(30) = %v, want the enum reason", err)
	}
	if err := o.check(50); err == nil || !strings.HasSuffix(err.Error(), "50 is greater than 20") {
		t.Errorf("check(50) = %v, want the max reason", err)
	}
	if calls != 0 {
		t.Errorf("validator called %d times after failing checks, want 0", calls)
	}
	if err := o.check(5); err != nil {
		t.Errorf("check(5) = %v, want nil", err)
	}
	if calls != 1 {
		t.Errorf("validator called %d times, want 1", calls)
	}
}

func TestCheckAnyType(t *testing.T) {
	d := table()[0]
	for _, v := range []any{"false", 1, nil} {
		err := d.checkAny(v)
		if err == nil || err.Error() != "userconfig: invalid value: telemetry.enabled: has the wrong type" {
			t.Errorf("checkAny(%#v) = %v", v, err)
		}
	}
	if err := d.checkAny(true); err != nil {
		t.Errorf("checkAny(true) = %v", err)
	}
}

func mustPanic(t *testing.T, contains string, f func()) {
	t.Helper()
	defer func() {
		t.Helper()
		r := recover()
		if r == nil {
			t.Errorf("no panic, want one naming %q", contains)
			return
		}
		if !strings.Contains(fmt.Sprint(r), contains) {
			t.Errorf("panic %q does not name %q", r, contains)
		}
	}()
	f()
}

func TestDeclarationPanics(t *testing.T) {
	nTable, nSections := len(table()), len(sections())
	for _, name := range []string{"Telemetry", "", "a.b"} {
		mustPanic(t, fmt.Sprintf("%q", name), func() { newSection(name) })
	}
	sec := newSection("t")
	ok := defSpec[bool]{Label: "x", Description: "x.", Apply: ApplyLive}
	mustPanic(t, "t.9x", func() { newDefinition(sec, "9x", ok) })
	mustPanic(t, "t.x", func() { newDefinition(sec, "x", defSpec[bool]{Description: "x.", Apply: ApplyLive}) })
	mustPanic(t, "t.x", func() { newDefinition(sec, "x", defSpec[bool]{Label: "a\nb", Description: "x.", Apply: ApplyLive}) })
	mustPanic(t, "t.x", func() { newDefinition(sec, "x", defSpec[bool]{Label: "x", Apply: ApplyLive}) })
	mustPanic(t, "t.x", func() { newDefinition(sec, "x", defSpec[bool]{Label: "x", Description: "x."}) })
	mustPanic(t, "t.x", func() {
		newDefinition(sec, "x", defSpec[bool]{Label: "x", Description: "x.", Apply: ApplyLive, Enum: []bool{true}})
	})
	mustPanic(t, "t.x", func() {
		newDefinition(sec, "x", defSpec[string]{Label: "x", Description: "x.", Apply: ApplyLive, Min: ptr(1)})
	})
	mustPanic(t, "t.x", func() {
		newDefinition(sec, "x", defSpec[int]{Label: "x", Description: "x.", Apply: ApplyLive, Min: ptr(5), Max: ptr(1)})
	})
	mustPanic(t, "t.x", func() {
		newDefinition(sec, "x", defSpec[int]{Label: "x", Description: "x.", Apply: ApplyLive, Enum: []int{1, 1}})
	})
	mustPanic(t, ".x", func() { newDefinition(Section{}, "x", ok) })

	field := func(s *Settings) *bool { return &s.Telemetry.Enabled }
	mustPanic(t, "telemetry.x", func() { define(SectionTelemetry, "x", ok) })
	withField := ok
	withField.Field = field
	mustPanic(t, "t.x", func() { define(newSection("t"), "x", withField) })
	mustPanic(t, "telemetry.enabled", func() { define(SectionTelemetry, "enabled", withField) })

	if len(table()) != nTable || len(sections()) != nSections {
		t.Errorf("table changed: %d/%d definitions, %d/%d sections", len(table()), nTable, len(sections()), nSections)
	}
}

func TestDefinitionsView(t *testing.T) {
	d := Definitions()
	d[0].Label = "x"
	d[0].Default = false
	assertV1Definitions(t, Definitions())

	m := newDefinition(newSection("t"), "m", defSpec[int]{
		Label: "m", Description: "m.", Apply: ApplyLive, Min: ptr(3), Enum: []int{3, 4},
	})
	a := m.view()
	*a.Min = 99
	a.Enum[0] = 99
	b := m.view()
	if *b.Min != 3 || b.Enum[0] != 3 {
		t.Errorf("view not fresh: Min=%d Enum[0]=%v", *b.Min, b.Enum[0])
	}
	if err := m.check(3); err != nil {
		t.Errorf("check(3) = %v", err)
	}
}

func TestSelectorPaths(t *testing.T) {
	var _ Selector = TelemetryEnabled
	var _ Selector = SectionTelemetry
	if TelemetryEnabled.Path() != "telemetry.enabled" || TelemetryEnabled.selectorPath() != "telemetry.enabled" {
		t.Errorf("TelemetryEnabled path = %q / %q", TelemetryEnabled.Path(), TelemetryEnabled.selectorPath())
	}
	if SectionTelemetry.Path() != "telemetry" || SectionTelemetry.selectorPath() != "telemetry" {
		t.Errorf("SectionTelemetry path = %q / %q", SectionTelemetry.Path(), SectionTelemetry.selectorPath())
	}
	if (Key[bool]{}).Path() != "" || (Section{}).Path() != "" {
		t.Error("zero selector paths are not empty")
	}
}

func TestChangedPaths(t *testing.T) {
	if got := changedPaths(DefaultSettings(), DefaultSettings()); len(got) != 0 {
		t.Errorf("changedPaths(equal) = %v", got)
	}
	if got := changedPaths(DefaultSettings(), FailSafeSettings()); !reflect.DeepEqual(got, []string{"telemetry.enabled"}) {
		t.Errorf("changedPaths = %v", got)
	}
}

func TestPutReplaces(t *testing.T) {
	var c Changes
	if c.Len() != 0 || len(c.list()) != 0 {
		t.Fatal("zero Changes is not empty")
	}
	Put(&c, TelemetryEnabled, true)
	Put(&c, Key[bool]{}, true)
	Put(&c, TelemetryEnabled, false)
	if c.Len() != 2 {
		t.Fatalf("Len() = %d, want 2", c.Len())
	}
	l := c.list()
	if changePath(l[0].d) != "telemetry.enabled" || changePath(l[1].d) != "" {
		t.Errorf("paths = %q, %q", changePath(l[0].d), changePath(l[1].d))
	}
	if l[0].v != false || l[1].v != true {
		t.Errorf("values = %v, %v", l[0].v, l[1].v)
	}
	if l[1].d != nil {
		t.Errorf("zero Key entry has d = %#v, want the nil interface", l[1].d)
	}

	c2 := c
	Put(&c2, TelemetryEnabled, true)
	if c.list()[0].v != false || c2.list()[0].v != true {
		t.Error("Put on a copy changed the original")
	}

	c.list()[0].v = true
	if c.list()[0].v != false {
		t.Error("mutating list() changed the set")
	}
}

func TestDefinitionsBuildAlone(t *testing.T) {
	files := []string{"definitions.go", "render.go", "codec.go"}
	assertBuildsAlone(t, files, []string{"go.yaml.in/yaml/v3", "gopkg.in/yaml.v3", "os", "io/fs", "log", "github.com/fsnotify/fsnotify"})
}

func assertBuildsAlone(t *testing.T, files []string, banned []string) {
	t.Helper()
	goBin, err := exec.LookPath("go")
	if err != nil {
		t.Skip("go tool not on PATH")
	}
	if out, err := exec.Command(goBin, append([]string{"build"}, files...)...).CombinedOutput(); err != nil {
		t.Fatalf("go build %v: %v\n%s", files, err, out)
	}
	out, err := exec.Command(goBin, append([]string{"list", "-f", "{{.Imports}}"}, files...)...).Output()
	if err != nil {
		t.Fatalf("go list: %v", err)
	}
	imports := strings.Fields(strings.Trim(strings.TrimSpace(string(out)), "[]"))
	for _, imp := range imports {
		for _, b := range banned {
			if imp == b {
				t.Errorf("%v import %s", files, imp)
			}
		}
		if imp == "net" || strings.HasPrefix(imp, "net/") {
			t.Errorf("%v import %s", files, imp)
		}
	}
}
