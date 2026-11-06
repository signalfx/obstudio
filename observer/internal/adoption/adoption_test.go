package adoption

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/otel/attribute"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"

	"github.com/signalfx/obstudio/observer/internal/adoption/export"
	"github.com/signalfx/obstudio/observer/internal/adoption/gate"
	"github.com/signalfx/obstudio/observer/internal/store"
)

// fakeGate is a controllable telemetry gate.
type fakeGate struct {
	mu      sync.Mutex
	allowed bool
	reason  gate.Reason
	opted   bool
	subs    []func()
	decides int
	block   chan struct{}
}

func (g *fakeGate) Decide() gate.Decision {
	g.mu.Lock()
	block := g.block
	g.mu.Unlock()
	if block != nil {
		<-block
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	g.decides++
	if g.allowed {
		return gate.Decision{Allowed: true}
	}
	r := g.reason
	if r == "" {
		r = gate.ReasonConsentOff
	}
	return gate.Decision{Reason: r}
}

func (g *fakeGate) OptedOut() bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.opted
}

func (g *fakeGate) SubscribeOptOut(fn func()) func() {
	g.mu.Lock()
	g.subs = append(g.subs, fn)
	g.mu.Unlock()
	return func() {}
}

func (g *fakeGate) set(allowed bool) {
	g.mu.Lock()
	g.allowed = allowed
	g.mu.Unlock()
}

func (g *fakeGate) optOutEntry() {
	g.mu.Lock()
	g.opted = true
	g.allowed = false
	subs := append([]func(){}, g.subs...)
	g.mu.Unlock()
	for _, fn := range subs {
		fn()
	}
}

// fakeExporter records batches and returns a scripted result.
type fakeExporter struct {
	mu      sync.Mutex
	next    []error
	batches []metricdata.ResourceMetrics
	block   chan struct{}
}

func (f *fakeExporter) Temporality(sdkmetric.InstrumentKind) metricdata.Temporality {
	return metricdata.CumulativeTemporality
}
func (f *fakeExporter) Aggregation(k sdkmetric.InstrumentKind) sdkmetric.Aggregation {
	return sdkmetric.DefaultAggregationSelector(k)
}
func (f *fakeExporter) ForceFlush(context.Context) error { return nil }
func (f *fakeExporter) Shutdown(context.Context) error   { return nil }
func (f *fakeExporter) Export(_ context.Context, rm *metricdata.ResourceMetrics) error {
	f.mu.Lock()
	f.batches = append(f.batches, *rm)
	block := f.block
	var err error
	if len(f.next) > 0 {
		err = f.next[0]
		f.next = f.next[1:]
	}
	f.mu.Unlock()
	if block != nil {
		<-block
	}
	return err
}

func (f *fakeExporter) results(errs ...error) {
	f.mu.Lock()
	f.next = append(f.next, errs...)
	f.mu.Unlock()
}

func (f *fakeExporter) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.batches)
}

func (f *fakeExporter) last() metricdata.ResourceMetrics {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.batches[len(f.batches)-1]
}

var errFailed = errors.New("503")

func dropped() error { return &export.DroppedError{Reason: gate.ReasonConsentOff} }

type clock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *clock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *clock) set(s string) {
	t, _ := time.Parse(time.RFC3339, s)
	c.mu.Lock()
	c.t = t
	c.mu.Unlock()
}

type harness struct {
	t      *testing.T
	dir    string
	g      *fakeGate
	next   *fakeExporter
	clock  *clock
	reader *sdkmetric.ManualReader
	e      *Emitter
	wrap   sdkmetric.Exporter
}

const validID = "3f1c2a9e-7b4d-4e2a-9c1f-0a8b6d5e4f32"

func newHarness(t *testing.T, open bool) *harness {
	t.Helper()
	h := &harness{t: t, dir: filepath.Join(t.TempDir(), ".obstudio"), g: &fakeGate{allowed: open}, next: &fakeExporter{}, clock: &clock{}}
	h.clock.set("2026-11-02T10:00:00Z")
	return h
}

func (h *harness) withID(id string) *harness {
	h.t.Helper()
	if err := os.MkdirAll(h.dir, 0o700); err != nil {
		h.t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(h.dir, installIDFile), []byte(id+"\n"), 0o600); err != nil {
		h.t.Fatal(err)
	}
	return h
}

func (h *harness) withState(doc string) *harness {
	h.t.Helper()
	_ = os.MkdirAll(h.dir, 0o700)
	if err := os.WriteFile(filepath.Join(h.dir, stateFile), []byte(doc), 0o600); err != nil {
		h.t.Fatal(err)
	}
	return h
}

func (h *harness) start(launcher string) *harness {
	h.t.Helper()
	e, err := New(Config{Dir: h.dir, Gate: h.g, Version: "1.2.3-test", Launcher: launcher, Now: h.clock.now})
	if err != nil {
		h.t.Fatal(err)
	}
	h.e = e
	h.wrap = e.Exporter(h.next)
	h.reader = sdkmetric.NewManualReader(sdkmetric.WithTemporalitySelector(h.wrap.Temporality))
	if err := e.Start(h.reader); err != nil {
		h.t.Fatal(err)
	}
	return h
}

func (h *harness) export() error {
	h.t.Helper()
	var rm metricdata.ResourceMetrics
	if err := h.reader.Collect(context.Background(), &rm); err != nil {
		h.t.Fatal(err)
	}
	return h.wrap.Export(context.Background(), &rm)
}

func (h *harness) state() map[string]any {
	h.t.Helper()
	data, err := os.ReadFile(filepath.Join(h.dir, stateFile))
	if err != nil {
		return nil
	}
	var m map[string]any
	_ = json.Unmarshal(data, &m)
	return m
}

func (h *harness) waitFile(name string) {
	h.t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(filepath.Join(h.dir, name)); err == nil {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	h.t.Fatalf("%s never appeared", name)
}

// points flattens a batch into "metric{dim=value}" → value.
func points(rm metricdata.ResourceMetrics) map[string]int64 {
	out := map[string]int64{}
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			sum, ok := m.Data.(metricdata.Sum[int64])
			if !ok {
				continue
			}
			for _, dp := range sum.DataPoints {
				k := m.Name
				for _, kv := range dp.Attributes.ToSlice() {
					k += "{" + string(kv.Key) + "=" + kv.Value.AsString() + "}"
				}
				out[k] += dp.Value
			}
		}
	}
	return out
}

func firstUse(f string) string { return MetricFirstUse + "{feature=" + f + "}" }
func active(s string) string   { return MetricActive + "{surface=" + s + "}" }

func TestFirstUseOncePerFeature(t *testing.T) {
	h := newHarness(t, true).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`).start("cli")
	for i := 0; i < 2; i++ {
		h.e.ObserverStarted()
		h.e.Connected()
		h.e.ValidationRun()
	}
	if err := h.export(); err != nil {
		t.Fatal(err)
	}
	got := points(h.next.last())
	want := map[string]int64{firstUse(FeatureObserverStart): 1, firstUse(FeatureConnect): 1, firstUse(FeatureValidationRun): 1}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("batch 1 = %v", got)
	}
	h.e.ObserverStarted()
	h.e.Connected()
	h.e.ValidationRun()
	n := h.next.count()
	_ = h.export()
	if h.next.count() != n {
		t.Fatalf("batch 2 forwarded: %v", points(h.next.last()))
	}
}

func TestActiveOncePerUTCDay(t *testing.T) {
	h := newHarness(t, true).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`).start("cli")
	h.e.ActiveMCP()
	h.e.ActiveMCP()
	_ = h.export()
	if got := points(h.next.last()); got[active(SurfaceMCP)] != 1 || len(got) != 1 {
		t.Fatalf("day one = %v", got)
	}
	n := h.next.count()
	h.e.ActiveMCP()
	_ = h.export()
	if h.next.count() != n {
		t.Fatal("same day exported again")
	}
	h.clock.set("2026-11-03T00:05:00Z")
	h.e.ActiveMCP()
	_ = h.export()
	if got := points(h.next.last()); got[active(SurfaceMCP)] != 1 {
		t.Fatalf("day two = %v", got)
	}
	if a := h.state()["active"].(map[string]any); a["mcp"] != "2026-11-03" {
		t.Fatalf("state active = %v", a)
	}
}

func TestResourceAttrsExact(t *testing.T) {
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=prod,obstudio.launcher=cli,service.instance.id=abc")
	t.Setenv("OTEL_SERVICE_NAME", "evil")
	h := newHarness(t, true).withID(validID).start("vscode-extension")
	h.e.ObserverStarted()
	_ = h.export()
	res := h.next.last().Resource
	got := map[string]string{}
	for _, kv := range res.Attributes() {
		got[string(kv.Key)] = kv.Value.AsString()
	}
	want := map[string]string{
		"service.name": "obstudio", "service.version": "1.2.3-test", "os.type": osType(runtime.GOOS),
		"host.arch": hostArch(runtime.GOARCH), "obstudio.launcher": "vscode-extension", "obstudio.user_hash": validID,
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("resource = %v", got)
	}
}

func TestLauncherBounded(t *testing.T) {
	for _, v := range []string{"vscode-extension", "cursor-extension", "windsurf-extension", "kiro-extension", "cli"} {
		if BoundLauncher(v) != v {
			t.Errorf("%s not kept", v)
		}
	}
	for _, v := range []string{"manual", "/home/x/bin", "VSCode-Extension", ""} {
		if BoundLauncher(v) != LauncherOther {
			t.Errorf("%q not other", v)
		}
	}
}

func TestExportConfirmedDelivery(t *testing.T) {
	h := newHarness(t, true).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`).start("cli")
	h.e.ObserverStarted()
	h.next.results(errFailed, dropped(), nil, nil)

	if err := h.export(); !errors.Is(err, errFailed) {
		t.Fatalf("export 1 = %v", err)
	}
	if points(h.next.last())[firstUse(FeatureObserverStart)] != 1 {
		t.Fatal("batch 1 missing the point")
	}
	if fu := h.state()["first_use"].(map[string]any); fu["observer_start"] != "pending" {
		t.Fatalf("after failed: %v", fu)
	}
	before, _ := os.ReadFile(filepath.Join(h.dir, stateFile))
	fi1, _ := os.Stat(filepath.Join(h.dir, stateFile))

	if err := h.export(); !errors.Is(err, export.ErrDropped) {
		t.Fatalf("export 2 = %v", err)
	}
	after, _ := os.ReadFile(filepath.Join(h.dir, stateFile))
	fi2, _ := os.Stat(filepath.Join(h.dir, stateFile))
	if string(before) != string(after) || !fi1.ModTime().Equal(fi2.ModTime()) {
		t.Fatal("dropped export wrote the state file")
	}
	if points(h.next.last())[firstUse(FeatureObserverStart)] != 1 {
		t.Fatal("batch 2 missing the point")
	}
	if err := h.export(); err != nil {
		t.Fatal(err)
	}
	if fu := h.state()["first_use"].(map[string]any); fu["observer_start"] != "delivered" {
		t.Fatalf("after sent: %v", fu)
	}
	n := h.next.count()
	_ = h.export()
	if h.next.count() != n {
		t.Fatal("delivered point exported again")
	}
}

func TestNoFilesWhileGateClosed(t *testing.T) {
	for _, r := range []gate.Reason{gate.ReasonConsentOff, gate.ReasonCI, gate.ReasonNoDestination} {
		t.Run(string(r), func(t *testing.T) {
			h := newHarness(t, false)
			h.g.reason = r
			h.start("cli")
			h.e.ObserverStarted()
			h.e.ActiveMCP()
			for i := 0; i < 3; i++ {
				_ = h.export()
			}
			time.Sleep(20 * time.Millisecond)
			if entries, _ := os.ReadDir(h.dir); len(entries) != 0 {
				t.Fatalf("files while closed: %v", entries)
			}
			if h.next.count() != 0 {
				t.Fatal("batch forwarded while closed")
			}
			h.g.set(true)
			_ = h.export()
			got := points(h.next.last())
			if got[firstUse(FeatureObserverStart)] != 1 || got[active(SurfaceMCP)] != 1 {
				t.Fatalf("pending points not carried: %v", got)
			}
			if _, err := os.Stat(filepath.Join(h.dir, installIDFile)); err != nil {
				t.Fatal("ID not created on the open export")
			}
		})
	}
}

func TestInstallIDInvalidRegenerates(t *testing.T) {
	cases := map[string]func(h *harness){
		"missing":   func(h *harness) { _ = os.MkdirAll(h.dir, 0o700) },
		"empty":     func(h *harness) { h.withID("") },
		"garbage":   func(h *harness) { h.withID("not-a-uuid") },
		"uppercase": func(h *harness) { h.withID("3F1C2A9E-7B4D-4E2A-9C1F-0A8B6D5E4F32") },
		"version1":  func(h *harness) { h.withID("3f1c2a9e-7b4d-1e2a-9c1f-0a8b6d5e4f32") },
	}
	for name, setup := range cases {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t, true)
			setup(h)
			h.withState(`{"first_use":{"install":"delivered"},"active":{}}`)
			h.start("cli")
			waitFor(t, func() bool {
				h.e.mu.Lock()
				defer h.e.mu.Unlock()
				return h.e.id != ""
			})
			if readInstallID(filepath.Join(h.dir, installIDFile)) == "" {
				t.Fatal("no valid install_id")
			}
			if fu := h.state()["first_use"].(map[string]any); !reflect.DeepEqual(fu, map[string]any{"install": "pending"}) {
				t.Fatalf("state = %v", h.state())
			}
		})
	}
	t.Run("closed-none", func(t *testing.T) {
		h := newHarness(t, false).withID("not-a-uuid").withState(`{"first_use":{"install":"delivered"},"active":{}}`)
		h.start("cli")
		time.Sleep(30 * time.Millisecond)
		if readInstallID(filepath.Join(h.dir, installIDFile)) != "" {
			t.Fatal("ID created with the gate closed")
		}
	})
	t.Run("unwritable", func(t *testing.T) {
		if runtime.GOOS == "windows" || os.Getuid() == 0 {
			t.Skip("needs POSIX permissions")
		}
		h := newHarness(t, true)
		_ = os.MkdirAll(h.dir, 0o500)
		t.Cleanup(func() { _ = os.Chmod(h.dir, 0o700) })
		h.start("cli")
		h.e.ObserverStarted()
		time.Sleep(30 * time.Millisecond)
		_ = h.export()
		if h.next.count() != 0 {
			t.Fatal("batch forwarded with no ID")
		}
	})
}

func waitFor(t *testing.T, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("condition never held")
}

func TestFirstUsePendingSurvivesRestart(t *testing.T) {
	h := newHarness(t, true).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`).start("cli")
	h.e.Connected()
	h.next.results(errFailed)
	_ = h.export()
	if fu := h.state()["first_use"].(map[string]any); fu["connect"] != "pending" {
		t.Fatalf("state = %v", fu)
	}
	h2 := &harness{t: t, dir: h.dir, g: h.g, next: &fakeExporter{}, clock: h.clock}
	h2.start("cli")
	_ = h2.export()
	if points(h2.next.last())[firstUse(FeatureConnect)] != 1 {
		t.Fatal("pending connect not re-recorded at start")
	}
	if fu := h2.state()["first_use"].(map[string]any); fu["connect"] != "delivered" {
		t.Fatalf("state = %v", fu)
	}
}

func TestActivePendingLapsesAtMidnight(t *testing.T) {
	h := newHarness(t, true).withID(validID).withState(`{"first_use":{"install":"delivered","ingest":"delivered"},"active":{}}`).start("cli")
	h.clock.set("2026-11-02T23:50:00Z")
	h.e.ActiveMCP()
	h.e.OTLPReceipt(appReceipt())
	h.next.results(errFailed, errFailed, nil)
	_ = h.export()
	h.clock.set("2026-11-03T00:10:00Z")
	_ = h.export() // carries the re-recorded 11-02 points; fails; they lapse
	h.e.ActiveMCP()
	h.e.OTLPReceipt(appReceipt())
	_ = h.export()
	for i, b := range h.next.batches {
		for k, v := range points(b) {
			if v != 1 {
				t.Fatalf("batch %d: %s = %d", i, k, v)
			}
		}
	}
	if got := points(h.next.last()); got[active(SurfaceMCP)] != 1 || got[MetricIngestActive] != 1 {
		t.Fatalf("new-date batch = %v", got)
	}
	st := h.state()
	if st["active"].(map[string]any)["mcp"] != "2026-11-03" || st["ingest_active"] != "2026-11-03" {
		t.Fatalf("state = %v", st)
	}
	// One more export: the lapsed 11-02 keys are not recorded again.
	n := h.next.count()
	_ = h.export()
	if h.next.count() != n {
		t.Fatalf("lapsed keys re-recorded: %v", points(h.next.last()))
	}
}

func TestOptOutWipe(t *testing.T) {
	h := newHarness(t, true).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`)
	flushes := 0
	var mu sync.Mutex
	h.start("cli")
	h.e.SetFlush(func(context.Context) error { mu.Lock(); flushes++; mu.Unlock(); return nil })
	h.e.Connected()
	h.g.optOutEntry()
	h.g.optOutEntry()
	for _, f := range []string{installIDFile, stateFile} {
		if _, err := os.Stat(filepath.Join(h.dir, f)); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("%s not wiped", f)
		}
	}
	h.g.set(true)
	_ = h.export()
	if h.next.count() != 0 {
		t.Fatalf("wiped connect still exported: %v", points(h.next.last()))
	}
	newID := readInstallID(filepath.Join(h.dir, installIDFile))
	if newID == "" || newID == validID {
		t.Fatalf("new ID = %q", newID)
	}
	waitFor(t, func() bool { mu.Lock(); defer mu.Unlock(); return flushes == 1 })
	_ = h.export()
	if got := points(h.next.last()); got[firstUse(FeatureInstall)] != 1 {
		t.Fatalf("install not pending after re-creation: %v", got)
	}

	t.Run("startup", func(t *testing.T) {
		h := newHarness(t, false).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`)
		h.g.opted = true
		h.start("cli")
		if _, err := os.Stat(filepath.Join(h.dir, installIDFile)); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("not wiped at start")
		}
	})
	t.Run("degraded-no-wipe", func(t *testing.T) {
		for _, r := range []gate.Reason{gate.ReasonConfigUnhealthy, gate.ReasonCI, gate.ReasonNoDestination} {
			h := newHarness(t, false).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`)
			h.g.reason = r
			h.start("cli")
			_ = h.export()
			if readInstallID(filepath.Join(h.dir, installIDFile)) != validID || h.state() == nil {
				t.Fatalf("%s: files changed", r)
			}
		}
	})
}

func TestOutcomeDiscardedAfterIDChange(t *testing.T) {
	h := newHarness(t, true).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`).start("cli")
	h.e.ObserverStarted()
	h.next.block = make(chan struct{})
	done := make(chan error)
	go func() { done <- h.export() }()
	waitFor(t, func() bool { return h.next.count() == 1 })
	h.g.optOutEntry()
	close(h.next.block)
	<-done
	for _, f := range []string{installIDFile, stateFile} {
		if _, err := os.Stat(filepath.Join(h.dir, f)); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("%s reappeared", f)
		}
	}
}

func TestInstallFlushOnlyForInstall(t *testing.T) {
	h := newHarness(t, true).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`)
	h.start("cli")
	calls := 0
	h.e.SetFlush(func(context.Context) error { calls++; return nil })
	h.e.ObserverStarted()
	h.e.Connected()
	h.e.ValidationRun()
	h.e.ActiveMCP()
	h.e.ActiveUI()
	h.e.OTLPReceipt(appReceipt())
	h.next.results(errFailed, nil)
	_ = h.export()
	if got := points(h.next.last()); len(got) != 7 {
		t.Fatalf("first batch = %v", got)
	}
	_ = h.export()
	time.Sleep(20 * time.Millisecond)
	if calls != 0 {
		t.Fatalf("flush calls = %d", calls)
	}
}

func TestCatalogOnlyV1Signals(t *testing.T) {
	h := newHarness(t, true).withID(validID).start("cli")
	h.e.ObserverStarted()
	h.e.Connected()
	h.e.ValidationRun()
	h.e.ActiveMCP()
	h.e.ActiveUI()
	h.e.OTLPReceipt(appReceipt())
	var rm metricdata.ResourceMetrics
	_ = h.reader.Collect(context.Background(), &rm)
	names := map[string]bool{}
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			names[m.Name] = true
			if _, ok := m.Data.(metricdata.Sum[int64]); !ok {
				t.Fatalf("%s is not an int64 sum", m.Name)
			}
			sum := m.Data.(metricdata.Sum[int64])
			if !sum.IsMonotonic || sum.Temporality != metricdata.DeltaTemporality {
				t.Fatalf("%s: monotonic=%v temporality=%v", m.Name, sum.IsMonotonic, sum.Temporality)
			}
			for _, dp := range sum.DataPoints {
				if len(dp.Exemplars) != 0 {
					t.Fatalf("%s carries exemplars", m.Name)
				}
			}
		}
	}
	if !reflect.DeepEqual(names, map[string]bool{MetricFirstUse: true, MetricActive: true, MetricIngestActive: true}) {
		t.Fatalf("instruments = %v", names)
	}
}

func appReceipt() store.Receipt {
	return store.Receipt{Spans: []store.Span{{Name: "GET /cart", Resource: store.Resource{ServiceName: "checkout"}}}}
}

func TestIngestQualifyingReceipt(t *testing.T) {
	h := newHarness(t, true).withID(validID).withState(`{"first_use":{"install":"delivered"},"active":{}}`).start("cli")
	excluded := []store.Receipt{
		{Spans: []store.Span{{Name: "x", Resource: store.Resource{ServiceName: "obstudio"}}}, Metrics: []store.MetricDataPoint{{Name: "m", Resource: store.Resource{ServiceName: "obstudio"}}}},
		{Logs: []store.LogRecord{{Attributes: map[string]any{"event.name": "api_request", "model": "claude-sonnet-4-5"}}}},
		{Metrics: []store.MetricDataPoint{{Name: "claude_code.session.count"}}},
		{Logs: []store.LogRecord{{Attributes: map[string]any{"event.name": "codex.tool_result"}}}},
		{Spans: []store.Span{{Name: "tool.execute", Resource: store.Resource{ServiceName: "codex-app-server"}, Scope: store.Scope{Name: "app"}}}},
		{Logs: []store.LogRecord{{Attributes: map[string]any{"event.name": "obstudio.repository_correlation"}, Resource: store.Resource{ServiceName: "obstudio-hook"}}}},
	}
	for _, r := range excluded {
		h.e.OTLPReceipt(r)
	}
	n := h.next.count()
	_ = h.export()
	if h.next.count() != n {
		t.Fatalf("an excluded receipt qualified: %v", points(h.next.last()))
	}
	h.e.OTLPReceipt(appReceipt())
	_ = h.export()
	got := points(h.next.last())
	if got[firstUse(FeatureIngest)] != 1 || got[MetricIngestActive] != 1 || len(got) != 2 {
		t.Fatalf("batch = %v", got)
	}
	st := h.state()
	if st["first_use"].(map[string]any)["ingest"] != "delivered" || st["ingest_active"] != "2026-11-02" {
		t.Fatalf("state = %v", st)
	}
	n = h.next.count()
	h.e.OTLPReceipt(appReceipt())
	_ = h.export()
	if h.next.count() != n {
		t.Fatal("same-day receipt exported again")
	}
	h.clock.set("2026-11-03T09:00:00Z")
	h.e.OTLPReceipt(store.Receipt{
		Metrics: []store.MetricDataPoint{{Name: "claude_code.session.count", Resource: store.Resource{ServiceName: "claude-code"}}},
		Spans:   []store.Span{{Name: "GET /cart", Resource: store.Resource{ServiceName: "checkout"}}},
	})
	_ = h.export()
	got = points(h.next.last())
	if got[MetricIngestActive] != 1 || got[firstUse(FeatureIngest)] != 0 {
		t.Fatalf("mixed batch = %v", got)
	}
	for _, b := range h.next.batches {
		for k := range points(b) {
			if k == active(SurfaceMCP) || k == active(SurfaceUI) {
				t.Fatal("ingest qualified active")
			}
		}
	}
}

func TestRegistrationIndependentOfConsent(t *testing.T) {
	h := newHarness(t, false).start("cli")
	h.e.ObserverStarted()
	h.e.ActiveMCP()
	var rm metricdata.ResourceMetrics
	_ = h.reader.Collect(context.Background(), &rm)
	if got := points(rm); got[firstUse(FeatureObserverStart)] != 1 || got[active(SurfaceMCP)] != 1 {
		t.Fatalf("recorded = %v", got)
	}
	if entries, _ := os.ReadDir(h.dir); len(entries) != 0 {
		t.Fatal("recording wrote a file")
	}
}

func TestUUIDv4(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 100; i++ {
		id, err := newUUIDv4()
		if err != nil || !uuidV4.MatchString(id) || seen[id] {
			t.Fatalf("id %q err %v", id, err)
		}
		seen[id] = true
	}
}

func TestNilEmitterIgnoresEvents(t *testing.T) {
	var e *Emitter
	e.ObserverStarted()
	e.Connected()
	e.ValidationRun()
	e.ActiveMCP()
	e.ActiveUI()
	e.OTLPReceipt(appReceipt())
	e.SetFlush(nil)
	if err := e.Start(nil); err != nil {
		t.Fatal(err)
	}
	if err := e.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
}

var _ = attribute.String
