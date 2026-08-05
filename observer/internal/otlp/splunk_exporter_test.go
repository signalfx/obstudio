package otlp

import (
	"bytes"
	"context"
	"errors"
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

func TestSplunkMetricsExportControllerTracksRedactedActivity(t *testing.T) {
	controller := &SplunkMetricsExportController{
		config: SplunkMetricsExporterConfig{
			Enabled:     true,
			Realm:       "us0",
			AccessToken: "secret-token",
		},
		exporter: &stubMetricsExporterRuntime{},
	}

	if err := controller.ExportMetrics(context.Background(), createTestMetric()); err != nil {
		t.Fatalf("export metrics: %v", err)
	}
	status := controller.Status()
	if status.ExportedBatches != 1 || status.ExportedDataPoints != 1 || status.FailedBatches != 0 {
		t.Fatalf("unexpected success status: %#v", status)
	}
	if status.LastExport == nil || !status.LastExport.Success {
		t.Fatalf("expected successful last export, got %#v", status.LastExport)
	}

	controller.mu.Lock()
	controller.exporter = &stubMetricsExporterRuntime{err: errors.New("backend echoed secret-token")}
	controller.mu.Unlock()
	if err := controller.ExportMetrics(context.Background(), createTestMetric()); err == nil {
		t.Fatal("expected export error")
	}
	status = controller.Status()
	if status.ExportedBatches != 1 || status.ExportedDataPoints != 1 || status.FailedBatches != 1 {
		t.Fatalf("unexpected failure status: %#v", status)
	}
	if status.LastExport == nil || status.LastExport.Success {
		t.Fatalf("expected failed last export, got %#v", status.LastExport)
	}
	if strings.Contains(status.LastExport.Error, "secret-token") {
		t.Fatalf("status leaked access token: %q", status.LastExport.Error)
	}
}

func TestSplunkMetricsExportControllerShutdownWaitsForInFlightExport(t *testing.T) {
	runtime := &blockingMetricsExporterRuntime{
		release:  make(chan struct{}),
		shutdown: make(chan struct{}),
		started:  make(chan struct{}),
	}
	controller := &SplunkMetricsExportController{
		config: SplunkMetricsExporterConfig{
			Enabled:     true,
			Realm:       "us0",
			AccessToken: "secret-token",
		},
		exporter: runtime,
	}

	exportDone := make(chan error, 1)
	go func() {
		exportDone <- controller.ExportMetrics(context.Background(), createTestMetric())
	}()
	awaitSignal(t, runtime.started, "metrics export start")

	shutdownAttempted := make(chan struct{})
	shutdownDone := make(chan struct{})
	go func() {
		close(shutdownAttempted)
		controller.Shutdown(context.Background())
		close(shutdownDone)
	}()
	awaitSignal(t, shutdownAttempted, "metrics shutdown attempt")
	select {
	case <-runtime.shutdown:
		t.Fatal("exporter shut down while an export was in flight")
	default:
	}

	close(runtime.release)
	if err := <-exportDone; err != nil {
		t.Fatalf("export metrics: %v", err)
	}
	awaitSignal(t, shutdownDone, "metrics controller shutdown")
	awaitSignal(t, runtime.shutdown, "metrics exporter shutdown")
	if got := controller.Status().ExportedBatches; got != 1 {
		t.Fatalf("exported batches = %d, want 1", got)
	}
}

func TestSplunkMetricsExportControllerShutdownHonorsContextWhileExportInFlight(t *testing.T) {
	runtime := &blockingMetricsExporterRuntime{
		release:  make(chan struct{}),
		shutdown: make(chan struct{}),
		started:  make(chan struct{}),
	}
	controller := &SplunkMetricsExportController{
		config: SplunkMetricsExporterConfig{
			Enabled:     true,
			Realm:       "us0",
			AccessToken: "secret-token",
		},
		exporter: runtime,
	}

	exportDone := make(chan error, 1)
	go func() {
		exportDone <- controller.ExportMetrics(context.Background(), createTestMetric())
	}()
	awaitSignal(t, runtime.started, "metrics export start")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	shutdownDone := make(chan struct{})
	go func() {
		controller.Shutdown(ctx)
		close(shutdownDone)
	}()

	awaitSignal(t, shutdownDone, "metrics controller shutdown deadline")
	select {
	case <-runtime.shutdown:
		t.Fatal("exporter shut down after the shutdown context expired")
	default:
	}

	close(runtime.release)
	if err := <-exportDone; err != nil {
		t.Fatalf("export metrics: %v", err)
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

func TestExportMetricsAsyncSkipsDisabledStatefulExporter(t *testing.T) {
	exporter := &statefulCaptureMetricsExporter{
		captureMetricsExporter: captureMetricsExporter{ch: make(chan pmetric.Metrics, 1)},
		enabled:                false,
	}

	exportMetricsAsync(exporter, createTestMetric())

	select {
	case <-exporter.ch:
		t.Fatal("disabled stateful metrics exporter received telemetry")
	case <-time.After(50 * time.Millisecond):
	}
}

type captureMetricsExporter struct {
	ch chan pmetric.Metrics
}

func (e *captureMetricsExporter) ExportMetrics(_ context.Context, md pmetric.Metrics) error {
	e.ch <- md
	return nil
}

type statefulCaptureMetricsExporter struct {
	captureMetricsExporter
	enabled bool
}

func (e *statefulCaptureMetricsExporter) ExportEnabled() bool {
	return e.enabled
}

type stubMetricsExporterRuntime struct {
	err error
}

func (e *stubMetricsExporterRuntime) ExportMetrics(_ context.Context, _ pmetric.Metrics) error {
	return e.err
}

func (e *stubMetricsExporterRuntime) Endpoints() []string {
	return []string{"https://ingest.us0.observability.splunkcloud.com/v2/datapoint/otlp"}
}

func (e *stubMetricsExporterRuntime) Shutdown(context.Context) {}

type blockingMetricsExporterRuntime struct {
	release  chan struct{}
	shutdown chan struct{}
	started  chan struct{}
}

func (e *blockingMetricsExporterRuntime) ExportMetrics(_ context.Context, _ pmetric.Metrics) error {
	close(e.started)
	<-e.release
	return nil
}

func (e *blockingMetricsExporterRuntime) Endpoints() []string {
	return []string{"https://ingest.us0.observability.splunkcloud.com/v2/datapoint/otlp"}
}

func (e *blockingMetricsExporterRuntime) Shutdown(context.Context) {
	close(e.shutdown)
}

func awaitSignal(t *testing.T, signal <-chan struct{}, name string) {
	t.Helper()
	select {
	case <-signal:
	case <-time.After(2 * time.Second):
		t.Fatalf("timed out waiting for %s", name)
	}
}
