// Package configstatus reports the state of ~/.obstudio/config.yaml and the
// settings in force, for the status endpoint and the MCP status tool.
package configstatus

import (
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

type State string

const (
	StateOK          State = "ok"
	StateInvalid     State = "invalid"
	StateUnparseable State = "unparseable"
	StateMissing     State = "missing"
)

type Diagnostic struct {
	Key     string `json:"key"`
	Kind    string `json:"kind"`
	Line    int    `json:"line"`
	Message string `json:"message"`
}

type Status struct {
	State State `json:"state"`
	// Problem is true when the file changes behavior: a setting the file
	// names is not in force because the file is invalid or unparseable.
	Problem  bool   `json:"problem"`
	Degraded bool   `json:"degraded"`
	Path     string `json:"path"`
	// Effective is every setting in force, in the same JSON shape as the
	// settings endpoint body.
	Effective   json.RawMessage `json:"effective"`
	Message     string          `json:"message"`
	Diagnostics []Diagnostic    `json:"diagnostics"`
}

// Getter is the settings source; the observer passes its config Manager.
type Getter interface{ Get() userconfig.Snapshot }

type Builder struct {
	g             Getter
	path, display string
}

// New returns a Builder over g, whose settings come from the file at path.
func New(g Getter, path string) *Builder {
	home, err := os.UserHomeDir()
	return &Builder{g: g, path: path, display: displayPath(path, home, err)}
}

// displayPath writes path with the home directory as ~ when path is inside it.
func displayPath(path, home string, err error) string {
	if err != nil || home == "" {
		return path
	}
	sep := string(filepath.Separator)
	prefix := filepath.Clean(home) + sep
	if rest, ok := strings.CutPrefix(path, prefix); ok && rest != "" {
		return "~" + sep + rest
	}
	return path
}

const fixSentence = "Fix the file, or delete it to restore defaults on next start."

// Build reports the settings in force and the current state of the file.
func (b *Builder) Build() Status {
	snap := b.g.Get()
	_, diags, err := userconfig.Load(b.path)

	st := Status{
		Path:        b.path,
		Degraded:    snap.Degraded,
		Effective:   userconfig.EncodeSettings(snap.Settings),
		Diagnostics: []Diagnostic{},
	}
	problems := false
	for _, d := range diags {
		st.Diagnostics = append(st.Diagnostics, Diagnostic{Key: d.Key, Kind: string(d.Kind), Line: d.Line, Message: d.Message})
		if d.Kind == userconfig.DiagInvalid || d.Kind == userconfig.DiagAbsent {
			problems = true
		}
	}
	switch {
	case err == nil && problems:
		st.State = StateInvalid
	case err == nil:
		st.State = StateOK
	case errors.Is(err, fs.ErrNotExist):
		st.State = StateMissing
	default:
		st.State = StateUnparseable
	}
	st.Problem = st.State == StateInvalid || st.State == StateUnparseable

	readFail := "Some settings could not be read from " + b.display
	switch {
	case st.State == StateInvalid:
		st.Message = readFail + ", so safe defaults are in use. " + fixSentence
	case st.State == StateUnparseable:
		inUse := ", so your last valid settings are in use. "
		if st.Degraded {
			inUse = ", so safe defaults are in use. "
		}
		errText := strings.NewReplacer("\r", " ", "\n", " ").Replace(err.Error())
		st.Message = readFail + inUse + errText + " " + fixSentence
	case st.State == StateOK && len(diags) > 0:
		st.Message = "Some entries in " + b.display + " are not recognized and have no effect."
	}
	return st
}
