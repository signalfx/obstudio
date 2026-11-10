package export

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"go.opentelemetry.io/otel/attribute"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	"go.opentelemetry.io/otel/sdk/resource"
	collmetric "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	"google.golang.org/protobuf/proto"

	"github.com/signalfx/obstudio/observer/internal/adoption/gate"
	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

// capture is an OTLP/HTTP sink that records connections, headers and bodies.
type capture struct {
	srv    *httptest.Server
	mu     sync.Mutex
	conns  int
	reqs   []captured
	status atomic.Int32
	hang   chan struct{}
}

type captured struct {
	path   string
	header http.Header
	body   *collmetric.ExportMetricsServiceRequest
}

func newCapture(t *testing.T) *capture {
	t.Helper()
	c := &capture{}
	c.status.Store(http.StatusOK)
	c.srv = httptest.NewUnstartedServer(http.HandlerFunc(c.serve))
	c.srv.Config.ConnState = func(_ net.Conn, s http.ConnState) {
		if s == http.StateNew {
			c.mu.Lock()
			c.conns++
			c.mu.Unlock()
		}
	}
	c.srv.Start()
	t.Cleanup(func() {
		if c.hang != nil {
			select {
			case <-c.hang:
			default:
				close(c.hang)
			}
		}
		c.srv.Close()
	})
	return c
}

func (c *capture) serve(w http.ResponseWriter, r *http.Request) {
	data, _ := io.ReadAll(r.Body)
	req := &collmetric.ExportMetricsServiceRequest{}
	_ = proto.Unmarshal(data, req)
	c.mu.Lock()
	c.reqs = append(c.reqs, captured{path: r.URL.Path, header: r.Header.Clone(), body: req})
	hang := c.hang
	c.mu.Unlock()
	if hang != nil {
		<-hang
		return
	}
	w.WriteHeader(int(c.status.Load()))
}

func (c *capture) requests() []captured {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]captured(nil), c.reqs...)
}

func (c *capture) connections() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.conns
}

// fakeGate returns scripted decisions and counts calls.
type fakeGate struct {
	mu    sync.Mutex
	seq   []gate.Decision
	def   gate.Decision
	calls int
}

func openGate() *fakeGate { return &fakeGate{def: gate.Decision{Allowed: true}} }

func (f *fakeGate) Decide() gate.Decision {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	if len(f.seq) > 0 {
		d := f.seq[0]
		f.seq = f.seq[1:]
		return d
	}
	return f.def
}

func envFor(c *capture) func(string) string {
	return func(k string) string {
		if k == EndpointEnv {
			return c.srv.URL
		}
		return ""
	}
}

func newExp(t *testing.T, g Decider, getenv func(string) string) *Exporter {
	t.Helper()
	e, err := NewExporter(ExporterConfig{ClientType: ClientTypeLongRunning, Gate: g, Getenv: getenv, Timeout: 2 * time.Second})
	if err != nil {
		t.Fatal(err)
	}
	return e
}

// oneBatch is a minimal delta Sum batch with one point.
func oneBatch(res *resource.Resource) *metricdata.ResourceMetrics {
	if res == nil {
		res = resource.Empty()
	}
	return &metricdata.ResourceMetrics{
		Resource: res,
		ScopeMetrics: []metricdata.ScopeMetrics{{
			Metrics: []metricdata.Metrics{{
				Name: "obstudio.first_use",
				Data: metricdata.Sum[int64]{
					Temporality: metricdata.DeltaTemporality,
					IsMonotonic: true,
					DataPoints: []metricdata.DataPoint[int64]{{
						Attributes: attribute.NewSet(attribute.String("feature", "install")),
						Value:      1,
						StartTime:  time.Now().Add(-time.Second),
						Time:       time.Now(),
					}},
				},
			}},
		}},
	}
}

func TestExportUsesSingleEndpointNoCredential(t *testing.T) {
	c := newCapture(t)
	e := newExp(t, openGate(), envFor(c))
	if err := e.Export(context.Background(), oneBatch(nil)); err != nil {
		t.Fatalf("Export: %v", err)
	}
	reqs := c.requests()
	if len(reqs) != 1 || reqs[0].path != "/v1/metrics" {
		t.Fatalf("requests = %+v", reqs)
	}
	for k := range reqs[0].header {
		if strings.EqualFold(k, "X-SF-"+"Token") || strings.EqualFold(k, "Authorization") {
			t.Fatalf("credential header %s", k)
		}
	}
	if len(reqs[0].body.ResourceMetrics) != 1 {
		t.Fatal("body is not an OTLP metrics request")
	}
}

func TestClientTypeLongRunningOnly(t *testing.T) {
	if _, err := NewExporter(ExporterConfig{ClientType: ClientTypeLongRunning}); err != nil {
		t.Fatalf("long-running: %v", err)
	}
	if e, err := NewExporter(ExporterConfig{ClientType: "one-shot"}); err == nil || e != nil {
		t.Fatal("one-shot exporter built")
	}
	if r, err := NewReader(newExp(t, nil, nil), ReaderConfig{ClientType: "one-shot"}); err == nil || r != nil {
		t.Fatal("one-shot reader built")
	}
}

func TestEndpointDefaultsToProductionWithoutOverride(t *testing.T) {
	got, set := Endpoint(func(string) string { return "" })
	if got != DefaultEndpoint || set {
		t.Fatalf("Endpoint() = %q, %v", got, set)
	}
	if _, err := NewExporter(ExporterConfig{ClientType: ClientTypeLongRunning, Getenv: func(string) string { return "" }}); err != nil {
		t.Fatalf("no override: %v", err)
	}
	got, set = Endpoint(func(string) string { return " http://localhost:4318/ " })
	if got != "http://localhost:4318" || !set {
		t.Fatalf("override: %q, %v", got, set)
	}
}

func TestGateDroppedNotSuccess(t *testing.T) {
	c := newCapture(t)
	reasons := []gate.Reason{gate.ReasonNoManager, gate.ReasonConfigUnhealthy, gate.ReasonConsentOff, gate.ReasonCI, gate.ReasonDoNotTrack, gate.ReasonHostOff, gate.ReasonNoDestination}
	for _, r := range reasons {
		e := newExp(t, &fakeGate{def: gate.Decision{Reason: r}}, envFor(c))
		err := e.Export(context.Background(), oneBatch(nil))
		if !errors.Is(err, ErrDropped) {
			t.Fatalf("%s: err = %v", r, err)
		}
		if got, _ := DropReason(err); got != r {
			t.Fatalf("%s: reason %q", r, got)
		}
	}
	var nilGate *gate.Gate
	for _, g := range []Decider{nilGate, nil} {
		err := newExp(t, g, envFor(c)).Export(context.Background(), oneBatch(nil))
		if got, _ := DropReason(err); !errors.Is(err, ErrDropped) || got != gate.ReasonNoManager {
			t.Fatalf("nil gate: %v", err)
		}
	}
	if c.connections() != 0 || len(c.requests()) != 0 {
		t.Fatal("a dropped export reached the endpoint")
	}

	c.status.Store(http.StatusBadRequest)
	err := newExp(t, openGate(), envFor(c)).Export(context.Background(), oneBatch(nil))
	if err == nil || errors.Is(err, ErrDropped) || !errors.Is(err, ErrFailed) {
		t.Fatalf("failed export: %v", err)
	}
}

func TestGateAskedPerExport(t *testing.T) {
	c := newCapture(t)
	g := &fakeGate{seq: []gate.Decision{{Reason: gate.ReasonConsentOff}, {Allowed: true}, {Reason: gate.ReasonConsentOff}}}
	e := newExp(t, g, envFor(c))
	r, err := NewReader(e, ReaderConfig{ClientType: ClientTypeLongRunning, Interval: time.Hour})
	if err != nil {
		t.Fatal(err)
	}
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(r))
	ctr, _ := mp.Meter("t").Int64Counter("obstudio.first_use")
	var results []error
	for i := 0; i < 3; i++ {
		ctr.Add(context.Background(), 1)
		results = append(results, r.ForceFlush(context.Background()))
	}
	if g.calls != 3 {
		t.Fatalf("Decide calls = %d", g.calls)
	}
	if !errors.Is(results[0], ErrDropped) || results[1] != nil || !errors.Is(results[2], ErrDropped) {
		t.Fatalf("results = %v", results)
	}
	if len(c.requests()) != 1 {
		t.Fatalf("requests = %d", len(c.requests()))
	}
}

func TestOptoutConfigSuppressesAllExport(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(strings.Replace(userconfig.Scaffold(), "enabled: true", "enabled: false", 1)), 0o600); err != nil {
		t.Fatal(err)
	}
	m, err := userconfig.NewManager(path)
	if err != nil {
		t.Fatal(err)
	}
	defer m.Close()
	g := gate.New(gate.Inputs{Config: m, Path: path, Getenv: func(string) string { return "" }, DestinationSet: true})
	defer g.Close()
	c := newCapture(t)
	e := newExp(t, g, envFor(c))
	r, _ := NewReader(e, ReaderConfig{ClientType: ClientTypeLongRunning})
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(r))
	ctr, _ := mp.Meter("t").Int64Counter("obstudio.first_use")
	ctr.Add(context.Background(), 1)
	err1 := r.ForceFlush(context.Background())
	ctr.Add(context.Background(), 1)
	err2 := r.Shutdown(context.Background())
	for _, err := range []error{err1, err2} {
		if reason, _ := DropReason(err); !errors.Is(err, ErrDropped) || reason != gate.ReasonConsentOff {
			t.Fatalf("outcome = %v", err)
		}
	}
	if c.connections() != 0 || len(c.requests()) != 0 {
		t.Fatal("network activity while opted out")
	}
}

func TestOtelMetricsExporterNotRead(t *testing.T) {
	t.Setenv("OTEL_METRICS_EXPORTER", "none")
	c := newCapture(t)
	if err := newExp(t, openGate(), envFor(c)).Export(context.Background(), oneBatch(nil)); err != nil {
		t.Fatal(err)
	}
	if len(c.requests()) != 1 {
		t.Fatal("not sent")
	}
}

type recordingExporter struct {
	mu      sync.Mutex
	batches []metricdata.ResourceMetrics
}

func (r *recordingExporter) Temporality(sdkmetric.InstrumentKind) metricdata.Temporality {
	return metricdata.DeltaTemporality
}
func (r *recordingExporter) Aggregation(k sdkmetric.InstrumentKind) sdkmetric.Aggregation {
	return sdkmetric.DefaultAggregationSelector(k)
}
func (r *recordingExporter) Export(_ context.Context, rm *metricdata.ResourceMetrics) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.batches = append(r.batches, *rm)
	return nil
}
func (r *recordingExporter) ForceFlush(context.Context) error { return nil }
func (r *recordingExporter) Shutdown(context.Context) error   { return nil }

func TestReaderAcceptsAnyExporter(t *testing.T) {
	rec := &recordingExporter{}
	r, err := NewReader(rec, ReaderConfig{ClientType: ClientTypeLongRunning, Interval: time.Hour})
	if err != nil {
		t.Fatal(err)
	}
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(r))
	ctr, _ := mp.Meter("t").Int64Counter("c")
	for i := 0; i < 2; i++ {
		ctr.Add(context.Background(), 1)
		if err := r.ForceFlush(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if len(rec.batches) != 2 {
		t.Fatalf("batches = %d", len(rec.batches))
	}
	for i, b := range rec.batches {
		sum := b.ScopeMetrics[0].Metrics[0].Data.(metricdata.Sum[int64])
		if sum.Temporality != metricdata.DeltaTemporality || sum.DataPoints[0].Value != 1 {
			t.Fatalf("batch %d: %+v", i, sum)
		}
	}
}

func TestObserverPeriodicFlushAndForceFlushResetsTimer(t *testing.T) {
	const interval = 400 * time.Millisecond
	rec := &timedExporter{}
	start := time.Now()
	r, _ := NewReader(rec, ReaderConfig{ClientType: ClientTypeLongRunning, Interval: interval})
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(r))
	ctr, _ := mp.Meter("t").Int64Counter("c")
	ctr.Add(context.Background(), 1)
	time.Sleep(interval / 2)
	_ = r.ForceFlush(context.Background())
	flushAt := time.Since(start)
	ctr.Add(context.Background(), 1)
	time.Sleep(interval + interval/2)
	_ = mp.Shutdown(context.Background())
	times := rec.times()
	if len(times) < 2 {
		t.Fatalf("exports = %v", times)
	}
	// The next periodic export follows the ForceFlush by one interval, not the
	// original tick at one interval after start.
	next := times[1].Sub(start)
	if next < flushAt+interval-interval/4 {
		t.Fatalf("periodic export at %v, ForceFlush at %v: timer not reset", next, flushAt)
	}
}

type timedExporter struct {
	recordingExporter
	mu sync.Mutex
	at []time.Time
}

func (e *timedExporter) Export(_ context.Context, rm *metricdata.ResourceMetrics) error {
	if len(rm.ScopeMetrics) == 0 {
		return nil
	}
	e.mu.Lock()
	e.at = append(e.at, time.Now())
	e.mu.Unlock()
	return nil
}

func (e *timedExporter) times() []time.Time {
	e.mu.Lock()
	defer e.mu.Unlock()
	return append([]time.Time(nil), e.at...)
}

func TestExportFailureBoundedRetries(t *testing.T) {
	c := newCapture(t)
	c.status.Store(http.StatusServiceUnavailable)
	e := newExp(t, openGate(), envFor(c))
	start := time.Now()
	err := e.Export(context.Background(), oneBatch(nil))
	if err == nil || errors.Is(err, ErrDropped) {
		t.Fatalf("err = %v", err)
	}
	if time.Since(start) > FlushTimeout {
		t.Fatalf("export took %v", time.Since(start))
	}
	if n := len(c.requests()); n < 2 || n > MaxAttempts {
		t.Fatalf("attempts = %d, want 2..%d", n, MaxAttempts)
	}
}

func TestShutdownFlushHonorsTimeout(t *testing.T) {
	c := newCapture(t)
	c.hang = make(chan struct{})
	e := newExp(t, openGate(), envFor(c))
	r, _ := NewReader(e, ReaderConfig{ClientType: ClientTypeLongRunning, Timeout: 500 * time.Millisecond})
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(r))
	ctr, _ := mp.Meter("t").Int64Counter("obstudio.first_use")
	ctr.Add(context.Background(), 1)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	start := time.Now()
	_ = r.ForceFlush(ctx)
	if d := time.Since(start); d > 1500*time.Millisecond {
		t.Fatalf("flush took %v", d)
	}
}

func TestExportFailureDoesNotBlockHostUnreachable(t *testing.T) {
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	addr := ln.Addr().String()
	_ = ln.Close()
	e := newExp(t, openGate(), func(k string) string {
		if k == EndpointEnv {
			return "http://" + addr
		}
		return ""
	})
	start := time.Now()
	if err := e.Export(context.Background(), oneBatch(nil)); err == nil || errors.Is(err, ErrDropped) {
		t.Fatalf("err = %v", err)
	}
	if time.Since(start) > FlushTimeout {
		t.Fatal("unreachable endpoint exceeded FlushTimeout")
	}
}

func TestExportShipsNoRawIdentity(t *testing.T) {
	const id = "3f2b8c1e-9a4d-4e7b-8c2f-1d6a5b9e0c47"
	c := newCapture(t)
	res := resource.NewSchemaless(
		attribute.String("service.name", "obstudio"),
		attribute.String("service.version", "0.0.0-test"),
		attribute.String("os.type", "darwin"),
		attribute.String("host.arch", "arm64"),
		attribute.String("obstudio.launcher", "other"),
		attribute.String("obstudio.user_hash", id),
	)
	if err := newExp(t, openGate(), envFor(c)).Export(context.Background(), oneBatch(res)); err != nil {
		t.Fatal(err)
	}
	attrs := c.requests()[0].body.ResourceMetrics[0].Resource.Attributes
	if len(attrs) != 6 {
		t.Fatalf("resource has %d attributes", len(attrs))
	}
	found := false
	for _, a := range attrs {
		if a.Key == "obstudio.repo_hash" {
			t.Fatal("repo_hash added")
		}
		if a.Key == "obstudio.user_hash" && a.Value.GetStringValue() == id {
			found = true
		}
	}
	if !found {
		t.Fatal("install ID not shipped verbatim")
	}
}

func TestExporterIgnoresOtelEnv(t *testing.T) {
	a := newCapture(t)
	b := newCapture(t)
	vars := map[string]string{
		"OTEL_EXPORTER_OTLP_HEADERS":                    "authorization=Bearer s3cret,x-tenant=acme",
		"OTEL_EXPORTER_OTLP_METRICS_HEADERS":            "x-other=1",
		"OTEL_EXPORTER_OTLP_ENDPOINT":                   b.srv.URL,
		"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT":           b.srv.URL + "/v1/metrics",
		"OTEL_EXPORTER_OTLP_INSECURE":                   "true",
		"OTEL_EXPORTER_OTLP_COMPRESSION":                "gzip",
		"OTEL_EXPORTER_OTLP_TIMEOUT":                    "1",
		"OTEL_EXPORTER_OTLP_METRICS_INSECURE":           "true",
		"OTEL_EXPORTER_OTLP_METRICS_COMPRESSION":        "gzip",
		"OTEL_EXPORTER_OTLP_METRICS_TIMEOUT":            "1",
		"OTEL_EXPORTER_OTLP_CERTIFICATE":                "/nonexistent/ca.pem",
		"OTEL_EXPORTER_OTLP_CLIENT_KEY":                 "/nonexistent/key.pem",
		"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE":         "/nonexistent/cert.pem",
		"OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE":        "/nonexistent/ca.pem",
		"OTEL_EXPORTER_OTLP_METRICS_CLIENT_KEY":         "/nonexistent/key.pem",
		"OTEL_EXPORTER_OTLP_METRICS_CLIENT_CERTIFICATE": "/nonexistent/cert.pem",
		"OTEL_METRIC_EXPORT_INTERVAL":                   "50",
		"OTEL_METRIC_EXPORT_TIMEOUT":                    "1",
	}
	for k, v := range vars {
		t.Setenv(k, v)
	}
	const interval = 300 * time.Millisecond
	e := newExp(t, openGate(), envFor(a))
	r, _ := NewReader(e, ReaderConfig{ClientType: ClientTypeLongRunning, Interval: interval})
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(r))
	ctr, _ := mp.Meter("t").Int64Counter("obstudio.first_use")
	ctr.Add(context.Background(), 1)
	time.Sleep(interval / 2)
	ctr.Add(context.Background(), 1)
	time.Sleep(interval)
	ctr.Add(context.Background(), 1)
	time.Sleep(interval)
	periodic := len(a.requests())
	_ = mp.Shutdown(context.Background())

	if periodic != 2 {
		t.Fatalf("cadence: %d periodic requests, want 2", periodic)
	}
	if b.connections() != 0 {
		t.Fatal("server B reached")
	}
	allowed := map[string]bool{"Content-Type": true, "User-Agent": true, "Content-Length": true, "Accept-Encoding": true, "Content-Encoding": true, "Host": true}
	for _, req := range a.requests() {
		for k := range req.header {
			if !allowed[http.CanonicalHeaderKey(k)] {
				t.Fatalf("header %s sent", k)
			}
		}
	}

	t.Run("selectors-ignore-env", func(t *testing.T) {
		t.Setenv("OTEL_EXPORTER_OTLP_METRICS_DEFAULT_HISTOGRAM_AGGREGATION", "base2_exponential_bucket_histogram")
		for _, pref := range []string{"delta", "lowmemory"} {
			t.Setenv("OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE", pref)
			e := newExp(t, openGate(), envFor(a))
			for k := sdkmetric.InstrumentKindCounter; k <= sdkmetric.InstrumentKindObservableGauge; k++ {
				if e.Temporality(k) != sdkmetric.DefaultTemporalitySelector(k) {
					t.Fatalf("%s: temporality for kind %v", pref, k)
				}
				if !sameAggregation(e.Aggregation(k), sdkmetric.DefaultAggregationSelector(k)) {
					t.Fatalf("%s: aggregation for kind %v", pref, k)
				}
			}
		}
	})
}

func sameAggregation(a, b sdkmetric.Aggregation) bool {
	return strings.TrimSpace(fmtAgg(a)) == strings.TrimSpace(fmtAgg(b))
}

func fmtAgg(a sdkmetric.Aggregation) string {
	switch v := a.(type) {
	case sdkmetric.AggregationExplicitBucketHistogram:
		return "explicit"
	case sdkmetric.AggregationBase2ExponentialHistogram:
		return "base2"
	case sdkmetric.AggregationSum:
		return "sum"
	case sdkmetric.AggregationLastValue:
		return "last"
	case sdkmetric.AggregationDrop:
		return "drop"
	case sdkmetric.AggregationDefault:
		return "default"
	default:
		_ = v
		return "other"
	}
}

func TestSingleDestinationNoMode(t *testing.T) {
	selector := "OBSTUDIO_TELEMETRY_" + "EXPORTER"
	token := "SPLUNK_ACCESS_" + "TOKEN"
	sfx := "X-SF-" + "Token"
	ingest := []*regexp.Regexp{
		regexp.MustCompile(`ingest\.[^./]+\.observability\.splunkcloud\.com`),
		regexp.MustCompile(`ingest\.[^./]+\.signalfx\.com`),
	}
	files, _ := filepath.Glob("*.go")
	for _, f := range files {
		data, _ := os.ReadFile(f)
		low := strings.ToLower(string(data))
		for _, s := range []string{selector, token, sfx} {
			if strings.Contains(low, strings.ToLower(s)) {
				t.Fatalf("%s contains %s", f, s)
			}
		}
		for _, re := range ingest {
			if re.Match(data) {
				t.Fatalf("%s contains an ingest URL", f)
			}
		}
	}
	t.Setenv(selector, "splunk")
	t.Setenv(token, "tok")
	c := newCapture(t)
	if err := newExp(t, openGate(), envFor(c)).Export(context.Background(), oneBatch(nil)); err != nil {
		t.Fatal(err)
	}
	if reqs := c.requests(); len(reqs) != 1 || reqs[0].header.Get(sfx) != "" {
		t.Fatal("request missing or carries a token")
	}
}

func TestExportDoesNotImportAdoption(t *testing.T) {
	out, err := exec.Command("go", "list", "-deps", ".").Output()
	if err != nil {
		t.Skipf("go list unavailable: %v", err)
	}
	for _, line := range strings.Split(string(out), "\n") {
		if strings.TrimSpace(line) == "github.com/signalfx/obstudio/observer/internal/adoption" {
			t.Fatal("export imports the adoption package")
		}
	}
}
