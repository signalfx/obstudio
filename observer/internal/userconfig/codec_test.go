package userconfig

import (
	"errors"
	"reflect"
	"strings"
	"testing"
)

type ttTable struct {
	t, u Section
	b    *definition[bool]
	n    *definition[int]
	s    *definition[string]
	c    *definition[bool]
	secs []Section
	defs []def
}

// newTT builds the test-only table: section t with b (bool), n (int, Min 1)
// and s (string, Enum low/high), then section u with c (bool).
func newTT() ttTable {
	var tt ttTable
	tt.t, tt.u = newSection("t", sectionSpec{Title: "T"}), newSection("u", sectionSpec{Title: "U"})
	tt.b = newDefinition(tt.t, "b", defSpec[bool]{Title: "b", Description: "b.", Apply: ApplyLive})
	tt.n = newDefinition(tt.t, "n", defSpec[int]{Title: "n", Description: "n.", Apply: ApplyLive, Min: ptr(1), Default: 1, FailSafe: 1})
	tt.s = newDefinition(tt.t, "s", defSpec[string]{Title: "s", Description: "s.", Apply: ApplyLive, Enum: []string{"low", "high"}, Default: "low", FailSafe: "low"})
	tt.c = newDefinition(tt.u, "c", defSpec[bool]{Title: "c", Description: "c.", Apply: ApplyLive})
	tt.secs = []Section{tt.t, tt.u}
	tt.defs = []def{tt.b, tt.n, tt.s, tt.c}
	return tt
}

type entry struct {
	path string
	v    any
}

func entries(c Changes) []entry {
	var out []entry
	for _, ch := range c.list() {
		out = append(out, entry{changePath(ch.d), ch.v})
	}
	return out
}

func TestDecodeChangesMatrix(t *testing.T) {
	tt := newTT()
	ok := []struct {
		body string
		want []entry
	}{
		{`{}`, nil},
		{`{"t":{}}`, nil},
		{`{"t":{"b":true}}`, []entry{{"t.b", true}}},
		{`{"u":{"c":true},"t":{"s":"low","n":5,"b":false}}`, []entry{{"t.b", false}, {"t.n", 5}, {"t.s", "low"}, {"u.c", true}}},
		{`{"t":{"b":true,"b":false}}`, []entry{{"t.b", false}}},
		{"  {\"t\":{\"n\":10}}\n", []entry{{"t.n", 10}}},
	}
	for _, tc := range ok {
		c, err := decodeChanges(tt.secs, tt.defs, []byte(tc.body))
		if err != nil {
			t.Errorf("%s: %v", tc.body, err)
			continue
		}
		if got := entries(c); !reflect.DeepEqual(got, tc.want) {
			t.Errorf("%s: entries %v, want %v", tc.body, got, tc.want)
		}
	}

	const (
		notOne = "userconfig: invalid value: body is not one JSON value"
		notObj = "userconfig: invalid value: body is not a JSON object"
	)
	bad := []struct {
		bodies  []string
		unknown bool
		want    string
	}{
		{[]string{``, `{"t":`, `{"t":{}} {}`}, false, notOne},
		{[]string{`[]`, `null`, `true`, `"t"`}, false, notObj},
		{[]string{`{"x":{}}`}, true, "userconfig: unknown key: x"},
		{[]string{`{"T":{"b":true}}`}, true, "userconfig: unknown key: T"},
		{[]string{`{"t":null}`, `{"t":true}`, `{"t":[]}`}, false, "userconfig: invalid value: t: is not a JSON object"},
		{[]string{`{"t":{"zz":1}}`, `{"t":{"b":true,"zz":1}}`}, true, "userconfig: unknown key: t.zz"},
		{[]string{`{"t":{"b":null}}`}, false, "userconfig: invalid value: t.b: is null"},
		{[]string{`{"t":{"b":"true"}}`, `{"t":{"b":1}}`}, false, "userconfig: invalid value: t.b: has the wrong type"},
		{[]string{`{"t":{"n":5.0}}`, `{"t":{"n":5e0}}`, `{"t":{"n":"5"}}`, `{"t":{"n":true}}`, `{"t":{"n":99999999999999999999}}`}, false, "userconfig: invalid value: t.n: has the wrong type"},
		{[]string{`{"t":{"s":5}}`}, false, "userconfig: invalid value: t.s: has the wrong type"},
		{[]string{`{"t":{"n":0}}`}, false, "userconfig: invalid value: t.n: 0 is less than 1"},
		{[]string{`{"t":{"s":"mid"}}`}, false, `userconfig: invalid value: t.s: "mid" is not one of "low", "high"`},
	}
	for _, tc := range bad {
		for _, body := range tc.bodies {
			c, err := decodeChanges(tt.secs, tt.defs, []byte(body))
			if err == nil {
				t.Errorf("%q: nil error, want %q", body, tc.want)
				continue
			}
			if err.Error() != tc.want {
				t.Errorf("%q: %q, want %q", body, err.Error(), tc.want)
			}
			if errors.Is(err, ErrUnknownKey) != tc.unknown || errors.Is(err, ErrInvalidValue) == tc.unknown {
				t.Errorf("%q: wrong sentinel for %v", body, err)
			}
			if c.Len() != 0 {
				t.Errorf("%q: partial set of %d entries", body, c.Len())
			}
		}
	}

	c, err := DecodeChanges([]byte(`{"telemetry":{"enabled":false}}`))
	if err != nil || !reflect.DeepEqual(entries(c), []entry{{"telemetry.enabled", false}}) {
		t.Errorf("registered decode = %v, %v", entries(c), err)
	}
	if _, err := DecodeChanges([]byte(`{"version":1}`)); err == nil || err.Error() != "userconfig: unknown key: version" {
		t.Errorf("version decode = %v", err)
	}
}

func ttValues(vals map[string]any) func(def) any {
	return func(d def) any { return vals[d.path()] }
}

func TestEncodeSettings(t *testing.T) {
	results := []string{string(EncodeSettings(DefaultSettings())), string(EncodeSettings(FailSafeSettings()))}
	if results[0] != `{"telemetry":{"enabled":true}}` || results[1] != `{"telemetry":{"enabled":false}}` {
		t.Errorf("v1 encode = %v", results)
	}
	tt := newTT()
	got := string(encodeSettings(tt.secs, tt.defs, ttValues(map[string]any{
		"t.b": true, "t.n": -7, "t.s": "a<b\"c", "u.c": false,
	})))
	results = append(results, got)
	if want := `{"t":{"b":true,"n":-7,"s":"a<b\"c"},"u":{"c":false}}`; got != want {
		t.Errorf("TT encode = %s, want %s", got, want)
	}
	if !strings.Contains(got, "a<b") || strings.Contains(got, `\u003c`) {
		t.Errorf("TT encode escaped HTML: %s", got)
	}
	for _, r := range results {
		if strings.HasSuffix(r, "\n") {
			t.Errorf("%q ends with a newline", r)
		}
	}
}

func TestCodecRoundTrip(t *testing.T) {
	for _, s := range []Settings{DefaultSettings(), FailSafeSettings()} {
		c, err := DecodeChanges(EncodeSettings(s))
		if err != nil {
			t.Fatalf("decode %+v: %v", s, err)
		}
		if c.Len() != len(table()) {
			t.Errorf("decoded %d entries, want %d", c.Len(), len(table()))
		}
		for _, base := range []Settings{DefaultSettings(), FailSafeSettings()} {
			got := base
			for _, ch := range c.list() {
				ch.d.assign(&got, ch.v)
			}
			if got != s {
				t.Errorf("round trip of %+v onto %+v = %+v", s, base, got)
			}
		}
	}

	tt := newTT()
	body := encodeSettings(tt.secs, tt.defs, ttValues(map[string]any{
		"t.b": false, "t.n": 3, "t.s": "high", "u.c": true,
	}))
	c, err := decodeChanges(tt.secs, tt.defs, body)
	if err != nil {
		t.Fatal(err)
	}
	want := []entry{{"t.b", false}, {"t.n", 3}, {"t.s", "high"}, {"u.c", true}}
	if got := entries(c); !reflect.DeepEqual(got, want) {
		t.Errorf("TT round trip = %v, want %v", got, want)
	}
}
