package main

import (
	"context"
	"errors"
	"fmt"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
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
	metricExporter, err := otlpmetrichttp.New(context.Background())
	if err != nil {
		panic(err)
	}
	meterProvider := sdkmetric.NewMeterProvider(sdkmetric.WithReader(sdkmetric.NewPeriodicReader(metricExporter)))
	defer meterProvider.Shutdown(context.Background())
	if err := serve(ctx, provider.Tracer("service"), meterProvider); err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
}

func settle(ctx context.Context, tracer trace.Tracer, failed bool) error {
	ctx, root := tracer.Start(ctx, "settle.batch")
	defer root.End()
	_, child := tracer.Start(ctx, "ledger.write", trace.WithSpanKind(trace.SpanKindClient))
	defer child.End()
	child.SetAttributes(attribute.String("server.address", "ledger.internal"))
	if failed {
		err := errors.New("ledger unavailable")
		child.RecordError(err)
		child.SetStatus(codes.Error, "ledger unavailable")
		root.RecordError(err)
		root.SetStatus(codes.Error, "ledger unavailable")
		return err
	}
	return nil
}

func serve(ctx context.Context, tracer trace.Tracer, meters *sdkmetric.MeterProvider) error {
	count, err := meters.Meter("settlement").Int64Counter("settlement.batches")
	if err != nil {
		return err
	}
	outcome := "ok"
	if settle(ctx, tracer, false) != nil {
		outcome = "error"
	}
	count.Add(ctx, 1, metric.WithAttributes(attribute.String("outcome", outcome)))
	<-ctx.Done()
	return nil
}
