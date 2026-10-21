package userconfig

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"strconv"

	"go.yaml.in/yaml/v3"
)

// Snapshot is one parsed state of the config file.
type Snapshot struct {
	Settings
	// Hash is the SHA-256 of the bytes the snapshot was parsed from; zero when
	// nothing was parsed.
	Hash [32]byte
	// Degraded is true only for FailSafeSnapshot.
	Degraded bool
}

func DefaultSnapshot() Snapshot { return Snapshot{Settings: DefaultSettings()} }

func FailSafeSnapshot() Snapshot { return Snapshot{Settings: FailSafeSettings(), Degraded: true} }

type DiagnosticKind string

const (
	DiagAbsent     DiagnosticKind = "absent"
	DiagInvalid    DiagnosticKind = "invalid"
	DiagUnknownKey DiagnosticKind = "unknown_key"
)

// Diagnostic describes one problem found while reading the file. Message
// holds only the key, the offending value text and fixed wording.
type Diagnostic struct {
	Key     string
	Kind    DiagnosticKind
	Line    int
	Message string
}

var (
	ErrSyntax     = errors.New("userconfig: not well-formed")
	ErrNotMapping = errors.New("userconfig: path segment is not a mapping")
)

type Result struct {
	Snapshot    Snapshot
	Diagnostics []Diagnostic
	Created     bool
}

// parseFile returns the document and its root mapping. Both are nil when the
// bytes hold no document (empty, whitespace or comments only).
func parseFile(data []byte) (*yaml.Node, *yaml.Node, error) {
	var doc yaml.Node
	if err := yaml.Unmarshal(data, &doc); err != nil {
		return nil, nil, fmt.Errorf("%w: %v", ErrSyntax, err)
	}
	if doc.Kind == 0 || len(doc.Content) == 0 {
		return nil, nil, nil
	}
	root := doc.Content[0]
	if root.Kind != yaml.MappingNode {
		return nil, nil, fmt.Errorf("%w: the top level is not a mapping", ErrSyntax)
	}
	return &doc, root, nil
}

// lookup returns the key and value nodes for name in mapping m. When a key
// repeats, the last one wins, as in a YAML-to-map decode.
func lookup(m *yaml.Node, name string) (*yaml.Node, *yaml.Node) {
	if m == nil || m.Kind != yaml.MappingNode {
		return nil, nil
	}
	var k, v *yaml.Node
	for i := 0; i+1 < len(m.Content); i += 2 {
		if m.Content[i].Value == name {
			k, v = m.Content[i], m.Content[i+1]
		}
	}
	return k, v
}

// Load reads the file at path. A missing, unreadable or malformed file gives
// FailSafeSnapshot and an error; a well-formed file never gives an error, and
// its problems are reported as diagnostics.
func Load(path string) (Snapshot, []Diagnostic, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return FailSafeSnapshot(), nil, err
	}
	_, root, err := parseFile(data)
	if err != nil {
		return FailSafeSnapshot(), nil, err
	}
	settings, diags := decodeTree(root)
	return Snapshot{Settings: settings, Hash: sha256.Sum256(data)}, diags, nil
}

func decodeTree(root *yaml.Node) (Settings, []Diagnostic) {
	settings := FailSafeSettings()
	var diags []Diagnostic
	badSections := map[string]bool{}
	for _, d := range table() {
		sec := d.sectionPath()
		if badSections[sec] {
			continue
		}
		_, secNode := lookup(root, sec)
		if secNode == nil {
			diags = append(diags, absent(d))
			continue
		}
		if isNullScalar(secNode) {
			diags = append(diags, absent(d))
			continue
		}
		if secNode.Kind != yaml.MappingNode {
			badSections[sec] = true
			diags = append(diags, Diagnostic{Key: sec, Kind: DiagInvalid, Line: secNode.Line, Message: sec + ": is not a mapping"})
			continue
		}
		_, valNode := lookup(secNode, defName(d))
		if valNode == nil {
			diags = append(diags, absent(d))
			continue
		}
		v, diag := decodeValue(valNode, d)
		if diag != nil {
			diags = append(diags, *diag)
			continue
		}
		d.assign(&settings, v)
	}
	return settings, append(diags, unknownKeys(root)...)
}

// isNullScalar reports a key left with no value, such as a section whose
// only entry was deleted; it reads as empty rather than malformed.
func isNullScalar(n *yaml.Node) bool {
	return n.Kind == yaml.ScalarNode && n.ShortTag() == "!!null"
}

func absent(d def) Diagnostic {
	return Diagnostic{Key: d.path(), Kind: DiagAbsent, Message: d.path() + ": is not set"}
}

func unknownKeys(root *yaml.Node) []Diagnostic {
	if root == nil {
		return nil
	}
	known := map[string]bool{}
	for _, s := range sections() {
		known[s.name] = true
	}
	defined := map[string]bool{}
	for _, d := range table() {
		defined[d.path()] = true
	}
	unknown := func(path string, line int) Diagnostic {
		return Diagnostic{Key: path, Kind: DiagUnknownKey, Line: line, Message: path + ": is not a known key"}
	}
	var diags []Diagnostic
	for i := 0; i+1 < len(root.Content); i += 2 {
		k, v := root.Content[i], root.Content[i+1]
		if !known[k.Value] {
			diags = append(diags, unknown(k.Value, k.Line))
			continue
		}
		if v.Kind != yaml.MappingNode {
			continue
		}
		for j := 0; j+1 < len(v.Content); j += 2 {
			ck := v.Content[j]
			if path := k.Value + "." + ck.Value; !defined[path] {
				diags = append(diags, unknown(path, ck.Line))
			}
		}
	}
	return diags
}

const quotedStyles = yaml.DoubleQuotedStyle | yaml.SingleQuotedStyle | yaml.LiteralStyle | yaml.FoldedStyle

// decodeValue decodes n strictly for d's type, then checks it. Decoding into
// a Go bool through yaml.v3 would accept True and on, so the node is read
// directly.
func decodeValue(n *yaml.Node, d def) (any, *Diagnostic) {
	invalid := func(msg string) (any, *Diagnostic) {
		return nil, &Diagnostic{Key: d.path(), Kind: DiagInvalid, Line: n.Line, Message: d.path() + ": " + msg}
	}
	if n.Kind != yaml.ScalarNode {
		return invalid("is not a single value")
	}
	plain := n.Style&quotedStyles == 0
	var v any
	switch d.typ() {
	case TypeBool:
		if !plain || n.ShortTag() != "!!bool" || (n.Value != "true" && n.Value != "false") {
			return invalid(jsonString(n.Value) + " is not true or false")
		}
		v = n.Value == "true"
	case TypeInt:
		i, err := strconv.Atoi(n.Value)
		if !plain || n.ShortTag() != "!!int" || err != nil {
			return invalid(jsonString(n.Value) + " is not a base-10 integer")
		}
		v = i
	default:
		if n.ShortTag() != "!!str" {
			return invalid(jsonString(n.Value) + " is not a string")
		}
		v = n.Value
	}
	if err := d.checkAny(v); err != nil {
		var ive *invalidValueError
		if errors.As(err, &ive) {
			return invalid(ive.reason)
		}
		return invalid(err.Error())
	}
	return v, nil
}

// encodeScalar returns the node written for v. Strings are always
// double-quoted so that values like "true" or "123" read back as strings.
func encodeScalar(v any) *yaml.Node {
	switch v := v.(type) {
	case bool:
		return &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!bool", Value: strconv.FormatBool(v)}
	case int:
		return &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!int", Value: strconv.Itoa(v)}
	default:
		return &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: v.(string), Style: yaml.DoubleQuotedStyle}
	}
}

// EnsureScaffold creates the file with Scaffold() if nothing exists at path.
// It never replaces an existing file, and when processes race exactly one of
// them creates it.
func EnsureScaffold(path string) (bool, error) {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return false, err
	}
	if _, err := os.Lstat(path); err == nil {
		return false, nil
	} else if !errors.Is(err, fs.ErrNotExist) {
		return false, err
	}
	tmp, err := writeTemp(dir, []byte(Scaffold()))
	if err != nil {
		return false, err
	}
	defer os.Remove(tmp)
	// A link fails if the target exists, so a concurrent creator's file is
	// never replaced and no reader ever sees a partial scaffold.
	if err := os.Link(tmp, path); err != nil {
		if errors.Is(err, fs.ErrExist) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// Open ensures the file exists and loads it. Every error comes with
// FailSafeSnapshot.
func Open(path string) (Result, error) {
	created, err := EnsureScaffold(path)
	if err != nil {
		return Result{Snapshot: FailSafeSnapshot()}, err
	}
	snap, diags, err := Load(path)
	if err != nil {
		return Result{Snapshot: FailSafeSnapshot(), Created: created}, err
	}
	return Result{Snapshot: snap, Diagnostics: diags, Created: created}, nil
}

// Write sets one key in the file.
func Write[T Value](path string, k Key[T], v T) error {
	var c Changes
	Put(&c, k, v)
	return WriteChanges(path, c)
}

// WriteChanges applies every entry of c to the file in one atomic replace,
// keeping comments and unknown keys, or changes nothing.
func WriteChanges(path string, c Changes) error {
	return writeChanges(path, c, os.Rename)
}

func writeChanges(path string, c Changes, rename func(oldpath, newpath string) error) error {
	if c.Len() == 0 {
		return nil
	}
	entries := c.list()
	for _, e := range entries {
		if e.d == nil {
			return ErrUnknownKey
		}
		if err := e.d.checkAny(e.v); err != nil {
			return err
		}
	}
	if _, err := EnsureScaffold(path); err != nil {
		return err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	out, err := applyChanges(data, entries)
	if err != nil {
		return err
	}
	return replaceFile(path, out, rename)
}

func applyChanges(data []byte, entries []change) ([]byte, error) {
	doc, root, err := parseFile(data)
	if err != nil {
		return nil, err
	}
	var prefix []byte
	if doc == nil {
		// The file holds only comments or whitespace, which a parse drops, so
		// keep the original bytes ahead of the new mapping.
		prefix = data
		if len(prefix) > 0 && !bytes.HasSuffix(prefix, []byte("\n")) {
			prefix = append(append([]byte(nil), prefix...), '\n')
		}
		root = &yaml.Node{Kind: yaml.MappingNode, Tag: "!!map"}
		doc = &yaml.Node{Kind: yaml.DocumentNode, Content: []*yaml.Node{root}}
	}
	for _, e := range entries {
		sec := e.d.sectionPath()
		_, secNode := lookup(root, sec)
		if secNode == nil {
			secNode = &yaml.Node{Kind: yaml.MappingNode, Tag: "!!map"}
			root.Content = append(root.Content, &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: sec}, secNode)
		} else if isNullScalar(secNode) {
			*secNode = yaml.Node{
				Kind: yaml.MappingNode, Tag: "!!map",
				HeadComment: secNode.HeadComment, LineComment: secNode.LineComment, FootComment: secNode.FootComment,
			}
		} else if secNode.Kind != yaml.MappingNode {
			return nil, fmt.Errorf("%w: %s", ErrNotMapping, sec)
		}
		name := defName(e.d)
		next := encodeScalar(e.v)
		if _, valNode := lookup(secNode, name); valNode != nil {
			next.HeadComment, next.LineComment, next.FootComment = valNode.HeadComment, valNode.LineComment, valNode.FootComment
			*valNode = *next
		} else {
			secNode.Content = append(secNode.Content, &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: name}, next)
		}
	}
	var b bytes.Buffer
	b.Write(prefix)
	enc := yaml.NewEncoder(&b)
	enc.SetIndent(2)
	if err := enc.Encode(doc); err != nil {
		return nil, err
	}
	if err := enc.Close(); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}

// writeTemp writes data to a new 0600 file in dir, fsynced, and returns its
// path.
func writeTemp(dir string, data []byte) (string, error) {
	f, err := os.CreateTemp(dir, ".config.yaml.tmp-*")
	if err != nil {
		return "", err
	}
	name := f.Name()
	err = f.Chmod(0o600)
	if err == nil {
		_, err = f.Write(data)
	}
	if err == nil {
		err = f.Sync()
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		os.Remove(name)
		return "", err
	}
	return name, nil
}

func replaceFile(path string, data []byte, rename func(oldpath, newpath string) error) error {
	dir := filepath.Dir(path)
	tmp, err := writeTemp(dir, data)
	if err != nil {
		return err
	}
	if err := rename(tmp, path); err != nil {
		os.Remove(tmp)
		return err
	}
	if runtime.GOOS == "windows" {
		return nil
	}
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}
