package otlp

import (
	"bytes"
	"compress/gzip"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/pmetric/pmetricotlp"
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

func TestSplunkMetricsExportControllerCountsAcceptedPoints(t *testing.T) {
	for _, encoding := range []string{"application/json", "application/x-protobuf"} {
		for _, rejected := range []int64{0, 1, 3, -1, 4} {
			t.Run(fmt.Sprintf("%s/rejected=%d", encoding, rejected), func(t *testing.T) {
				response := pmetricotlp.NewExportResponse()
				response.PartialSuccess().SetRejectedDataPoints(rejected)
				var body []byte
				var err error
				if encoding == "application/json" {
					body, err = response.MarshalJSON()
				} else {
					body, err = response.MarshalProto()
				}
				if err != nil {
					t.Fatal(err)
				}
				var requests atomic.Int32
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					requests.Add(1)
					w.Header().Set("Content-Type", encoding)
					_, _ = w.Write(body)
				}))
				defer server.Close()
				controller, err := NewSplunkMetricsExportController(SplunkMetricsExporterConfig{
					Enabled: true, Endpoint: server.URL, AccessToken: "test-token",
				})
				if err != nil {
					t.Fatal(err)
				}
				defer controller.Shutdown(context.Background())
				metrics := createTestMetric()
				points := metrics.ResourceMetrics().At(0).ScopeMetrics().At(0).Metrics().At(0).Gauge().DataPoints()
				points.AppendEmpty().SetIntValue(2)
				points.AppendEmpty().SetIntValue(3)
				err = controller.ExportMetrics(context.Background(), metrics)
				want := uint64(0)
				if rejected >= 0 && rejected <= 3 {
					want = uint64(3 - rejected)
				}
				status := controller.Status()
				if status.ExportedDataPoints != want || (err == nil) != (rejected == 0) {
					t.Fatalf("exported=%d, want %d; error=%v", status.ExportedDataPoints, want, err)
				}
				if (status.ExportedBatches == 1) != (rejected == 0) || (status.FailedBatches == 1) != (rejected != 0) {
					t.Fatalf("unexpected batch status: %#v", status)
				}
				if requests.Load() != 1 {
					t.Fatalf("requests = %d; partial batches must not be retried", requests.Load())
				}
			})
		}
	}
}

func TestSplunkMetricsExportControllerConcurrentAcceptedCounts(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		if r.Header.Get("Content-Encoding") == "gzip" {
			reader, err := gzip.NewReader(bytes.NewReader(body))
			if err != nil {
				t.Error(err)
				return
			}
			body, _ = io.ReadAll(reader)
			reader.Close()
		}
		metrics, err := (&pmetric.ProtoUnmarshaler{}).UnmarshalMetrics(body)
		if err != nil {
			t.Error(err)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		if metrics.DataPointCount() == 2 {
			_, _ = io.WriteString(w, `{"partialSuccess":{"rejectedDataPoints":"1"}}`)
		}
	}))
	defer server.Close()
	controller, err := NewSplunkMetricsExportController(SplunkMetricsExporterConfig{
		Enabled: true, Endpoint: server.URL, AccessToken: "test-token",
	})
	if err != nil {
		t.Fatal(err)
	}
	defer controller.Shutdown(context.Background())
	var exports sync.WaitGroup
	for i := range 20 {
		exports.Go(func() {
			metrics := createTestMetric()
			partial := i%2 == 0
			if partial {
				metrics.ResourceMetrics().At(0).ScopeMetrics().At(0).Metrics().At(0).Gauge().DataPoints().AppendEmpty().SetIntValue(2)
			}
			err := controller.ExportMetrics(context.Background(), metrics)
			if (err != nil) != partial {
				t.Errorf("partial=%t, error=%v", partial, err)
			}
		})
	}
	exports.Wait()
	status := controller.Status()
	if status.ExportedDataPoints != 20 || status.ExportedBatches != 10 || status.FailedBatches != 10 {
		t.Fatalf("unexpected concurrent export totals: %#v", status)
	}
}

func TestSplunkMetricsExportControllerFailedResponseCounts(t *testing.T) {
	for _, test := range []struct {
		name   string
		status int
		body   string
		length string
	}{
		{name: "unauthorized", status: 401},
		{name: "invalid JSON", status: 200, body: "{"},
		{name: "oversized", status: 200, body: strings.Repeat(" ", 64*1024+1)},
		{name: "truncated", status: 200, body: "{}", length: "100"},
	} {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				if test.length != "" {
					w.Header().Set("Content-Length", test.length)
				}
				w.WriteHeader(test.status)
				_, _ = io.WriteString(w, test.body)
			}))
			defer server.Close()
			controller, err := NewSplunkMetricsExportController(SplunkMetricsExporterConfig{
				Enabled: true, Endpoint: server.URL, AccessToken: "test-token",
			})
			if err != nil {
				t.Fatal(err)
			}
			defer controller.Shutdown(context.Background())
			ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			defer cancel()
			if err := controller.ExportMetrics(ctx, createTestMetric()); err == nil {
				t.Fatal("expected a delivery error")
			}
			status := controller.Status()
			if status.ExportedDataPoints != 0 || status.ExportedBatches != 0 || status.FailedBatches != 1 {
				t.Fatalf("failed delivery changed exported totals: %#v", status)
			}
		})
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

func TestSplunkMetricsConnectionEditsKeepCountsAndRefreshDestinationHealth(t *testing.T) {
	for _, change := range []string{"same", "realm", "token", "endpoint"} {
		t.Run(change, func(t *testing.T) {
			requests := make(chan string, 2)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
				_, _ = io.Copy(io.Discard, request.Body)
				requests <- request.URL.Path + ":" + request.Header.Get("X-SF-Token")
				w.WriteHeader(http.StatusOK)
			}))
			defer server.Close()
			config := SplunkMetricsExporterConfig{Enabled: true, Realm: "us1", Endpoint: server.URL + "/first", AccessToken: "first-token"}
			controller, err := NewSplunkMetricsExportController(config)
			if err != nil {
				t.Fatal(err)
			}
			defer controller.Shutdown(context.Background())
			if err := controller.ExportMetrics(context.Background(), createTestMetric()); err != nil {
				t.Fatal(err)
			}
			if got := <-requests; got != "/first:first-token" {
				t.Fatal("first export reached the wrong destination", got)
			}
			switch change {
			case "realm":
				config.Realm = "eu0"
			case "token":
				config.AccessToken = "replacement-token"
			case "endpoint":
				config.Endpoint = server.URL + "/second"
			}
			if err := controller.ConfigureKeepingActivity(config); err != nil {
				t.Fatal(err)
			}
			status := controller.Status()
			if status.ExportedDataPoints != 1 || status.ExportedBatches != 1 {
				t.Fatal("editing reset accepted activity")
			}
			if change == "same" {
				if status.LastExport == nil || !status.LastExport.Success {
					t.Fatal("unchanged destination lost its accepted export")
				}
			} else if status.LastExport != nil {
				t.Fatal("new destination inherited the previous destination's successful export")
			}
			if err := controller.ExportMetrics(context.Background(), createTestMetric()); err != nil {
				t.Fatal(err)
			}
			path := "/first"
			if change == "endpoint" {
				path = "/second"
			}
			if got := <-requests; got != path+":"+config.AccessToken {
				t.Fatal("edited export reached the wrong destination", got)
			}
			status = controller.Status()
			if status.LastExport == nil || !status.LastExport.Success || status.ExportedDataPoints != 2 || status.ExportedBatches != 2 {
				t.Fatal("new accepted export did not update its health and totals")
			}
		})
	}
}
