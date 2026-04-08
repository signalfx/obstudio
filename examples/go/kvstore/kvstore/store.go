package kvstore

import (
	"bytes"
	"container/list"
	"errors"
	"fmt"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
)

const (
	// MaxKeySize is the maximum allowed key size in bytes.
	MaxKeySize = 64
	// MaxValueSize is the maximum allowed value size in bytes.
	MaxValueSize = 4 * 1024 * 1024
)

var (
	// ErrInvalidKey is returned when a key does not match key constraints.
	ErrInvalidKey = errors.New("invalid key")
	// ErrValueTooLarge is returned when a value is larger than MaxValueSize.
	ErrValueTooLarge = errors.New("value too large")
	// ErrNotFound is returned when a key does not exist.
	ErrNotFound = errors.New("key not found")
)

var keyPattern = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// StoreConfig configures a Store.
type StoreConfig struct {
	Capacity int
	DataDir  string
	Logger   *log.Logger
}

// Store is an in-memory key/value store with asynchronous filesystem persistence.
type Store struct {
	mu       sync.RWMutex
	capacity int
	dataDir  string
	logger   *log.Logger
	items    map[string]*entry
	lru      *list.List

	indexMu sync.RWMutex
	index   map[string]map[string]struct{}

	indexCh chan indexEvent
	doneCh  chan struct{}
	wg      sync.WaitGroup
}

type entry struct {
	key   string
	value []byte
	node  *list.Element
}

type indexEvent struct {
	kind string
	key  string
	old  []byte
	new  []byte
}

// NewStore creates a new Store and loads persisted data from disk.
func NewStore(cfg StoreConfig) (*Store, error) {
	if cfg.Capacity <= 0 {
		return nil, fmt.Errorf("capacity must be positive")
	}
	if cfg.DataDir == "" {
		return nil, fmt.Errorf("data directory must be provided")
	}
	if err := os.MkdirAll(cfg.DataDir, 0o755); err != nil {
		return nil, err
	}
	logger := cfg.Logger
	if logger == nil {
		logger = log.Default()
	}

	s := &Store{
		capacity: cfg.Capacity,
		dataDir:  cfg.DataDir,
		logger:   logger,
		items:    make(map[string]*entry),
		lru:      list.New(),
		index:    make(map[string]map[string]struct{}),
		indexCh:  make(chan indexEvent, 1024),
		doneCh:   make(chan struct{}),
	}
	s.wg.Add(1)
	go s.indexLoop()
	if err := s.loadFromDisk(); err != nil {
		return nil, err
	}
	return s, nil
}

// Close waits for background goroutines to stop.
func (s *Store) Close() {
	close(s.doneCh)
	s.wg.Wait()
}

// Get returns the value for a key and marks the key as recently used.
func (s *Store) Get(key string) ([]byte, error) {
	if err := validateKey(key); err != nil {
		return nil, err
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	e, ok := s.items[key]
	if !ok {
		return nil, ErrNotFound
	}
	s.lru.MoveToFront(e.node)
	v := append([]byte(nil), e.value...)
	return v, nil
}

// Set stores a key/value pair in memory and persists it asynchronously.
func (s *Store) Set(key string, value []byte) error {
	if err := validateKey(key); err != nil {
		return err
	}
	if len(value) > MaxValueSize {
		return ErrValueTooLarge
	}

	valueCopy := append([]byte(nil), value...)
	var oldValue []byte

	s.mu.Lock()
	if e, ok := s.items[key]; ok {
		oldValue = append([]byte(nil), e.value...)
		e.value = valueCopy
		s.lru.MoveToFront(e.node)
	} else {
		node := s.lru.PushFront(key)
		s.items[key] = &entry{key: key, value: valueCopy, node: node}
	}
	for len(s.items) > s.capacity {
		s.evictOldestLocked()
	}
	s.mu.Unlock()

	s.enqueueIndex(indexEvent{kind: "set", key: key, old: oldValue, new: valueCopy})

	s.wg.Add(1)
	go s.persistAsync(key, valueCopy)
	return nil
}

// Delete removes a key from memory and disk.
func (s *Store) Delete(key string) error {
	if err := validateKey(key); err != nil {
		return err
	}

	var oldValue []byte
	s.mu.Lock()
	e, ok := s.items[key]
	if ok {
		oldValue = append([]byte(nil), e.value...)
		s.lru.Remove(e.node)
		delete(s.items, key)
	}
	s.mu.Unlock()

	if ok {
		s.enqueueIndex(indexEvent{kind: "delete", key: key, old: oldValue})
	}

	if err := os.Remove(filepath.Join(s.dataDir, key)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if !ok {
		return ErrNotFound
	}
	return nil
}

// Search returns keys where values contain the exact word.
func (s *Store) Search(word string) []string {
	s.indexMu.RLock()
	defer s.indexMu.RUnlock()
	keys := s.index[word]
	if len(keys) == 0 {
		return nil
	}
	out := make([]string, 0, len(keys))
	for k := range keys {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func (s *Store) enqueueIndex(ev indexEvent) {
	select {
	case s.indexCh <- ev:
	case <-s.doneCh:
		return
	default:
		go func() {
			select {
			case s.indexCh <- ev:
			case <-s.doneCh:
			}
		}()
	}
}

func (s *Store) persistAsync(key string, value []byte) {
	defer s.wg.Done()
	path := filepath.Join(s.dataDir, key)
	if err := os.WriteFile(path, value, 0o644); err != nil {
		s.logger.Printf("failed persisting key %q: %v", key, err)
		s.mu.Lock()
		e, ok := s.items[key]
		if ok && bytes.Equal(e.value, value) {
			old := append([]byte(nil), e.value...)
			s.lru.Remove(e.node)
			delete(s.items, key)
			s.mu.Unlock()
			s.enqueueIndex(indexEvent{kind: "delete", key: key, old: old})
			return
		}
		s.mu.Unlock()
	}
}

func (s *Store) evictOldestLocked() {
	back := s.lru.Back()
	if back == nil {
		return
	}
	key := back.Value.(string)
	e := s.items[key]
	old := append([]byte(nil), e.value...)
	s.lru.Remove(back)
	delete(s.items, key)
	s.enqueueIndex(indexEvent{kind: "delete", key: key, old: old})
}

func (s *Store) indexLoop() {
	defer s.wg.Done()
	for {
		select {
		case <-s.doneCh:
			return
		case ev := <-s.indexCh:
			s.indexMu.Lock()
			s.applyIndexEventLocked(ev)
			s.indexMu.Unlock()
		}
	}
}

func (s *Store) applyIndexEventLocked(ev indexEvent) {
	switch ev.kind {
	case "set":
		for _, w := range words(ev.old) {
			s.removeWordKeyLocked(w, ev.key)
		}
		for _, w := range words(ev.new) {
			set := s.index[w]
			if set == nil {
				set = make(map[string]struct{})
				s.index[w] = set
			}
			set[ev.key] = struct{}{}
		}
	case "delete":
		for _, w := range words(ev.old) {
			s.removeWordKeyLocked(w, ev.key)
		}
	}
}

func (s *Store) removeWordKeyLocked(word, key string) {
	set := s.index[word]
	if set == nil {
		return
	}
	delete(set, key)
	if len(set) == 0 {
		delete(s.index, word)
	}
}

func (s *Store) loadFromDisk() error {
	return filepath.WalkDir(s.dataDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			if path == s.dataDir {
				return nil
			}
			return filepath.SkipDir
		}
		key := filepath.Base(path)
		if err := validateKey(key); err != nil {
			s.logger.Printf("skipping invalid key file %q: %v", key, err)
			return nil
		}
		value, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if len(value) > MaxValueSize {
			s.logger.Printf("skipping oversized value for key %q", key)
			return nil
		}

		s.mu.Lock()
		if _, exists := s.items[key]; !exists {
			node := s.lru.PushFront(key)
			s.items[key] = &entry{key: key, value: value, node: node}
			for len(s.items) > s.capacity {
				s.evictOldestLocked()
			}
		}
		s.mu.Unlock()
		s.enqueueIndex(indexEvent{kind: "set", key: key, new: value})
		return nil
	})
}

func words(value []byte) []string {
	if len(value) == 0 {
		return nil
	}
	return strings.Fields(string(value))
}

func validateKey(key string) error {
	if key == "" || len(key) > MaxKeySize || !keyPattern.MatchString(key) {
		return ErrInvalidKey
	}
	return nil
}
