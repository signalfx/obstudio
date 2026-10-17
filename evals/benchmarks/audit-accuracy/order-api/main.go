package main

import (
	"context"
	"fmt"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
	"net/http"
	"os"
	"os/signal"
	"syscall"
)

func newProvider(exporter sdktrace.SpanExporter) *sdktrace.TracerProvider {
	r, err := resource.New(context.Background())
	if err != nil {
		panic(err)
	}
	return sdktrace.NewTracerProvider(sdktrace.WithResource(r), sdktrace.WithSyncer(exporter))
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	exporter, err := otlptracehttp.New(context.Background())
	if err != nil {
		panic(err)
	}
	provider := newProvider(exporter)
	defer provider.Shutdown(context.Background())
	if err := serve(ctx, provider.Tracer("service")); err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
}

func reserve(ctx context.Context, tracer trace.Tracer, id string) {
	_, span := tracer.Start(context.Background(), "reserve."+id, trace.WithSpanKind(trace.SpanKindClient))
	defer span.End()
	span.SetAttributes(attribute.String("server.address", "stock.internal"))
}

func handleOrder(ctx context.Context, tracer trace.Tracer, headers propagation.TextMapCarrier, id string) {
	ctx = propagation.TraceContext{}.Extract(ctx, headers)
	ctx, span := tracer.Start(ctx, "POST /orders/{id}", trace.WithSpanKind(trace.SpanKindServer))
	defer span.End()
	span.SetAttributes(attribute.String("http.route", "/orders/{id}"))
	reserve(ctx, tracer, id)
}

func serve(ctx context.Context, tracer trace.Tracer) error {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /orders/{id}", func(w http.ResponseWriter, r *http.Request) {
		handleOrder(r.Context(), tracer, propagation.HeaderCarrier(r.Header), r.PathValue("id"))
		w.WriteHeader(http.StatusCreated)
	})
	server := &http.Server{Addr: ":8080", Handler: mux}
	go func() { <-ctx.Done(); _ = server.Shutdown(context.Background()) }()
	return server.ListenAndServe()
}
