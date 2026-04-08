package store

import (
	"errors"
	"strings"
	"testing"
)

func TestStoreSetGetDelete(t *testing.T) {
	s := New()

	if err := s.Set("k1", "v1"); err != nil {
		t.Fatalf("Set() error = %v", err)
	}

	got, err := s.Get("k1")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if got != "v1" {
		t.Fatalf("Get() value = %q, want %q", got, "v1")
	}

	if err := s.Delete("k1"); err != nil {
		t.Fatalf("Delete() error = %v", err)
	}

	_, err = s.Get("k1")
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("Get() error = %v, want ErrNotFound", err)
	}
}

func TestStoreListByPrefix(t *testing.T) {
	s := New()
	mustSet(t, s, "app:1", "x")
	mustSet(t, s, "app:2", "y")
	mustSet(t, s, "other", "z")

	keys, err := s.ListByPrefix("app:")
	if err != nil {
		t.Fatalf("ListByPrefix() error = %v", err)
	}

	want := []string{"app:1", "app:2"}
	if len(keys) != len(want) {
		t.Fatalf("ListByPrefix() len = %d, want %d", len(keys), len(want))
	}
	for i := range want {
		if keys[i] != want[i] {
			t.Fatalf("ListByPrefix() key[%d] = %q, want %q", i, keys[i], want[i])
		}
	}
}

func TestStoreLimits(t *testing.T) {
	s := New()
	largeKey := strings.Repeat("k", MaxKeySize+1)
	if err := s.Set(largeKey, "v"); !errors.Is(err, ErrKeyTooLarge) {
		t.Fatalf("Set() error = %v, want ErrKeyTooLarge", err)
	}

	largeValue := strings.Repeat("v", MaxValueSize+1)
	if err := s.Set("k", largeValue); !errors.Is(err, ErrValueTooLarge) {
		t.Fatalf("Set() error = %v, want ErrValueTooLarge", err)
	}
}

func TestDeleteNotFound(t *testing.T) {
	s := New()
	err := s.Delete("missing")
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("Delete() error = %v, want ErrNotFound", err)
	}
}

func mustSet(t *testing.T, s *Store, key, value string) {
	t.Helper()
	if err := s.Set(key, value); err != nil {
		t.Fatalf("Set(%q, %q) error = %v", key, value, err)
	}
}
