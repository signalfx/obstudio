package userconfig

import (
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/fsnotify/fsnotify"
	"go.yaml.in/yaml/v3"
)

// eventually polls cond every 10ms for up to 2s.
func eventually(t *testing.T, cond func() bool, msg string) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting: %s", msg)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

type logSink struct {
	mu    sync.Mutex
	lines []string
}

func (l *logSink) logf(format string, args ...any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.lines = append(l.lines, fmt.Sprintf(format, args...))
}

func (l *logSink) count(substr string) int {
	l.mu.Lock()
	defer l.mu.Unlock()
	n := 0
	for _, line := range l.lines {
		if strings.Contains(line, substr) {
			n++
		}
	}
	return n
}

func (l *logSink) len() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return len(l.lines)
}

type fakeClock struct {
	mu      sync.Mutex
	now     time.Duration
	timers  []*fakeTimer
	invoked int
}

type fakeTimer struct {
	c       *fakeClock
	at      time.Duration
	f       func()
	stopped bool
	fired   bool
}

func (c *fakeClock) afterFunc(d time.Duration, f func()) stopper {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.invoked++
	t := &fakeTimer{c: c, at: c.now + d, f: f}
	c.timers = append(c.timers, t)
	return t
}

func (t *fakeTimer) Stop() bool {
	t.c.mu.Lock()
	defer t.c.mu.Unlock()
	active := !t.stopped && !t.fired
	t.stopped = true
	return active
}

func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	c.now += d
	var due []func()
	for _, t := range c.timers {
		if !t.stopped && !t.fired && t.at <= c.now {
			t.fired = true
			due = append(due, t.f)
		}
	}
	c.mu.Unlock()
	for _, f := range due {
		f()
	}
}

func (c *fakeClock) invocations() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.invoked
}

type fakeWatcher struct {
	events chan fsnotify.Event
	errs   chan error
	addErr error
	closes atomic.Int32
}

func newFakeWatcher() *fakeWatcher {
	return &fakeWatcher{events: make(chan fsnotify.Event), errs: make(chan error)}
}

func (f *fakeWatcher) Add(string) error              { return f.addErr }
func (f *fakeWatcher) Events() <-chan fsnotify.Event { return f.events }
func (f *fakeWatcher) Errors() <-chan error          { return f.errs }
func (f *fakeWatcher) Close() error                  { f.closes.Add(1); return nil }

// harness holds a Manager built with test seams.
type harness struct {
	m       *Manager
	path    string
	log     *logSink
	clock   *fakeClock
	fw      *fakeWatcher
	reloads atomic.Int32
}

type harnessOpt func(*harness, *options)

func unwatched() harnessOpt {
	return func(_ *harness, o *options) { o.noWatch = true }
}

func withWatcher(fw *fakeWatcher) harnessOpt {
	return func(h *harness, o *options) {
		h.fw = fw
		o.newWatcher = func() (watcher, error) { return fw, nil }
	}
}

func withOption(f func(*options)) harnessOpt {
	return func(_ *harness, o *options) { f(o) }
}

// newHarness builds a Manager on path with a fake clock and, unless another
// option says otherwise, a fake watcher.
func newHarness(t *testing.T, path string, hopts ...harnessOpt) *harness {
	t.Helper()
	h := &harness{path: path, log: &logSink{}, clock: &fakeClock{}}
	fw := newFakeWatcher()
	opt := func(o *options) {
		o.logf = h.log.logf
		o.afterFunc = h.clock.afterFunc
		o.newWatcher = func() (watcher, error) { return fw, nil }
		h.fw = fw
		o.onReload = func() { h.reloads.Add(1) }
		for _, ho := range hopts {
			ho(h, o)
		}
	}
	m, err := NewManager(path, opt)
	if err != nil {
		t.Fatal(err)
	}
	h.m = m
	t.Cleanup(func() { m.Close() })
	return h
}

func scaffoldPath(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(Scaffold()), 0o600); err != nil {
		t.Fatal(err)
	}
	age(t, path)
	return path
}

func age(t *testing.T, path string) {
	t.Helper()
	old := time.Now().Add(-time.Second)
	if err := os.Chtimes(path, old, old); err != nil {
		t.Fatal(err)
	}
}

// external replaces the file with content by temp file and rename, as
// another writer would.
func external(t *testing.T, path, content string, aged bool) {
	t.Helper()
	tmp := path + ".ext-tmp"
	if err := os.WriteFile(tmp, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	if aged {
		age(t, tmp)
	}
	if err := os.Rename(tmp, path); err != nil {
		t.Fatal(err)
	}
}

func scaffoldWith(enabled string) string {
	return strings.Replace(Scaffold(), "enabled: true", "enabled: "+enabled, 1)
}

func (h *harness) generation() uint64 {
	h.m.reloadMu.Lock()
	defer h.m.reloadMu.Unlock()
	return h.m.generation
}

type recorder struct {
	ch chan Event
}

func record(m *Manager) *recorder {
	r := &recorder{ch: make(chan Event, 100)}
	m.Subscribe(func(e Event) { r.ch <- e })
	return r
}

func (r *recorder) next(t *testing.T) Event {
	t.Helper()
	select {
	case e := <-r.ch:
		return e
	case <-time.After(2 * time.Second):
		t.Fatal("no event delivered")
		return Event{}
	}
}

// none checks that nothing is pending. Events are handed to the mailbox
// before reload returns, so a short wait covers only the goroutine hop.
func (r *recorder) none(t *testing.T) {
	t.Helper()
	select {
	case e := <-r.ch:
		t.Fatalf("unexpected event %+v", e)
	case <-time.After(50 * time.Millisecond):
	}
}

func TestNewManagerValidFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(scaffoldWith("false")), 0o600); err != nil {
		t.Fatal(err)
	}
	h := newHarness(t, path)
	s := h.m.Get()
	if s.Telemetry.Enabled || s.Degraded || !h.m.isWatched() {
		t.Errorf("a: %+v watched=%v", s, h.m.isWatched())
	}
	r := record(h.m)

	pathB := filepath.Join(t.TempDir(), "config.yaml")
	hb := newHarness(t, pathB)
	if readFile(t, pathB) != Scaffold() || !hb.m.Get().Telemetry.Enabled {
		t.Errorf("b: not scaffolded")
	}
	r.none(t)
}

func TestNewManagerDegradedStart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte("telemetry: ["), 0o600); err != nil {
		t.Fatal(err)
	}
	cases := map[string]string{"broken": path}
	if runtime.GOOS != "windows" && os.Geteuid() != 0 {
		parent := t.TempDir()
		if err := os.Chmod(parent, 0o500); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { os.Chmod(parent, 0o700) })
		cases["unwritable"] = filepath.Join(parent, ".obstudio", "config.yaml")
	}
	for name, p := range cases {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t, p, withOption(func(o *options) { o.newWatcher = newFSWatcher }))
			s := h.m.Get()
			if s.Telemetry.Enabled || !s.Degraded {
				t.Errorf("snapshot %+v", s)
			}
			if n := h.log.count("fail-safe"); n != 1 {
				t.Errorf("%d degraded-start warnings, want 1: %v", n, h.log.lines)
			}
			if name == "unwritable" && h.m.isWatched() {
				t.Error("watched a directory that does not exist")
			}
		})
	}
}

func TestNewManagerRejectsRelativePath(t *testing.T) {
	wd, _ := os.Getwd()
	for _, p := range []string{"", "config.yaml"} {
		m, err := NewManager(p)
		if m != nil || err != ErrInvalidPath {
			t.Errorf("%q: %v, %v", p, m, err)
		}
	}
	if _, err := os.Stat(filepath.Join(wd, "config.yaml")); err == nil {
		t.Error("config.yaml created in the working directory")
	}
}

func TestGetWatchedNoIO(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	external(t, path, scaffoldWith("false"), true)
	for range 10 {
		if !h.m.Get().Telemetry.Enabled {
			t.Fatal("watched Get read the file")
		}
	}
	if h.reloads.Load() != 0 {
		t.Errorf("%d reloads before the event", h.reloads.Load())
	}
	h.m.onWatchEvent(fsnotify.Event{Name: path, Op: fsnotify.Write})
	h.clock.advance(DebounceInterval)
	if h.reloads.Load() != 1 || h.m.Get().Telemetry.Enabled {
		t.Errorf("after event: reloads=%d enabled=%v", h.reloads.Load(), h.m.Get().Telemetry.Enabled)
	}
}

func TestReloadEmitsOnChange(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	r := record(h.m)
	external(t, path, scaffoldWith("false"), false)
	h.m.reload()
	e := r.next(t)
	if e.Generation != 1 || !e.Old.Telemetry.Enabled || e.New.Telemetry.Enabled {
		t.Errorf("event %+v", e)
	}
	if !e.Affects(SectionTelemetry) || !e.Affects(TelemetryEnabled) {
		t.Error("Affects is false for the changed key")
	}
	if e.Affects(Key[bool]{}) || e.Affects(Section{}) || e.Affects(nil) {
		t.Error("Affects is true for a zero selector")
	}
	if h.m.Get() != e.New {
		t.Error("Get differs from New")
	}
	r.none(t)
}

func TestReloadNoEventWithoutValueChange(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	r := record(h.m)

	withComment := Scaffold() + "# note\n"
	external(t, path, withComment, false)
	h.m.reload()
	if h.m.Get().Hash != sha256Of(withComment) {
		t.Error("hash not swapped after a comment edit")
	}
	before := h.m.snap.Load()
	logs := h.log.len()
	h.m.reload()
	if h.m.snap.Load() != before || h.log.len() != logs {
		t.Error("unchanged reload swapped or logged")
	}
	withUnknown := withComment + "zz: 1\n"
	external(t, path, withUnknown, false)
	h.m.reload()
	if h.m.Get().Hash != sha256Of(withUnknown) || h.log.count("zz") != 1 {
		t.Errorf("unknown key: hash or log missing: %v", h.log.lines)
	}
	if h.generation() != 0 {
		t.Error("an event was emitted")
	}
	r.none(t)
}

func sha256Of(s string) [32]byte { return sha256.Sum256([]byte(s)) }

func TestReloadSemanticsTable(t *testing.T) {
	t.Run("syntax-keeps-last-good", func(t *testing.T) {
		path := scaffoldPath(t)
		h := newHarness(t, path)
		logs := h.log.len()
		external(t, path, "telemetry: [", false)
		h.m.reload()
		if !h.m.Get().Telemetry.Enabled || h.generation() != 0 || h.log.len() != logs+1 {
			t.Errorf("enabled=%v gen=%d logs=%v", h.m.Get().Telemetry.Enabled, h.generation(), h.log.lines)
		}
	})
	t.Run("delete-keeps-last-good", func(t *testing.T) {
		path := scaffoldPath(t)
		h := newHarness(t, path)
		os.Remove(path)
		h.m.reload()
		if !h.m.Get().Telemetry.Enabled || h.generation() != 0 {
			t.Error("last-good not kept")
		}
		if _, err := os.Stat(path); err == nil {
			t.Error("reload recreated the file")
		}
	})
	t.Run("invalid-key-failsafe", func(t *testing.T) {
		path := scaffoldPath(t)
		h := newHarness(t, path)
		external(t, path, scaffoldWith("maybe"), false)
		h.m.reload()
		if h.m.Get().Telemetry.Enabled || h.generation() != 1 || h.log.count("invalid") != 1 {
			t.Errorf("enabled=%v gen=%d logs=%v", h.m.Get().Telemetry.Enabled, h.generation(), h.log.lines)
		}
	})
	t.Run("absent-key-failsafe", func(t *testing.T) {
		path := scaffoldPath(t)
		h := newHarness(t, path)
		external(t, path, strings.Replace(Scaffold(), "  enabled: true\n", "", 1), false)
		h.m.reload()
		if h.m.Get().Telemetry.Enabled || h.generation() != 1 {
			t.Error("absent key did not fail safe with one event")
		}
	})
	t.Run("degraded-to-valid-same-values", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "config.yaml")
		if err := os.WriteFile(path, []byte("telemetry: ["), 0o600); err != nil {
			t.Fatal(err)
		}
		h := newHarness(t, path)
		if !h.m.Get().Degraded {
			t.Fatal("not degraded")
		}
		external(t, path, scaffoldWith("false"), false)
		h.m.reload()
		s := h.m.Get()
		if s.Degraded || s.Telemetry.Enabled || h.generation() != 0 {
			t.Errorf("snapshot %+v gen=%d", s, h.generation())
		}
	})
}

func TestSetReadYourWrites(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	r := record(h.m)
	if err := Set(h.m, TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	if h.m.Get().Telemetry.Enabled {
		t.Error("Get does not reflect the write")
	}
	if s, _ := mustLoad(t, path); s.Telemetry.Enabled {
		t.Error("file does not hold the write")
	}
	assertCommentsKept(t, readFile(t, path))
	r.next(t)
	before := h.m.snap.Load()
	h.m.reload()
	if h.m.snap.Load() != before || h.generation() != 1 {
		t.Error("follow-up reload swapped or emitted")
	}
	r.none(t)

	hu := newHarness(t, scaffoldPath(t), unwatched())
	if err := Set(hu.m, TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	n := hu.reloads.Load()
	if hu.m.Get().Telemetry.Enabled || hu.reloads.Load() != n {
		t.Error("unwatched Get after Set reloaded again")
	}
}

func TestSetInvalidPassthrough(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	before := h.m.Get()
	if err := Set(h.m, Key[bool]{}, true); !errors.Is(err, ErrUnknownKey) {
		t.Errorf("err = %v", err)
	}
	if h.m.Get() != before || readFile(t, path) != Scaffold() || h.generation() != 0 || h.reloads.Load() != 0 {
		t.Error("a rejected Set changed something")
	}
}

func TestUpdateOneReloadOneEvent(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	r := record(h.m)
	x := newDefinition(newSection("t"), "x", defSpec[int]{Label: "x", Description: "x.", Apply: ApplyLive})
	var c1 Changes
	Put(&c1, TelemetryEnabled, false)
	c1.put(x, 5)
	if err := Update(h.m, c1); err != nil {
		t.Fatal(err)
	}
	if h.reloads.Load() != 1 {
		t.Errorf("%d reloads, want 1", h.reloads.Load())
	}
	e := r.next(t)
	if e.Generation != 1 || e.New.Telemetry.Enabled || !e.Affects(TelemetryEnabled) || h.m.Get() != e.New {
		t.Errorf("event %+v", e)
	}
	var parsed struct {
		Telemetry struct{ Enabled bool }
		T         struct{ X int }
	}
	if err := yaml.Unmarshal([]byte(readFile(t, path)), &parsed); err != nil || parsed.Telemetry.Enabled || parsed.T.X != 5 {
		t.Errorf("file %+v, %v", parsed, err)
	}
	var c2 Changes
	Put(&c2, TelemetryEnabled, false)
	if err := Update(h.m, c2); err != nil {
		t.Fatal(err)
	}
	if h.reloads.Load() != 2 {
		t.Errorf("%d reloads, want 2", h.reloads.Load())
	}
	r.none(t)
}

func TestUpdateEmptyNoReload(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	fi, _ := os.Stat(path)
	if err := Update(h.m, Changes{}); err != nil {
		t.Error(err)
	}
	fi2, _ := os.Stat(path)
	if h.reloads.Load() != 0 || readFile(t, path) != Scaffold() || !fi.ModTime().Equal(fi2.ModTime()) {
		t.Error("empty Update reloaded or wrote")
	}
}

func TestUpdateAfterClose(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	h.m.Close()
	var c Changes
	Put(&c, TelemetryEnabled, false)
	for i, err := range []error{Update(h.m, Changes{}), Update(h.m, c), Set(h.m, TelemetryEnabled, false)} {
		if err != ErrClosed {
			t.Errorf("call %d: %v", i+1, err)
		}
	}
	if readFile(t, path) != Scaffold() {
		t.Error("file written after Close")
	}
}

func TestConcurrentUpdatesSerialized(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	sec := newSection("t")
	start := make(chan struct{})
	var wg sync.WaitGroup
	errs := make(chan error, 20)
	for i := range 20 {
		k := newDefinition(sec, fmt.Sprintf("k%d", i), defSpec[int]{Label: "k", Description: "k.", Apply: ApplyLive})
		wg.Add(1)
		go func() {
			defer wg.Done()
			var c Changes
			c.put(k, i)
			<-start
			errs <- Update(h.m, c)
		}()
	}
	close(start)
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Error(err)
		}
	}
	var parsed struct{ T map[string]int }
	out := readFile(t, path)
	if err := yaml.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatal(err)
	}
	for i := range 20 {
		if v, ok := parsed.T[fmt.Sprintf("k%d", i)]; !ok || v != i {
			t.Errorf("t.k%d = %v, %v", i, v, ok)
		}
	}
	if h.reloads.Load() != 20 {
		t.Errorf("%d reloads, want 20", h.reloads.Load())
	}
	assertCommentsKept(t, out)
}

func TestUnwatchedGetReloads(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path, unwatched())
	r := record(h.m)
	external(t, path, scaffoldWith("false"), true)
	if h.m.Get().Telemetry.Enabled || h.reloads.Load() != 1 {
		t.Errorf("enabled=%v reloads=%d", h.m.Get().Telemetry.Enabled, h.reloads.Load())
	}
	if e := r.next(t); e.New.Telemetry.Enabled {
		t.Errorf("event %+v", e)
	}
}

func TestUnwatchedGetUnchanged(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path, unwatched())
	for range 100 {
		h.m.Get()
	}
	if h.reloads.Load() != 0 {
		t.Errorf("%d reloads with an unchanged file", h.reloads.Load())
	}
	external(t, path, "telemetry: [", true)
	h.m.Get()
	if !h.m.Get().Telemetry.Enabled || h.reloads.Load() != 1 {
		t.Errorf("enabled=%v reloads=%d", h.m.Get().Telemetry.Enabled, h.reloads.Load())
	}
}

func TestSettleWindow(t *testing.T) {
	path := scaffoldPath(t)
	base := time.Now()
	var now atomic.Pointer[time.Time]
	now.Store(&base)
	h := newHarness(t, path, unwatched(), withOption(func(o *options) {
		o.now = func() time.Time { return *now.Load() }
	}))
	setMtime := func(at time.Time) {
		if err := os.Chtimes(path, at, at); err != nil {
			t.Fatal(err)
		}
	}

	external(t, path, scaffoldWith("false"), false)
	setMtime(base.Add(-50 * time.Millisecond))
	if !h.m.Get().Telemetry.Enabled || !h.m.Get().Telemetry.Enabled || h.reloads.Load() != 0 {
		t.Fatal("settling file was read")
	}
	later := base.Add(50 * time.Millisecond)
	now.Store(&later)
	if h.m.Get().Telemetry.Enabled || h.reloads.Load() != 1 {
		t.Fatal("file at the window boundary was not read")
	}
	external(t, path, scaffoldWith("true"), false)
	setMtime(base.Add(10 * time.Second))
	if !h.m.Get().Telemetry.Enabled || h.reloads.Load() != 2 {
		t.Fatal("future mtime was treated as settling")
	}
	os.Remove(path)
	if !h.m.Get().Telemetry.Enabled || h.reloads.Load() != 3 {
		t.Fatal("absent file did not reload or lost last-good")
	}
}

func TestStampBeforeRead(t *testing.T) {
	path := scaffoldPath(t)
	var armed atomic.Bool
	h := newHarness(t, path, unwatched(), withOption(func(o *options) {
		o.afterRead = func() {
			if armed.CompareAndSwap(true, false) {
				external(t, path, scaffoldWith("false"), true)
			}
		}
	}))
	external(t, path, Scaffold()+"# changed\n", true)
	armed.Store(true)
	if !h.m.Get().Telemetry.Enabled {
		t.Fatal("first Get should see the comment-only change")
	}
	if h.m.Get().Telemetry.Enabled {
		t.Fatal("second Get is stale: the stamp was taken after the read")
	}
}

func TestStampIdentity(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	a, b := "telemetry:\n  enabled: true \n", "telemetry:\n  enabled: false\n"
	if len(a) != len(b) {
		t.Fatal("contents differ in size")
	}
	if err := os.WriteFile(path, []byte(a), 0o600); err != nil {
		t.Fatal(err)
	}
	age(t, path)
	fi, _ := os.Stat(path)
	h := newHarness(t, path, unwatched())
	tmp := path + ".b"
	if err := os.WriteFile(tmp, []byte(b), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(tmp, fi.ModTime(), fi.ModTime()); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(tmp, path); err != nil {
		t.Fatal(err)
	}
	if h.m.Get().Telemetry.Enabled {
		t.Error("same-size same-mtime replace was not detected")
	}
}

func TestUnwatchedEventsReadDriven(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path, unwatched())
	release := make(chan struct{})
	got := make(chan Event, 10)
	h.m.Subscribe(func(e Event) { <-release; got <- e })
	external(t, path, scaffoldWith("false"), true)
	h.m.Get()
	close(release)
	select {
	case <-got:
	case <-time.After(2 * time.Second):
		t.Fatal("no event")
	}
	select {
	case e := <-got:
		t.Errorf("second event %+v", e)
	case <-time.After(50 * time.Millisecond):
	}
}

func TestWatcherFailureStartsUnwatched(t *testing.T) {
	for _, name := range []string{"new-fails", "add-fails"} {
		t.Run(name, func(t *testing.T) {
			path := scaffoldPath(t)
			calls := 0
			h := newHarness(t, path, withOption(func(o *options) {
				o.newWatcher = func() (watcher, error) {
					calls++
					if name == "new-fails" {
						return nil, errors.New("no inotify")
					}
					fw := newFakeWatcher()
					fw.addErr = errors.New("no such directory")
					return fw, nil
				}
			}))
			if h.m.isWatched() {
				t.Error("watched")
			}
			if n := h.log.count("warning"); n != 1 {
				t.Errorf("%d warnings: %v", n, h.log.lines)
			}
			external(t, path, scaffoldWith("false"), true)
			if h.m.Get().Telemetry.Enabled {
				t.Error("Get is stale")
			}
			n := h.reloads.Load()
			h.clock.advance(time.Second)
			if calls != 1 || h.clock.invocations() != 0 || h.reloads.Load() != n {
				t.Errorf("calls=%d afterFunc=%d reloads %d->%d", calls, h.clock.invocations(), n, h.reloads.Load())
			}
		})
	}
}

func TestModeSwitchDirectoryRemoved(t *testing.T) {
	for _, op := range []fsnotify.Op{fsnotify.Remove, fsnotify.Rename} {
		t.Run(op.String(), func(t *testing.T) {
			path := scaffoldPath(t)
			h := newHarness(t, path)
			h.m.onWatchEvent(fsnotify.Event{Name: filepath.Dir(path), Op: op})
			if h.m.isWatched() || h.fw.closes.Load() != 1 {
				t.Errorf("watched=%v closes=%d", h.m.isWatched(), h.fw.closes.Load())
			}
			if n := h.log.count("warning"); n != 1 {
				t.Errorf("%d warnings", n)
			}
			external(t, path, scaffoldWith("false"), true)
			if h.m.Get().Telemetry.Enabled {
				t.Error("Get is stale after the switch")
			}
		})
	}
	h := newHarness(t, scaffoldPath(t))
	h.m.onWatchEvent(fsnotify.Event{Name: filepath.Dir(h.path), Op: fsnotify.Chmod})
	if !h.m.isWatched() {
		t.Error("a chmod of the directory switched modes")
	}
}

func TestModeSwitchEventsClosed(t *testing.T) {
	h := newHarness(t, scaffoldPath(t))
	close(h.fw.events)
	eventually(t, func() bool { return !h.m.isWatched() }, "switch to unwatched")
	if n := h.log.count("warning"); n != 1 {
		t.Errorf("%d warnings", n)
	}
	h.m.onWatchClosed()
	if n := h.log.count("warning"); n != 1 {
		t.Errorf("%d warnings after a second close", n)
	}
}

func TestWatchErrorOneReload(t *testing.T) {
	h := newHarness(t, scaffoldPath(t))
	h.m.onWatchError(errors.New("queue overflow"))
	h.clock.advance(DebounceInterval)
	if h.reloads.Load() != 1 || !h.m.isWatched() || h.log.count("queue overflow") != 1 {
		t.Errorf("reloads=%d watched=%v logs=%v", h.reloads.Load(), h.m.isWatched(), h.log.lines)
	}
}

func TestDebounceBurstOneReload(t *testing.T) {
	h := newHarness(t, scaffoldPath(t))
	for i := range 50 {
		if i > 0 {
			h.clock.advance(10 * time.Millisecond)
		}
		h.m.onWatchEvent(fsnotify.Event{Name: h.path, Op: fsnotify.Write})
	}
	h.clock.advance(99 * time.Millisecond)
	if h.reloads.Load() != 0 {
		t.Errorf("%d reloads before quiet", h.reloads.Load())
	}
	h.clock.advance(time.Millisecond)
	if h.reloads.Load() != 1 {
		t.Errorf("%d reloads, want 1", h.reloads.Load())
	}
}

func TestIrrelevantEventsDropped(t *testing.T) {
	h := newHarness(t, scaffoldPath(t))
	dir := filepath.Dir(h.path)
	for _, name := range []string{"observer.log", "config.yaml.tmp-123", "config.yml"} {
		for range 20 {
			h.m.onWatchEvent(fsnotify.Event{Name: filepath.Join(dir, name), Op: fsnotify.Write})
		}
	}
	h.clock.advance(time.Second)
	if h.reloads.Load() != 0 || h.clock.invocations() != 0 || !h.m.isWatched() {
		t.Errorf("reloads=%d afterFunc=%d watched=%v", h.reloads.Load(), h.clock.invocations(), h.m.isWatched())
	}
}

func TestSlowSubscriberIsolated(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	release := make(chan struct{})
	defer close(release)
	h.m.Subscribe(func(Event) { <-release })
	b := record(h.m)
	for i, v := range []string{"false", "true", "false"} {
		external(t, path, scaffoldWith(v), false)
		h.m.reload()
		if e := b.next(t); e.Generation != uint64(i+1) {
			t.Errorf("B got generation %d, want %d", e.Generation, i+1)
		}
	}
	if h.m.Get().Telemetry.Enabled {
		t.Error("Get does not reflect the third change")
	}
}

func TestCoalescing(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	started := make(chan struct{}, 1)
	release := make(chan struct{})
	got := make(chan Event, 10)
	h.m.Subscribe(func(e Event) {
		got <- e
		if e.Generation == 1 {
			started <- struct{}{}
			<-release
		}
	})
	external(t, path, scaffoldWith("false"), false)
	h.m.reload()
	<-started
	for _, v := range []string{"true", "false", "true"} {
		external(t, path, scaffoldWith(v), false)
		h.m.reload()
	}
	close(release)
	first := <-got
	var second Event
	select {
	case second = <-got:
	case <-time.After(2 * time.Second):
		t.Fatal("no coalesced event")
	}
	if first.Generation != 1 || second.Generation != 4 {
		t.Errorf("generations %d, %d", first.Generation, second.Generation)
	}
	if second.Old.Telemetry.Enabled || !second.New.Telemetry.Enabled || second.New != h.m.Get() {
		t.Errorf("coalesced event %+v", second)
	}
	if !second.Affects(TelemetryEnabled) {
		t.Error("coalesced event does not affect the key")
	}
	select {
	case e := <-got:
		t.Errorf("third event %+v", e)
	case <-time.After(50 * time.Millisecond):
	}
}

func TestPanicRecoveredStaysSubscribed(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	var calls atomic.Int32
	p := make(chan Event, 10)
	h.m.Subscribe(func(e Event) {
		if calls.Add(1) == 1 {
			panic("boom")
		}
		p <- e
	})
	q := record(h.m)
	// Each change waits for delivery, so the mailboxes never coalesce the two.
	for i, v := range []string{"false", "true"} {
		external(t, path, scaffoldWith(v), false)
		h.m.reload()
		if e := q.next(t); e.Generation != uint64(i+1) {
			t.Fatalf("Q got generation %d", e.Generation)
		}
		if i == 0 {
			eventually(t, func() bool { return calls.Load() == 1 }, "P's first call")
		}
	}
	select {
	case e := <-p:
		if e.Generation != 2 {
			t.Errorf("P got generation %d", e.Generation)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("P did not receive the second event")
	}
	eventually(t, func() bool { return h.log.count("panicked") == 1 }, "panic logged")
	if err := Set(h.m, TelemetryEnabled, false); err != nil || h.m.Get().Telemetry.Enabled {
		t.Error("Manager unusable after a panic")
	}
}

func TestCancelIdempotentReentrant(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	baseline := runtime.NumGoroutine()
	var calls atomic.Int32
	var cancel func()
	ready := make(chan struct{})
	cancel = h.m.Subscribe(func(Event) {
		<-ready
		calls.Add(1)
		cancel()
	})
	close(ready)
	for _, v := range []string{"false", "true", "false"} {
		external(t, path, scaffoldWith(v), false)
		h.m.reload()
	}
	eventually(t, func() bool { return calls.Load() == 1 }, "first call")
	cancel()
	cancel()
	eventually(t, func() bool { return runtime.NumGoroutine() <= baseline }, "subscriber goroutine exit")
	if calls.Load() != 1 {
		t.Errorf("%d calls, want 1", calls.Load())
	}
}

func TestNoReplay(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(scaffoldWith("false")), 0o600); err != nil {
		t.Fatal(err)
	}
	h := newHarness(t, path)
	r := record(h.m)
	h.m.reload()
	r.none(t)
}

func TestCallbackReentrancy(t *testing.T) {
	for _, name := range []string{"watched", "unwatched"} {
		t.Run(name, func(t *testing.T) {
			var hopts []harnessOpt
			if name == "unwatched" {
				hopts = append(hopts, unwatched())
			}
			h := newHarness(t, scaffoldPath(t), hopts...)
			done := make(chan error, 10)
			h.m.Subscribe(func(e Event) {
				h.m.Get()
				h.m.Subscribe(func(Event) {})
				done <- Set(h.m, TelemetryEnabled, e.New.Telemetry.Enabled)
			})
			if err := Set(h.m, TelemetryEnabled, false); err != nil {
				t.Fatal(err)
			}
			select {
			case err := <-done:
				if err != nil {
					t.Error(err)
				}
			case <-time.After(2 * time.Second):
				t.Fatal("callback deadlocked")
			}
			if h.generation() != 1 {
				t.Errorf("generation %d, want 1", h.generation())
			}
		})
	}
}

func TestCloseStopsEverything(t *testing.T) {
	baseline := runtime.NumGoroutine()
	path := scaffoldPath(t)
	h := newHarness(t, path, withOption(func(o *options) {
		o.newWatcher = newFSWatcher
		o.afterFunc = func(d time.Duration, f func()) stopper { return time.AfterFunc(d, f) }
	}))
	if !h.m.isWatched() {
		t.Fatal("real watcher did not start")
	}
	a, b := record(h.m), record(h.m)
	pre := h.m.Get()
	if err := h.m.Close(); err != nil {
		t.Errorf("first Close: %v", err)
	}
	if err := h.m.Close(); err != nil {
		t.Errorf("second Close: %v", err)
	}
	reloads := h.reloads.Load()
	external(t, path, scaffoldWith("false"), true)
	if err := Set(h.m, TelemetryEnabled, true); err != ErrClosed {
		t.Errorf("Set after Close: %v", err)
	}
	var called atomic.Bool
	cancel := h.m.Subscribe(func(Event) { called.Store(true) })
	cancel()
	if h.m.Get() != pre || h.reloads.Load() != reloads {
		t.Error("Get after Close did I/O")
	}
	if readFile(t, path) != scaffoldWith("false") {
		t.Error("Manager wrote after Close")
	}
	a.none(t)
	b.none(t)
	if called.Load() {
		t.Error("subscriber added after Close was called")
	}

	upath := scaffoldPath(t)
	hu := newHarness(t, upath, unwatched())
	upre := hu.m.Get()
	hu.m.Close()
	external(t, upath, scaffoldWith("false"), true)
	if hu.m.Get() != upre || hu.reloads.Load() != 0 {
		t.Error("unwatched Get after Close did I/O")
	}
	eventually(t, func() bool { return runtime.NumGoroutine() <= baseline }, "goroutines back to baseline")
}

func TestCloseFromCallback(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	done := make(chan error, 1)
	h.m.Subscribe(func(Event) { done <- h.m.Close() })
	external(t, path, scaffoldWith("false"), false)
	h.m.reload()
	select {
	case err := <-done:
		if err != nil {
			t.Error(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Close from a callback deadlocked")
	}
	if err := Set(h.m, TelemetryEnabled, true); err != ErrClosed {
		t.Errorf("Set after Close: %v", err)
	}
}

func realHarness(t *testing.T, path string) *harness {
	return newHarness(t, path, withOption(func(o *options) {
		o.newWatcher = newFSWatcher
		o.afterFunc = func(d time.Duration, f func()) stopper { return time.AfterFunc(d, f) }
	}))
}

func TestFsnotifyIntegration(t *testing.T) {
	path := scaffoldPath(t)
	h := realHarness(t, path)
	external(t, path, scaffoldWith("false"), false)
	eventually(t, func() bool { return !h.m.Get().Telemetry.Enabled }, "watched reload")
	if !h.m.isWatched() {
		t.Error("no longer watched")
	}
}

func TestFsnotifyNoiseIgnored(t *testing.T) {
	path := scaffoldPath(t)
	h := realHarness(t, path)
	logPath := filepath.Join(filepath.Dir(path), "observer.log")
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	for i := range 100 {
		fmt.Fprintf(f, "line %d\n", i)
	}
	f.Close()
	external(t, path, scaffoldWith("false"), false)
	eventually(t, func() bool { return !h.m.Get().Telemetry.Enabled }, "sentinel")
	if n := h.reloads.Load(); n < 1 || n > 2 {
		t.Errorf("%d reloads, want 1 or 2", n)
	}
}

func TestFsnotifyDirectoryRemoved(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Linux and macOS only")
	}
	dir := filepath.Join(t.TempDir(), ".obstudio")
	path := filepath.Join(dir, "config.yaml")
	h := realHarness(t, path)
	if !h.m.isWatched() {
		t.Fatal("not watched")
	}
	if err := os.RemoveAll(dir); err != nil {
		t.Fatal(err)
	}
	eventually(t, func() bool { return !h.m.isWatched() }, "switch to unwatched")
	if n := h.log.count("warning"); n != 1 {
		t.Errorf("%d warnings: %v", n, h.log.lines)
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	external(t, path, scaffoldWith("false"), true)
	if h.m.Get().Telemetry.Enabled {
		t.Error("Get is stale after the directory was recreated")
	}
}

func TestManagerIgnoresEnv(t *testing.T) {
	t.Setenv("DO_NOT_TRACK", "1")
	t.Setenv("OBSTUDIO_TELEMETRY", "0")
	t.Setenv("OBSTUDIO_TELEMETRY_ENABLED", "false")
	for _, hopts := range [][]harnessOpt{nil, {unwatched()}} {
		h := newHarness(t, scaffoldPath(t), hopts...)
		if !h.m.Get().Telemetry.Enabled {
			t.Error("environment changed the snapshot")
		}
	}
	goBin, err := exec.LookPath("go")
	if err != nil {
		t.Skip("go tool not on PATH")
	}
	out, err := exec.Command(goBin, "list", "-deps", ".").Output()
	if err != nil {
		t.Fatal(err)
	}
	for _, dep := range strings.Fields(string(out)) {
		if strings.HasPrefix(dep, "github.com/signalfx/obstudio/") && !strings.HasSuffix(dep, "/internal/userconfig") {
			t.Errorf("userconfig depends on %s", dep)
		}
	}
}
