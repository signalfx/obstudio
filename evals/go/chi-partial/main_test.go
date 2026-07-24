package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"go.opentelemetry.io/otel"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"go.opentelemetry.io/otel/trace"
)

func TestGetTaskPreservesServerSpanContext(t *testing.T) {
	previousProvider := otel.GetTracerProvider()
	otel.SetTracerProvider(trace.NewNoopTracerProvider())

	recorder := tracetest.NewSpanRecorder()
	provider := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(recorder))
	otel.SetTracerProvider(provider)
	t.Cleanup(func() {
		otel.SetTracerProvider(previousProvider)
		if err := provider.Shutdown(context.Background()); err != nil {
			t.Errorf("shut down tracer provider: %v", err)
		}
	})

	request := httptest.NewRequest(http.MethodGet, "/tasks/1", nil)
	response := httptest.NewRecorder()
	newHandler().ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("GET /tasks/1 returned %d, want %d", response.Code, http.StatusOK)
	}

	spans := recorder.Ended()
	if len(spans) != 2 {
		t.Fatalf("ended spans = %d, want exactly 2", len(spans))
	}

	var serverSpan, taskSpan sdktrace.ReadOnlySpan
	for _, span := range spans {
		switch {
		case span.SpanKind() == trace.SpanKindServer:
			if serverSpan != nil {
				t.Fatal("found more than one SERVER span")
			}
			serverSpan = span
		case span.InstrumentationScope().Name == "task-service":
			if taskSpan != nil {
				t.Fatal("found more than one task-service span")
			}
			taskSpan = span
		}
	}

	if serverSpan == nil {
		t.Fatal("SERVER span was not recorded")
	}
	if taskSpan == nil {
		t.Fatal("task-service custom span was not recorded")
	}
	if taskSpan.SpanContext().TraceID() != serverSpan.SpanContext().TraceID() {
		t.Fatalf(
			"task-service trace ID %s does not match SERVER trace ID %s",
			taskSpan.SpanContext().TraceID(),
			serverSpan.SpanContext().TraceID(),
		)
	}
	if taskSpan.Parent().SpanID() != serverSpan.SpanContext().SpanID() {
		t.Fatalf(
			"task-service parent span ID %s does not match SERVER span ID %s",
			taskSpan.Parent().SpanID(),
			serverSpan.SpanContext().SpanID(),
		)
	}
}
