package otlp

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

const defaultSplunkTracesExportTimeout = 5 * time.Second
const splunkTracesOTLPPath = "/v2/trace/otlp"

// TracesExporter forwards OTLP traces to an external traces backend.
type TracesExporter interface {
	ExportTraces(ctx context.Context, td ptrace.Traces) error
}

// SplunkTracesExporterConfig configures optional Splunk Observability Cloud
// trace forwarding.
type SplunkTracesExporterConfig struct {
	Enabled     bool
	Realm       string
	Endpoint    string
	AccessToken string
	Timeout     time.Duration
}

// SplunkTracesExportStatus is a redacted snapshot of outbound Splunk traces
// forwarding state.
type SplunkTracesExportStatus struct {
	Enabled               bool                        `json:"enabled"`
	Configured            bool                        `json:"configured"`
	Realm                 string                      `json:"realm,omitempty"`
	Endpoints             []string                    `json:"endpoints,omitempty"`
	AccessTokenConfigured bool                        `json:"accessTokenConfigured"`
	AccessToken           string                      `json:"accessToken,omitempty"`
	Timeout               string                      `json:"timeout,omitempty"`
	LastExport            *SplunkTracesExportAttempt `json:"lastExport,omitempty"`
}

// SplunkTracesExportAttempt records the latest outbound export result without
// carrying request secrets.
type SplunkTracesExportAttempt struct {
	Time    time.Time `json:"time"`
	Success bool      `json:"success"`
	Error   string    `json:"error,omitempty"`
}

type splunkTracesExporterRuntime interface {
	TracesExporter
	Endpoints() []string
}

// SplunkTracesExportController owns a live Splunk traces exporter and allows
// the control plane to inspect or replace it while the OTLP receivers keep
// using the same TracesExporter reference.
type SplunkTracesExportController struct {
	mu            sync.RWMutex
	config        SplunkTracesExporterConfig
	exporter      splunkTracesExporterRuntime
	lastExport    SplunkTracesExportAttempt
	hasLastExport bool
}

// NewSplunkTracesExportController creates a runtime controller. Disabled
// configs are valid and simply produce a no-op exporter.
func NewSplunkTracesExportController(config SplunkTracesExporterConfig) (*SplunkTracesExportController, error) {
	controller := &SplunkTracesExportController{}
	if err := controller.Configure(config); err != nil {
		return nil, err
	}
	return controller, nil
}

// Configure replaces the live exporter after validating the supplied config.
func (c *SplunkTracesExportController) Configure(config SplunkTracesExporterConfig) error {
	exporter, err := newConfiguredSplunkTracesExporter(config)
	if err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.config = normalizeSplunkTracesExporterConfig(config)
	c.exporter = exporter
	c.lastExport = SplunkTracesExportAttempt{}
	c.hasLastExport = false
	return nil
}

// Config returns the current config. Callers must not log or return the access
// token from this value.
func (c *SplunkTracesExportController) Config() SplunkTracesExporterConfig {
	if c == nil {
		return SplunkTracesExporterConfig{}
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.config
}

// Status returns a redacted snapshot of the controller state.
func (c *SplunkTracesExportController) Status() SplunkTracesExportStatus {
	if c == nil {
		return SplunkTracesExportStatus{}
	}
	c.mu.RLock()
	defer c.mu.RUnlock()

	status := SplunkTracesExportStatus{
		Enabled:               c.config.Enabled,
		Configured:            c.exporter != nil,
		Realm:                 c.config.Realm,
		AccessTokenConfigured: c.config.AccessToken != "",
		AccessToken:           redactConfiguredToken(c.config.AccessToken),
		Timeout:               effectiveSplunkTracesTimeout(c.config.Timeout).String(),
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

// ExportTraces forwards traces through the current live exporter.
func (c *SplunkTracesExportController) ExportTraces(ctx context.Context, td ptrace.Traces) error {
	if c == nil {
		return nil
	}
	c.mu.RLock()
	exporter := c.exporter
	c.mu.RUnlock()
	if exporter == nil {
		return nil
	}
	err := exporter.ExportTraces(ctx, td)
	c.recordExport(err)
	return err
}

// TestConnection sends a single canary span through the current exporter and
// returns the updated redacted status.
func (c *SplunkTracesExportController) TestConnection(ctx context.Context) (SplunkTracesExportStatus, error) {
	if c == nil {
		return SplunkTracesExportStatus{}, fmt.Errorf("Splunk traces export controller is not available")
	}
	c.mu.RLock()
	configured := c.exporter != nil
	c.mu.RUnlock()
	if !configured {
		return c.Status(), fmt.Errorf("Splunk traces export is disabled or not configured")
	}
	err := c.ExportTraces(ctx, splunkTracesCanary())
	return c.Status(), err
}

func (c *SplunkTracesExportController) recordExport(err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.hasLastExport = true
	c.lastExport = SplunkTracesExportAttempt{
		Time:    time.Now(),
		Success: err == nil,
	}
	if err != nil {
		c.lastExport.Error = err.Error()
	}
}

func normalizeSplunkTracesExporterConfig(config SplunkTracesExporterConfig) SplunkTracesExporterConfig {
	config.Realm = strings.TrimSpace(config.Realm)
	config.Endpoint = strings.TrimSpace(config.Endpoint)
	config.AccessToken = strings.TrimSpace(config.AccessToken)
	config.Timeout = effectiveSplunkTracesTimeout(config.Timeout)
	return config
}

func effectiveSplunkTracesTimeout(timeout time.Duration) time.Duration {
	if timeout <= 0 {
		return defaultSplunkTracesExportTimeout
	}
	return timeout
}

func newConfiguredSplunkTracesExporter(config SplunkTracesExporterConfig) (splunkTracesExporterRuntime, error) {
	if !config.Enabled {
		return nil, nil
	}
	return NewSplunkTracesExporter(config)
}

// SplunkTracesExporter forwards traces to Splunk Observability Cloud using
// OTLP/HTTP protobuf and an org access token in the X-SF-Token header.
type SplunkTracesExporter struct {
	endpoints   []splunkEndpoint
	accessToken string
	timeout     time.Duration
	client      *http.Client
}

// NewSplunkTracesExporter creates a Splunk traces exporter when enabled. It
// returns nil when the config is disabled.
func NewSplunkTracesExporter(config SplunkTracesExporterConfig) (*SplunkTracesExporter, error) {
	if !config.Enabled {
		return nil, nil
	}
	endpoint := strings.TrimSpace(config.Endpoint)
	if endpoint == "" {
		realm := strings.TrimSpace(config.Realm)
		if realm == "" {
			return nil, fmt.Errorf("splunk traces export requires SPLUNK_REALM or OBSTUDIO_SPLUNK_TRACES_ENDPOINT")
		}
		endpoint = fmt.Sprintf("https://ingest.%s.observability.splunkcloud.com%s", realm, splunkTracesOTLPPath)
	}
	primaryEndpoint, err := normalizeSplunkMetricsEndpoint(endpoint)
	if err != nil {
		return nil, fmt.Errorf("invalid Splunk traces endpoint: %w", err)
	}
	token := strings.TrimSpace(config.AccessToken)
	if token == "" {
		return nil, fmt.Errorf("splunk traces export requires SPLUNK_ACCESS_TOKEN")
	}
	timeout := effectiveSplunkTracesTimeout(config.Timeout)
	return &SplunkTracesExporter{
		endpoints:   []splunkEndpoint{{name: "primary", url: primaryEndpoint}},
		accessToken: token,
		timeout:     timeout,
		client:      &http.Client{Timeout: timeout},
	}, nil
}

// Endpoint returns the configured non-secret export endpoint.
func (e *SplunkTracesExporter) Endpoint() string {
	if e == nil || len(e.endpoints) == 0 {
		return ""
	}
	return e.endpoints[0].url
}

// Endpoints returns all configured non-secret export endpoints.
func (e *SplunkTracesExporter) Endpoints() []string {
	if e == nil {
		return nil
	}
	endpoints := make([]string, 0, len(e.endpoints))
	for _, ep := range e.endpoints {
		endpoints = append(endpoints, ep.url)
	}
	return endpoints
}

// ExportTraces serializes and POSTs the traces to Splunk ingest.
func (e *SplunkTracesExporter) ExportTraces(ctx context.Context, td ptrace.Traces) error {
	if e == nil {
		return nil
	}
	body, err := (&ptrace.ProtoMarshaler{}).MarshalTraces(td)
	if err != nil {
		return fmt.Errorf("marshal traces: %w", err)
	}
	if len(e.endpoints) == 0 {
		return nil
	}
	return e.exportTracesToEndpoint(ctx, e.endpoints[0], body)
}

func (e *SplunkTracesExporter) exportTracesToEndpoint(ctx context.Context, endpoint splunkEndpoint, body []byte) error {
	reqCtx, cancel := context.WithTimeout(ctx, e.timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, endpoint.url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-protobuf")
	req.Header.Set("X-SF-Token", e.accessToken)
	req.Header.Set("User-Agent", "obstudio-splunk-traces-exporter")

	started := time.Now()
	resp, err := e.client.Do(req)
	if err != nil {
		return fmt.Errorf("post traces: %w", err)
	}
	defer resp.Body.Close()
	duration := time.Since(started)
	log.Printf("[splunk-traces] response endpoint=%s status=%d duration=%s", endpoint.name, resp.StatusCode, duration.Round(time.Millisecond))
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return nil
	}
	responseBody, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
	if len(responseBody) == 0 {
		return fmt.Errorf("splunk traces export returned status %d", resp.StatusCode)
	}
	return fmt.Errorf("splunk traces export returned status %d: %s", resp.StatusCode, redactSensitiveText(strings.TrimSpace(string(responseBody)), e.accessToken))
}

// exportTracesAsync forwards td to exporter in a background goroutine.
// One goroutine is fired per batch with no concurrency cap — intentional for
// a dev-tool workload where batches are infrequent and ingest latency is low.
func exportTracesAsync(exporter TracesExporter, td ptrace.Traces) {
	if exporter == nil {
		return
	}
	cloned := ptrace.NewTraces()
	td.CopyTo(cloned)
	go func() {
		if err := exporter.ExportTraces(context.Background(), cloned); err != nil {
			log.Printf("[splunk-traces] traces export failed: %v", err)
		}
	}()
}

// splunkTracesCanary builds a single minimal span for connectivity testing.
func splunkTracesCanary() ptrace.Traces {
	td := ptrace.NewTraces()
	rs := td.ResourceSpans().AppendEmpty()
	rs.Resource().Attributes().PutStr("service.name", "obstudio")
	rs.Resource().Attributes().PutStr("telemetry.source", "obstudio")
	ss := rs.ScopeSpans().AppendEmpty()
	ss.Scope().SetName("obstudio.splunk_traces_exporter")
	ss.Scope().SetVersion("0.1.0")
	span := ss.Spans().AppendEmpty()
	span.SetName("obstudio.splunk_exporter.test")
	span.SetTraceID([16]byte{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16})
	span.SetSpanID([8]byte{1, 2, 3, 4, 5, 6, 7, 8})
	now := pcommon.NewTimestampFromTime(time.Now())
	span.SetStartTimestamp(now)
	span.SetEndTimestamp(now)
	return td
}

