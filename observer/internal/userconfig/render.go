package userconfig

import (
	"bytes"
	"encoding/json"
	"strings"
)

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
				{"title", v.Title},
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
		so := object{{"type", "object"}, {"title", s.title()}}
		if s.description() != "" {
			so = append(so, member{"description", s.description()})
		}
		root = append(root, member{s.name, append(so, member{"properties", props})})
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
