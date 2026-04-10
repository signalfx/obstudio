package kvstore

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/sdk/metric"
	metricdata "go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

func TestAPIInstrumentationRecordsMetricsAndSpans(t *testing.T) {
	reader, spans := installTestTelemetry(t)

	s, err := NewStore(StoreConfig{Capacity: 10, DataDir: t.TempDir()})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()

	ts := httptest.NewServer(NewAPI(s).Handler())
	defer ts.Close()

	req, _ := http.NewRequest(http.MethodPut, ts.URL+"/kv/test", http.NoBody)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("PUT: %v", err)
	}
	resp.Body.Close()

	resp, err = http.Get(ts.URL + "/kv/test")
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	resp.Body.Close()

	resp, err = http.Get(ts.URL + "/kv/missing")
	if err != nil {
		t.Fatalf("GET missing: %v", err)
	}
	resp.Body.Close()

	metrics := collectMetrics(t, reader)
	assertMetricNames(t, metrics,
		"http.server.request.count",
		"http.server.request.errors",
		"kvstore.store.operation.duration",
		"kvstore.store.operation.errors",
	)

	assertSpanNames(t, spans.Ended(),
		"/kv/{key}",
		"kvstore.store.set",
		"kvstore.store.get",
	)
}

func TestStoreInstrumentationRecordsPersistenceAndCapacityMetrics(t *testing.T) {
	reader, spans := installTestTelemetry(t)

	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "alpha"), []byte("hello world"), 0o644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	s, err := NewStore(StoreConfig{Capacity: 1, DataDir: dir})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()

	s.dataDir = filepath.Join(dir, "missing", "nested")
	if err := s.Set("beta", []byte("value")); err != nil {
		t.Fatalf("Set: %v", err)
	}

	waitFor(t, time.Second, func() bool {
		_, err := s.Get("beta")
		return err == ErrNotFound
	})

	metrics := collectMetrics(t, reader)
	assertMetricNames(t, metrics,
		"kvstore.persistence.load.duration",
		"kvstore.persistence.write.duration",
		"kvstore.persistence.write.errors",
		"kvstore.store.evictions.count",
		"kvstore.index.backlog",
	)

	assertSpanNames(t, spans.Ended(),
		"kvstore.persistence.load",
		"kvstore.persistence.write",
	)
}

func installTestTelemetry(t *testing.T) (*metric.ManualReader, *tracetest.SpanRecorder) {
	t.Helper()

	reader := metric.NewManualReader()
	mp := metric.NewMeterProvider(metric.WithReader(reader))

	spanRecorder := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider()
	tp.RegisterSpanProcessor(spanRecorder)

	prevTP := otel.GetTracerProvider()
	prevMP := otel.GetMeterProvider()
	otel.SetTracerProvider(tp)
	otel.SetMeterProvider(mp)

	t.Cleanup(func() {
		otel.SetTracerProvider(prevTP)
		otel.SetMeterProvider(prevMP)
		_ = tp.Shutdown(context.Background())
	})

	return reader, spanRecorder
}

func collectMetrics(t *testing.T, reader *metric.ManualReader) metricdata.ResourceMetrics {
	t.Helper()

	var metrics metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &metrics); err != nil {
		t.Fatalf("Collect: %v", err)
	}
	return metrics
}

func assertMetricNames(t *testing.T, metrics metricdata.ResourceMetrics, names ...string) {
	t.Helper()

	seen := make(map[string]bool)
	for _, scopeMetric := range metrics.ScopeMetrics {
		for _, m := range scopeMetric.Metrics {
			seen[m.Name] = true
		}
	}

	for _, name := range names {
		if !seen[name] {
			t.Fatalf("metric %q not found; saw %v", name, mapKeys(seen))
		}
	}
}

func assertSpanNames(t *testing.T, spans []sdktrace.ReadOnlySpan, names ...string) {
	t.Helper()

	seen := make(map[string]bool)
	for _, span := range spans {
		seen[span.Name()] = true
	}

	for _, name := range names {
		if !seen[name] {
			t.Fatalf("span %q not found; saw %v", name, mapKeys(seen))
		}
	}
}

func mapKeys[K comparable](m map[K]bool) []K {
	keys := make([]K, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}
