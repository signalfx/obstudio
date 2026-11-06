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
	do(http.MethodPost, "/api/splunk/export", false)
	if got := recordedPoints(t, r); len(got) != 0 {
		t.Fatalf("recorded %v", got)
	}

	status = http.StatusOK
	do(http.MethodGet, "/api/query/traces", true)
	do(http.MethodPost, "/api/validation/run", false)
	do(http.MethodPost, "/api/splunk/export", false)
	got := recordedPoints(t, r)
	want := map[string]int64{
		adoption.MetricActive + "{ui}":               1,
		adoption.MetricFirstUse + "{validation_run}": 1,
		adoption.MetricFirstUse + "{connect}":        1,
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
