package userconfig

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"os"
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

const v1KeysDoc = "# config.yaml keys\n" +
	"\n" +
	"<!-- Generated from observer/internal/userconfig. Do not edit. Regenerate: cd observer && go test ./internal/userconfig -update -->\n" +
	"\n" +
	"Splunk Observability Studio reads these keys from `~/.obstudio/config.yaml`. A key that is absent or has an invalid value uses its fail-safe value. A change applies while Splunk Observability Studio is running unless the key requires a restart.\n" +
	"\n" +
	"## " + v1SectionTitle + " (`telemetry`)\n" +
	"\n" +
	"### `telemetry.enabled`\n" +
	"\n" +
	"**" + v1Title + "**\n" +
	"\n" +
	v1Description + "\n" +
	"\n" +
	v1Hint + "\n" +
	"\n" +
	"| Property | Value |\n" +
	"|---|---|\n" +
	"| Type | `bool` |\n" +
	"| Default | `true` |\n" +
	"| Fail-safe | `false` |\n" +
	"| Applies | Live |\n"

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

func TestKeysDocGolden(t *testing.T) {
	got := KeysDoc()
	assertGolden(t, "../../../docs/config-keys.md", got)
	if string(got) != v1KeysDoc {
		t.Errorf("KeysDoc() differs from the v1 reference:\n%s", got)
	}
}

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

	props := root["properties"].(map[string]any)
	for _, d := range Definitions() {
		sec := props[d.Section].(map[string]any)["properties"].(map[string]any)
		entry := sec[strings.TrimPrefix(d.Path, d.Section+".")].(map[string]any)
		if entry["title"] != d.Title || entry["description"] != d.Description ||
			entry["default"] != d.Default || entry["x-obstudio-failSafe"] != d.FailSafe ||
			entry["x-obstudio-apply"] != string(d.Apply) {
			t.Errorf("%s: document entry %v does not match the definition", d.Path, entry)
		}
	}
	for _, s := range sections() {
		sec := props[s.Path()].(map[string]any)
		if sec["title"] != s.title() {
			t.Errorf("section %s title = %v, want %q", s.Path(), sec["title"], s.title())
		}
		if desc, ok := sec["description"]; s.description() == "" && ok || s.description() != "" && desc != s.description() {
			t.Errorf("section %s description = %v, want %q", s.Path(), desc, s.description())
		}
	}
	if _, ok := root["title"]; ok {
		t.Error("root has a title")
	}
	if _, ok := root["description"]; ok {
		t.Error("root has a description")
	}
	for _, d := range Definitions() {
		if d.Hint != "" && bytes.Contains(doc, []byte(d.Hint)) {
			t.Errorf("%s: document contains the hint", d.Path)
		}
	}
	if bytes.Contains(doc, []byte(".obstudio")) || bytes.Contains(doc, []byte("config.yaml")) {
		t.Error("document names a filesystem path")
	}
	if doc[len(doc)-1] != '\n' || doc[len(doc)-2] == '\n' {
		t.Error("document does not end with exactly one newline")
	}
}

func TestRenderOptionalFields(t *testing.T) {
	sec := newSection("t", sectionSpec{Title: "Tee"})
	n := newDefinition(sec, "n", defSpec[int]{
		Title: "N", Description: "N value.", Hint: "Run tee --reset.", Default: 5, FailSafe: 1,
		Min: ptr(1), Max: ptr(10), Enum: []int{1, 5, 10}, Apply: ApplyRestart,
	})
	v := newDefinition(sec, "v", defSpec[string]{
		Title: "V", Description: "V value.", Default: "a<b", FailSafe: "a<b",
		Validate: func(string) error { return errors.New("never") }, Apply: ApplyLive,
	})
	usec := newSection("u", sectionSpec{Title: "You", Description: "About u."})
	c := newDefinition(usec, "c", defSpec[bool]{Title: "C", Description: "C value.", Apply: ApplyLive})
	secs, defs := []Section{sec, usec}, []def{n, v, c}

	doc := string(renderKeysDoc(secs, defs))
	tableN := "| Property | Value |\n|---|---|\n| Type | `int` |\n| Default | `5` |\n| Fail-safe | `1` |\n" +
		"| Allowed values | `1`, `5`, `10` |\n| Minimum | `1` |\n| Maximum | `10` |\n| Applies | Requires restart |\n"
	tableV := "| Property | Value |\n|---|---|\n| Type | `string` |\n| Default | `\"a<b\"` |\n| Fail-safe | `\"a<b\"` |\n" +
		"| Additional checks | Checked by Splunk Observability Studio |\n| Applies | Live |\n"
	for _, want := range []string{
		"## Tee (`t`)\n\n### `t.n`\n",
		"### `t.n`\n\n**N**\n\nN value.\n\nRun tee --reset.\n\n" + tableN,
		"### `t.v`\n\n**V**\n\nV value.\n\n" + tableV,
		"## You (`u`)\n\nAbout u.\n\n### `u.c`\n",
	} {
		if !strings.Contains(doc, want) {
			t.Errorf("keys doc has no block %q:\n%s", want, doc)
		}
	}

	js := string(renderDefinitionsDocument(secs, defs))
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
	if strings.Contains(js, "Run tee --reset.") {
		t.Error("definitions document contains a hint")
	}
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
