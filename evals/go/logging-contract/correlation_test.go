package loggingcontract

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

func TestPeerTraceFlagsDoNotBreakContextExtraction(t *testing.T) {
	const traceID = "0af7651916cd43dd8448eb211c80319c"
	const spanID = "b7ad6b7169203331"
	for _, flags := range []string{"00", "01", "02", "03"} {
		carrier := propagation.MapCarrier{"traceparent": "00-" + traceID + "-" + spanID + "-" + flags}
		ctx := propagation.TraceContext{}.Extract(context.Background(), carrier)
		sc := trace.SpanContextFromContext(ctx)
		if !sc.IsValid() || !sc.IsRemote() || sc.TraceID().String() != traceID || sc.SpanID().String() != spanID || sc.TraceFlags().String() != flags {
			t.Fatalf("peer flags %s were rejected or changed: %v", flags, sc)
		}
		injected := propagation.MapCarrier{}
		propagation.TraceContext{}.Inject(ctx, injected)
		if injected.Get("traceparent") != carrier.Get("traceparent") {
			t.Fatalf("peer flags %s changed during injection: %s", flags, injected.Get("traceparent"))
		}
	}
}

func TestRealSpansJoinCallerAndAsyncLogsAtReceiver(t *testing.T) {
	base := os.Getenv("LOGGING_CONTRACT_RECEIVER_URL")
	if base == "" {
		t.Skip("Use run_logging_contract.py for the owned loopback receiver")
	}
	parsed, err := url.Parse(base)
	if err != nil || parsed.Hostname() != "127.0.0.1" {
		t.Fatal("correlation fixture requires loopback receiver")
	}
	res := resource.NewSchemaless(attribute.String("service.name", "go-correlation"))
	providers := []*sdktrace.TracerProvider{}
	for _, sampler := range []sdktrace.Sampler{sdktrace.AlwaysSample(), sdktrace.NeverSample()} {
		exporter, err := otlptracehttp.New(context.Background(), otlptracehttp.WithEndpointURL(base+"/correlation/v1/traces"), otlptracehttp.WithTimeout(time.Second))
		if err != nil {
			t.Fatal(err)
		}
		provider := sdktrace.NewTracerProvider(sdktrace.WithResource(res), sdktrace.WithSampler(sampler),
			sdktrace.WithBatcher(exporter, sdktrace.WithMaxQueueSize(128), sdktrace.WithMaxExportBatchSize(64),
				sdktrace.WithBatchTimeout(time.Minute), sdktrace.WithExportTimeout(3*time.Second)))
		providers = append(providers, provider)
		t.Cleanup(func() {
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()
			if err := provider.Shutdown(ctx); err != nil {
				t.Error(err)
			}
		})
	}
	exporter, err := otlploghttp.New(context.Background(), otlploghttp.WithEndpointURL(base+"/correlation/v1/logs"), otlploghttp.WithTimeout(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	logs := sdklog.NewLoggerProvider(sdklog.WithResource(res), sdklog.WithProcessor(sdklog.NewBatchProcessor(exporter,
		sdklog.WithMaxQueueSize(128), sdklog.WithExportMaxBatchSize(64), sdklog.WithExportInterval(time.Minute),
		sdklog.WithExportTimeout(3*time.Second))))
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		if err := logs.Shutdown(ctx); err != nil {
			t.Error(err)
		}
	})
	sink := &bytes.Buffer{}
	logger := slog.New(teeHandler{bridge: otelslog.NewHandler("correlation", otelslog.WithLoggerProvider(logs)), sink: slog.NewJSONHandler(sink, nil)})
	tracer := providers[0].Tracer("correlation")
	expected := map[string]trace.SpanContext{}
	var mu sync.Mutex
	remember := func(body string, sc trace.SpanContext) { mu.Lock(); expected[body] = sc; mu.Unlock() }
	var workers sync.WaitGroup
	for i := 0; i < 10; i++ {
		parentContext, parentSpan := tracer.Start(context.Background(), fmt.Sprintf("request-%d", i))
		body := fmt.Sprintf("parent-%d", i)
		remember(body, parentSpan.SpanContext())
		logger.InfoContext(parentContext, body)
		workers.Add(1)
		go func(index int, caller context.Context, parent trace.Span) {
			defer workers.Done()
			defer parent.End()
			ctx, child := tracer.Start(caller, fmt.Sprintf("work-%d", index))
			defer child.End()
			body := fmt.Sprintf("child-%d", index)
			remember(body, child.SpanContext())
			logger.InfoContext(ctx, body)
		}(i, parentContext, parentSpan)
	}
	workers.Wait()
	ctx, unsampled := providers[1].Tracer("correlation").Start(context.Background(), "unsampled")
	sc := unsampled.SpanContext()
	if !sc.IsValid() || sc.IsSampled() || unsampled.IsRecording() {
		t.Fatal("expected valid non-recording SDK span")
	}
	logger.InfoContext(ctx, "unsampled")
	unsampled.End()
	logger.InfoContext(context.Background(), "outside")
	flushContext, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	if err := logs.ForceFlush(flushContext); err != nil {
		t.Fatal(err)
	}
	for _, provider := range providers {
		if err := provider.ForceFlush(flushContext); err != nil {
			t.Fatal(err)
		}
	}
	client := &http.Client{Timeout: 2 * time.Second}
	get := func(suffix string) wireReceipt {
		t.Helper()
		response, err := client.Get(parsed.Scheme + "://" + parsed.Host + "/evidence" + parsed.Path + "/correlation" + suffix)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		if response.StatusCode != http.StatusOK {
			t.Fatal(response.Status)
		}
		var receipt wireReceipt
		if err := json.NewDecoder(response.Body).Decode(&receipt); err != nil {
			t.Fatal(err)
		}
		return receipt
	}
	receivedLogs, receivedSpans := get(""), get("/traces")
	if receivedLogs.Accepted != 22 || receivedSpans.Accepted != 20 {
		t.Fatalf("logs=%d spans=%d", receivedLogs.Accepted, receivedSpans.Accepted)
	}
	if receivedLogs.Requests != 1 || receivedSpans.Requests != 1 {
		t.Fatal("caller/worker records must drain in one SDK batch per signal")
	}
	spans := map[string]int{}
	for i, span := range receivedSpans.Spans {
		spans[span.TraceID+"/"+span.SpanID] = i
	}
	if len(spans) != 20 || len(receivedLogs.Records) != 22 {
		t.Fatal("duplicate or missing signal records")
	}
	seen := map[string]bool{}
	for _, record := range receivedLogs.Records {
		body := record.Body.String
		if seen[body] {
			t.Fatal("duplicate application log")
		}
		seen[body] = true
		if body == "outside" {
			if record.TraceID != "" || record.SpanID != "" {
				t.Fatal("outside log inherited stale context")
			}
			continue
		}
		if body == "unsampled" {
			if record.TraceID != sc.TraceID().String() || record.SpanID != sc.SpanID().String() || record.Flags&0xff != int(sc.TraceFlags()) {
				t.Fatal("unsampled correlation lost")
			}
			if _, exists := spans[record.TraceID+"/"+record.SpanID]; exists {
				t.Fatal("unsampled span unexpectedly exported")
			}
			continue
		}
		want, exists := expected[body]
		if !exists || !want.IsSampled() || record.TraceID != want.TraceID().String() || record.SpanID != want.SpanID().String() || record.Flags&0xff != int(want.TraceFlags()) {
			t.Fatal("log paired to wrong request/span")
		}
		index, exists := spans[record.TraceID+"/"+record.SpanID]
		if !exists {
			t.Fatal("log did not join an actual received span")
		}
		span := receivedSpans.Spans[index]
		service := map[string]any{"stringValue": "go-correlation"}
		if !reflect.DeepEqual(record.Resource["service.name"], service) || !reflect.DeepEqual(span.Resource["service.name"], service) {
			t.Fatal("signal resource identity diverged")
		}
		if strings.HasPrefix(body, "child-") {
			parent := expected[strings.Replace(body, "child-", "parent-", 1)]
			if span.ParentSpanID != parent.SpanID().String() || span.TraceID != parent.TraceID().String() {
				t.Fatal("async span lost its real parent")
			}
		}
	}
	if strings.Count(sink.String(), "\n") != 22 {
		t.Fatal("original sink lost application logs")
	}
}
