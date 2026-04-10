package kvstore

import (
	"context"
	"net/http"
	"os"
	"strconv"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/contrib/instrumentation/runtime"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

const telemetryMeterName = "kvstore"

func InitTelemetry(ctx context.Context, serviceName string) (func(context.Context) error, error) {
	if os.Getenv("OTEL_SDK_DISABLED") == "true" {
		return func(context.Context) error { return nil }, nil
	}

	res, err := resource.New(
		ctx,
		resource.WithAttributes(
			attribute.String("service.name", envOr("OTEL_SERVICE_NAME", serviceName)),
		),
	)
	if err != nil {
		return nil, err
	}

	traceExporter, err := otlptracehttp.New(ctx)
	if err != nil {
		return nil, err
	}

	metricExporter, err := otlpmetrichttp.New(ctx)
	if err != nil {
		return nil, err
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(traceExporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(
		propagation.NewCompositeTextMapPropagator(
			propagation.TraceContext{},
			propagation.Baggage{},
		),
	)

	metricInterval := metricExportInterval()
	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(metricExporter, sdkmetric.WithInterval(metricInterval))),
		sdkmetric.WithResource(res),
	)
	otel.SetMeterProvider(mp)

	if err := runtime.Start(); err != nil {
		_ = tp.Shutdown(ctx)
		_ = mp.Shutdown(ctx)
		return nil, err
	}

	return func(ctx context.Context) error {
		if err := tp.Shutdown(ctx); err != nil {
			return err
		}
		return mp.Shutdown(ctx)
	}, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func metricExportInterval() time.Duration {
	if raw := os.Getenv("OTEL_METRIC_EXPORT_INTERVAL"); raw != "" {
		if ms, err := strconv.Atoi(raw); err == nil && ms > 0 {
			return time.Duration(ms) * time.Millisecond
		}
	}
	return time.Minute
}

func telemetryHTTPHandler(next http.Handler, route string) http.Handler {
	handler := otelhttp.NewHandler(next, route)
	return http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			recorder := &statusRecorder{ResponseWriter: w, statusCode: http.StatusOK}
			handler.ServeHTTP(recorder, r)

			attrs := []attribute.KeyValue{
				attribute.String("http.request.method", r.Method),
				attribute.String("http.route", route),
				attribute.Int("http.response.status_code", recorder.statusCode),
			}
			recordInt64Counter("http.server.request.count", 1, attrs...)
			if recorder.statusCode >= 400 {
				recordInt64Counter("http.server.request.errors", 1, attrs...)
			}
		},
	)
}

type statusRecorder struct {
	http.ResponseWriter
	statusCode int
}

func (r *statusRecorder) WriteHeader(statusCode int) {
	r.statusCode = statusCode
	r.ResponseWriter.WriteHeader(statusCode)
}

func storeOperationTracer() trace.Tracer {
	return otel.Tracer("kvstore/store")
}

func persistenceTracer() trace.Tracer {
	return otel.Tracer("kvstore/persistence")
}

func recordOperationDuration(operation string, duration time.Duration) {
	recordFloat64Histogram(
		"kvstore.store.operation.duration", duration.Seconds(),
		attribute.String("kvstore.operation", operation),
	)
}

func recordOperationError(operation string, err error) {
	recordInt64Counter(
		"kvstore.store.operation.errors", 1,
		attribute.String("kvstore.operation", operation),
		attribute.String("error.type", classifyError(err)),
	)
}

func recordPersistenceDuration(operation string, duration time.Duration) {
	recordFloat64Histogram(
		"kvstore.persistence.write.duration", duration.Seconds(),
		attribute.String("kvstore.operation", operation),
	)
}

func recordPersistenceError(operation string, err error) {
	recordInt64Counter(
		"kvstore.persistence.write.errors", 1,
		attribute.String("kvstore.operation", operation),
		attribute.String("error.type", classifyError(err)),
	)
}

func recordLoadDuration(duration time.Duration) {
	recordFloat64Histogram("kvstore.persistence.load.duration", duration.Seconds())
}

func recordEviction() {
	recordInt64Counter("kvstore.store.evictions.count", 1)
}

func recordIndexBacklog(delta int64) {
	recordInt64UpDownCounter("kvstore.index.backlog", delta)
}

func recordInt64Counter(name string, value int64, attrs ...attribute.KeyValue) {
	counter, err := otel.Meter(telemetryMeterName).Int64Counter(name)
	if err != nil {
		return
	}
	counter.Add(context.Background(), value, metric.WithAttributes(attrs...))
}

func recordInt64UpDownCounter(name string, value int64, attrs ...attribute.KeyValue) {
	counter, err := otel.Meter(telemetryMeterName).Int64UpDownCounter(name)
	if err != nil {
		return
	}
	counter.Add(context.Background(), value, metric.WithAttributes(attrs...))
}

func recordFloat64Histogram(name string, value float64, attrs ...attribute.KeyValue) {
	histogram, err := otel.Meter(telemetryMeterName).Float64Histogram(name)
	if err != nil {
		return
	}
	histogram.Record(context.Background(), value, metric.WithAttributes(attrs...))
}

func markSpanError(span trace.Span, err error) {
	span.RecordError(err)
	span.SetStatus(codes.Error, err.Error())
}

func classifyError(err error) string {
	switch {
	case err == nil:
		return "none"
	case os.IsNotExist(err):
		return "not_found"
	case os.IsPermission(err):
		return "permission_denied"
	default:
		switch err {
		case ErrInvalidKey:
			return "invalid_key"
		case ErrValueTooLarge:
			return "value_too_large"
		case ErrNotFound:
			return "not_found"
		default:
			return "internal"
		}
	}
}
