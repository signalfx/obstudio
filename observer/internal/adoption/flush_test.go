package adoption

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	collmetric "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	"google.golang.org/protobuf/proto"

	"github.com/signalfx/obstudio/observer/internal/adoption/export"
)

// sink is the flush harness capture server.
type sink struct {
	srv    *httptest.Server
	mu     sync.Mutex
	conns  int
	bodies []*collmetric.ExportMetricsServiceRequest
	status atomic.Int32
}

func newSink(t *testing.T) *sink {
	s := &sink{}
	s.status.Store(http.StatusOK)
	s.srv = httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		data, _ := io.ReadAll(r.Body)
		req := &collmetric.ExportMetricsServiceRequest{}
		_ = proto.Unmarshal(data, req)
		s.mu.Lock()
		s.bodies = append(s.bodies, req)
		s.mu.Unlock()
		w.WriteHeader(int(s.status.Load()))
	}))
	s.srv.Config.ConnState = func(_ net.Conn, st http.ConnState) {
		if st == http.StateNew {
			s.mu.Lock()
			s.conns++
			s.mu.Unlock()
		}
	}
	s.srv.Start()
	t.Cleanup(s.srv.Close)
	return s
}

func (s *sink) requests() []*collmetric.ExportMetricsServiceRequest {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]*collmetric.ExportMetricsServiceRequest(nil), s.bodies...)
}

// features returns the first_use feature values in a request.
func reqFeatures(req *collmetric.ExportMetricsServiceRequest) (feats []string, userHash string) {
	for _, rm := range req.ResourceMetrics {
		for _, a := range rm.Resource.Attributes {
			if a.Key == "obstudio.user_hash" {
				userHash = a.Value.GetStringValue()
			}
		}
		for _, sm := range rm.ScopeMetrics {
			for _, m := range sm.Metrics {
				if m.Name != MetricFirstUse {
					continue
				}
				for _, dp := range m.GetSum().DataPoints {
					for _, a := range dp.Attributes {
						if a.Key == "feature" {
							feats = append(feats, a.Value.GetStringValue())
						}
					}
				}
			}
		}
	}
	return feats, userHash
}

type flushHarness struct {
	dir     string
	g       *fakeGate
	sink    *sink
	e       *Emitter
	reader  *export.Reader
	flushes atomic.Int32
}

// newFlushHarness builds the pipeline the way cmd/obstudio does: the adoption
// exporter, the emitter's confirming exporter around it, the periodic reader
// over the wrapper, and the reader's ForceFlush injected into the emitter
// through a counting wrapper.
func newFlushHarness(t *testing.T, dir string, g *fakeGate, s *sink, interval time.Duration) *flushHarness {
	t.Helper()
	h := &flushHarness{dir: dir, g: g, sink: s}
	getenv := func(k string) string {
		if k == export.EndpointEnv {
			return s.srv.URL
		}
		return ""
	}
	exp, err := export.NewExporter(export.ExporterConfig{ClientType: export.ClientTypeLongRunning, Gate: g, Getenv: getenv, Timeout: time.Second})
	if err != nil {
		t.Fatal(err)
	}
	h.e, err = New(Config{Dir: dir, Gate: g, Version: "test", Launcher: "cli"})
	if err != nil {
		t.Fatal(err)
	}
	h.reader, err = export.NewReader(h.e.Exporter(exp), export.ReaderConfig{ClientType: export.ClientTypeLongRunning, Interval: interval, Timeout: time.Second})
	if err != nil {
		t.Fatal(err)
	}
	h.e.SetFlush(func(ctx context.Context) error {
		h.flushes.Add(1)
		return h.reader.ForceFlush(ctx)
	})
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = h.e.Shutdown(ctx)
	})
	return h
}

func TestInstallFlushAtFirstStart(t *testing.T) {
	t.Setenv("USER", "sentinel-user-xyz")
	dir := filepath.Join(t.TempDir(), ".obstudio")
	g := &fakeGate{allowed: true, block: make(chan struct{})}
	s := newSink(t)
	h := newFlushHarness(t, dir, g, s, time.Hour)

	started := make(chan struct{})
	go func() { _ = h.e.Start(h.reader); close(started) }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("start waited for Decide")
	}
	if len(s.requests()) != 0 {
		t.Fatal("request before release")
	}
	close(g.block)
	waitFor(t, func() bool { return len(s.requests()) == 1 })

	data, err := os.ReadFile(filepath.Join(dir, installIDFile))
	if err != nil {
		t.Fatal(err)
	}
	id := strings.TrimSpace(string(data))
	if !uuidV4.MatchString(id) || !strings.HasSuffix(string(data), "\n") {
		t.Fatalf("install_id = %q", data)
	}
	if fi, _ := os.Stat(filepath.Join(dir, installIDFile)); fi.Mode().Perm() != 0o600 {
		t.Fatalf("install_id mode %v", fi.Mode().Perm())
	}
	if fi, _ := os.Stat(dir); fi.Mode().Perm() != 0o700 {
		t.Fatalf("dir mode %v", fi.Mode().Perm())
	}
	feats, hash := reqFeatures(s.requests()[0])
	if len(feats) != 1 || feats[0] != FeatureInstall || hash != id {
		t.Fatalf("forced export = %v %q", feats, hash)
	}
	if h.flushes.Load() != 1 {
		t.Fatalf("flushes = %d", h.flushes.Load())
	}
	waitFor(t, func() bool {
		st, _ := os.ReadFile(filepath.Join(dir, stateFile))
		return strings.Contains(string(st), `"install":"delivered"`)
	})
	for _, f := range []string{installIDFile, stateFile} {
		b, _ := os.ReadFile(filepath.Join(dir, f))
		if strings.Contains(string(b), "sentinel-user-xyz") {
			t.Fatal("identity leaked into a file")
		}
	}

	// stable: a new process over the same directory reads the same ID,
	// creates nothing and requests no flush.
	h2 := newFlushHarness(t, dir, &fakeGate{allowed: true}, s, time.Hour)
	_ = h2.e.Start(h2.reader)
	time.Sleep(50 * time.Millisecond)
	if h2.flushes.Load() != 0 || readInstallID(filepath.Join(dir, installIDFile)) != id {
		t.Fatal("second process changed the ID or flushed")
	}
}

func TestInstallIDCreatedOnOpenExport(t *testing.T) {
	const interval = 400 * time.Millisecond
	dir := filepath.Join(t.TempDir(), ".obstudio")
	g := &fakeGate{allowed: false}
	s := newSink(t)
	h := newFlushHarness(t, dir, g, s, interval)
	_ = h.e.Start(h.reader)
	h.e.ObserverStarted()
	time.Sleep(50 * time.Millisecond)
	if entries, _ := os.ReadDir(dir); len(entries) != 0 || h.flushes.Load() != 0 {
		t.Fatal("files or flush before the gate opened")
	}
	g.set(true)
	waitFor(t, func() bool { return len(s.requests()) >= 2 })
	first, hash := reqFeatures(s.requests()[0])
	second, _ := reqFeatures(s.requests()[1])
	if len(first) != 1 || first[0] != FeatureObserverStart || hash == "" {
		t.Fatalf("first request = %v", first)
	}
	if len(second) != 1 || second[0] != FeatureInstall {
		t.Fatalf("forced request = %v", second)
	}
	if h.flushes.Load() != 1 {
		t.Fatalf("flushes = %d", h.flushes.Load())
	}
	waitFor(t, func() bool {
		st, _ := os.ReadFile(filepath.Join(dir, stateFile))
		return strings.Contains(string(st), `"install":"delivered"`) && strings.Contains(string(st), `"observer_start":"delivered"`)
	})
}

func TestInstallFlushFailureLeavesPending(t *testing.T) {
	const interval = 700 * time.Millisecond
	dir := filepath.Join(t.TempDir(), ".obstudio")
	g := &fakeGate{allowed: true}
	s := newSink(t)
	s.status.Store(http.StatusBadRequest) // fails without SDK retries
	h := newFlushHarness(t, dir, g, s, interval)
	_ = h.e.Start(h.reader)
	waitFor(t, func() bool {
		st, _ := os.ReadFile(filepath.Join(dir, stateFile))
		return len(s.requests()) == 1 && strings.Contains(string(st), `"install":"pending"`)
	})
	time.Sleep(interval / 2)
	if len(s.requests()) != 1 || h.flushes.Load() != 1 {
		t.Fatalf("retry loop: requests=%d flushes=%d", len(s.requests()), h.flushes.Load())
	}
	s.status.Store(http.StatusOK)
	waitFor(t, func() bool {
		st, _ := os.ReadFile(filepath.Join(dir, stateFile))
		return strings.Contains(string(st), `"install":"delivered"`)
	})
	feats, _ := reqFeatures(s.requests()[len(s.requests())-1])
	if len(feats) != 1 || feats[0] != FeatureInstall {
		t.Fatalf("periodic request = %v", feats)
	}
	if h.flushes.Load() != 1 {
		t.Fatal("a failure requested another flush")
	}

	t.Run("restart-re-records", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), ".obstudio")
		s := newSink(t)
		s.status.Store(http.StatusBadRequest)
		h := newFlushHarness(t, dir, &fakeGate{allowed: true}, s, time.Hour)
		_ = h.e.Start(h.reader)
		waitFor(t, func() bool {
			st, _ := os.ReadFile(filepath.Join(dir, stateFile))
			return len(s.requests()) == 1 && strings.Contains(string(st), `"install":"pending"`)
		})
		s.status.Store(http.StatusOK)
		h2 := newFlushHarness(t, dir, &fakeGate{allowed: true}, s, time.Hour)
		_ = h2.e.Start(h2.reader)
		waitFor(t, func() bool { return len(s.requests()) == 2 })
		if h2.flushes.Load() != 1 {
			t.Fatalf("restart flushes = %d", h2.flushes.Load())
		}
		feats, _ := reqFeatures(s.requests()[1])
		if len(feats) != 1 || feats[0] != FeatureInstall {
			t.Fatalf("restart request = %v", feats)
		}
	})
}

func TestInstallFlushOptOutBeforeFirstStart(t *testing.T) {
	dir := filepath.Join(t.TempDir(), ".obstudio")
	g := &fakeGate{allowed: false, opted: true}
	s := newSink(t)
	h := newFlushHarness(t, dir, g, s, time.Hour)
	_ = h.e.Start(h.reader)
	h.e.ObserverStarted()
	time.Sleep(100 * time.Millisecond)
	if _, err := os.Stat(dir); err == nil {
		if entries, _ := os.ReadDir(dir); len(entries) != 0 {
			t.Fatal("files created")
		}
	}
	s.mu.Lock()
	conns := s.conns
	s.mu.Unlock()
	if conns != 0 || h.flushes.Load() != 0 {
		t.Fatalf("conns=%d flushes=%d", conns, h.flushes.Load())
	}
}
