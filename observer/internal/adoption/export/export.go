// Package export ships obstudio's own adoption data off-box: one
// OTLP/HTTP metrics exporter to one endpoint, asked of the adoption gate
// immediately before every export, and a periodic reader built in a separate
// step so the caller can put another exporter between the two.
//
// The exporter carries no credential and no header of its own, and no OTEL_*
// environment variable changes where, what or when it sends: every setting
// the OTel SDK would read from the environment is given explicitly.
package export

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"

	"github.com/signalfx/obstudio/observer/internal/adoption/gate"
)

const (
	// DefaultEndpoint is the single production endpoint. The exporter posts
	// to DefaultEndpoint + "/v1/metrics".
	DefaultEndpoint = "https://obstudio-ingest.observability.splunkcloud.com"

	// EndpointEnv overrides DefaultEndpoint for local, dev and test runs. A
	// normal production run does not set it.
	EndpointEnv = "OBSTUDIO_ADOPTION_OTLP_ENDPOINT"

	// ExportIntervalLongRunning is the periodic export interval for the
	// long-running observer. Ingest cost falls steeply up to one hour and
	// barely after it, while a longer interval would lose more short
	// sessions. The clean-exit flush covers sessions shorter than one
	// interval.
	ExportIntervalLongRunning = time.Hour

	// FlushTimeout bounds every export: the shutdown flush, the install
	// flush and each periodic export, retries included.
	FlushTimeout = 5 * time.Second

	// MaxAttempts documents the retry bound. The SDK retries a retryable
	// response (429, 502, 503, 504) with randomized exponential backoff from
	// retryInitialInterval (factor 1.5, jitter ±50%, capped at
	// retryMaxInterval), waits at least as long as a Retry-After header asks,
	// and makes no new attempt once retryMaxElapsed has passed since the
	// first. The shortest possible waits are 0.5 s, 0.75 s and 1 s, so the
	// fifth attempt is the last one that can start; FlushTimeout bounds the
	// whole export as well.
	MaxAttempts          = 5
	retryInitialInterval = time.Second
	retryMaxInterval     = 2 * time.Second
	retryMaxElapsed      = 3 * time.Second
)

// ClientType is the lifecycle class the export path is built for. Long-running
// is the only v1 value.
type ClientType string

const ClientTypeLongRunning ClientType = "long-running"

// ErrDropped is the outcome of an export the gate closed: nothing was sent and
// no connection was opened. It is never success and is never retried.
var ErrDropped = errors.New("adoption export dropped: telemetry gate closed")

// ErrFailed marks an export that was attempted and did not get a 2xx. It is
// distinct from ErrDropped.
var ErrFailed = errors.New("adoption export failed")

// DroppedError carries the gate's reason for a dropped export.
type DroppedError struct{ Reason gate.Reason }

func (e *DroppedError) Error() string        { return ErrDropped.Error() + " (" + string(e.Reason) + ")" }
func (e *DroppedError) Is(target error) bool { return target == ErrDropped }

// DropReason returns the gate reason of a dropped export.
func DropReason(err error) (gate.Reason, bool) {
	var d *DroppedError
	if errors.As(err, &d) {
		return d.Reason, true
	}
	return "", false
}

type failedError struct{ err error }

func (e *failedError) Error() string        { return ErrFailed.Error() + ": " + e.err.Error() }
func (e *failedError) Unwrap() error        { return e.err }
func (e *failedError) Is(target error) bool { return target == ErrFailed }

// Decider is the part of the telemetry gate the export path uses. A nil
// *gate.Gate is a valid, closed Decider.
type Decider interface{ Decide() gate.Decision }

// Endpoint returns the endpoint base URL and whether the override was set.
func Endpoint(getenv func(string) string) (string, bool) {
	if getenv == nil {
		getenv = os.Getenv
	}
	if v := strings.TrimSpace(getenv(EndpointEnv)); v != "" {
		return strings.TrimRight(v, "/"), true
	}
	return DefaultEndpoint, false
}

// Exporter is the adoption exporter: it asks the gate before every export
// and sends through the OTLP/HTTP exporter only when the gate is open.
type Exporter struct {
	gate    Decider
	inner   sdkmetric.Exporter
	timeout time.Duration
}

var _ sdkmetric.Exporter = (*Exporter)(nil)

// ExporterConfig configures NewExporter. Zero values select the production
// constants.
type ExporterConfig struct {
	ClientType ClientType
	Gate       Decider
	// Getenv reads EndpointEnv; nil means os.Getenv.
	Getenv func(string) string
	// Timeout overrides FlushTimeout for tests.
	Timeout time.Duration
}

// NewExporter builds the adoption exporter. It opens no connection; the gate
// is applied per export, not here.
func NewExporter(cfg ExporterConfig) (*Exporter, error) {
	if cfg.ClientType != ClientTypeLongRunning {
		return nil, fmt.Errorf("adoption export: unsupported client type %q", cfg.ClientType)
	}
	endpoint, _ := Endpoint(cfg.Getenv)
	u, err := url.Parse(endpoint)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return nil, fmt.Errorf("adoption export: invalid endpoint %q", endpoint)
	}
	timeout := cfg.Timeout
	if timeout <= 0 {
		timeout = FlushTimeout
	}
	inner, err := otlpmetrichttp.New(context.Background(),
		// Every option below overrides an OTEL_* variable the SDK reads.
		otlpmetrichttp.WithEndpointURL(strings.TrimRight(u.String(), "/")+"/v1/metrics"),
		otlpmetrichttp.WithTLSClientConfig(tlsConfig(u.Scheme)),
		otlpmetrichttp.WithHeaders(map[string]string{}),
		otlpmetrichttp.WithCompression(otlpmetrichttp.NoCompression),
		otlpmetrichttp.WithTimeout(timeout),
		otlpmetrichttp.WithRetry(otlpmetrichttp.RetryConfig{
			Enabled:         true,
			InitialInterval: retryInitialInterval,
			MaxInterval:     retryMaxInterval,
			MaxElapsedTime:  retryMaxElapsed,
		}),
		otlpmetrichttp.WithTemporalitySelector(sdkmetric.DefaultTemporalitySelector),
		otlpmetrichttp.WithAggregationSelector(sdkmetric.DefaultAggregationSelector),
	)
	if err != nil {
		return nil, fmt.Errorf("adoption export: %w", err)
	}
	return &Exporter{gate: cfg.Gate, inner: inner, timeout: timeout}, nil
}

// Export asks the gate, then sends. A closed gate returns a DroppedError
// (errors.Is ErrDropped) and opens no connection; a send that does not get a
// 2xx returns an error that is ErrFailed and not ErrDropped; a 2xx returns nil.
func (e *Exporter) Export(ctx context.Context, rm *metricdata.ResourceMetrics) error {
	d := decide(e.gate)
	if !d.Allowed {
		return &DroppedError{Reason: d.Reason}
	}
	// The SDK's timeout bounds one request; this bounds the export, retries
	// included.
	ctx, cancel := context.WithTimeout(ctx, e.timeout)
	defer cancel()
	if err := e.inner.Export(ctx, rm); err != nil {
		return &failedError{err: err}
	}
	return nil
}

// tlsConfig replaces any TLS setting from OTEL_EXPORTER_OTLP_*CERTIFICATE or
// *CLIENT_KEY: system roots and TLS 1.2+ for https, none for plain http.
func tlsConfig(scheme string) *tls.Config {
	if scheme != "https" {
		return nil
	}
	return &tls.Config{MinVersion: tls.VersionTLS12}
}

func decide(d Decider) gate.Decision {
	if d == nil {
		return gate.Decision{Reason: gate.ReasonNoManager}
	}
	return d.Decide()
}

func (e *Exporter) Temporality(k sdkmetric.InstrumentKind) metricdata.Temporality {
	return e.inner.Temporality(k)
}

func (e *Exporter) Aggregation(k sdkmetric.InstrumentKind) sdkmetric.Aggregation {
	return e.inner.Aggregation(k)
}

func (e *Exporter) ForceFlush(ctx context.Context) error { return e.inner.ForceFlush(ctx) }
func (e *Exporter) Shutdown(ctx context.Context) error   { return e.inner.Shutdown(ctx) }

// ReaderConfig configures NewReader. Zero values select the production
// constants; tests shorten them.
type ReaderConfig struct {
	ClientType ClientType
	Interval   time.Duration
	Timeout    time.Duration
}

// Reader is the adoption periodic reader. Its ForceFlush and Shutdown are the
// SDK reader's.
type Reader struct {
	*sdkmetric.PeriodicReader
}

// NewReader builds the periodic reader over any exporter. Its timer starts
// now, relative to process start, with no wall-clock anchor, and the reader
// keeps the exporter's temporality.
func NewReader(exp sdkmetric.Exporter, cfg ReaderConfig) (*Reader, error) {
	if cfg.ClientType != ClientTypeLongRunning {
		return nil, fmt.Errorf("adoption export: unsupported client type %q", cfg.ClientType)
	}
	if exp == nil {
		return nil, errors.New("adoption export: nil exporter")
	}
	interval := cfg.Interval
	if interval <= 0 {
		interval = ExportIntervalLongRunning
	}
	timeout := cfg.Timeout
	if timeout <= 0 {
		timeout = FlushTimeout
	}
	// Explicit interval and timeout override OTEL_METRIC_EXPORT_INTERVAL and
	// OTEL_METRIC_EXPORT_TIMEOUT.
	r := sdkmetric.NewPeriodicReader(exp,
		sdkmetric.WithInterval(interval),
		sdkmetric.WithTimeout(timeout),
	)
	return &Reader{PeriodicReader: r}, nil
}

// IsAdoptionError reports an export outcome this package produced. The
// composition root uses it to keep dropped and failed adoption exports out of
// the process log.
func IsAdoptionError(err error) bool {
	return errors.Is(err, ErrDropped) || errors.Is(err, ErrFailed)
}
