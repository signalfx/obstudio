// Package configmanagertest provides an in-memory configmanager.ConfigManager
// for tests.
package configmanagertest

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"

	"github.com/signalfx/obstudio/observer/internal/configmanager"
)

// SetCall records one accepted Set.
type SetCall struct {
	Key   string
	Value any
}

// Mock is an in-memory ConfigManager. Only keys present in the initial values
// are known; Set rejects any other key.
type Mock struct {
	mu         sync.Mutex
	values     map[string]any
	validators map[string]func(value any) error
	specs      map[string]configmanager.KeySpec
	getErr     error
	setErr     error
	setCalls   []SetCall
}

var _ configmanager.ConfigManager = (*Mock)(nil)

// New returns a Mock seeded with flat dotted-key values, for example
// {"splunk.realm": "us1"}.
func New(initial map[string]any) *Mock {
	values := make(map[string]any, len(initial))
	for key, value := range initial {
		values[key] = value
	}
	return &Mock{
		values:     values,
		validators: map[string]func(any) error{},
		specs:      map[string]configmanager.KeySpec{},
	}
}

// WithValidator rejects Set values for key when fn returns an error; the error
// text becomes the ValidationError message.
func (m *Mock) WithValidator(key string, fn func(value any) error) *Mock {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.validators[key] = fn
	return m
}

// WithSpec declares the type and constraints of spec.Key. The spec is reported
// by Schema and enforced by Set and SetMany, ahead of any WithValidator check.
// Keys without a spec get a type inferred from their current value and no
// constraints.
func (m *Mock) WithSpec(spec configmanager.KeySpec) *Mock {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.specs[spec.Key] = spec
	return m
}

// FailGetWith makes GetAll and Get return err until cleared with nil.
func (m *Mock) FailGetWith(err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.getErr = err
}

// FailSetWith makes Set return err until cleared with nil.
func (m *Mock) FailSetWith(err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.setErr = err
}

// SetCalls returns the accepted Set calls in order.
func (m *Mock) SetCalls() []SetCall {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]SetCall(nil), m.setCalls...)
}

func (m *Mock) GetAll(_ context.Context) (map[string]any, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.getErr != nil {
		return nil, m.getErr
	}
	return m.tree(), nil
}

func (m *Mock) Get(_ context.Context, key string) (any, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.getErr != nil {
		return nil, m.getErr
	}
	if value, ok := m.values[key]; ok {
		return value, nil
	}
	var node any = m.tree()
	for _, part := range strings.Split(key, ".") {
		branch, ok := node.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("%w: %s", configmanager.ErrUnknownKey, key)
		}
		if node, ok = branch[part]; !ok {
			return nil, fmt.Errorf("%w: %s", configmanager.ErrUnknownKey, key)
		}
	}
	return node, nil
}

func (m *Mock) Set(_ context.Context, key string, value any) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.setErr != nil {
		return m.setErr
	}
	if _, ok := m.values[key]; !ok {
		return fmt.Errorf("%w: %s", configmanager.ErrUnknownKey, key)
	}
	if err := m.check(key, value); err != nil {
		return &configmanager.ValidationError{Key: key, Message: err.Error()}
	}
	m.values[key] = value
	m.setCalls = append(m.setCalls, SetCall{Key: key, Value: value})
	return nil
}

func (m *Mock) SetMany(_ context.Context, values map[string]any) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.setErr != nil {
		return m.setErr
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)

	var rejected []*configmanager.ValidationError
	for _, key := range keys {
		if _, ok := m.values[key]; !ok {
			rejected = append(rejected, &configmanager.ValidationError{Key: key, Message: "unknown configuration key"})
			continue
		}
		if err := m.check(key, values[key]); err != nil {
			rejected = append(rejected, &configmanager.ValidationError{Key: key, Message: err.Error()})
		}
	}
	if len(rejected) > 0 {
		return &configmanager.ValidationErrors{Errors: rejected}
	}
	for _, key := range keys {
		m.values[key] = values[key]
		m.setCalls = append(m.setCalls, SetCall{Key: key, Value: values[key]})
	}
	return nil
}

func (m *Mock) Schema(_ context.Context) ([]configmanager.KeySpec, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.getErr != nil {
		return nil, m.getErr
	}
	keys := make([]string, 0, len(m.values))
	for key := range m.values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	specs := make([]configmanager.KeySpec, 0, len(keys))
	for _, key := range keys {
		if spec, ok := m.specs[key]; ok {
			specs = append(specs, spec)
			continue
		}
		specs = append(specs, configmanager.KeySpec{Key: key, Type: inferType(m.values[key])})
	}
	return specs, nil
}

// check applies the key's declared spec, then its custom validator.
func (m *Mock) check(key string, value any) error {
	if spec, ok := m.specs[key]; ok {
		if err := checkSpec(spec, value); err != nil {
			return err
		}
	}
	if validate := m.validators[key]; validate != nil {
		return validate(value)
	}
	return nil
}

func checkSpec(spec configmanager.KeySpec, value any) error {
	switch spec.Type {
	case configmanager.TypeString:
		if _, ok := value.(string); !ok {
			return errors.New("must be a string")
		}
	case configmanager.TypeBoolean:
		if _, ok := value.(bool); !ok {
			return errors.New("must be true or false")
		}
	case configmanager.TypeInteger:
		number, ok := wholeNumber(value)
		if !ok {
			return errors.New("must be a whole number")
		}
		switch {
		case spec.Minimum != nil && spec.Maximum != nil && (number < *spec.Minimum || number > *spec.Maximum):
			return fmt.Errorf("must be a whole number between %d and %d", *spec.Minimum, *spec.Maximum)
		case spec.Minimum != nil && number < *spec.Minimum:
			return fmt.Errorf("must be at least %d", *spec.Minimum)
		case spec.Maximum != nil && number > *spec.Maximum:
			return fmt.Errorf("must be at most %d", *spec.Maximum)
		}
	}
	if len(spec.AllowedValues) > 0 {
		for _, allowed := range spec.AllowedValues {
			if sameValue(allowed, value) {
				return nil
			}
		}
		choices := make([]string, 0, len(spec.AllowedValues))
		for _, allowed := range spec.AllowedValues {
			choices = append(choices, fmt.Sprint(allowed))
		}
		return fmt.Errorf("must be one of: %s", strings.Join(choices, ", "))
	}
	return nil
}

func sameValue(allowed, value any) bool {
	if a, ok := wholeNumber(allowed); ok {
		b, ok := wholeNumber(value)
		return ok && a == b
	}
	return allowed == value
}

// wholeNumber accepts the float64 the API produces for JSON numbers, and Go
// integers for direct callers.
func wholeNumber(value any) (int64, bool) {
	switch number := value.(type) {
	case float64:
		if number == float64(int64(number)) {
			return int64(number), true
		}
	case int:
		return int64(number), true
	case int64:
		return number, true
	}
	return 0, false
}

func inferType(value any) configmanager.ValueType {
	switch value.(type) {
	case bool:
		return configmanager.TypeBoolean
	case string:
		return configmanager.TypeString
	}
	if _, ok := wholeNumber(value); ok {
		return configmanager.TypeInteger
	}
	return configmanager.TypeString
}

func (m *Mock) tree() map[string]any {
	root := map[string]any{}
	for key, value := range m.values {
		parts := strings.Split(key, ".")
		node := root
		for _, part := range parts[:len(parts)-1] {
			child, ok := node[part].(map[string]any)
			if !ok {
				child = map[string]any{}
				node[part] = child
			}
			node = child
		}
		node[parts[len(parts)-1]] = value
	}
	return root
}
