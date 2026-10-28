// Package userconfig owns ~/.obstudio/config.yaml: the settings it declares,
// how the file is read and edited, and the live view of it held by a running
// observer.
package userconfig

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

// Value is the set of Go types a setting may have.
type Value interface{ bool | int | string }

// Type names a setting's value type.
type Type string

const (
	TypeBool   Type = "bool"
	TypeInt    Type = "int"
	TypeString Type = "string"
)

// Apply says whether a change takes effect while the observer runs or only
// after a restart. It is metadata for consumers; this package treats both the
// same.
type Apply string

const (
	ApplyLive    Apply = "live"
	ApplyRestart Apply = "restart"
)

var (
	ErrUnknownKey   = errors.New("userconfig: unknown key")
	ErrInvalidValue = errors.New("userconfig: invalid value")
)

// Key names one setting of type T. The only non-zero Keys are the package's
// declared settings.
type Key[T Value] struct{ d *definition[T] }

// Path returns the dotted path, or "" for the zero Key.
func (k Key[T]) Path() string {
	if k.d == nil {
		return ""
	}
	return k.d.path()
}

func (k Key[T]) selectorPath() string { return k.Path() }

// Section names a group of settings.
type Section struct{ name, titleText, descText string }

// Path returns the section name, or "" for the zero Section.
func (s Section) Path() string { return s.name }

func (s Section) selectorPath() string { return s.name }

func (s Section) title() string       { return s.titleText }
func (s Section) description() string { return s.descText }

// Selector is a Key or a Section.
type Selector interface{ selectorPath() string }

var SectionTelemetry = section("telemetry", sectionSpec{
	Title: "Privacy",
})

var TelemetryEnabled = define(SectionTelemetry, "enabled", defSpec[bool]{
	Title:       "Send anonymous usage data",
	Description: "Allow Cisco to collect anonymous usage data about Splunk Observability Studio itself. Turning this off does not change what Splunk Observability Studio collects from your agents or shows you locally.",
	Hint:        "To turn this off, run: obstudio telemetry disable",
	Default:     true,
	FailSafe:    false,
	Apply:       ApplyLive,
	Field:       func(s *Settings) *bool { return &s.Telemetry.Enabled },
})

// Settings holds one value per declared setting, grouped by section.
type Settings struct{ Telemetry TelemetrySettings }

type TelemetrySettings struct{ Enabled bool }

// DefaultSettings returns every setting at the value a fresh file has.
func DefaultSettings() Settings {
	var s Settings
	for _, d := range table() {
		d.setDefault(&s)
	}
	return s
}

// FailSafeSettings returns every setting at the value used when it is absent
// or invalid.
func FailSafeSettings() Settings {
	var s Settings
	for _, d := range table() {
		d.setFailSafe(&s)
	}
	return s
}

// failSafeSummary lists every setting's fail-safe value as path=value, for
// log lines.
func failSafeSummary() string {
	defs := table()
	parts := make([]string, len(defs))
	for i, d := range defs {
		parts[i] = d.path() + "=" + valueText(d.view().FailSafe)
	}
	return strings.Join(parts, ", ")
}

// Definition is a read-only description of one declared setting.
type Definition struct {
	Path        string
	Section     string
	Type        Type
	Title       string
	Description string
	Hint        string
	Default     any
	FailSafe    any
	Enum        []any
	Min, Max    *int
	Validated   bool
	Apply       Apply
}

// Definitions returns every declared setting in declaration order. The result
// is a fresh copy on every call.
func Definitions() []Definition {
	defs := table()
	out := make([]Definition, len(defs))
	for i, d := range defs {
		out[i] = d.view()
	}
	return out
}

// sectionSpec is a section's wording. Title is required; Description is
// optional.
type sectionSpec struct{ Title, Description string }

type defSpec[T Value] struct {
	Title       string
	Description string
	Hint        string
	Default     T
	FailSafe    T
	Enum        []T
	Min, Max    *int
	Validate    func(T) error
	Apply       Apply
	Field       func(*Settings) *T
}

type definition[T Value] struct {
	sec  Section
	name string
	spec defSpec[T]
}

// def lets the file and live layers handle every setting without knowing its
// type parameter.
type def interface {
	path() string
	sectionPath() string
	typ() Type
	checkAny(v any) error
	assign(s *Settings, v any)
	get(s *Settings) any
	setFailSafe(s *Settings)
	setDefault(s *Settings)
	differs(a, b *Settings) bool
	view() Definition
}

// Written only during package initialization.
var (
	registeredSections []Section
	registeredDefs     []def
)

func table() []def {
	return append([]def(nil), registeredDefs...)
}

func sections() []Section {
	return append([]Section(nil), registeredSections...)
}

func changedPaths(old, new Settings) []string {
	var out []string
	for _, d := range table() {
		if d.differs(&old, &new) {
			out = append(out, d.path())
		}
	}
	return out
}

func isSegment(s string) bool {
	if s == "" || s[0] < 'a' || s[0] > 'z' {
		return false
	}
	for i := 1; i < len(s); i++ {
		c := s[i]
		if (c < 'a' || c > 'z') && (c < 'A' || c > 'Z') && (c < '0' || c > '9') {
			return false
		}
	}
	return true
}

func newSection(name string, d sectionSpec) Section {
	fail := func(reason string) {
		panic(fmt.Sprintf("userconfig: invalid section %q: %s", name, reason))
	}
	if !isSegment(name) {
		fail("invalid name")
	}
	if d.Title == "" || strings.Contains(d.Title, "\n") {
		fail("title must be one non-empty line")
	}
	if strings.Contains(d.Description, "\n") {
		fail("description must be one line")
	}
	return Section{name: name, titleText: d.Title, descText: d.Description}
}

func typeOf[T Value]() Type {
	var zero T
	switch any(zero).(type) {
	case bool:
		return TypeBool
	case int:
		return TypeInt
	default:
		return TypeString
	}
}

func newDefinition[T Value](s Section, name string, d defSpec[T]) *definition[T] {
	path := s.name + "." + name
	fail := func(reason string) {
		panic(fmt.Sprintf("userconfig: invalid definition %q: %s", path, reason))
	}
	if s.name == "" {
		fail("zero section")
	}
	if !isSegment(name) {
		fail("invalid name")
	}
	if d.Title == "" || strings.Contains(d.Title, "\n") {
		fail("title must be one non-empty line")
	}
	if d.Description == "" || strings.Contains(d.Description, "\n") {
		fail("description must be one non-empty line")
	}
	if strings.Contains(d.Hint, "\n") {
		fail("hint must be one line")
	}
	if d.Apply != ApplyLive && d.Apply != ApplyRestart {
		fail("apply must be live or restart")
	}
	t := typeOf[T]()
	if len(d.Enum) > 0 && t == TypeBool {
		fail("enum on a bool")
	}
	for i := range d.Enum {
		for j := i + 1; j < len(d.Enum); j++ {
			if d.Enum[i] == d.Enum[j] {
				fail("duplicate enum member")
			}
		}
	}
	if (d.Min != nil || d.Max != nil) && t != TypeInt {
		fail("min or max on a non-int")
	}
	if d.Min != nil && d.Max != nil && *d.Min > *d.Max {
		fail("min greater than max")
	}
	return &definition[T]{sec: s, name: name, spec: d}
}

func section(name string, d sectionSpec) Section {
	s := newSection(name, d)
	for _, r := range registeredSections {
		if r.name == name {
			panic(fmt.Sprintf("userconfig: duplicate section %q", name))
		}
	}
	registeredSections = append(registeredSections, s)
	return s
}

func define[T Value](s Section, name string, d defSpec[T]) Key[T] {
	nd := newDefinition(s, name, d)
	path := nd.path()
	if d.Field == nil {
		panic(fmt.Sprintf("userconfig: definition %q has no Settings field", path))
	}
	registered := false
	for _, r := range registeredSections {
		if r == s {
			registered = true
		}
	}
	if !registered {
		panic(fmt.Sprintf("userconfig: definition %q is in an unregistered section", path))
	}
	for _, r := range registeredDefs {
		if r.path() == path {
			panic(fmt.Sprintf("userconfig: duplicate definition %q", path))
		}
	}
	registeredDefs = append(registeredDefs, nd)
	return Key[T]{d: nd}
}

func (d *definition[T]) path() string        { return d.sec.name + "." + d.name }
func (d *definition[T]) sectionPath() string { return d.sec.name }
func (d *definition[T]) typ() Type           { return typeOf[T]() }

type invalidValueError struct{ path, reason string }

func (e *invalidValueError) Error() string {
	if e.path == "" {
		return ErrInvalidValue.Error() + ": " + e.reason
	}
	return ErrInvalidValue.Error() + ": " + e.path + ": " + e.reason
}

func (e *invalidValueError) Is(target error) bool { return target == ErrInvalidValue }

type unknownKeyError struct{ path string }

func (e *unknownKeyError) Error() string { return ErrUnknownKey.Error() + ": " + e.path }

func (e *unknownKeyError) Is(target error) bool { return target == ErrUnknownKey }

// valueText is how a value is written in messages and documents.
func valueText(v any) string {
	if s, ok := v.(string); ok {
		return jsonString(s)
	}
	return fmt.Sprint(v)
}

func jsonString(s string) string {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(s)
	return strings.TrimSuffix(b.String(), "\n")
}

func (d *definition[T]) check(v T) error {
	fail := func(reason string) error { return &invalidValueError{path: d.path(), reason: reason} }
	if len(d.spec.Enum) > 0 {
		found := false
		for _, e := range d.spec.Enum {
			if e == v {
				found = true
				break
			}
		}
		if !found {
			members := make([]string, len(d.spec.Enum))
			for i, e := range d.spec.Enum {
				members[i] = valueText(e)
			}
			return fail(valueText(v) + " is not one of " + strings.Join(members, ", "))
		}
	}
	if n, ok := any(v).(int); ok {
		if d.spec.Min != nil && n < *d.spec.Min {
			return fail(fmt.Sprintf("%d is less than %d", n, *d.spec.Min))
		}
		if d.spec.Max != nil && n > *d.spec.Max {
			return fail(fmt.Sprintf("%d is greater than %d", n, *d.spec.Max))
		}
	}
	if d.spec.Validate != nil {
		if err := d.spec.Validate(v); err != nil {
			return fail(err.Error())
		}
	}
	return nil
}

func (d *definition[T]) checkAny(v any) error {
	t, ok := v.(T)
	if !ok {
		return &invalidValueError{path: d.path(), reason: "has the wrong type"}
	}
	return d.check(t)
}

func (d *definition[T]) assign(s *Settings, v any) { *d.spec.Field(s) = v.(T) }
func (d *definition[T]) get(s *Settings) any       { return *d.spec.Field(s) }
func (d *definition[T]) setFailSafe(s *Settings)   { *d.spec.Field(s) = d.spec.FailSafe }
func (d *definition[T]) setDefault(s *Settings)    { *d.spec.Field(s) = d.spec.Default }

func (d *definition[T]) differs(a, b *Settings) bool {
	return *d.spec.Field(a) != *d.spec.Field(b)
}

func (d *definition[T]) view() Definition {
	out := Definition{
		Path:        d.path(),
		Section:     d.sec.name,
		Type:        typeOf[T](),
		Title:       d.spec.Title,
		Description: d.spec.Description,
		Hint:        d.spec.Hint,
		Default:     d.spec.Default,
		FailSafe:    d.spec.FailSafe,
		Validated:   d.spec.Validate != nil,
		Apply:       d.spec.Apply,
	}
	if len(d.spec.Enum) > 0 {
		out.Enum = make([]any, len(d.spec.Enum))
		for i, e := range d.spec.Enum {
			out.Enum[i] = e
		}
	}
	if d.spec.Min != nil {
		m := *d.spec.Min
		out.Min = &m
	}
	if d.spec.Max != nil {
		m := *d.spec.Max
		out.Max = &m
	}
	return out
}

// Changes is a set of setting writes, at most one per path, in first-put
// order. The zero value is an empty set.
type Changes struct{ entries []change }

type change struct {
	d def
	v any
}

// Put records k = v in c, replacing an earlier value for the same key in
// place. It does not check v; the writer checks the whole set.
func Put[T Value](c *Changes, k Key[T], v T) {
	var d def
	if k.d != nil {
		d = k.d
	}
	c.put(d, v)
}

// Len returns the number of entries.
func (c Changes) Len() int { return len(c.entries) }

func (c Changes) list() []change {
	return append([]change(nil), c.entries...)
}

func changePath(d def) string {
	if d == nil {
		return ""
	}
	return d.path()
}

func (c *Changes) put(d def, v any) {
	// Copy on write so a Changes value copied before this call is unaffected.
	entries := append([]change(nil), c.entries...)
	path := changePath(d)
	for i := range entries {
		if changePath(entries[i].d) == path {
			entries[i].v = v
			c.entries = entries
			return
		}
	}
	c.entries = append(entries, change{d: d, v: v})
}
