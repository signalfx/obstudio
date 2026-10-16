package main

import (
	"context"
	"errors"
	"fmt"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
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

func readFeed(ctx context.Context, tracer trace.Tracer, failed bool) error {
	ctx, outer := tracer.Start(ctx, "GET /feed", trace.WithSpanKind(trace.SpanKindServer))
	defer outer.End()
	outer.SetAttributes(attribute.String("http.route", "/feed"))
	_, inner := tracer.Start(ctx, "GET /feed", trace.WithSpanKind(trace.SpanKindServer))
	defer inner.End()
	inner.SetAttributes(attribute.String("http.route", "/feed"))
	if failed {
		outer.SetAttributes(attribute.Int("http.response.status_code", 503))
		inner.SetAttributes(attribute.Int("http.response.status_code", 503))
		return errors.New("feed unavailable")
	}
	return nil
}

func serve(ctx context.Context, tracer trace.Tracer) error {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /feed", func(w http.ResponseWriter, r *http.Request) {
		if readFeed(r.Context(), tracer, r.URL.Query().Get("fail") == "1") != nil {
			http.Error(w, "feed unavailable", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
	})
	server := &http.Server{Addr: ":8080", Handler: mux}
	go func() { <-ctx.Done(); _ = server.Shutdown(context.Background()) }()
	return server.ListenAndServe()
}
