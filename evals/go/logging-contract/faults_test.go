package loggingcontract

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/otel"
	otellog "go.opentelemetry.io/otel/log"
	sdklog "go.opentelemetry.io/otel/sdk/log"
)

func faultPath(t *testing.T, e sdklog.Exporter, batch bool) (*sdklog.LoggerProvider, *slog.Logger, *bytes.Buffer) {
	t.Helper()
	var processor sdklog.Processor = sdklog.NewSimpleProcessor(e)
	if batch {
		processor = sdklog.NewBatchProcessor(e, sdklog.WithMaxQueueSize(8), sdklog.WithExportMaxBatchSize(8),
			sdklog.WithExportBufferSize(1), sdklog.WithExportInterval(time.Minute), sdklog.WithExportTimeout(2*time.Second))
	}
	p := sdklog.NewLoggerProvider(sdklog.WithProcessor(processor))
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		if err := p.Shutdown(ctx); err != nil {
			t.Error(err)
		}
	})
	sink := &bytes.Buffer{}
	bridge := otelslog.NewHandler("logging-fault", otelslog.WithLoggerProvider(p))
	return p, slog.New(teeHandler{bridge: bridge, sink: slog.NewJSONHandler(sink, nil)}), sink
}

func logFailure(l *slog.Logger, err error, fields map[string]any) {
	// Fixture-owned policy: fixed category and explicitly permitted fields only.
	l.Error("request failed", "exception.type", reflect.TypeOf(err).String(), "request.id", fields["request.id"])
}

func stringAttributes(record sdklog.Record) map[string]string {
	attributes := map[string]string{}
	record.WalkAttributes(func(kv otellog.KeyValue) bool {
		if kv.Value.Kind() == otellog.KindString {
			attributes[kv.Key] = kv.Value.AsString()
		} else {
			attributes[kv.Key] = fmt.Sprint(kv.Value)
		}
		return true
	})
	return attributes
}

func TestRealExceptionMinimizedBeforeBridgeAndOriginalSink(t *testing.T) {
	e := &exporter{}
	_, l, sink := faultPath(t, e, false)
	canary := "password=synthetic-private-canary"
	err := errors.New(canary)
	fields := map[string]any{"request.id": "request-1", "payload": map[string]string{"token": canary}, "error.kind": reflect.TypeOf(err).String()}
	l.Error("unsafe control", "error", err, "payload", fields["payload"], "error.kind", fields["error.kind"])
	if stringAttributes(e.records[0])["exception.message"] != canary || !strings.Contains(sink.String(), canary) {
		t.Fatal("unsafe real-error control did not demonstrate sensitive capture")
	}
	if stringAttributes(e.records[0])["error.kind"] != fields["error.kind"] {
		t.Fatal("unsafe control did not retain the unapproved alias")
	}
	sink.Reset()
	logFailure(l, err, fields)
	safe := e.records[1]
	attributes := stringAttributes(safe)
	if attributes["exception.type"] != reflect.TypeOf(err).String() || attributes["request.id"] != "request-1" || safe.Body().AsString() != "request failed" {
		t.Fatal("permitted type/category/request identity lost")
	}
	for _, key := range []string{"exception.message", "exception.stacktrace", "payload", "error.kind"} {
		if _, exists := attributes[key]; exists {
			t.Fatalf("prohibited field retained: %s", key)
		}
	}
	if strings.Contains(fmt.Sprint(attributes), canary) || strings.Contains(sink.String(), canary) || !strings.Contains(sink.String(), "request failed") {
		t.Fatal("producer policy leaked sensitive input or lost original sink output")
	}
}

type blockedExporter struct {
	entered chan struct{}
	release chan struct{}
	once    sync.Once
	mu      sync.Mutex
	bodies  []string
	sizes   []int
}

func (e *blockedExporter) Export(ctx context.Context, records []sdklog.Record) error {
	e.once.Do(func() { close(e.entered) })
	select {
	case <-e.release:
	case <-ctx.Done():
		return ctx.Err()
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	e.sizes = append(e.sizes, len(records))
	for _, record := range records {
		e.bodies = append(e.bodies, record.Body().AsString())
	}
	return nil
}
func (*blockedExporter) ForceFlush(context.Context) error { return nil }
func (*blockedExporter) Shutdown(context.Context) error   { return nil }

func TestOverloadBoundsBatchesAndExposesLocalLoss(t *testing.T) {
	e := &blockedExporter{entered: make(chan struct{}), release: make(chan struct{})}
	p, l, sink := faultPath(t, e, true)
	released := false
	defer func() {
		if !released {
			close(e.release)
		}
	}()
	const attempted = 48
	for i := 0; i < 8; i++ {
		l.Info(fmt.Sprintf("record-%d", i))
	}
	await(t, e.entered)
	for i := 8; i < attempted; i++ {
		l.Info(fmt.Sprintf("record-%d", i))
	}
	if strings.Count(sink.String(), "\n") != attempted {
		t.Fatal("original sink stopped during overload")
	}
	close(e.release)
	released = true
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := p.ForceFlush(ctx); err != nil {
		t.Fatal(err)
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	exported := len(e.bodies)
	if exported < 8 || exported >= attempted {
		t.Fatalf("expected bounded local loss: attempted=%d exported=%d", attempted, exported)
	}
	seen := map[string]bool{}
	for _, body := range e.bodies {
		if seen[body] {
			t.Fatal("duplicate exported record")
		}
		seen[body] = true
	}
	for _, size := range e.sizes {
		if size > 8 {
			t.Fatal("batch exceeded configured ceiling/queue capacity")
		}
	}
	t.Logf("attempted=%d exported=%d inferred_local_drops=%d exporter_rejected=0", attempted, exported, attempted-exported)
}

type diagnosticExporter struct{ calls atomic.Int32 }

func (e *diagnosticExporter) Export(context.Context, []sdklog.Record) error {
	e.calls.Add(1)
	return errors.New("synthetic receiver unavailable")
}
func (*diagnosticExporter) ForceFlush(context.Context) error { return nil }
func (*diagnosticExporter) Shutdown(context.Context) error   { return nil }

func TestSDKFailureDiagnosticsVisibleOutsideApplicationBridge(t *testing.T) {
	// The SDK's first global handler assignment redirects earlier delegators.
	// A child test process keeps that one-way global transition isolated.
	if os.Getenv("OBSTUDIO_LOGGING_DIAGNOSTIC_CHILD") != "1" {
		ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
		defer cancel()
		command := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestSDKFailureDiagnosticsVisibleOutsideApplicationBridge$", "-test.v")
		command.Env = append(os.Environ(), "OBSTUDIO_LOGGING_DIAGNOSTIC_CHILD=1")
		output, err := command.CombinedOutput()
		if err != nil {
			t.Fatalf("isolated diagnostic check failed: %v\n%s", err, output)
		}
		return
	}
	diagnostics := make(chan error, 4)
	var count atomic.Int32
	otel.SetErrorHandler(otel.ErrorHandlerFunc(func(err error) {
		count.Add(1)
		select {
		case diagnostics <- err:
		default:
		}
	}))
	e := &diagnosticExporter{}
	p, l, sink := faultPath(t, e, true)
	for i := 0; i < 8; i++ {
		l.Error("first failure")
	}
	select {
	case err := <-diagnostics:
		if !strings.Contains(err.Error(), "synthetic receiver unavailable") {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("SDK diagnostic was not visible")
	}
	l.Info("application continued")
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := p.ForceFlush(ctx); err != nil && !strings.Contains(err.Error(), "synthetic receiver unavailable") {
		t.Fatal(err)
	}
	if e.calls.Load() != 2 || count.Load() < 1 || count.Load() > 2 || strings.Count(sink.String(), "\n") != 9 || !strings.Contains(sink.String(), "application continued") {
		t.Fatal("unbounded export/diagnostics or application sink stopped")
	}
}
