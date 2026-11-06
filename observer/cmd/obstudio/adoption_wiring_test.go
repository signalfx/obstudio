package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	"go.opentelemetry.io/otel/sdk/resource"

	"github.com/signalfx/obstudio/observer/internal/adoption"
	"github.com/signalfx/obstudio/observer/internal/adoption/gate"
	"github.com/signalfx/obstudio/observer/internal/store"
)

type closedGate struct{}

func (closedGate) Decide() gate.Decision         { return gate.Decision{Reason: gate.ReasonConsentOff} }
func (closedGate) OptedOut() bool                { return false }
func (closedGate) SubscribeOptOut(func()) func() { return func() {} }

func TestBuildAdoptionWithoutManagerIsInert(t *testing.T) {
	home := t.TempDir()
	s := store.New()
	w := buildAdoption(nil, filepath.Join(home, ".obstudio", "config.yaml"), "cli", s)
	if w.emitter != nil || w.gate != nil {
		t.Fatal("adoption built with no Manager")
	}
	mux := http.NewServeMux()
	if h := w.handler(mux); h != http.Handler(mux) {
		t.Fatal("handler wrapped with no emitter")
	}
	hooks := w.mcpHooks()
	hooks.ToolsCall()
	hooks.ValidationRun()
	hooks.Connect()
	if w.cloudConnected() != nil {
		t.Fatal("cloud connect hook built with no emitter")
	}
	w.observerStarted()
	w.shutdown()
	if _, err := os.Stat(filepath.Join(home, ".obstudio")); !os.IsNotExist(err) {
		t.Fatal("files created with no Manager")
	}
}

func recordedPoints(t *testing.T, r *sdkmetric.ManualReader) map[string]int64 {
	t.Helper()
	var rm metricdata.ResourceMetrics
	if err := r.Collect(context.Background(), &rm); err != nil {
		t.Fatal(err)
	}
	out := map[string]int64{}
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			for _, dp := range m.Data.(metricdata.Sum[int64]).DataPoints {
				k := m.Name
				for _, kv := range dp.Attributes.ToSlice() {
					k += "{" + kv.Value.AsString() + "}"
				}
				out[k] += dp.Value
			}
		}
	}
	return out
}

func newTestEmitter(t *testing.T) (*adoption.Emitter, *sdkmetric.ManualReader) {
	t.Helper()
	em, err := adoption.New(adoption.Config{Dir: filepath.Join(t.TempDir(), ".obstudio"), Gate: closedGate{}, Version: "test"})
	if err != nil {
		t.Fatal(err)
	}
	r := sdkmetric.NewManualReader(sdkmetric.WithTemporalitySelector(func(sdkmetric.InstrumentKind) metricdata.Temporality {
		return metricdata.DeltaTemporality
	}))
	if err := em.Start(r); err != nil {
		t.Fatal(err)
	}
	return em, r
}

func TestAdoptionHandlerObservesUIAndRoutes(t *testing.T) {
	em, r := newTestEmitter(t)
	w := adoptionWiring{emitter: em}
	status := http.StatusOK
	h := w.handler(http.HandlerFunc(func(rw http.ResponseWriter, _ *http.Request) { rw.WriteHeader(status) }))
	do := func(method, path string, ui bool) {
		req := httptest.NewRequest(method, path, nil)
		if ui {
			req.Header.Set(surfaceHeader, "ui")
		}
		h.ServeHTTP(httptest.NewRecorder(), req)
	}

	do(http.MethodGet, "/api/health", true)
	do(http.MethodGet, "/api/splunk/export", true)
	do(http.MethodGet, "/api/query/traces", false)
	status = http.StatusInternalServerError
	do(http.MethodPost, "/api/validation/run", false)
	if got := recordedPoints(t, r); len(got) != 0 {
		t.Fatalf("recorded %v", got)
	}

	status = http.StatusOK
	do(http.MethodGet, "/api/query/traces", true)
	do(http.MethodPost, "/api/validation/run", false)
	// The api package reports connects; a 2xx here is not one.
	do(http.MethodPost, "/api/splunk/export", false)
	got := recordedPoints(t, r)
	want := map[string]int64{
		adoption.MetricActive + "{ui}":               1,
		adoption.MetricFirstUse + "{validation_run}": 1,
	}
	if len(got) != len(want) {
		t.Fatalf("recorded %v", got)
	}
	for k, v := range want {
		if got[k] != v {
			t.Fatalf("recorded %v", got)
		}
	}
}

func TestAdoptionCloudConnected(t *testing.T) {
	em, r := newTestEmitter(t)
	adoptionWiring{emitter: em}.cloudConnected()()
	if got := recordedPoints(t, r); got[adoption.MetricFirstUse+"{connect}"] != 1 {
		t.Fatalf("recorded %v", got)
	}
}

func TestAdoptionMCPHooks(t *testing.T) {
	em, r := newTestEmitter(t)
	hooks := adoptionWiring{emitter: em}.mcpHooks()
	hooks.ToolsCall()
	hooks.ToolsCall()
	hooks.ValidationRun()
	hooks.Connect()
	got := recordedPoints(t, r)
	if got[adoption.MetricActive+"{mcp}"] != 1 || got[adoption.MetricFirstUse+"{validation_run}"] != 1 || got[adoption.MetricFirstUse+"{connect}"] != 1 {
		t.Fatalf("recorded %v", got)
	}
}

type openGate struct{}

func (openGate) Decide() gate.Decision         { return gate.Decision{Allowed: true} }
func (openGate) OptedOut() bool                { return false }
func (openGate) SubscribeOptOut(func()) func() { return func() {} }

// captureExporter keeps the last resource the emitter forwarded.
type captureExporter struct{ res *resource.Resource }

func (*captureExporter) Temporality(sdkmetric.InstrumentKind) metricdata.Temporality {
	return metricdata.DeltaTemporality
}
func (*captureExporter) Aggregation(k sdkmetric.InstrumentKind) sdkmetric.Aggregation {
	return sdkmetric.DefaultAggregationSelector(k)
}
func (c *captureExporter) Export(_ context.Context, rm *metricdata.ResourceMetrics) error {
	c.res = rm.Resource
	return nil
}
func (*captureExporter) ForceFlush(context.Context) error { return nil }
func (*captureExporter) Shutdown(context.Context) error   { return nil }

func TestAdoptionLauncherFromObserverOwner(t *testing.T) {
	cases := []struct {
		name, owner, otelAttrs, want string
		unset                        bool
	}{
		{name: "unset", unset: true, want: "cli"},
		{name: "vscode extension", owner: "vscode-extension", want: "vscode-extension"},
		{name: "plugin", owner: "codex-plugin", want: adoption.LauncherOther},
		{name: "otel env ignored", owner: "codex-eval", otelAttrs: "obstudio.launcher=cli", want: adoption.LauncherOther},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("OBSTUDIO_OWNER", tc.owner)
			if tc.unset {
				_ = os.Unsetenv("OBSTUDIO_OWNER")
			}
			t.Setenv("OTEL_RESOURCE_ATTRIBUTES", tc.otelAttrs)
			dir := filepath.Join(t.TempDir(), ".obstudio")
			if err := os.MkdirAll(dir, 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(dir, "install_id"), []byte("3f1c2a9e-7b4d-4e2a-9c1f-0a8b6d5e4f32\n"), 0o600); err != nil {
				t.Fatal(err)
			}
			em, err := adoption.New(adoption.Config{Dir: dir, Gate: openGate{}, Version: "test", Launcher: resolveObserverOwner()})
			if err != nil {
				t.Fatal(err)
			}
			capture := &captureExporter{}
			wrap := em.Exporter(capture)
			r := sdkmetric.NewManualReader(sdkmetric.WithTemporalitySelector(wrap.Temporality))
			if err := em.Start(r); err != nil {
				t.Fatal(err)
			}
			em.ObserverStarted()
			var rm metricdata.ResourceMetrics
			if err := r.Collect(context.Background(), &rm); err != nil {
				t.Fatal(err)
			}
			if err := wrap.Export(context.Background(), &rm); err != nil {
				t.Fatal(err)
			}
			if capture.res == nil {
				t.Fatal("nothing forwarded")
			}
			got, _ := capture.res.Set().Value("obstudio.launcher")
			if got.AsString() != tc.want {
				t.Fatalf("obstudio.launcher = %q, want %q", got.AsString(), tc.want)
			}
		})
	}
}
