package otlp

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/pmetric"
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
	defer c.mu.Unlock()
	c.config = normalizeSplunkMetricsExporterConfig(config)
	c.exporter = exporter
	c.lastExport = SplunkMetricsExportAttempt{}
	c.hasLastExport = false
	return nil
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
		c.lastExport.Error = err.Error()
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

func newConfiguredSplunkMetricsExporter(config SplunkMetricsExporterConfig) (splunkMetricsExporterRuntime, error) {
	if !config.Enabled {
		return nil, nil
	}
	return NewSplunkMetricsExporter(config)
}

// splunkEndpoint is a named outbound export target shared by metrics and traces exporters.
type splunkEndpoint struct {
	name string
	url  string
}

// SplunkMetricsExporter forwards metrics to Splunk Observability Cloud using
// OTLP/HTTP protobuf and an org access token in the X-SF-Token header.
type SplunkMetricsExporter struct {
	endpoints   []splunkEndpoint
	accessToken string
	timeout     time.Duration
	client      *http.Client
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
	primaryEndpoint, err := normalizeSplunkMetricsEndpoint(endpoint)
	if err != nil {
		return nil, fmt.Errorf("invalid Splunk metrics endpoint: %w", err)
	}
	token := strings.TrimSpace(config.AccessToken)
	if token == "" {
		return nil, fmt.Errorf("splunk metrics export requires SPLUNK_ACCESS_TOKEN")
	}
	timeout := effectiveSplunkMetricsTimeout(config.Timeout)
	endpoints := []splunkEndpoint{{name: "primary", url: primaryEndpoint}}
	return &SplunkMetricsExporter{
		endpoints:   endpoints,
		accessToken: token,
		timeout:     timeout,
		client:      &http.Client{Timeout: timeout},
	}, nil
}

// Endpoint returns the configured non-secret export endpoint.
func (e *SplunkMetricsExporter) Endpoint() string {
	if e == nil || len(e.endpoints) == 0 {
		return ""
	}
	return e.endpoints[0].url
}

// Endpoints returns all configured non-secret export endpoints.
func (e *SplunkMetricsExporter) Endpoints() []string {
	if e == nil {
		return nil
	}
	endpoints := make([]string, 0, len(e.endpoints))
	for _, endpoint := range e.endpoints {
		endpoints = append(endpoints, endpoint.url)
	}
	return endpoints
}

func (e *SplunkMetricsExporter) ExportMetrics(ctx context.Context, md pmetric.Metrics) error {
	if e == nil {
		return nil
	}
	body, err := (&pmetric.ProtoMarshaler{}).MarshalMetrics(md)
	if err != nil {
		return fmt.Errorf("marshal metrics: %w", err)
	}

	if len(e.endpoints) == 0 {
		return nil
	}
	return e.exportMetricsToEndpoint(ctx, e.endpoints[0], body)
}

func (e *SplunkMetricsExporter) exportMetricsToEndpoint(ctx context.Context, endpoint splunkEndpoint, body []byte) error {
	reqCtx, cancel := context.WithTimeout(ctx, e.timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, endpoint.url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-protobuf")
	req.Header.Set("X-SF-Token", e.accessToken)
	req.Header.Set("User-Agent", "obstudio-splunk-metrics-exporter")

	started := time.Now()
	resp, err := e.client.Do(req)
	if err != nil {
		return fmt.Errorf("post metrics: %w", err)
	}
	defer resp.Body.Close()
	duration := time.Since(started)
	log.Printf("[splunk-export] response endpoint=%s status=%d duration=%s", endpoint.name, resp.StatusCode, duration.Round(time.Millisecond))
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return nil
	}
	responseBody, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
	if len(responseBody) == 0 {
		return fmt.Errorf("splunk metrics export returned status %d", resp.StatusCode)
	}
	return fmt.Errorf("splunk metrics export returned status %d: %s", resp.StatusCode, redactSensitiveText(strings.TrimSpace(string(responseBody)), e.accessToken))
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

func redactSensitiveText(text string, secrets ...string) string {
	redacted := text
	for _, secret := range secrets {
		if strings.TrimSpace(secret) != "" {
			redacted = strings.ReplaceAll(redacted, secret, "<redacted>")
		}
	}
	for _, marker := range []string{"authorization", "x-sf-token", "token", "secret", "password"} {
		redacted = redactKeyedSecret(redacted, marker)
	}
	return redacted
}

func redactKeyedSecret(text, marker string) string {
	lower := strings.ToLower(text)
	searchStart := 0
	for {
		idx := strings.Index(lower[searchStart:], marker)
		if idx < 0 {
			return text
		}
		idx += searchStart
		valueStart := idx + len(marker)
		for valueStart < len(text) && (text[valueStart] == ' ' || text[valueStart] == ':' || text[valueStart] == '=') {
			valueStart++
		}
		valueEnd := valueStart
		for valueEnd < len(text) && !strings.ContainsRune(" \t\r\n,;\"'}", rune(text[valueEnd])) {
			valueEnd++
		}
		if valueEnd > valueStart {
			text = text[:valueStart] + "<redacted>" + text[valueEnd:]
			lower = strings.ToLower(text)
			searchStart = valueStart + len("<redacted>")
			continue
		}
		searchStart = valueStart
	}
}

func redactHeaderValue(key, value string) string {
	lowerKey := strings.ToLower(key)
	switch {
	case strings.Contains(lowerKey, "authorization"),
		strings.Contains(lowerKey, "cookie"),
		strings.Contains(lowerKey, "key"),
		strings.Contains(lowerKey, "secret"),
		strings.Contains(lowerKey, "token"):
		return fmt.Sprintf("<redacted len=%d>", len(value))
	default:
		return value
	}
}

func metricExportSummary(md pmetric.Metrics) string {
	resourceMetrics := md.ResourceMetrics().Len()
	scopeMetrics := 0
	metrics := 0
	dataPoints := 0
	names := make([]string, 0, 6)
	for i := 0; i < md.ResourceMetrics().Len(); i++ {
		resourceMetric := md.ResourceMetrics().At(i)
		scopeMetrics += resourceMetric.ScopeMetrics().Len()
		for j := 0; j < resourceMetric.ScopeMetrics().Len(); j++ {
			scopeMetric := resourceMetric.ScopeMetrics().At(j)
			metrics += scopeMetric.Metrics().Len()
			for k := 0; k < scopeMetric.Metrics().Len(); k++ {
				metric := scopeMetric.Metrics().At(k)
				if len(names) < 6 {
					names = append(names, metric.Name())
				}
				dataPoints += metricDataPointCount(metric)
			}
		}
	}
	return fmt.Sprintf(
		"resourceMetrics=%d scopeMetrics=%d metrics=%d dataPoints=%d names=%s",
		resourceMetrics,
		scopeMetrics,
		metrics,
		dataPoints,
		strings.Join(names, ","),
	)
}

func metricDataPointCount(metric pmetric.Metric) int {
	switch metric.Type() {
	case pmetric.MetricTypeGauge:
		return metric.Gauge().DataPoints().Len()
	case pmetric.MetricTypeSum:
		return metric.Sum().DataPoints().Len()
	case pmetric.MetricTypeHistogram:
		return metric.Histogram().DataPoints().Len()
	case pmetric.MetricTypeExponentialHistogram:
		return metric.ExponentialHistogram().DataPoints().Len()
	case pmetric.MetricTypeSummary:
		return metric.Summary().DataPoints().Len()
	default:
		return 0
	}
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
