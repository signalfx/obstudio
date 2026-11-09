package userconfig

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"os"
	"reflect"
	"strings"
	"testing"
)

var update = flag.Bool("update", false, "rewrite golden files")

func assertGolden(t *testing.T, path string, got []byte) {
	t.Helper()
	if *update {
		if err := os.WriteFile(path, got, 0o644); err != nil {
			t.Fatal(err)
		}
		return
	}
	want, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v (regenerate: go test ./internal/userconfig -update)", path, err)
	}
	if !bytes.Equal(got, want) {
		t.Errorf("%s is stale; regenerate: go test ./internal/userconfig -update\n--- got ---\n%s\n--- want ---\n%s", path, got, want)
	}
}

const v1DefinitionsDoc = `{
  "type": "object",
  "properties": {
    "telemetry": {
      "type": "object",
      "title": "` + v1SectionTitle + `",
      "properties": {
        "enabled": {
          "type": "boolean",
          "title": "` + v1Title + `",
          "description": "` + v1Description + `",
          "default": true,
          "x-obstudio-failSafe": false,
          "x-obstudio-apply": "live"
        }
      }
    }
  }
}
`

func TestDefinitionsDocGolden(t *testing.T) {
	got := DefinitionsDocument()
	assertGolden(t, "testdata/definitions.golden.json", got)
	if string(got) != v1DefinitionsDoc {
		t.Errorf("DefinitionsDocument() differs from the v1 reference:\n%s", got)
	}
}

func TestDefinitionsDocShape(t *testing.T) {
	doc := DefinitionsDocument()
	var root map[string]any
	if err := json.Unmarshal(doc, &root); err != nil {
		t.Fatal(err)
	}
	keywords := map[string]bool{
		"type": true, "properties": true, "title": true, "description": true, "default": true,
		"enum": true, "minimum": true, "maximum": true, "x-obstudio-failSafe": true, "x-obstudio-apply": true,
	}
	var walk func(v any, underProperties bool)
	walk = func(v any, underProperties bool) {
		switch v := v.(type) {
		case map[string]any:
			for k, child := range v {
				if !underProperties && !keywords[k] {
					t.Errorf("unexpected member %q", k)
				}
				walk(child, !underProperties && k == "properties")
			}
		case []any:
			for _, child := range v {
				walk(child, false)
			}
		}
	}
	walk(root, false)

	assertDocMatchesDefinitions(t, sections(), table())
	if _, ok := root["title"]; ok {
		t.Error("root has a title")
	}
	if _, ok := root["description"]; ok {
		t.Error("root has a description")
	}
	if bytes.Contains(doc, []byte(".obstudio")) || bytes.Contains(doc, []byte("config.yaml")) {
		t.Error("document names a filesystem path")
	}
	if doc[len(doc)-1] != '\n' || doc[len(doc)-2] == '\n' {
		t.Error("document does not end with exactly one newline")
	}
}

// assertDocMatchesDefinitions renders the definitions document for secs and
// defs and checks every entry against its definition. Default and failSafe
// go through JSON first, so an int compares with the float64 it decodes to.
func assertDocMatchesDefinitions(t *testing.T, secs []Section, defs []def) {
	t.Helper()
	var root map[string]any
	if err := json.Unmarshal(renderDefinitionsDocument(secs, defs), &root); err != nil {
		t.Fatal(err)
	}
	asJSON := func(v any) any {
		b, err := json.Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		var out any
		if err := json.Unmarshal(b, &out); err != nil {
			t.Fatal(err)
		}
		return out
	}
	props := root["properties"].(map[string]any)
	for _, dd := range defs {
		d := dd.view()
		sec := props[d.Section].(map[string]any)["properties"].(map[string]any)
		entry := sec[strings.TrimPrefix(d.Path, d.Section+".")].(map[string]any)
		if entry["title"] != d.Title || entry["description"] != d.Description ||
			!reflect.DeepEqual(entry["default"], asJSON(d.Default)) ||
			!reflect.DeepEqual(entry["x-obstudio-failSafe"], asJSON(d.FailSafe)) ||
			entry["x-obstudio-apply"] != string(d.Apply) {
			t.Errorf("%s: document entry %v does not match the definition", d.Path, entry)
		}
	}
	for _, s := range secs {
		sec := props[s.Path()].(map[string]any)
		if sec["title"] != s.title() {
			t.Errorf("section %s title = %v, want %q", s.Path(), sec["title"], s.title())
		}
		if desc, ok := sec["description"]; s.description() == "" && ok || s.description() != "" && desc != s.description() {
			t.Errorf("section %s description = %v, want %q", s.Path(), desc, s.description())
		}
	}
}

// The real table has only a bool, so the int and string paths of
// assertDocMatchesDefinitions run here on synthetic definitions.
func TestDocMatchesDefinitionsAllTypes(t *testing.T) {
	sec := newSection("t", sectionSpec{Title: "Tee"})
	n := newDefinition(sec, "n", defSpec[int]{
		Title: "N", Description: "N value.", Default: 5, FailSafe: 1,
		Min: ptr(1), Max: ptr(10), Enum: []int{1, 5, 10}, Apply: ApplyRestart,
	})
	v := newDefinition(sec, "v", defSpec[string]{
		Title: "V", Description: "V value.", Default: "a<b", FailSafe: "x", Apply: ApplyLive,
	})
	usec := newSection("u", sectionSpec{Title: "You", Description: "About u."})
	c := newDefinition(usec, "c", defSpec[bool]{Title: "C", Description: "C value.", Default: true, Apply: ApplyLive})
	assertDocMatchesDefinitions(t, []Section{sec, usec}, []def{n, v, c})
}

func TestRenderOptionalFields(t *testing.T) {
	sec := newSection("t", sectionSpec{Title: "Tee"})
	n := newDefinition(sec, "n", defSpec[int]{
		Title: "N", Description: "N value.", Default: 5, FailSafe: 1,
		Min: ptr(1), Max: ptr(10), Enum: []int{1, 5, 10}, Apply: ApplyRestart,
	})
	v := newDefinition(sec, "v", defSpec[string]{
		Title: "V", Description: "V value.", Default: "a<b", FailSafe: "a<b",
		Validate: func(string) error { return errors.New("never") }, Apply: ApplyLive,
	})
	usec := newSection("u", sectionSpec{Title: "You", Description: "About u."})
	c := newDefinition(usec, "c", defSpec[bool]{Title: "C", Description: "C value.", Apply: ApplyLive})
	secs, defs := []Section{sec, usec}, []def{n, v, c}

	js := string(renderDefinitionsDocument(secs, defs))
	var root struct {
		Properties map[string]struct {
			Title       string
			Description *string
			Properties  map[string]map[string]any
		}
	}
	if err := json.Unmarshal([]byte(js), &root); err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]struct{ title, description string }{
		"t": {"Tee", ""},
		"u": {"You", "About u."},
	} {
		sec := root.Properties[name]
		if sec.Title != want.title || want.description == "" && sec.Description != nil ||
			want.description != "" && (sec.Description == nil || *sec.Description != want.description) {
			t.Errorf("section %s = %+v, want title %q description %q", name, sec, want.title, want.description)
		}
	}
	for _, tc := range []struct {
		section, name string
		want          map[string]any
	}{
		{"t", "n", map[string]any{
			"type": "integer", "title": "N", "description": "N value.", "default": 5.0,
			"enum": []any{1.0, 5.0, 10.0}, "minimum": 1.0, "maximum": 10.0,
			"x-obstudio-failSafe": 1.0, "x-obstudio-apply": "restart",
		}},
		{"t", "v", map[string]any{
			"type": "string", "title": "V", "description": "V value.", "default": "a<b",
			"x-obstudio-failSafe": "a<b", "x-obstudio-apply": "live",
		}},
		{"u", "c", map[string]any{
			"type": "boolean", "title": "C", "description": "C value.", "default": false,
			"x-obstudio-failSafe": false, "x-obstudio-apply": "live",
		}},
	} {
		if got := root.Properties[tc.section].Properties[tc.name]; !reflect.DeepEqual(got, tc.want) {
			t.Errorf("%s.%s = %v, want %v", tc.section, tc.name, got, tc.want)
		}
	}

	sectionOrder := func(name string, members []string) {
		obj := js[strings.Index(js, `"`+name+`": {`):]
		obj = obj[:strings.Index(obj, `"properties"`)+len(`"properties"`)]
		last := -1
		for _, m := range members {
			i := strings.Index(obj, m)
			if i <= last {
				t.Errorf("section %s: member %s out of order in %s", name, m, obj)
			}
			last = i
		}
		if len(members) == 3 && strings.Contains(obj, `"description"`) {
			t.Errorf("section %s has a description: %s", name, obj)
		}
	}
	sectionOrder("t", []string{`"type"`, `"title": "Tee"`, `"properties"`})
	sectionOrder("u", []string{`"type"`, `"title": "You"`, `"description": "About u."`, `"properties"`})
	nObj := js[strings.Index(js, `"n": {`):strings.Index(js, `"v": {`)]
	last := -1
	for _, m := range []string{`"type"`, `"title"`, `"description"`, `"default"`, `"enum"`, `"minimum"`, `"maximum"`, `"x-obstudio-failSafe"`, `"x-obstudio-apply"`} {
		i := strings.Index(nObj, m)
		if i <= last {
			t.Errorf("member %s out of order in %s", m, nObj)
		}
		last = i
	}
	if !strings.Contains(nObj, `"x-obstudio-apply": "restart"`) {
		t.Errorf("n is not marked restart: %s", nObj)
	}
	vObj := js[strings.Index(js, `"v": {`):strings.Index(js, `"u": {`)]
	if !strings.Contains(vObj, `"default": "a<b"`) || strings.Contains(js, `\u003c`) {
		t.Errorf("v default is HTML-escaped or missing: %s", vObj)
	}
	if strings.Contains(strings.ToLower(vObj), "valid") || strings.Contains(strings.ToLower(vObj), "check") {
		t.Errorf("v mentions validation: %s", vObj)
	}
}
