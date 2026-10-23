package userconfig

import (
	"bytes"
	"encoding/json"
	"sort"
	"strconv"
)

// DecodeChanges turns a JSON merge body shaped like the file, for example
// {"telemetry":{"enabled":false}}, into a change set. Settings absent from the
// body are absent from the set. Any failure returns an empty set.
func DecodeChanges(data []byte) (Changes, error) {
	return decodeChanges(sections(), table(), data)
}

// EncodeSettings returns s as compact JSON in the file's shape.
func EncodeSettings(s Settings) []byte {
	return encodeSettings(sections(), table(), func(d def) any { return d.get(&s) })
}

func isJSONObject(raw []byte) bool {
	raw = bytes.TrimLeft(raw, " \t\r\n")
	return len(raw) > 0 && raw[0] == '{'
}

func sortedKeys(m map[string]json.RawMessage) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func decodeChanges(secs []Section, defs []def, data []byte) (Changes, error) {
	if !json.Valid(data) {
		return Changes{}, &invalidValueError{reason: "body is not one JSON value"}
	}
	if !isJSONObject(data) {
		return Changes{}, &invalidValueError{reason: "body is not a JSON object"}
	}
	var root map[string]json.RawMessage
	if err := json.Unmarshal(data, &root); err != nil {
		return Changes{}, &invalidValueError{reason: "body is not a JSON object"}
	}
	values := map[string]any{}
	for _, secName := range sortedKeys(root) {
		var sec *Section
		for i := range secs {
			if secs[i].name == secName {
				sec = &secs[i]
			}
		}
		if sec == nil {
			return Changes{}, &unknownKeyError{path: secName}
		}
		raw := root[secName]
		if !isJSONObject(raw) {
			return Changes{}, &invalidValueError{path: secName, reason: "is not a JSON object"}
		}
		var members map[string]json.RawMessage
		if err := json.Unmarshal(raw, &members); err != nil {
			return Changes{}, &invalidValueError{path: secName, reason: "is not a JSON object"}
		}
		for _, name := range sortedKeys(members) {
			path := secName + "." + name
			var d def
			for _, cand := range defsIn(*sec, defs) {
				if cand.path() == path {
					d = cand
				}
			}
			if d == nil {
				return Changes{}, &unknownKeyError{path: path}
			}
			v, err := decodeJSONValue(d, members[name])
			if err != nil {
				return Changes{}, err
			}
			if err := d.checkAny(v); err != nil {
				return Changes{}, err
			}
			values[path] = v
		}
	}
	var c Changes
	for _, d := range defs {
		if v, ok := values[d.path()]; ok {
			c.put(d, v)
		}
	}
	return c, nil
}

func isJSONInteger(s string) bool {
	if len(s) > 0 && s[0] == '-' {
		s = s[1:]
	}
	if s == "" {
		return false
	}
	if s[0] == '0' {
		return len(s) == 1
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

func decodeJSONValue(d def, raw json.RawMessage) (any, error) {
	text := string(bytes.TrimSpace(raw))
	if text == "null" {
		return nil, &invalidValueError{path: d.path(), reason: "is null"}
	}
	wrong := &invalidValueError{path: d.path(), reason: "has the wrong type"}
	switch d.typ() {
	case TypeBool:
		switch text {
		case "true":
			return true, nil
		case "false":
			return false, nil
		}
	case TypeInt:
		if isJSONInteger(text) {
			if n, err := strconv.Atoi(text); err == nil {
				return n, nil
			}
		}
	case TypeString:
		if len(text) > 0 && text[0] == '"' {
			var s string
			if err := json.Unmarshal(raw, &s); err == nil {
				return s, nil
			}
		}
	}
	return nil, wrong
}

func encodeSettings(secs []Section, defs []def, value func(def) any) []byte {
	root := object{}
	for _, s := range secs {
		sec := object{}
		for _, d := range defsIn(s, defs) {
			sec = append(sec, member{defName(d), value(d)})
		}
		root = append(root, member{s.name, sec})
	}
	b, err := marshalNoEscape(root)
	if err != nil {
		// Every value is a bool, int or string.
		panic(err)
	}
	return b
}
