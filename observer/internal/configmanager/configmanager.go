// Package configmanager defines the contract between the configuration REST
// API and whatever component owns config.yaml. The API depends only on this
// package, so the real manager and the in-memory mock in configmanagertest are
// interchangeable.
package configmanager

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"unicode"
	"unicode/utf8"
)

// ErrUnknownKey is returned (possibly wrapped) when a key does not exist.
var ErrUnknownKey = errors.New("unknown configuration key")

// ValidationError reports that a well-formed value was rejected for a key.
// Message is shown to API clients, so it must not contain secrets.
type ValidationError struct {
	Key     string
	Message string
}

func (e *ValidationError) Error() string {
	return "invalid value for " + e.Key + ": " + e.Message
}

// ValidationErrors reports every rejected key from a SetMany call, so a client
// can show all problems at once. Unknown keys are reported here too, with a
// message such as "unknown configuration key".
type ValidationErrors struct {
	Errors []*ValidationError
}

func (e *ValidationErrors) Error() string {
	messages := make([]string, 0, len(e.Errors))
	for _, err := range e.Errors {
		messages = append(messages, err.Error())
	}
	return strings.Join(messages, "; ")
}

// ValueType is the data type of a configuration value.
type ValueType string

const (
	TypeString  ValueType = "string"
	TypeBoolean ValueType = "boolean"
	TypeInteger ValueType = "integer"
)

// Limits on the human-readable text in a KeySpec, in characters.
const (
	MaxLabelLength       = 40
	MaxDescriptionLength = 120
)

// KeySpec describes one settable configuration key. AllowedValues, Minimum and
// Maximum are optional constraints: AllowedValues is an exhaustive list (for
// example an enum of strings), and Minimum/Maximum bound integer values.
//
// Label and Description are optional plain text for people. Label is a short
// name for the setting (at most MaxLabelLength characters); Description is one
// sentence saying what it does (at most MaxDescriptionLength characters). Both
// must be a single line with no surrounding whitespace.
type KeySpec struct {
	Key           string    `json:"key"`
	Type          ValueType `json:"type"`
	Label         string    `json:"label,omitempty"`
	Description   string    `json:"description,omitempty"`
	AllowedValues []any     `json:"allowedValues,omitempty"`
	Minimum       *int64    `json:"minimum,omitempty"`
	Maximum       *int64    `json:"maximum,omitempty"`
}

// Validate reports whether the spec is well formed: it has a key and a type,
// and its label and description respect the documented limits.
func (s KeySpec) Validate() error {
	if s.Key == "" {
		return errors.New("key spec has no key")
	}
	if s.Type == "" {
		return fmt.Errorf("key spec %q has no type", s.Key)
	}
	if err := validateText("label", s.Label, MaxLabelLength); err != nil {
		return fmt.Errorf("key spec %q: %w", s.Key, err)
	}
	if err := validateText("description", s.Description, MaxDescriptionLength); err != nil {
		return fmt.Errorf("key spec %q: %w", s.Key, err)
	}
	return nil
}

func validateText(name, text string, maxLength int) error {
	if text == "" {
		return nil
	}
	if length := utf8.RuneCountInString(text); length > maxLength {
		return fmt.Errorf("%s is %d characters, the limit is %d", name, length, maxLength)
	}
	if strings.TrimSpace(text) != text {
		return fmt.Errorf("%s must not have leading or trailing whitespace", name)
	}
	if strings.IndexFunc(text, unicode.IsControl) >= 0 {
		return fmt.Errorf("%s must be a single line without control characters", name)
	}
	return nil
}

// ConfigManager reads, validates and persists configuration values.
// Implementations must be safe for concurrent use.
//
// Keys are dotted paths into the configuration tree (for example
// "splunk.realm"). Values are JSON-decoded by the API before they reach the
// manager: strings, bool, float64 for every number, []any, map[string]any, or
// nil.
type ConfigManager interface {
	// GetAll returns the whole configuration as a nested map.
	GetAll(ctx context.Context) (map[string]any, error)
	// Get returns the value at key. It returns ErrUnknownKey when the key does
	// not exist.
	Get(ctx context.Context, key string) (any, error)
	// Set validates value and, if valid, persists it at key. It returns
	// ErrUnknownKey for an unknown key and *ValidationError for a rejected
	// value. A rejected value must leave the stored configuration unchanged.
	Set(ctx context.Context, key string, value any) error
	// SetMany validates every entry and persists them all or none. If any
	// entry is rejected (including unknown keys) it returns *ValidationErrors
	// listing every rejected key and leaves the stored configuration
	// unchanged. Keys are dotted leaf paths, as for Set.
	SetMany(ctx context.Context, values map[string]any) error
	// Schema describes every settable key. It must agree with what Set and
	// SetMany accept: a value that satisfies a key's spec must not be rejected
	// for type, allowed-value or range reasons.
	Schema(ctx context.Context) ([]KeySpec, error)
}
