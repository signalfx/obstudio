package otlp

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/pmetric"
)

func TestNewSplunkMetricsExporterDisabled(t *testing.T) {
	exporter, err := NewSplunkMetricsExporter(SplunkMetricsExporterConfig{})
	if err != nil {
		t.Fatalf("expected no error for disabled config, got %v", err)
	}
	if exporter != nil {
		t.Fatalf("expected nil exporter for disabled config")
	}
}

func TestNewSplunkMetricsExporterBuildsRealmEndpoint(t *testing.T) {
	exporter, err := NewSplunkMetricsExporter(SplunkMetricsExporterConfig{
		Enabled:     true,
		Realm:       "us1",
		AccessToken: "test-token",
	})
	if err != nil {
		t.Fatalf("expected exporter, got error %v", err)
	}
	defer exporter.Shutdown(context.Background())
	want := "https://ingest.us1.observability.splunkcloud.com/v2/datapoint/otlp"
	if exporter.Endpoint() != want {
		t.Fatalf("endpoint = %q, want %q", exporter.Endpoint(), want)
	}
}

func TestNewSplunkMetricsExporterPreservesExplicitEndpoint(t *testing.T) {
	exporter, err := NewSplunkMetricsExporter(SplunkMetricsExporterConfig{
		Enabled:     true,
		Endpoint:    "https://mon-ingest.signalfx.com",
		AccessToken: "test-token",
	})
	if err != nil {
		t.Fatalf("expected exporter, got error %v", err)
	}
	defer exporter.Shutdown(context.Background())
	want := []string{"https://mon-ingest.signalfx.com"}
	got := exporter.Endpoints()
	if len(got) != len(want) {
		t.Fatalf("endpoints = %#v, want %#v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("endpoint[%d] = %q, want %q", i, got[i], want[i])
		}
	}
}

func TestNewSplunkMetricsExporterRequiresRealmOrEndpoint(t *testing.T) {
	_, err := NewSplunkMetricsExporter(SplunkMetricsExporterConfig{
		Enabled:     true,
		AccessToken: "test-token",
	})
	if err == nil || !strings.Contains(err.Error(), "SPLUNK_REALM") {
		t.Fatalf("expected realm error, got %v", err)
	}
}

func TestNewSplunkMetricsExporterRequiresAccessToken(t *testing.T) {
	_, err := NewSplunkMetricsExporter(SplunkMetricsExporterConfig{
		Enabled: true,
		Realm:   "us1",
	})
	if err == nil || !strings.Contains(err.Error(), "SPLUNK_ACCESS_TOKEN") {
		t.Fatalf("expected token error, got %v", err)
	}
}

func TestSplunkMetricsExporterPostsOTLPProtobuf(t *testing.T) {
	md := createTestMetric()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method = %s, want POST", r.Method)
		}
		if r.URL.Path != "/v2/datapoint/otlp" {
			t.Errorf("path = %s, want /v2/datapoint/otlp", r.URL.Path)
		}
		if got := r.Header.Get("X-SF-Token"); got != "test-token" {
			t.Errorf("X-SF-Token = %q, want test-token", got)
		}
		if got := r.Header.Get("Content-Type"); got != "application/x-protobuf" {
			t.Errorf("Content-Type = %q, want application/x-protobuf", got)
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatalf("read body: %v", err)
		}
		got, err := (&pmetric.ProtoUnmarshaler{}).UnmarshalMetrics(body)
		if err != nil {
			t.Fatalf("unmarshal metrics: %v", err)
		}
		metrics := ConvertMetrics(got)
		if len(metrics) != 1 || metrics[0].Name != "test.metric" {
			t.Fatalf("unexpected exported metrics: %#v", metrics)
		}
		w.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()

	exporter, err := NewSplunkMetricsExporter(SplunkMetricsExporterConfig{
		Enabled:     true,
		Endpoint:    server.URL + "/v2/datapoint/otlp",
		AccessToken: "test-token",
	})
	if err != nil {
		t.Fatalf("create exporter: %v", err)
	}
	defer exporter.Shutdown(context.Background())
	if err := exporter.ExportMetrics(context.Background(), md); err != nil {
		t.Fatalf("export metrics: %v", err)
	}
}

func TestSplunkMetricsExporterReportsHTTPErrorWithoutToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
	}))
	defer server.Close()

	exporter, err := NewSplunkMetricsExporter(SplunkMetricsExporterConfig{
		Enabled:     true,
		Endpoint:    server.URL,
		AccessToken: "secret-token",
	})
	if err != nil {
		t.Fatalf("create exporter: %v", err)
	}
	defer exporter.Shutdown(context.Background())
	err = exporter.ExportMetrics(context.Background(), createTestMetric())
	if err == nil {
		t.Fatal("expected export error")
	}
	if strings.Contains(err.Error(), "secret-token") {
		t.Fatalf("export error leaked token: %v", err)
	}
	if !strings.Contains(err.Error(), "401") {
		t.Fatalf("expected status in error, got %v", err)
	}
}

func TestOTLPHTTPMetricsHandlerForwardsMetricsWhenExporterConfigured(t *testing.T) {
	s := store.New()
	exporter := &captureMetricsExporter{ch: make(chan pmetric.Metrics, 1)}
	handler := &otlpHTTPHandler{
		store:    s,
		ct:       &ConnTracker{},
		exporter: exporter,
	}

	body, err := (&pmetric.JSONMarshaler{}).MarshalMetrics(createTestMetric())
	if err != nil {
		t.Fatalf("marshal metrics: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/metrics", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}
	if got := s.Stats().DataPointCount; got != 1 {
		t.Fatalf("expected local metric storage, got %d datapoints", got)
	}

	select {
	case exported := <-exporter.ch:
		metrics := ConvertMetrics(exported)
		if len(metrics) != 1 || metrics[0].Name != "test.metric" {
			t.Fatalf("unexpected forwarded metrics: %#v", metrics)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for metrics export")
	}
}

type captureMetricsExporter struct {
	ch chan pmetric.Metrics
}

func (e *captureMetricsExporter) ExportMetrics(_ context.Context, md pmetric.Metrics) error {
	e.ch <- md
	return nil
}
