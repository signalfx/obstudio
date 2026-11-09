package loggingcontract

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	otellog "go.opentelemetry.io/otel/log"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	"go.opentelemetry.io/otel/trace"
)

type capture struct {
	mu      sync.Mutex
	records []sdklog.Record
}

func (e *capture) Export(_ context.Context, rs []sdklog.Record) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	for _, r := range rs {
		e.records = append(e.records, r.Clone())
	}
	return nil
}
func (*capture) Shutdown(context.Context) error   { return nil }
func (*capture) ForceFlush(context.Context) error { return nil }

type want struct {
	id    byte
	flags trace.TraceFlags
}

func parent(id byte, flags trace.TraceFlags) context.Context {
	return trace.ContextWithSpanContext(context.Background(), trace.NewSpanContext(trace.SpanContextConfig{
		TraceID: trace.TraceID{id}, SpanID: trace.SpanID{id, 100}, TraceFlags: flags,
	}))
}
func setupAsync(t *testing.T, batch bool) (*capture, *sdklog.LoggerProvider, *slog.Logger) {
	t.Helper()
	e := &capture{}
	var processor sdklog.Processor = sdklog.NewSimpleProcessor(e)
	if batch {
		processor = sdklog.NewBatchProcessor(e, sdklog.WithExportInterval(time.Minute))
	}
	p := sdklog.NewLoggerProvider(sdklog.WithProcessor(processor))
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		if err := p.Shutdown(ctx); err != nil {
			t.Error(err)
		}
	})
	return e, p, slog.New(otelslog.NewHandler("async-contract", otelslog.WithLoggerProvider(p)))
}
func expect(t *testing.T, e *capture, expected map[string]want) {
	t.Helper()
	e.mu.Lock()
	defer e.mu.Unlock()
	if len(e.records) != len(expected) {
		t.Fatalf("records=%d expected=%d", len(e.records), len(expected))
	}
	seen := map[string]bool{}
	for _, r := range e.records {
		body := r.Body().AsString()
		w, ok := expected[body]
		if !ok || seen[body] {
			t.Fatalf("unknown/duplicate record %q", body)
		}
		seen[body] = true
		tid, sid := trace.TraceID{}, trace.SpanID{}
		if w.id != 0 {
			tid = trace.TraceID{w.id}
			sid = trace.SpanID{w.id, 100}
		}
		if r.TraceID() != tid || r.SpanID() != sid || r.TraceFlags() != w.flags || r.Severity() != otellog.SeverityInfo {
			t.Errorf("wrong emit-time context/severity for %s: %s %s %d", body, r.TraceID(), r.SpanID(), r.TraceFlags())
		}
	}
}
func await(t *testing.T, done <-chan struct{}) {
	t.Helper()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("async worker deadline")
	}
}

func TestParentContextPassedAcrossGoroutineBoundary(t *testing.T) {
	e, _, l := setupAsync(t, false)
	gate := make(chan struct{})
	done := make(chan struct{})
	var wg sync.WaitGroup
	expected := map[string]want{"outside": {}}
	for flags := trace.TraceFlags(0); flags <= 1; flags++ {
		id := byte(11 + flags)
		ctx := parent(id, flags)
		message := fmt.Sprintf("task-%d", flags)
		expected[message] = want{id, flags}
		wg.Add(1)
		go func(ctx context.Context, body string) { defer wg.Done(); <-gate; l.InfoContext(ctx, body) }(ctx, message)
	}
	l.InfoContext(context.Background(), "outside")
	close(gate)
	go func() { wg.Wait(); close(done) }()
	await(t, done)
	expect(t, e, expected)
}

func TestConcurrentParentsMatchExactRecordContext(t *testing.T) {
	e, p, l := setupAsync(t, true)
	gate := make(chan struct{})
	done := make(chan struct{})
	var wg sync.WaitGroup
	expected := map[string]want{}
	for i := byte(1); i <= 20; i++ {
		ctx := parent(i, trace.TraceFlags(i%2))
		body := fmt.Sprintf("task-%d", i)
		expected[body] = want{i, trace.TraceFlags(i % 2)}
		wg.Add(1)
		go func(ctx context.Context, body string) { defer wg.Done(); <-gate; l.InfoContext(ctx, body) }(ctx, body)
	}
	close(gate)
	go func() { wg.Wait(); close(done) }()
	await(t, done)
	flush, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := p.ForceFlush(flush); err != nil {
		t.Fatal(err)
	}
	expect(t, e, expected)
}

func TestWorkerReuseAndMissingContextNegativeControl(t *testing.T) {
	e, _, l := setupAsync(t, false)
	type job struct {
		ctx  context.Context
		body string
	}
	jobs := make(chan job, 3)
	done := make(chan struct{})
	go func() {
		defer close(done)
		for j := range jobs {
			l.InfoContext(j.ctx, j.body)
		}
	}()
	ctx := parent(31, 1)
	jobs <- job{context.Background(), "raw-background"}
	jobs <- job{ctx, "passed-parent"}
	jobs <- job{context.Background(), "reused-clean"}
	close(jobs)
	await(t, done)
	expect(t, e, map[string]want{"raw-background": {}, "passed-parent": {31, 1}, "reused-clean": {}})
}

func TestCancelledContextRetainsCorrelationWithoutLeakingToOutside(t *testing.T) {
	e, _, l := setupAsync(t, false)
	ctx, cancel := context.WithCancel(parent(41, 1))
	done := make(chan struct{})
	fail := make(chan error, 1)
	go func(ctx context.Context) {
		defer close(done)
		<-ctx.Done()
		l.InfoContext(ctx, "cancel-cleanup")
		fail <- errors.New("synthetic failure")
	}(ctx)
	cancel()
	await(t, done)
	if <-fail == nil {
		t.Fatal("expected worker failure")
	}
	l.InfoContext(context.Background(), "outside-after-cancel-error")
	expect(t, e, map[string]want{"cancel-cleanup": {41, 1}, "outside-after-cancel-error": {}})
}

func TestBatchExportUsesEmitContextAfterHandoff(t *testing.T) {
	e, p, l := setupAsync(t, true)
	done := make(chan struct{})
	ctx := parent(51, 0)
	go func(ctx context.Context) { defer close(done); l.InfoContext(ctx, "queued") }(ctx)
	await(t, done)
	flush, cancel := context.WithTimeout(parent(99, 1), 2*time.Second)
	defer cancel()
	if err := p.ForceFlush(flush); err != nil {
		t.Fatal(err)
	}
	expect(t, e, map[string]want{"queued": {51, 0}})
}
