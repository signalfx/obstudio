package store

import (
	"errors"
	"fmt"
	"sort"
	"sync"
)

const (
	// MaxKeySize is the maximum key size in bytes.
	MaxKeySize = 256
	// MaxValueSize is the maximum value size in bytes.
	MaxValueSize = 4 * 1024 * 1024
)

var (
	// ErrNotFound indicates the key does not exist in the store.
	ErrNotFound = errors.New("key not found")
	// ErrKeyTooLarge indicates the key exceeds MaxKeySize.
	ErrKeyTooLarge = errors.New("key exceeds 256-byte limit")
	// ErrValueTooLarge indicates the value exceeds MaxValueSize.
	ErrValueTooLarge = errors.New("value exceeds 4MiB limit")
)

// Store is an in-memory key/value database safe for concurrent access.
type Store struct {
	mu   sync.RWMutex
	data map[string]string
}

// New creates a new empty Store.
func New() *Store {
	return &Store{data: make(map[string]string)}
}

// Set stores value under key.
func (s *Store) Set(key, value string) error {
	if err := validateKey(key); err != nil {
		return err
	}
	if err := validateValue(value); err != nil {
		return err
	}

	s.mu.Lock()
	s.data[key] = value
	s.mu.Unlock()

	return nil
}

// Get returns the value stored under key.
func (s *Store) Get(key string) (string, error) {
	if err := validateKey(key); err != nil {
		return "", err
	}

	s.mu.RLock()
	value, ok := s.data[key]
	s.mu.RUnlock()
	if !ok {
		return "", ErrNotFound
	}

	return value, nil
}

// Delete removes key from the store.
func (s *Store) Delete(key string) error {
	if err := validateKey(key); err != nil {
		return err
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.data[key]; !ok {
		return ErrNotFound
	}
	delete(s.data, key)

	return nil
}

// ListByPrefix returns all keys that start with prefix.
func (s *Store) ListByPrefix(prefix string) ([]string, error) {
	if len(prefix) > MaxKeySize {
		return nil, fmt.Errorf("invalid prefix: %w", ErrKeyTooLarge)
	}

	s.mu.RLock()
	keys := make([]string, 0)
	for key := range s.data {
		if len(key) >= len(prefix) && key[:len(prefix)] == prefix {
			keys = append(keys, key)
		}
	}
	s.mu.RUnlock()

	sort.Strings(keys)
	return keys, nil
}

func validateKey(key string) error {
	if len(key) > MaxKeySize {
		return fmt.Errorf("invalid key: %w", ErrKeyTooLarge)
	}
	return nil
}

func validateValue(value string) error {
	if len(value) > MaxValueSize {
		return fmt.Errorf("invalid value: %w", ErrValueTooLarge)
	}
	return nil
}
