package store

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"sync"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/trace"
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
	s := &Store{data: make(map[string]string)}
	registerStoreGauge(s)
	return s
}

// Set stores value under key.
func (s *Store) Set(ctx context.Context, key, value string) error {
	ctx, span := otel.Tracer("kvstore/internal/store").Start(ctx, "kvstore.store.set",
		trace.WithAttributes(attribute.String("kvstore.operation", "set")))
	defer span.End()

	start := time.Now()
	if err := validateKey(key); err != nil {
		recordStoreOutcome(ctx, "set", start, err)
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return err
	}
	if err := validateValue(value); err != nil {
		recordStoreOutcome(ctx, "set", start, err)
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return err
	}

	s.mu.Lock()
	s.data[key] = value
	s.mu.Unlock()

	recordStoreOutcome(ctx, "set", start, nil)
	return nil
}

// Get returns the value stored under key.
func (s *Store) Get(ctx context.Context, key string) (string, error) {
	ctx, span := otel.Tracer("kvstore/internal/store").Start(ctx, "kvstore.store.get",
		trace.WithAttributes(attribute.String("kvstore.operation", "get")))
	defer span.End()

	start := time.Now()
	if err := validateKey(key); err != nil {
		recordStoreOutcome(ctx, "get", start, err)
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return "", err
	}

	s.mu.RLock()
	value, ok := s.data[key]
	s.mu.RUnlock()
	if !ok {
		recordStoreOutcome(ctx, "get", start, ErrNotFound)
		span.RecordError(ErrNotFound)
		span.SetStatus(codes.Error, ErrNotFound.Error())
		return "", ErrNotFound
	}

	recordStoreOutcome(ctx, "get", start, nil)
	return value, nil
}

// Delete removes key from the store.
func (s *Store) Delete(ctx context.Context, key string) error {
	ctx, span := otel.Tracer("kvstore/internal/store").Start(ctx, "kvstore.store.delete",
		trace.WithAttributes(attribute.String("kvstore.operation", "delete")))
	defer span.End()

	start := time.Now()
	if err := validateKey(key); err != nil {
		recordStoreOutcome(ctx, "delete", start, err)
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return err
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.data[key]; !ok {
		recordStoreOutcome(ctx, "delete", start, ErrNotFound)
		span.RecordError(ErrNotFound)
		span.SetStatus(codes.Error, ErrNotFound.Error())
		return ErrNotFound
	}
	delete(s.data, key)

	recordStoreOutcome(ctx, "delete", start, nil)
	return nil
}

// ListByPrefix returns all keys that start with prefix.
func (s *Store) ListByPrefix(ctx context.Context, prefix string) ([]string, error) {
	ctx, span := otel.Tracer("kvstore/internal/store").Start(ctx, "kvstore.store.list",
		trace.WithAttributes(attribute.String("kvstore.operation", "list")))
	defer span.End()

	start := time.Now()
	if len(prefix) > MaxKeySize {
		err := fmt.Errorf("invalid prefix: %w", ErrKeyTooLarge)
		recordStoreOutcome(ctx, "list", start, err)
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return nil, err
	}

	s.mu.RLock()
	keys := make([]string, 0)
	for key := range s.data {
		if len(key) >= len(prefix) && key[:len(prefix)] == prefix {
			keys = append(keys, key)
		}
	}
	s.mu.RUnlock()

	recordStoreOutcome(ctx, "list", start, nil)
	sort.Strings(keys)
	return keys, nil
}

func (s *Store) keyCount() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.data)
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

func registerStoreGauge(s *Store) {
	meter := otel.GetMeterProvider().Meter("kvstore/internal/store")
	gauge, err := meter.Int64ObservableGauge(
		"kvstore.store.keys",
		metric.WithDescription("Current number of keys in the store"),
		metric.WithUnit("{keys}"),
	)
	if err != nil {
		return
	}

	_, _ = meter.RegisterCallback(func(ctx context.Context, observer metric.Observer) error {
		observer.ObserveInt64(gauge, int64(s.keyCount()))
		return nil
	}, gauge)
}

func recordStoreOutcome(ctx context.Context, operation string, start time.Time, err error) {
	attrs := metric.WithAttributes(attribute.String("kvstore.operation", operation))
	meter := otel.GetMeterProvider().Meter("kvstore/internal/store")
	operationCount, countErr := meter.Int64Counter(
		"kvstore.store.operation.count",
		metric.WithDescription("Total in-memory store operations"),
		metric.WithUnit("{operations}"),
	)
	if countErr == nil {
		operationCount.Add(ctx, 1, attrs)
	}

	operationDuration, durationErr := meter.Float64Histogram(
		"kvstore.store.operation.duration",
		metric.WithDescription("Store operation duration"),
		metric.WithUnit("s"),
	)
	if durationErr == nil {
		operationDuration.Record(ctx, time.Since(start).Seconds(), attrs)
	}

	if errors.Is(err, ErrNotFound) {
		notFoundCount, notFoundErr := meter.Int64Counter(
			"kvstore.store.not_found.count",
			metric.WithDescription("Total store not-found results"),
			metric.WithUnit("{responses}"),
		)
		if notFoundErr == nil {
			notFoundCount.Add(ctx, 1, attrs)
		}
	}
}
