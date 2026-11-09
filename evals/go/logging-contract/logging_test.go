package loggingcontract

import (
	"context"
	"errors"
	"log/slog"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/otel/log"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	"go.opentelemetry.io/otel/trace"
)

type exporter struct {
	mu      sync.Mutex
	records []sdklog.Record
	fail    bool
	calls   int
}

func (e *exporter) Export(_ context.Context, records []sdklog.Record) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.calls++
	if e.fail {
		return errors.New("synthetic receiver unavailable")
	}
	for _, r := range records {
		e.records = append(e.records, r.Clone())
	}
	return nil
}
func (*exporter) Shutdown(context.Context) error   { return nil }
func (*exporter) ForceFlush(context.Context) error { return nil }

func setup(t *testing.T, e *exporter) (*sdklog.LoggerProvider, *slog.Logger) {
	t.Helper()
	p := sdklog.NewLoggerProvider(sdklog.WithAttributeCountLimit(8), sdklog.WithAttributeValueLengthLimit(32), sdklog.WithProcessor(sdklog.NewSimpleProcessor(e)))
	t.Cleanup(func() { _ = p.Shutdown(context.Background()) })
	return p, slog.New(otelslog.NewHandler("contract", otelslog.WithLoggerProvider(p)))
}

func TestSeverityAndTimestamp(t *testing.T) {
	e := &exporter{}
	_, l := setup(t, e)
	at := time.Unix(1730000000, 1)
	r := slog.NewRecord(at, slog.LevelError, "failed", 0)
	if err := l.Handler().Handle(context.Background(), r); err != nil {
		t.Fatal(err)
	}
	got := e.records[0]
	if got.Severity() != log.SeverityError || !got.Timestamp().Equal(at) || !got.ObservedTimestamp().After(at) {
		t.Fatalf("wrong severity/timestamps: %v %v %v", got.Severity(), got.Timestamp(), got.ObservedTimestamp())
	}
}

func TestSampledUnsampledDetachedContext(t *testing.T) {
	e := &exporter{}
	_, l := setup(t, e)
	for _, flags := range []trace.TraceFlags{0, trace.FlagsSampled} {
		sc := trace.NewSpanContext(trace.SpanContextConfig{TraceID: trace.TraceID{1}, SpanID: trace.SpanID{2}, TraceFlags: flags})
		l.ErrorContext(trace.ContextWithSpanContext(context.Background(), sc), "inside")
	}
	l.InfoContext(context.Background(), "outside")
	if len(e.records) != 3 {
		t.Fatalf("wanted 3 records, got %d", len(e.records))
	}
	for i := 0; i < 2; i++ {
		r := e.records[i]
		if r.TraceID() != (trace.TraceID{1}) || r.SpanID() != (trace.SpanID{2}) || r.TraceFlags() != trace.TraceFlags(i) {
			t.Fatal("lost context/flags")
		}
	}
	if e.records[2].TraceID().IsValid() || e.records[2].SpanID().IsValid() {
		t.Fatal("leaked context")
	}
}

func TestConcurrentContextIsolation(t *testing.T) {
	e := &exporter{}
	_, l := setup(t, e)
	var wg sync.WaitGroup
	for _, id := range []byte{1, 2} {
		sc := trace.NewSpanContext(trace.SpanContextConfig{TraceID: trace.TraceID{id}, SpanID: trace.SpanID{id}})
		ctx := trace.ContextWithSpanContext(context.Background(), sc)
		wg.Add(1)
		go func(ctx context.Context, id byte) {
			defer wg.Done()
			l.InfoContext(ctx, "parallel", "id", int(id))
		}(ctx, id)
	}
	wg.Wait()
	if len(e.records) != 2 || e.records[0].TraceID() == e.records[1].TraceID() {
		t.Fatal("concurrent contexts mixed")
	}
	for _, record := range e.records {
		var id byte
		record.WalkAttributes(func(kv log.KeyValue) bool {
			if kv.Key == "id" {
				id = byte(kv.Value.AsInt64())
			}
			return true
		})
		if id == 0 || record.TraceID() != (trace.TraceID{id}) || record.SpanID() != (trace.SpanID{id}) {
			t.Fatal("record was associated with the wrong request")
		}
	}
}

func TestLimitsAndPolicy(t *testing.T) {
	e := &exporter{}
	p, l := setup(t, e)
	l.Error("request failed", "exception.type", "ValueError")
	r := log.Record{}
	r.SetBody(log.StringValue(string(make([]byte, 400))))
	for i := 0; i < 20; i++ {
		r.AddAttributes(log.String(string(rune('a'+i)), "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"))
	}
	p.Logger("limits").Emit(context.Background(), r)
	got := e.records[1]
	if got.AttributesLen() != 8 || got.DroppedAttributes() != 12 || len(got.Body().AsString()) != 400 {
		t.Fatalf("limits/accounting/body mismatch: %v", got)
	}
	got.WalkAttributes(func(kv log.KeyValue) bool {
		if len(kv.Value.AsString()) != 32 {
			t.Error("attribute length not bounded")
		}
		return true
	})
	typePresent := false
	e.records[0].WalkAttributes(func(kv log.KeyValue) bool {
		if kv.Key == "exception.type" && kv.Value.AsString() == "ValueError" {
			typePresent = true
		}
		if kv.Key == "exception.message" || kv.Key == "exception.stacktrace" {
			t.Error("unexpected sensitive capture")
		}
		return true
	})
	if !typePresent {
		t.Error("permitted exception.type was not retained")
	}
}

func TestFailureBoundedWithOriginalSink(t *testing.T) {
	e := &exporter{fail: true}
	p := sdklog.NewLoggerProvider(sdklog.WithProcessor(sdklog.NewBatchProcessor(e, sdklog.WithMaxQueueSize(8), sdklog.WithExportMaxBatchSize(8), sdklog.WithExportTimeout(100*time.Millisecond))))
	sink := &countHandler{}
	l := slog.New(teeHandler{otelslog.NewHandler("failure", otelslog.WithLoggerProvider(p)), sink})
	start := time.Now()
	l.Error("receiver unavailable")
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_ = p.ForceFlush(ctx)
	_ = p.Shutdown(ctx)
	if time.Since(start) > 3*time.Second || e.calls != 1 || len(e.records) != 0 {
		t.Fatal("unbounded/recursive failure or false receipt")
	}
	if sink.count != 1 {
		t.Fatal("original sink unavailable")
	}
}

type countHandler struct{ count int }

func (h *countHandler) Handle(context.Context, slog.Record) error { h.count++; return nil }
func (*countHandler) Enabled(context.Context, slog.Level) bool    { return true }
func (h *countHandler) WithAttrs([]slog.Attr) slog.Handler        { return h }
func (h *countHandler) WithGroup(string) slog.Handler             { return h }

type teeHandler struct {
	bridge slog.Handler
	sink   slog.Handler
}

func (h teeHandler) Enabled(ctx context.Context, level slog.Level) bool {
	return h.bridge.Enabled(ctx, level) || h.sink.Enabled(ctx, level)
}
func (h teeHandler) Handle(ctx context.Context, r slog.Record) error {
	_ = h.sink.Handle(ctx, r.Clone())
	return h.bridge.Handle(ctx, r)
}
func (h teeHandler) WithAttrs(a []slog.Attr) slog.Handler {
	return teeHandler{h.bridge.WithAttrs(a), h.sink.WithAttrs(a)}
}
func (h teeHandler) WithGroup(g string) slog.Handler {
	return teeHandler{h.bridge.WithGroup(g), h.sink.WithGroup(g)}
}

func TestExplicitBridgeOptOutKeepsOriginalSink(t *testing.T) {
	e := &exporter{}
	_, _ = setup(t, e)
	sink := &countHandler{}
	// The startup owner omits the bridge in its explicit opt-out branch.
	slog.New(sink).Error("disabled")
	if len(e.records) != 0 || sink.count != 1 {
		t.Fatal("opt-out did not isolate the bridge")
	}
}
