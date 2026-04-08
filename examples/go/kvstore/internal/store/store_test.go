package store

import (
	"context"
	"errors"
	"strings"
	"testing"

	"go.opentelemetry.io/otel"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

func TestStoreSetGetDelete(t *testing.T) {
	restore := installStoreTestTelemetry()
	defer restore()

	s := New()

	if err := s.Set(context.Background(), "k1", "v1"); err != nil {
		t.Fatalf("Set() error = %v", err)
	}

	got, err := s.Get(context.Background(), "k1")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if got != "v1" {
		t.Fatalf("Get() value = %q, want %q", got, "v1")
	}

	if err := s.Delete(context.Background(), "k1"); err != nil {
		t.Fatalf("Delete() error = %v", err)
	}

	_, err = s.Get(context.Background(), "k1")
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("Get() error = %v, want ErrNotFound", err)
	}
}

func TestStoreListByPrefix(t *testing.T) {
	restore := installStoreTestTelemetry()
	defer restore()

	s := New()
	mustSet(t, s, "app:1", "x")
	mustSet(t, s, "app:2", "y")
	mustSet(t, s, "other", "z")

	keys, err := s.ListByPrefix(context.Background(), "app:")
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
	restore := installStoreTestTelemetry()
	defer restore()

	s := New()
	largeKey := strings.Repeat("k", MaxKeySize+1)
	if err := s.Set(context.Background(), largeKey, "v"); !errors.Is(err, ErrKeyTooLarge) {
		t.Fatalf("Set() error = %v, want ErrKeyTooLarge", err)
	}

	largeValue := strings.Repeat("v", MaxValueSize+1)
	if err := s.Set(context.Background(), "k", largeValue); !errors.Is(err, ErrValueTooLarge) {
		t.Fatalf("Set() error = %v, want ErrValueTooLarge", err)
	}
}

func TestDeleteNotFound(t *testing.T) {
	restore := installStoreTestTelemetry()
	defer restore()

	s := New()
	err := s.Delete(context.Background(), "missing")
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("Delete() error = %v, want ErrNotFound", err)
	}
}

func TestStoreTelemetry(t *testing.T) {
	reader, recorder, restore := installStoreTestTelemetryWithState()
	defer restore()

	s := New()
	ctx := context.Background()

	mustStoreSet(t, s, ctx, "app:1", "x")
	if _, err := s.Get(ctx, "app:1"); err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if _, err := s.ListByPrefix(ctx, "app:"); err != nil {
		t.Fatalf("ListByPrefix() error = %v", err)
	}
	if err := s.Delete(ctx, "app:1"); err != nil {
		t.Fatalf("Delete() error = %v", err)
	}
	if _, err := s.Get(ctx, "app:1"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("Get() error = %v, want ErrNotFound", err)
	}

	metrics := collectStoreMetrics(t, reader)
	if got := sumStoreMetric(metrics, "kvstore.store.operation.count"); got != 5 {
		t.Fatalf("operation count = %d, want 5", got)
	}
	if got := sumStoreMetric(metrics, "kvstore.store.not_found.count"); got != 1 {
		t.Fatalf("not found count = %d, want 1", got)
	}
	if got := countHistogramPoints(metrics, "kvstore.store.operation.duration"); got != 5 {
		t.Fatalf("duration count = %d, want 5", got)
	}
	if !gaugeHasValue(metrics, "kvstore.store.keys", 0) {
		t.Fatal("expected key gauge to report 0")
	}

	if len(recorder.Ended()) != 5 {
		t.Fatalf("span count = %d, want 5", len(recorder.Ended()))
	}
}

func mustSet(t *testing.T, s *Store, key, value string) {
	t.Helper()
	if err := s.Set(context.Background(), key, value); err != nil {
		t.Fatalf("Set(%q, %q) error = %v", key, value, err)
	}
}

func mustStoreSet(t *testing.T, s *Store, ctx context.Context, key, value string) {
	t.Helper()
	if err := s.Set(ctx, key, value); err != nil {
		t.Fatalf("Set(%q, %q) error = %v", key, value, err)
	}
}

func installStoreTestTelemetry() func() {
	_, _, restore := installStoreTestTelemetryWithState()
	return restore
}

func installStoreTestTelemetryWithState() (*sdkmetric.ManualReader, *tracetest.SpanRecorder, func()) {
	tpPrev := otel.GetTracerProvider()
	mpPrev := otel.GetMeterProvider()

	recorder := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider()
	tp.RegisterSpanProcessor(recorder)

	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))

	otel.SetTracerProvider(tp)
	otel.SetMeterProvider(mp)

	return reader, recorder, func() {
		_ = tp.Shutdown(context.Background())
		_ = mp.Shutdown(context.Background())
		otel.SetTracerProvider(tpPrev)
		otel.SetMeterProvider(mpPrev)
	}
}

func collectStoreMetrics(t *testing.T, reader *sdkmetric.ManualReader) metricdata.ResourceMetrics {
	t.Helper()

	var rm metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &rm); err != nil {
		t.Fatalf("collect metrics: %v", err)
	}
	return rm
}

func sumStoreMetric(rm metricdata.ResourceMetrics, name string) int64 {
	var total int64
	for _, sm := range rm.ScopeMetrics {
		for _, metric := range sm.Metrics {
			if metric.Name != name {
				continue
			}
			switch data := metric.Data.(type) {
			case metricdata.Sum[int64]:
				for _, dp := range data.DataPoints {
					total += dp.Value
				}
			}
		}
	}
	return total
}

func countHistogramPoints(rm metricdata.ResourceMetrics, name string) uint64 {
	var total uint64
	for _, sm := range rm.ScopeMetrics {
		for _, metric := range sm.Metrics {
			if metric.Name != name {
				continue
			}
			switch data := metric.Data.(type) {
			case metricdata.Histogram[float64]:
				for _, dp := range data.DataPoints {
					total += dp.Count
				}
			}
		}
	}
	return total
}

func gaugeHasValue(rm metricdata.ResourceMetrics, name string, want int64) bool {
	for _, sm := range rm.ScopeMetrics {
		for _, metric := range sm.Metrics {
			if metric.Name != name {
				continue
			}
			switch data := metric.Data.(type) {
			case metricdata.Gauge[int64]:
				for _, dp := range data.DataPoints {
					if dp.Value == want {
						return true
					}
				}
			}
		}
	}
	return false
}
