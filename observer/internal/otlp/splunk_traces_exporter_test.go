package otlp

import (
	"context"
	"errors"
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

func TestSplunkTracesExportControllerTracksRedactedActivity(t *testing.T) {
	controller := &SplunkTracesExportController{
		config: SplunkTracesExporterConfig{
			Enabled:     true,
			Realm:       "us0",
			AccessToken: "secret-token",
		},
		exporter: &stubTracesExporterRuntime{},
	}

	if err := controller.ExportTraces(context.Background(), createTestSpan()); err != nil {
		t.Fatalf("export traces: %v", err)
	}
	status := controller.Status()
	if status.ExportedBatches != 1 || status.ExportedSpans != 1 || status.FailedBatches != 0 {
		t.Fatalf("unexpected success status: %#v", status)
	}
	if status.LastExport == nil || !status.LastExport.Success {
		t.Fatalf("expected successful last export, got %#v", status.LastExport)
	}

	controller.mu.Lock()
	controller.exporter = &stubTracesExporterRuntime{err: errors.New("backend echoed secret-token")}
	controller.mu.Unlock()
	if err := controller.ExportTraces(context.Background(), createTestSpan()); err == nil {
		t.Fatal("expected export error")
	}
	status = controller.Status()
	if status.ExportedBatches != 1 || status.ExportedSpans != 1 || status.FailedBatches != 1 {
		t.Fatalf("unexpected failure status: %#v", status)
	}
	if status.LastExport == nil || status.LastExport.Success {
		t.Fatalf("expected failed last export, got %#v", status.LastExport)
	}
	if strings.Contains(status.LastExport.Error, "secret-token") {
		t.Fatalf("status leaked access token: %q", status.LastExport.Error)
	}
}

func TestSplunkTracesExportControllerShutdownWaitsForInFlightExport(t *testing.T) {
	runtime := &blockingTracesExporterRuntime{
		release:  make(chan struct{}),
		shutdown: make(chan struct{}),
		started:  make(chan struct{}),
	}
	controller := &SplunkTracesExportController{
		config: SplunkTracesExporterConfig{
			Enabled:     true,
			Realm:       "us0",
			AccessToken: "secret-token",
		},
		exporter: runtime,
	}

	exportDone := make(chan error, 1)
	go func() {
		exportDone <- controller.ExportTraces(context.Background(), createTestSpan())
	}()
	awaitSignal(t, runtime.started, "traces export start")

	shutdownAttempted := make(chan struct{})
	shutdownDone := make(chan struct{})
	go func() {
		close(shutdownAttempted)
		controller.Shutdown(context.Background())
		close(shutdownDone)
	}()
	awaitSignal(t, shutdownAttempted, "traces shutdown attempt")
	select {
	case <-runtime.shutdown:
		t.Fatal("exporter shut down while an export was in flight")
	default:
	}

	close(runtime.release)
	if err := <-exportDone; err != nil {
		t.Fatalf("export traces: %v", err)
	}
	awaitSignal(t, shutdownDone, "traces controller shutdown")
	awaitSignal(t, runtime.shutdown, "traces exporter shutdown")
	if got := controller.Status().ExportedBatches; got != 1 {
		t.Fatalf("exported batches = %d, want 1", got)
	}
}

func TestSplunkTracesExportControllerShutdownHonorsContextWhileExportInFlight(t *testing.T) {
	runtime := &blockingTracesExporterRuntime{
		release:  make(chan struct{}),
		shutdown: make(chan struct{}),
		started:  make(chan struct{}),
	}
	controller := &SplunkTracesExportController{
		config: SplunkTracesExporterConfig{
			Enabled:     true,
			Realm:       "us0",
			AccessToken: "secret-token",
		},
		exporter: runtime,
	}

	exportDone := make(chan error, 1)
	go func() {
		exportDone <- controller.ExportTraces(context.Background(), createTestSpan())
	}()
	awaitSignal(t, runtime.started, "traces export start")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	shutdownDone := make(chan struct{})
	go func() {
		controller.Shutdown(ctx)
		close(shutdownDone)
	}()

	awaitSignal(t, shutdownDone, "traces controller shutdown deadline")
	select {
	case <-runtime.shutdown:
		t.Fatal("exporter shut down after the shutdown context expired")
	default:
	}

	close(runtime.release)
	if err := <-exportDone; err != nil {
		t.Fatalf("export traces: %v", err)
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

func TestExportTracesAsyncSkipsDisabledStatefulExporter(t *testing.T) {
	exporter := &statefulCaptureTracesExporter{
		captureTracesExporter: captureTracesExporter{ch: make(chan ptrace.Traces, 1)},
		enabled:               false,
	}

	exportTracesAsync(exporter, createTestSpan())

	select {
	case <-exporter.ch:
		t.Fatal("disabled stateful traces exporter received telemetry")
	case <-time.After(50 * time.Millisecond):
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

type statefulCaptureTracesExporter struct {
	captureTracesExporter
	enabled bool
}

func (e *statefulCaptureTracesExporter) ExportEnabled() bool {
	return e.enabled
}

type stubTracesExporterRuntime struct {
	err error
}

func (e *stubTracesExporterRuntime) ExportTraces(_ context.Context, _ ptrace.Traces) error {
	return e.err
}

func (e *stubTracesExporterRuntime) Endpoints() []string {
	return []string{"https://ingest.us0.observability.splunkcloud.com/v2/trace/otlp"}
}

func (e *stubTracesExporterRuntime) Shutdown(context.Context) {}

type blockingTracesExporterRuntime struct {
	release  chan struct{}
	shutdown chan struct{}
	started  chan struct{}
}

func (e *blockingTracesExporterRuntime) ExportTraces(_ context.Context, _ ptrace.Traces) error {
	close(e.started)
	<-e.release
	return nil
}

func (e *blockingTracesExporterRuntime) Endpoints() []string {
	return []string{"https://ingest.us0.observability.splunkcloud.com/v2/trace/otlp"}
}

func (e *blockingTracesExporterRuntime) Shutdown(context.Context) {
	close(e.shutdown)
}
