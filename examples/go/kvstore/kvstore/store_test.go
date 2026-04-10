package kvstore

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

func TestSetGetDelete(t *testing.T) {
	dir := t.TempDir()
	s, err := NewStore(StoreConfig{Capacity: 10, DataDir: dir})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()

	if err := s.Set("k1", []byte("hello world")); err != nil {
		t.Fatalf("Set: %v", err)
	}
	waitFor(t, time.Second, func() bool {
		_, err := os.Stat(filepath.Join(dir, "k1"))
		return err == nil
	})

	got, err := s.Get("k1")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if string(got) != "hello world" {
		t.Fatalf("unexpected value: %q", got)
	}

	if err := s.Delete("k1"); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, err := s.Get("k1"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestLRUEviction(t *testing.T) {
	s, err := NewStore(StoreConfig{Capacity: 2, DataDir: t.TempDir()})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()

	_ = s.Set("a", []byte("x"))
	_ = s.Set("b", []byte("y"))
	_, _ = s.Get("a")
	_ = s.Set("c", []byte("z"))

	if _, err := s.Get("b"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected key b evicted, got %v", err)
	}
	if _, err := s.Get("a"); err != nil {
		t.Fatalf("expected key a present: %v", err)
	}
	if _, err := s.Get("c"); err != nil {
		t.Fatalf("expected key c present: %v", err)
	}
}

func TestValidation(t *testing.T) {
	s, err := NewStore(StoreConfig{Capacity: 1, DataDir: t.TempDir()})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()

	if err := s.Set("bad key", []byte("x")); !errors.Is(err, ErrInvalidKey) {
		t.Fatalf("expected ErrInvalidKey, got %v", err)
	}
	big := make([]byte, MaxValueSize+1)
	if err := s.Set("ok", big); !errors.Is(err, ErrValueTooLarge) {
		t.Fatalf("expected ErrValueTooLarge, got %v", err)
	}
}

func TestSearchIndex(t *testing.T) {
	s, err := NewStore(StoreConfig{Capacity: 10, DataDir: t.TempDir()})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()

	_ = s.Set("k1", []byte("foo bar"))
	_ = s.Set("k2", []byte("bar baz"))
	waitFor(t, time.Second, func() bool {
		keys := s.Search("bar")
		return reflect.DeepEqual(keys, []string{"k1", "k2"})
	})

	_ = s.Delete("k1")
	waitFor(t, time.Second, func() bool {
		keys := s.Search("bar")
		return reflect.DeepEqual(keys, []string{"k2"})
	})
}

func TestLoadFromDiskOnStartup(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "alpha"), []byte("hello world"), 0o644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	s, err := NewStore(StoreConfig{Capacity: 10, DataDir: dir})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()

	got, err := s.Get("alpha")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if string(got) != "hello world" {
		t.Fatalf("unexpected value: %q", got)
	}

	waitFor(t, time.Second, func() bool {
		keys := s.Search("hello")
		return reflect.DeepEqual(keys, []string{"alpha"})
	})
}

func waitFor(t *testing.T, timeout time.Duration, fn func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if fn() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("condition not met before timeout")
}
