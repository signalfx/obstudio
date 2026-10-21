package userconfig

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
)

// KeysDoc returns the Markdown reference for every declared setting.
func KeysDoc() []byte { return renderKeysDoc(sections(), table()) }

// DefinitionsDocument returns the JSON description of every declared setting
// that the webview renders its wording from.
func DefinitionsDocument() []byte { return renderDefinitionsDocument(sections(), table()) }

func defsIn(s Section, defs []def) []def {
	var out []def
	for _, d := range defs {
		if d.sectionPath() == s.name {
			out = append(out, d)
		}
	}
	return out
}

func defName(d def) string {
	return strings.TrimPrefix(d.path(), d.sectionPath()+".")
}

func renderKeysDoc(secs []Section, defs []def) []byte {
	blocks := []string{
		"# config.yaml keys",
		"<!-- Generated from observer/internal/userconfig. Do not edit. Regenerate: cd observer && go test ./internal/userconfig -update -->",
		"Splunk Observability Studio reads these keys from `~/.obstudio/config.yaml`. A key that is absent or has an invalid value uses its fail-safe value. A change applies while Splunk Observability Studio is running unless the key requires a restart.",
	}
	for _, s := range secs {
		blocks = append(blocks, "## `"+s.name+"`")
		for _, d := range defsIn(s, defs) {
			v := d.view()
			rows := []string{
				"| Property | Value |",
				"|---|---|",
				"| Type | `" + string(v.Type) + "` |",
				"| Default | `" + valueText(v.Default) + "` |",
				"| Fail-safe | `" + valueText(v.FailSafe) + "` |",
			}
			if v.Enum != nil {
				members := make([]string, len(v.Enum))
				for i, e := range v.Enum {
					members[i] = "`" + valueText(e) + "`"
				}
				rows = append(rows, "| Allowed values | "+strings.Join(members, ", ")+" |")
			}
			if v.Min != nil {
				rows = append(rows, fmt.Sprintf("| Minimum | `%d` |", *v.Min))
			}
			if v.Max != nil {
				rows = append(rows, fmt.Sprintf("| Maximum | `%d` |", *v.Max))
			}
			if v.Validated {
				rows = append(rows, "| Additional checks | Checked by Splunk Observability Studio |")
			}
			applies := "Live"
			if v.Apply == ApplyRestart {
				applies = "Requires restart"
			}
			rows = append(rows, "| Applies | "+applies+" |")
			blocks = append(blocks,
				"### `"+v.Path+"`",
				"**"+v.Label+"**",
				v.Description,
				strings.Join(rows, "\n"),
			)
		}
	}
	return []byte(strings.Join(blocks, "\n\n") + "\n")
}

// object is a JSON object that keeps its members in insertion order, so the
// generated documents are byte-stable.
type object []member

type member struct {
	key   string
	value any
}

func (o object) MarshalJSON() ([]byte, error) {
	var b bytes.Buffer
	b.WriteByte('{')
	for i, m := range o {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(jsonString(m.key))
		b.WriteByte(':')
		v, err := marshalNoEscape(m.value)
		if err != nil {
			return nil, err
		}
		b.Write(v)
	}
	b.WriteByte('}')
	return b.Bytes(), nil
}

func marshalNoEscape(v any) ([]byte, error) {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(b.Bytes(), []byte("\n")), nil
}

func jsonSchemaType(t Type) string {
	switch t {
	case TypeBool:
		return "boolean"
	case TypeInt:
		return "integer"
	default:
		return "string"
	}
}

func renderDefinitionsDocument(secs []Section, defs []def) []byte {
	root := object{}
	for _, s := range secs {
		props := object{}
		for _, d := range defsIn(s, defs) {
			v := d.view()
			o := object{
				{"type", jsonSchemaType(v.Type)},
				{"title", v.Label},
				{"description", v.Description},
				{"default", v.Default},
			}
			if v.Enum != nil {
				o = append(o, member{"enum", v.Enum})
			}
			if v.Min != nil {
				o = append(o, member{"minimum", *v.Min})
			}
			if v.Max != nil {
				o = append(o, member{"maximum", *v.Max})
			}
			o = append(o,
				member{"x-obstudio-failSafe", v.FailSafe},
				member{"x-obstudio-apply", string(v.Apply)},
			)
			props = append(props, member{defName(d), o})
		}
		root = append(root, member{s.name, object{{"type", "object"}, {"properties", props}}})
	}
	doc := object{{"type", "object"}, {"properties", root}}
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(doc); err != nil {
		// Every value in the document is a bool, int, string or object.
		panic(err)
	}
	return b.Bytes()
}
