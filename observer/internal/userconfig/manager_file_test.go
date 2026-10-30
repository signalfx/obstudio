package userconfig

import (
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

// fileCounter counts a file subscriber's calls, one channel send per call.
type fileCounter struct {
	ch chan struct{}
	n  int
}

func countFile(m *Manager) *fileCounter {
	c := &fileCounter{ch: make(chan struct{}, 100)}
	m.SubscribeFile(func() { c.ch <- struct{}{} })
	return c
}

// expect waits until the subscriber has been called want times in total,
// then checks that no further call is pending. Notifications reach the
// mailbox before reload returns, so a short wait covers the goroutine hop.
func (c *fileCounter) expect(t *testing.T, want int) {
	t.Helper()
	for c.n < want {
		select {
		case <-c.ch:
			c.n++
		case <-time.After(2 * time.Second):
			t.Fatalf("file subscriber called %d times, want %d", c.n, want)
		}
	}
	select {
	case <-c.ch:
		c.n++
		t.Fatalf("file subscriber called %d times, want %d", c.n, want)
	case <-time.After(50 * time.Millisecond):
	}
}

func TestFileSubBrokenAndFixed(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	f, r := countFile(h.m), record(h.m)
	b := readFile(t, path)
	before := h.m.Get()

	external(t, path, "telemetry: [", false)
	h.m.reload()
	f.expect(t, 1)
	if h.m.Get() != before {
		t.Error("broken-notifies: Get changed")
	}

	external(t, path, b, false)
	h.m.reload()
	f.expect(t, 2)
	if h.m.Get().Hash != sha256Of(b) {
		t.Error("fixed-notifies: hash is not the restored bytes'")
	}
	r.none(t)
}

func TestFileSubSameValueInvalid(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(scaffoldWith("false")), 0o600); err != nil {
		t.Fatal(err)
	}
	h := newHarness(t, path)
	f, r := countFile(h.m), record(h.m)

	external(t, path, scaffoldWith("maybe"), false)
	h.m.reload()
	f.expect(t, 1)
	if h.m.Get().Telemetry.Enabled {
		t.Error("enabled after an invalid value")
	}
	external(t, path, scaffoldWith("false"), false)
	h.m.reload()
	f.expect(t, 2)
	if h.m.Get().Telemetry.Enabled {
		t.Error("enabled after the fix")
	}
	r.none(t)
}

func TestFileSubUnknownKey(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	f, r := countFile(h.m), record(h.m)

	external(t, path, Scaffold()+"zz: 1\n", false)
	h.m.reload()
	f.expect(t, 1)
	external(t, path, Scaffold(), false)
	h.m.reload()
	f.expect(t, 2)
	r.none(t)
}

func TestFileSubIdenticalResult(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	f := countFile(h.m)

	h.m.reload()
	f.expect(t, 0)

	external(t, path, "telemetry: [", false)
	h.m.reload()
	h.m.reload()
	f.expect(t, 1)

	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	h.m.reload()
	f.expect(t, 2)
	h.m.reload()
	f.expect(t, 2)
}

func TestFileSubValueChange(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	f, r := countFile(h.m), record(h.m)

	external(t, path, scaffoldWith("false"), false)
	h.m.reload()
	r.next(t)
	f.expect(t, 1)

	if err := Set(h.m, TelemetryEnabled, true); err != nil {
		t.Fatal(err)
	}
	r.next(t)
	f.expect(t, 2)

	h.m.reload()
	r.none(t)
	f.expect(t, 2)
}

func TestFileSubDegradedStart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte("telemetry: ["), 0o600); err != nil {
		t.Fatal(err)
	}
	h := newHarness(t, path)
	f := countFile(h.m)

	h.m.reload()
	f.expect(t, 0)

	external(t, path, Scaffold(), false)
	h.m.reload()
	f.expect(t, 1)
	if h.m.Get().Degraded {
		t.Error("still Degraded after the fix")
	}
}

func TestFileSubDelivery(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path)
	edit := 0
	change := func() {
		edit++
		external(t, path, Scaffold()+"# edit "+string(rune('a'+edit))+"\n", false)
		h.m.reload()
	}

	aStarted := make(chan struct{}, 1)
	release := make(chan struct{})
	var aCalls atomic.Int32
	h.m.SubscribeFile(func() {
		if aCalls.Add(1) == 1 {
			aStarted <- struct{}{}
			<-release
		}
	})
	var pCalls atomic.Int32
	h.m.SubscribeFile(func() {
		if pCalls.Add(1) == 1 {
			panic("boom")
		}
	})
	var sCalls atomic.Int32
	var sCancel func()
	sReady := make(chan struct{})
	sCancel = h.m.SubscribeFile(func() {
		<-sReady
		sCalls.Add(1)
		sCancel()
	})
	close(sReady)

	change()
	<-aStarted
	eventually(t, func() bool { return pCalls.Load() == 1 && sCalls.Load() == 1 }, "P and S first calls")
	for range 3 {
		returned := make(chan struct{})
		go func() { change(); close(returned) }()
		select {
		case <-returned:
		case <-time.After(2 * time.Second):
			t.Fatal("isolated: reload blocked on a slow file subscriber")
		}
	}
	eventually(t, func() bool { return pCalls.Load() >= 2 }, "panic: P called again after its panic")
	if aCalls.Load() != 1 {
		t.Errorf("A called %d times while blocked", aCalls.Load())
	}
	close(release)
	eventually(t, func() bool { return aCalls.Load() == 2 }, "coalesced: A's second call")
	time.Sleep(50 * time.Millisecond)
	if aCalls.Load() != 2 {
		t.Errorf("coalesced: A called %d times, want 2", aCalls.Load())
	}
	if n := h.log.count("panicked"); n != 1 {
		t.Errorf("panic logged %d times, want 1", n)
	}
	if sCalls.Load() != 1 {
		t.Errorf("cancel: S called %d times, want 1", sCalls.Load())
	}
	sCancel()
	sCancel()

	var fCalls atomic.Int32
	fDone := make(chan error, 10)
	h.m.SubscribeFile(func() {
		fCalls.Add(1)
		h.m.SubscribeFile(func() {})
		h.m.Get()
		fDone <- Set(h.m, TelemetryEnabled, false)
	})
	time.Sleep(50 * time.Millisecond)
	if fCalls.Load() != 0 {
		t.Error("no-replay: F called before any result change")
	}
	change()
	select {
	case err := <-fDone:
		if err != nil {
			t.Error(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("reentrant: F's callback deadlocked")
	}

	if err := h.m.Close(); err != nil {
		t.Fatal(err)
	}
	time.Sleep(50 * time.Millisecond)
	a, p, s, fc := aCalls.Load(), pCalls.Load(), sCalls.Load(), fCalls.Load()
	external(t, path, Scaffold()+"# after close\n", false)
	h.m.reload()
	var called atomic.Bool
	cancel := h.m.SubscribeFile(func() { called.Store(true) })
	cancel()
	time.Sleep(50 * time.Millisecond)
	if aCalls.Load() != a || pCalls.Load() != p || sCalls.Load() != s || fCalls.Load() != fc || called.Load() {
		t.Error("closed: a file subscriber was called after Close")
	}
}

func TestFileSubUnwatched(t *testing.T) {
	path := scaffoldPath(t)
	h := newHarness(t, path, unwatched())
	r := record(h.m)
	started := make(chan struct{}, 1)
	release := make(chan struct{})
	var calls atomic.Int32
	h.m.SubscribeFile(func() {
		calls.Add(1)
		started <- struct{}{}
		<-release
	})

	external(t, path, Scaffold()+"# note\n", true)
	returned := make(chan struct{})
	go func() { h.m.Get(); close(returned) }()
	<-started
	select {
	case <-returned:
	case <-time.After(2 * time.Second):
		t.Fatal("returns: Get blocked on the file subscriber")
	}
	close(release)
	time.Sleep(50 * time.Millisecond)
	if calls.Load() != 1 {
		t.Errorf("notified: %d calls, want 1", calls.Load())
	}
	r.none(t)
}
