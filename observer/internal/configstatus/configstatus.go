// Package configstatus reports whether ~/.obstudio/config.yaml is in a state
// the user should be warned about, for the status endpoint, the MCP status
// tool and the editor extension.
package configstatus

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"sort"
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
	State       State        `json:"state"`
	Warn        bool         `json:"warn"`
	Degraded    bool         `json:"degraded"`
	Path        string       `json:"path"`
	Effective   Effective    `json:"effective"`
	Message     string       `json:"message"`
	Diagnostics []Diagnostic `json:"diagnostics"`
	Fingerprint string       `json:"fingerprint"`
}

type Effective struct {
	Telemetry struct {
		Enabled bool `json:"enabled"`
	} `json:"telemetry"`
}

// Getter is the settings source; the observer passes its config Manager.
type Getter interface{ Get() userconfig.Snapshot }

type Builder struct {
	g    Getter
	path string
}

// New returns a Builder over g, whose settings come from the file at path.
func New(g Getter, path string) *Builder { return &Builder{g: g, path: path} }

// warnKeys are the settings whose fail-safe differs from their default, so a
// problem with them changes behavior the user chose.
func warnKeys() []string {
	var keys []string
	for _, d := range userconfig.Definitions() {
		if d.Default != d.FailSafe {
			keys = append(keys, d.Path)
		}
	}
	return keys
}

func isProblem(d userconfig.Diagnostic) bool {
	return d.Kind == userconfig.DiagInvalid || d.Kind == userconfig.DiagAbsent
}

// warnWorthy reports a problem diagnostic on a warn key, or on a section
// holding one.
func warnWorthy(d userconfig.Diagnostic, keys []string) bool {
	if !isProblem(d) {
		return false
	}
	for _, k := range keys {
		if d.Key == k || strings.HasPrefix(k, d.Key+".") {
			return true
		}
	}
	return false
}

// Build reports the settings in force and the current state of the file.
func (b *Builder) Build() Status {
	snap := b.g.Get()
	_, diags, err := userconfig.Load(b.path)

	st := Status{Path: b.path, Degraded: snap.Degraded, Diagnostics: []Diagnostic{}}
	st.Effective.Telemetry.Enabled = snap.Telemetry.Enabled
	problems := false
	for _, d := range diags {
		st.Diagnostics = append(st.Diagnostics, Diagnostic{Key: d.Key, Kind: string(d.Kind), Line: d.Line, Message: d.Message})
		if isProblem(d) {
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

	keys := warnKeys()
	var worthy []userconfig.Diagnostic
	for _, d := range diags {
		if warnWorthy(d, keys) {
			worthy = append(worthy, d)
		}
	}
	st.Warn = st.State == StateUnparseable || (st.State == StateInvalid && len(worthy) > 0)
	errText := ""
	if st.State == StateUnparseable {
		errText = err.Error()
	}
	st.Fingerprint = fingerprint(st.State, st.Effective.Telemetry.Enabled, worthy, errText)
	if st.Warn {
		st.Message = message(st, worthy, errText)
	}
	return st
}

func fingerprint(state State, enabled bool, worthy []userconfig.Diagnostic, errText string) string {
	b := "0"
	if enabled {
		b = "1"
	}
	entries := make([]string, len(worthy))
	for i, d := range worthy {
		entries[i] = fmt.Sprintf("%s:%s:%d", d.Key, d.Kind, d.Line)
	}
	sort.Strings(entries)
	sum := sha256.Sum256([]byte(string(state) + "\n" + b + "\n" + strings.Join(entries, "\n") + "\n" + errText))
	return hex.EncodeToString(sum[:])
}

func message(st Status, worthy []userconfig.Diagnostic, errText string) string {
	prefix := "Using your last valid settings"
	if !st.Effective.Telemetry.Enabled {
		prefix = "Telemetry is off"
	}
	var msg string
	if st.State == StateUnparseable {
		msg = fmt.Sprintf("%s: %s cannot be used: %s. Fix the file, or delete it to restore defaults on next start.", prefix, st.Path, errText)
	} else {
		parts := make([]string, len(worthy))
		for i, d := range worthy {
			parts[i] = d.Message
		}
		msg = fmt.Sprintf("%s: %s in %s. Fix the value, or delete the file to restore defaults on next start.", prefix, strings.Join(parts, "; "), st.Path)
	}
	return strings.NewReplacer("\r\n", " ", "\n", " ", "\r", " ").Replace(msg)
}
