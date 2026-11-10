package gate

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

// fakeConfig stands in for the Manager: Get returns a settable snapshot and
// SubscribeFile records fn so the test can fire it synchronously.
type fakeConfig struct {
	mu          sync.Mutex
	enabled     bool
	gets        int
	subscribes  int
	cancels     int
	closes      int
	fn          func()
	onSubscribe func()
}

func (f *fakeConfig) Get() userconfig.Snapshot {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.gets++
	return userconfig.Snapshot{Settings: userconfig.Settings{Telemetry: userconfig.TelemetrySettings{Enabled: f.enabled}}}
}

func (f *fakeConfig) SubscribeFile(fn func()) func() {
	f.mu.Lock()
	f.subscribes++
	f.fn = fn
	hook := f.onSubscribe
	f.mu.Unlock()
	if hook != nil {
		hook()
	}
	return func() {
		f.mu.Lock()
		f.cancels++
		f.mu.Unlock()
	}
}

func (f *fakeConfig) Close() error {
	f.mu.Lock()
	f.closes++
	f.mu.Unlock()
	return nil
}

func (f *fakeConfig) setEnabled(v bool) {
	f.mu.Lock()
	f.enabled = v
	f.mu.Unlock()
}

func (f *fakeConfig) getCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.gets
}

func (f *fakeConfig) fire() {
	f.mu.Lock()
	fn := f.fn
	f.mu.Unlock()
	fn()
}

const brokenYAML = "telemetry: [\n"

func scaffold(enabled bool) string {
	s := userconfig.Scaffold()
	if !enabled {
		s = strings.Replace(s, "enabled: true", "enabled: false", 1)
	}
	return s
}

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

type env struct {
	mu   sync.Mutex
	vals map[string]string
	read map[string]bool
}

func newEnv(kv ...string) *env {
	e := &env{vals: map[string]string{}, read: map[string]bool{}}
	for i := 0; i+1 < len(kv); i += 2 {
		e.vals[kv[i]] = kv[i+1]
	}
	return e
}

func (e *env) get(k string) string {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.read[k] = true
	return e.vals[k]
}

func (e *env) set(k, v string) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if v == "" {
		delete(e.vals, k)
		return
	}
	e.vals[k] = v
}

type harness struct {
	t       *testing.T
	path    string
	cfg     *fakeConfig
	env     *env
	hostOff atomic.Bool
	dest    bool
}

// openHarness is "open inputs": consent true, scaffold file, empty
// environment, host not off, destination set.
func openHarness(t *testing.T) *harness {
	t.Helper()
	h := &harness{t: t, path: filepath.Join(t.TempDir(), "config.yaml"), cfg: &fakeConfig{enabled: true}, env: newEnv(), dest: true}
	writeFile(t, h.path, scaffold(true))
	return h
}

func (h *harness) inputs() Inputs {
	return Inputs{Config: h.cfg, Path: h.path, Getenv: h.env.get, HostOff: h.hostOff.Load, DestinationSet: h.dest}
}

func (h *harness) gate() *Gate { return New(h.inputs()) }

func expect(t *testing.T, got Decision, allowed bool, reason Reason) {
	t.Helper()
	if got.Allowed != allowed || got.Reason != reason {
		t.Fatalf("Decide() = %+v, want {Allowed:%v Reason:%q}", got, allowed, reason)
	}
}

func TestOpenWhenAllHold(t *testing.T) {
	h := openHarness(t)
	g := h.gate()
	expect(t, g.Decide(), true, ReasonNone)
	if h.cfg.subscribes != 1 {
		t.Fatalf("SubscribeFile calls = %d, want 1", h.cfg.subscribes)
	}

	h2 := openHarness(t)
	h2.cfg.onSubscribe = func() { writeFile(t, h2.path, scaffold(false)) }
	g2 := h2.gate()
	if !g2.OptedOut() {
		t.Fatal("subscribed-first: initial load did not run after the subscription")
	}
}

func TestNoManagerClosed(t *testing.T) {
	e := newEnv("CI", "true")
	var hostCalls atomic.Int32
	hostOff := func() bool { hostCalls.Add(1); return false }
	missing := filepath.Join(t.TempDir(), "absent.yaml")
	gates := map[string]*Gate{
		"nil":       nil,
		"zero":      {},
		"no-config": New(Inputs{Config: nil, Path: missing, Getenv: e.get, HostOff: hostOff, DestinationSet: true}),
		"typed-nil": New(Inputs{Config: (*userconfig.Manager)(nil), Path: missing, Getenv: e.get, HostOff: hostOff, DestinationSet: true}),
	}
	for name, g := range gates {
		t.Run(name, func(t *testing.T) {
			expect(t, g.Decide(), false, ReasonNoManager)
			if g.OptedOut() {
				t.Fatal("OptedOut() = true")
			}
			called := false
			cancel := g.SubscribeOptOut(func() { called = true })
			cancel()
			cancel()
			g.Close()
			g.Close()
			expect(t, g.Decide(), false, ReasonNoManager)
			if called {
				t.Fatal("subscriber called")
			}
		})
	}
	if len(e.read) != 0 {
		t.Fatalf("Getenv read %v with no Manager", e.read)
	}
	if hostCalls.Load() != 0 {
		t.Fatal("HostOff called with no Manager")
	}
}

func TestOffOnlyInputCloses(t *testing.T) {
	cases := []struct {
		name   string
		apply  func(h *harness)
		revert func(h *harness)
		reason Reason
	}{
		{"ci", func(h *harness) { h.env.set("CI", "true") }, func(h *harness) { h.env.set("CI", "") }, ReasonCI},
		{"dnt", func(h *harness) { h.env.set("DO_NOT_TRACK", "1") }, func(h *harness) { h.env.set("DO_NOT_TRACK", "") }, ReasonDoNotTrack},
		{"host", func(h *harness) { h.hostOff.Store(true) }, func(h *harness) { h.hostOff.Store(false) }, ReasonHostOff},
		{"dest", func(h *harness) { h.dest = false }, nil, ReasonNoDestination},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := openHarness(t)
			c.apply(h)
			g := h.gate()
			expect(t, g.Decide(), false, c.reason)
			if g.OptedOut() {
				t.Fatal("OptedOut() = true")
			}
			if c.revert != nil {
				c.revert(h)
				expect(t, g.Decide(), true, ReasonNone)
			}
		})
	}
}

func TestConsentReadPerDecision(t *testing.T) {
	h := openHarness(t)
	g := h.gate()
	before := h.cfg.getCount()
	expect(t, g.Decide(), true, ReasonNone)
	h.cfg.setEnabled(false)
	expect(t, g.Decide(), false, ReasonConsentOff)
	h.cfg.setEnabled(true)
	expect(t, g.Decide(), true, ReasonNone)
	if got := h.cfg.getCount() - before; got != 3 {
		t.Fatalf("Get() calls = %d, want 3", got)
	}
}

func TestBrokenWhileRunning(t *testing.T) {
	h := openHarness(t)
	g := h.gate()
	steps := []struct {
		do      func()
		allowed bool
		reason  Reason
	}{
		{func() { writeFile(t, h.path, brokenYAML) }, false, ReasonConfigUnhealthy},
		{func() { writeFile(t, h.path, scaffold(true)) }, true, ReasonNone},
		{func() { _ = os.Remove(h.path) }, false, ReasonConfigUnhealthy},
		{func() { writeFile(t, h.path, scaffold(true)) }, true, ReasonNone},
	}
	for i, s := range steps {
		s.do()
		h.cfg.fire()
		got := g.Decide()
		if got.Allowed != s.allowed || got.Reason != s.reason {
			t.Fatalf("step %d: Decide() = %+v", i+1, got)
		}
		if g.OptedOut() {
			t.Fatalf("step %d: OptedOut() = true", i+1)
		}
	}
}

func TestOptedOutAtStartup(t *testing.T) {
	h := openHarness(t)
	writeFile(t, h.path, scaffold(false))
	h.cfg.enabled = false
	g := h.gate()
	called := 0
	g.SubscribeOptOut(func() { called++ })
	if !g.OptedOut() {
		t.Fatal("OptedOut() = false")
	}
	expect(t, g.Decide(), false, ReasonConsentOff)
	if called != 0 {
		t.Fatal("subscriber had an initial call")
	}
	h.env.set("CI", "true")
	if !g.OptedOut() {
		t.Fatal("a kill cleared OptedOut")
	}
	expect(t, g.Decide(), false, ReasonConsentOff)
}

func TestDegradedNeverOptedOut(t *testing.T) {
	cases := []struct {
		name    string
		file    *string
		enabled bool
		apply   func(h *harness)
		noMgr   bool
		reason  Reason
	}{
		{name: "a-syntax", file: ptr(brokenYAML), reason: ReasonConfigUnhealthy},
		{name: "b-missing", file: nil, reason: ReasonConfigUnhealthy},
		{name: "c-maybe", file: ptr(strings.Replace(scaffold(true), "enabled: true", "enabled: maybe", 1)), reason: ReasonConsentOff},
		{name: "d-absent", file: ptr(strings.Replace(scaffold(true), "  enabled: true\n", "", 1)), reason: ReasonConsentOff},
		{name: "e-not-mapping", file: ptr("telemetry: true\n"), reason: ReasonConsentOff},
		{name: "f-ci", file: ptr(scaffold(true)), enabled: true, apply: func(h *harness) { h.env.set("CI", "true") }, reason: ReasonCI},
		{name: "g-dnt", file: ptr(scaffold(true)), enabled: true, apply: func(h *harness) { h.env.set("DO_NOT_TRACK", "1") }, reason: ReasonDoNotTrack},
		{name: "h-host", file: ptr(scaffold(true)), enabled: true, apply: func(h *harness) { h.hostOff.Store(true) }, reason: ReasonHostOff},
		{name: "i-dest", file: ptr(scaffold(true)), enabled: true, apply: func(h *harness) { h.dest = false }, reason: ReasonNoDestination},
		{name: "j-no-manager", file: ptr(scaffold(true)), noMgr: true, reason: ReasonNoManager},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := openHarness(t)
			if c.file == nil {
				_ = os.Remove(h.path)
			} else {
				writeFile(t, h.path, *c.file)
			}
			h.cfg.enabled = c.enabled
			if c.apply != nil {
				c.apply(h)
			}
			in := h.inputs()
			if c.noMgr {
				in.Config = nil
			}
			g := New(in)
			called := 0
			g.SubscribeOptOut(func() { called++ })
			if g.OptedOut() {
				t.Fatal("OptedOut() = true before fire")
			}
			if !c.noMgr {
				h.cfg.fire()
			}
			if g.OptedOut() {
				t.Fatal("OptedOut() = true after fire")
			}
			if called != 0 {
				t.Fatal("subscriber called")
			}
			expect(t, g.Decide(), false, c.reason)
		})
	}
}

func ptr(s string) *string { return &s }

func TestOffOnlyNeverOpens(t *testing.T) {
	bases := []struct {
		name   string
		setup  func(h *harness) Inputs
		reason Reason
	}{
		{"no-manager", func(h *harness) Inputs { in := h.inputs(); in.Config = nil; return in }, ReasonNoManager},
		{"unhealthy", func(h *harness) Inputs { writeFile(h.t, h.path, brokenYAML); return h.inputs() }, ReasonConfigUnhealthy},
		{"consent-off", func(h *harness) Inputs { h.cfg.enabled = false; return h.inputs() }, ReasonConsentOff},
	}
	for _, b := range bases {
		t.Run(b.name, func(t *testing.T) {
			for _, ci := range []string{"", "false", "true"} {
				for _, dnt := range []string{"", "0", "1"} {
					for _, host := range []bool{false, true} {
						for _, dest := range []bool{false, true} {
							h := openHarness(t)
							h.env.set("CI", ci)
							h.env.set("DO_NOT_TRACK", dnt)
							h.hostOff.Store(host)
							h.dest = dest
							g := New(b.setup(h))
							expect(t, g.Decide(), false, b.reason)
						}
					}
				}
			}
		})
	}
}

func TestReasonOrder(t *testing.T) {
	h := openHarness(t)
	g := h.gate()
	steps := []struct {
		do     func()
		reason Reason
	}{
		{func() { g.dest = false }, ReasonNoDestination},
		{func() { h.hostOff.Store(true) }, ReasonHostOff},
		{func() { h.env.set("DO_NOT_TRACK", "1") }, ReasonDoNotTrack},
		{func() { h.env.set("CI", "true") }, ReasonCI},
		{func() { h.cfg.setEnabled(false) }, ReasonConsentOff},
		{func() { writeFile(t, h.path, brokenYAML); h.cfg.fire() }, ReasonConfigUnhealthy},
		{func() { g.Close() }, ReasonNoManager},
	}
	for _, s := range steps {
		s.do()
		expect(t, g.Decide(), false, s.reason)
	}
}

func TestCITable(t *testing.T) {
	flagRows := []string{"CI", "TF_BUILD", "GITHUB_ACTIONS", "APPVEYOR", "TRAVIS", "CIRCLECI", "CIRRUS_CI", "CONTINUOUS_INTEGRATION", "BOT"}
	setRows := []string{"TEAMCITY_VERSION", "JB_SPACE_API_URL", "JENKINS_URL", "CODEBUILD_INITIATOR"}
	pairRows := [][2]string{{"CODEBUILD_BUILD_ID", "AWS_REGION"}, {"BUILD_ID", "BUILD_URL"}, {"BUILD_ID", "PROJECT_ID"}}

	decide := func(kv ...string) (Decision, *env) {
		h := openHarness(t)
		h.env = newEnv(kv...)
		return h.gate().Decide(), h.env
	}
	for _, v := range flagRows {
		for _, val := range []string{"true", "TRUE", "1", " yes "} {
			if d, _ := decide(v, val); d.Reason != ReasonCI {
				t.Errorf("%s=%q: %+v, want ci", v, val, d)
			}
		}
		for _, val := range []string{"false", "False", "0", ""} {
			if d, _ := decide(v, val); !d.Allowed {
				t.Errorf("%s=%q: %+v, want open", v, val, d)
			}
		}
	}
	for _, v := range setRows {
		if d, _ := decide(v, "x"); d.Reason != ReasonCI {
			t.Errorf("%s set: %+v, want ci", v, d)
		}
		if d, _ := decide(v, "   "); !d.Allowed {
			t.Errorf("%s blank: %+v, want open", v, d)
		}
	}
	for _, p := range pairRows {
		if d, _ := decide(p[0], "a", p[1], "b"); d.Reason != ReasonCI {
			t.Errorf("%v both: %+v, want ci", p, d)
		}
		if d, _ := decide(p[0], "a"); !d.Allowed {
			t.Errorf("%s alone: %+v, want open", p[0], d)
		}
		if d, _ := decide(p[1], "b"); !d.Allowed {
			t.Errorf("%s alone: %+v, want open", p[1], d)
		}
	}
	for _, v := range []string{"CLAUDECODE", "CURSOR_EDITOR", "GEMINI_CLI"} {
		if d, _ := decide(v, "1"); !d.Allowed {
			t.Errorf("agent var %s: %+v, want open", v, d)
		}
	}
	d, e := decide("OTEL_METRICS_EXPORTER", "none", "OTEL_SDK_DISABLED", "true")
	if !d.Allowed {
		t.Errorf("OTEL vars closed the gate: %+v", d)
	}
	if e.read["OTEL_METRICS_EXPORTER"] || e.read["OTEL_SDK_DISABLED"] {
		t.Error("gate read an OTEL_* variable")
	}
	for _, val := range []string{"1", "true"} {
		if d, _ := decide("DO_NOT_TRACK", val); d.Reason != ReasonDoNotTrack {
			t.Errorf("DO_NOT_TRACK=%s: %+v", val, d)
		}
	}
	for _, val := range []string{"0", "false", ""} {
		if d, _ := decide("DO_NOT_TRACK", val); !d.Allowed {
			t.Errorf("DO_NOT_TRACK=%q: %+v", val, d)
		}
	}
}

func TestOptOutSubscribers(t *testing.T) {
	h := openHarness(t)
	g := h.gate()
	var f1Calls int
	var f1Saw []bool
	f2Calls := 0
	cancel1 := g.SubscribeOptOut(func() { f1Calls++; f1Saw = append(f1Saw, g.OptedOut()) })
	g.SubscribeOptOut(func() {
		f2Calls++
		if f2Calls == 1 {
			panic("boom")
		}
	})

	writeFile(t, h.path, scaffold(false))
	h.cfg.fire()
	if f1Calls != 1 || !f1Saw[0] {
		t.Fatalf("entry-once: f1Calls=%d saw=%v", f1Calls, f1Saw)
	}
	h.cfg.fire()
	if f1Calls != 1 {
		t.Fatal("no-repeat: an unchanged load called a subscriber")
	}
	writeFile(t, h.path, brokenYAML)
	h.cfg.fire()
	if g.OptedOut() || f1Calls != 1 {
		t.Fatal("leave-silent failed")
	}
	writeFile(t, h.path, scaffold(false))
	h.cfg.fire()
	if f1Calls != 2 || f2Calls != 2 {
		t.Fatalf("re-entry: f1=%d f2=%d", f1Calls, f2Calls)
	}
	cancel1()
	cancel1()
	writeFile(t, h.path, scaffold(true))
	h.cfg.fire()
	writeFile(t, h.path, scaffold(false))
	h.cfg.fire()
	if f1Calls != 2 || f2Calls != 3 {
		t.Fatalf("cancelled: f1=%d f2=%d", f1Calls, f2Calls)
	}
}

func TestClose(t *testing.T) {
	h := openHarness(t)
	g := h.gate()
	old := 0
	g.SubscribeOptOut(func() { old++ })
	g.Close()
	g.Close()
	expect(t, g.Decide(), false, ReasonNoManager)
	if g.OptedOut() {
		t.Fatal("OptedOut() = true after Close")
	}
	fresh := 0
	g.SubscribeOptOut(func() { fresh++ })
	writeFile(t, h.path, scaffold(false))
	h.cfg.fire()
	if old != 0 || fresh != 0 {
		t.Fatal("a subscriber ran after Close")
	}
	if h.cfg.cancels < 1 {
		t.Fatal("file subscription not cancelled")
	}
	if h.cfg.closes != 0 {
		t.Fatal("Close closed the Manager")
	}
}

func TestConcurrentDecide(t *testing.T) {
	h := openHarness(t)
	g := h.gate()
	var wg sync.WaitGroup
	stop := make(chan struct{})
	var bad atomic.Int32
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
				}
				d := g.Decide()
				_ = g.OptedOut()
				if !(d.Allowed && d.Reason == ReasonNone) && !(!d.Allowed && d.Reason == ReasonConfigUnhealthy) {
					bad.Add(1)
				}
			}
		}()
	}
	for i := 0; i < 100; i++ {
		if i%2 == 0 {
			writeFile(t, h.path, brokenYAML)
		} else {
			writeFile(t, h.path, scaffold(true))
		}
		h.cfg.fire()
	}
	close(stop)
	wg.Wait()
	if bad.Load() != 0 {
		t.Fatalf("%d invalid decisions", bad.Load())
	}
}
