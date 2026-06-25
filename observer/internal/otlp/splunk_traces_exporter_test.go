package otlp

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

func TestNewSplunkTracesExporterDisabled(t *testing.T) {
	exporter, err := NewSplunkTracesExporter(SplunkTracesExporterConfig{})
	if err != nil {
		t.Fatalf("expected no error for disabled config, got %v", err)
	}
	if exporter != nil {
		t.Fatalf("expected nil exporter for disabled config")
	}
}

func TestNewSplunkTracesExporterBuildsRealmEndpoint(t *testing.T) {
	exporter, err := NewSplunkTracesExporter(SplunkTracesExporterConfig{
		Enabled:     true,
		Realm:       "us1",
		AccessToken: "test-token",
	})
	if err != nil {
		t.Fatalf("expected exporter, got error %v", err)
	}
	defer exporter.Shutdown(context.Background())
	want := "https://ingest.us1.observability.splunkcloud.com/v2/trace/otlp"
	if exporter.Endpoint() != want {
		t.Fatalf("endpoint = %q, want %q", exporter.Endpoint(), want)
	}
}

func TestNewSplunkTracesExporterPreservesExplicitEndpoint(t *testing.T) {
	exporter, err := NewSplunkTracesExporter(SplunkTracesExporterConfig{
		Enabled:     true,
		Endpoint:    "https://mon-ingest.signalfx.com/v2/trace/otlp",
		AccessToken: "test-token",
	})
	if err != nil {
		t.Fatalf("expected exporter, got error %v", err)
	}
	defer exporter.Shutdown(context.Background())
	want := []string{"https://mon-ingest.signalfx.com/v2/trace/otlp"}
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

func TestNewSplunkTracesExporterRequiresRealmOrEndpoint(t *testing.T) {
	_, err := NewSplunkTracesExporter(SplunkTracesExporterConfig{
		Enabled:     true,
		AccessToken: "test-token",
	})
	if err == nil || !strings.Contains(err.Error(), "SPLUNK_REALM") {
		t.Fatalf("expected realm error, got %v", err)
	}
}

func TestNewSplunkTracesExporterRequiresAccessToken(t *testing.T) {
	_, err := NewSplunkTracesExporter(SplunkTracesExporterConfig{
		Enabled: true,
		Realm:   "us1",
	})
	if err == nil || !strings.Contains(err.Error(), "SPLUNK_ACCESS_TOKEN") {
		t.Fatalf("expected token error, got %v", err)
	}
}

func TestSplunkTracesExporterPostsOTLPProtobuf(t *testing.T) {
	td := createTestSpan()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method = %s, want POST", r.Method)
		}
		if r.URL.Path != "/v2/trace/otlp" {
			t.Errorf("path = %s, want /v2/trace/otlp", r.URL.Path)
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
		got, err := (&ptrace.ProtoUnmarshaler{}).UnmarshalTraces(body)
		if err != nil {
			t.Fatalf("unmarshal traces: %v", err)
		}
		spans := ConvertTraces(got)
		if len(spans) != 1 || spans[0].Name != "test-span" {
			t.Fatalf("unexpected exported spans: %#v", spans)
		}
		w.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()

	exporter, err := NewSplunkTracesExporter(SplunkTracesExporterConfig{
		Enabled:     true,
		Endpoint:    server.URL + "/v2/trace/otlp",
		AccessToken: "test-token",
	})
	if err != nil {
		t.Fatalf("create exporter: %v", err)
	}
	defer exporter.Shutdown(context.Background())
	if err := exporter.ExportTraces(context.Background(), td); err != nil {
		t.Fatalf("export traces: %v", err)
	}
}

func TestSplunkTracesExporterReportsHTTPErrorWithoutToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
	}))
	defer server.Close()

	exporter, err := NewSplunkTracesExporter(SplunkTracesExporterConfig{
		Enabled:     true,
		Endpoint:    server.URL,
		AccessToken: "secret-token",
	})
	if err != nil {
		t.Fatalf("create exporter: %v", err)
	}
	defer exporter.Shutdown(context.Background())
	err = exporter.ExportTraces(context.Background(), createTestSpan())
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

func TestOTLPHTTPTracesHandlerForwardsTracesWhenExporterConfigured(t *testing.T) {
	s := store.New()
	exporter := &captureTracesExporter{ch: make(chan ptrace.Traces, 1)}
	handler := &otlpHTTPHandler{
		store:          s,
		ct:             &ConnTracker{},
		tracesExporter: exporter,
	}

	body, err := (&ptrace.JSONMarshaler{}).MarshalTraces(createTestSpan())
	if err != nil {
		t.Fatalf("marshal traces: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/traces", strings.NewReader(string(body)))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}
	if got := s.Stats().SpanCount; got != 1 {
		t.Fatalf("expected local span storage, got %d spans", got)
	}

	select {
	case exported := <-exporter.ch:
		spans := ConvertTraces(exported)
		if len(spans) != 1 || spans[0].Name != "test-span" {
			t.Fatalf("unexpected forwarded spans: %#v", spans)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for traces export")
	}
}

// captureTracesExporter is a test stub that captures exported traces.
type captureTracesExporter struct {
	ch chan ptrace.Traces
}

func (e *captureTracesExporter) ExportTraces(_ context.Context, td ptrace.Traces) error {
	e.ch <- td
	return nil
}
