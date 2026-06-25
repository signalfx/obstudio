package otlp

import (
	"context"
	"fmt"
	"log"
	"net/url"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/config/confighttp"
	"go.opentelemetry.io/collector/config/configopaque"
	"go.opentelemetry.io/collector/config/configoptional"
	"go.opentelemetry.io/collector/exporter"
	"go.opentelemetry.io/collector/exporter/exporterhelper"
	"go.opentelemetry.io/collector/exporter/otlphttpexporter"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/pmetric"
	metricnoop "go.opentelemetry.io/otel/metric/noop"
	tracenoop "go.opentelemetry.io/otel/trace/noop"
	"go.uber.org/zap"
)

const defaultSplunkMetricsExportTimeout = 5 * time.Second
const splunkMetricsOTLPPath = "/v2/datapoint/otlp"

// MetricsExporter forwards OTLP metrics to an external metrics backend.
type MetricsExporter interface {
	ExportMetrics(ctx context.Context, md pmetric.Metrics) error
}

// SplunkMetricsExporterConfig configures optional Splunk Observability Cloud
// metric forwarding.
type SplunkMetricsExporterConfig struct {
	Enabled     bool
	Realm       string
	Endpoint    string
	AccessToken string
	Timeout     time.Duration
}

// SplunkMetricsExportStatus is a redacted snapshot of outbound Splunk metrics
// forwarding state.
type SplunkMetricsExportStatus struct {
	Enabled               bool                        `json:"enabled"`
	Configured            bool                        `json:"configured"`
	Realm                 string                      `json:"realm,omitempty"`
	Endpoints             []string                    `json:"endpoints,omitempty"`
	AccessTokenConfigured bool                        `json:"accessTokenConfigured"`
	AccessToken           string                      `json:"accessToken,omitempty"`
	Timeout               string                      `json:"timeout,omitempty"`
	LastExport            *SplunkMetricsExportAttempt `json:"lastExport,omitempty"`
}

// SplunkMetricsExportAttempt records the latest outbound export result without
// carrying request secrets.
type SplunkMetricsExportAttempt struct {
	Time    time.Time `json:"time"`
	Success bool      `json:"success"`
	Error   string    `json:"error,omitempty"`
}

// SplunkMetricsExportController owns a live Splunk exporter and allows the
// MCP control plane to inspect or replace it while the OTLP receivers keep
// using the same MetricsExporter reference.
type SplunkMetricsExportController struct {
	mu            sync.RWMutex
	config        SplunkMetricsExporterConfig
	exporter      splunkMetricsExporterRuntime
	lastExport    SplunkMetricsExportAttempt
	hasLastExport bool
}

type splunkMetricsExporterRuntime interface {
	MetricsExporter
	Endpoints() []string
	Shutdown(ctx context.Context)
}

// NewSplunkMetricsExportController creates a runtime controller. Disabled
// configs are valid and simply produce a no-op exporter.
func NewSplunkMetricsExportController(config SplunkMetricsExporterConfig) (*SplunkMetricsExportController, error) {
	controller := &SplunkMetricsExportController{}
	if err := controller.Configure(config); err != nil {
		return nil, err
	}
	return controller, nil
}

// Configure replaces the live exporter after validating the supplied config.
func (c *SplunkMetricsExportController) Configure(config SplunkMetricsExporterConfig) error {
	exporter, err := newConfiguredSplunkMetricsExporter(config)
	if err != nil {
		return err
	}
	c.mu.Lock()
	old := c.exporter
	c.config = normalizeSplunkMetricsExporterConfig(config)
	c.exporter = exporter
	c.lastExport = SplunkMetricsExportAttempt{}
	c.hasLastExport = false
	c.mu.Unlock()
	if old != nil {
		old.Shutdown(context.Background())
	}
	return nil
}

// Shutdown stops the active exporter component cleanly.
func (c *SplunkMetricsExportController) Shutdown(ctx context.Context) {
	if c == nil {
		return
	}
	c.mu.Lock()
	exp := c.exporter
	c.exporter = nil
	c.mu.Unlock()
	if exp != nil {
		exp.Shutdown(ctx)
	}
}

// Config returns the current config. Callers must not log or return the access
// token from this value.
func (c *SplunkMetricsExportController) Config() SplunkMetricsExporterConfig {
	if c == nil {
		return SplunkMetricsExporterConfig{}
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.config
}

// Status returns a redacted snapshot of the controller state.
func (c *SplunkMetricsExportController) Status() SplunkMetricsExportStatus {
	if c == nil {
		return SplunkMetricsExportStatus{}
	}
	c.mu.RLock()
	defer c.mu.RUnlock()

	status := SplunkMetricsExportStatus{
		Enabled:               c.config.Enabled,
		Configured:            c.exporter != nil,
		Realm:                 c.config.Realm,
		AccessTokenConfigured: c.config.AccessToken != "",
		AccessToken:           redactConfiguredToken(c.config.AccessToken),
		Timeout:               effectiveSplunkMetricsTimeout(c.config.Timeout).String(),
	}
	if c.exporter != nil {
		status.Endpoints = c.exporter.Endpoints()
	}
	if c.hasLastExport {
		last := c.lastExport
		status.LastExport = &last
	}
	return status
}

// ExportMetrics forwards metrics through the current live exporter.
func (c *SplunkMetricsExportController) ExportMetrics(ctx context.Context, md pmetric.Metrics) error {
	if c == nil {
		return nil
	}
	c.mu.RLock()
	exporter := c.exporter
	c.mu.RUnlock()
	if exporter == nil {
		return nil
	}
	err := exporter.ExportMetrics(ctx, md)
	c.recordExport(err)
	return err
}

// TestConnection sends a single Splunk-friendly canary metric through the
// current exporter and returns the updated redacted status.
func (c *SplunkMetricsExportController) TestConnection(ctx context.Context, metricName string) (SplunkMetricsExportStatus, error) {
	if c == nil {
		return SplunkMetricsExportStatus{}, fmt.Errorf("Splunk metrics export controller is not available")
	}
	c.mu.RLock()
	configured := c.exporter != nil
	c.mu.RUnlock()
	if !configured {
		return c.Status(), fmt.Errorf("Splunk metrics export is disabled or not configured")
	}
	if strings.TrimSpace(metricName) == "" {
		metricName = "obstudio.splunk_exporter.test"
	}
	err := c.ExportMetrics(ctx, splunkExporterCanaryMetric(metricName))
	return c.Status(), err
}

func (c *SplunkMetricsExportController) recordExport(err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.hasLastExport = true
	c.lastExport = SplunkMetricsExportAttempt{
		Time:    time.Now(),
		Success: err == nil,
	}
	if err != nil {
		c.lastExport.Error = sanitizeExportError(err, c.config.AccessToken)
	}
}

func normalizeSplunkMetricsExporterConfig(config SplunkMetricsExporterConfig) SplunkMetricsExporterConfig {
	config.Realm = strings.TrimSpace(config.Realm)
	config.Endpoint = strings.TrimSpace(config.Endpoint)
	config.AccessToken = strings.TrimSpace(config.AccessToken)
	config.Timeout = effectiveSplunkMetricsTimeout(config.Timeout)
	return config
}

func effectiveSplunkMetricsTimeout(timeout time.Duration) time.Duration {
	if timeout <= 0 {
		return defaultSplunkMetricsExportTimeout
	}
	return timeout
}

func redactConfiguredToken(token string) string {
	if strings.TrimSpace(token) == "" {
		return ""
	}
	return fmt.Sprintf("<redacted len=%d>", len(token))
}

// sanitizeExportError returns err.Error() with the access token replaced by
// "<redacted>" if it appears. The otlphttpexporter uses configopaque.String so
// the token should never appear in its own error messages, but a Splunk backend
// can echo submitted credentials in a 401 body; this is a defence-in-depth guard.
func sanitizeExportError(err error, token string) string {
	msg := err.Error()
	if token == "" {
		return msg
	}
	return strings.ReplaceAll(msg, token, "<redacted>")
}

func newConfiguredSplunkMetricsExporter(config SplunkMetricsExporterConfig) (splunkMetricsExporterRuntime, error) {
	if !config.Enabled {
		return nil, nil
	}
	return NewSplunkMetricsExporter(config)
}

// SplunkMetricsExporter forwards metrics to Splunk Observability Cloud using
// the Collector otlphttpexporter with X-SF-Token auth and queue disabled for
// synchronous delivery.
type SplunkMetricsExporter struct {
	endpoint string
	exp      exporter.Metrics
}

// NewSplunkMetricsExporter creates a Splunk metrics exporter when enabled. It
// returns nil when the config is disabled.
func NewSplunkMetricsExporter(config SplunkMetricsExporterConfig) (*SplunkMetricsExporter, error) {
	if !config.Enabled {
		return nil, nil
	}
	endpoint := strings.TrimSpace(config.Endpoint)
	if endpoint == "" {
		realm := strings.TrimSpace(config.Realm)
		if realm == "" {
			return nil, fmt.Errorf("splunk metrics export requires SPLUNK_REALM or OBSTUDIO_SPLUNK_METRICS_ENDPOINT")
		}
		endpoint = fmt.Sprintf("https://ingest.%s.observability.splunkcloud.com%s", realm, splunkMetricsOTLPPath)
	}
	if _, err := normalizeSplunkMetricsEndpoint(endpoint); err != nil {
		return nil, fmt.Errorf("invalid Splunk metrics endpoint: %w", err)
	}
	token := strings.TrimSpace(config.AccessToken)
	if token == "" {
		return nil, fmt.Errorf("splunk metrics export requires SPLUNK_ACCESS_TOKEN")
	}

	factory := otlphttpexporter.NewFactory()
	cfg := factory.CreateDefaultConfig().(*otlphttpexporter.Config)
	cfg.MetricsEndpoint = endpoint
	cfg.ClientConfig = confighttp.ClientConfig{
		Timeout: effectiveSplunkMetricsTimeout(config.Timeout),
		Headers: configopaque.MapList{
			{Name: "X-SF-Token", Value: configopaque.String(token)},
		},
	}
	cfg.QueueConfig = configoptional.None[exporterhelper.QueueBatchConfig]()

	set := exporter.Settings{
		ID: component.MustNewID("otlphttp"),
		TelemetrySettings: component.TelemetrySettings{
			Logger:         zap.NewNop(),
			MeterProvider:  metricnoop.NewMeterProvider(),
			TracerProvider: tracenoop.NewTracerProvider(),
		},
	}
	exp, err := factory.CreateMetrics(context.Background(), set, cfg)
	if err != nil {
		return nil, fmt.Errorf("create Splunk metrics exporter: %w", err)
	}
	if err := exp.Start(context.Background(), minimalHost{}); err != nil {
		_ = exp.Shutdown(context.Background())
		return nil, fmt.Errorf("start Splunk metrics exporter: %w", err)
	}
	return &SplunkMetricsExporter{endpoint: endpoint, exp: exp}, nil
}

// Endpoint returns the configured non-secret export endpoint.
func (e *SplunkMetricsExporter) Endpoint() string {
	if e == nil {
		return ""
	}
	return e.endpoint
}

// Endpoints returns all configured non-secret export endpoints.
func (e *SplunkMetricsExporter) Endpoints() []string {
	if e == nil {
		return nil
	}
	return []string{e.endpoint}
}

// ExportMetrics forwards metrics to the Splunk ingest endpoint synchronously.
func (e *SplunkMetricsExporter) ExportMetrics(ctx context.Context, md pmetric.Metrics) error {
	if e == nil {
		return nil
	}
	return e.exp.ConsumeMetrics(ctx, md)
}

// Shutdown stops the underlying exporter component.
func (e *SplunkMetricsExporter) Shutdown(ctx context.Context) {
	if e == nil {
		return
	}
	if err := e.exp.Shutdown(ctx); err != nil {
		log.Printf("[splunk-export] shutdown error: %v", err)
	}
}

func normalizeSplunkMetricsEndpoint(rawEndpoint string) (string, error) {
	trimmed := strings.TrimSpace(rawEndpoint)
	if trimmed == "" {
		return "", fmt.Errorf("endpoint is empty")
	}
	parsed, err := url.Parse(trimmed)
	if err != nil {
		return "", err
	}
	if parsed.Scheme == "" || parsed.Host == "" {
		return "", fmt.Errorf("endpoint must include scheme and host")
	}
	return parsed.String(), nil
}

func splunkExporterCanaryMetric(metricName string) pmetric.Metrics {
	md := pmetric.NewMetrics()
	rm := md.ResourceMetrics().AppendEmpty()
	rm.Resource().Attributes().PutStr("service.name", "obstudio")
	rm.Resource().Attributes().PutStr("telemetry.source", "obstudio")
	sm := rm.ScopeMetrics().AppendEmpty()
	sm.Scope().SetName("obstudio.splunk_exporter")
	sm.Scope().SetVersion("0.1.0")

	metric := sm.Metrics().AppendEmpty()
	metric.SetName(metricName)
	metric.SetDescription("Obstudio Splunk metrics exporter connectivity canary")
	metric.SetUnit("1")
	dp := metric.SetEmptyGauge().DataPoints().AppendEmpty()
	now := pcommon.NewTimestampFromTime(time.Now())
	dp.SetTimestamp(now)
	dp.SetDoubleValue(1)
	dp.Attributes().PutStr("source", "obstudio")
	dp.Attributes().PutStr("probe", "splunk_exporter_test")
	return md
}

// exportMetricsAsync forwards md to exporter in a background goroutine.
// One goroutine is fired per batch with no concurrency cap — intentional for
// a dev-tool workload where batches are infrequent and ingest latency is low.
func exportMetricsAsync(exporter MetricsExporter, md pmetric.Metrics) {
	if exporter == nil {
		return
	}
	cloned := pmetric.NewMetrics()
	md.CopyTo(cloned)
	go func() {
		if err := exporter.ExportMetrics(context.Background(), cloned); err != nil {
			log.Printf("[splunk-export] metrics export failed: %v", err)
		}
	}()
}
