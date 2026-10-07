package otlp

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"mime"
	"net"
	"net/http"
	"regexp"
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
	"go.opentelemetry.io/collector/pdata/ptrace"
	"go.opentelemetry.io/collector/pdata/ptrace/ptraceotlp"
	metricnoop "go.opentelemetry.io/otel/metric/noop"
	tracenoop "go.opentelemetry.io/otel/trace/noop"
	"go.uber.org/zap"
)

const defaultSplunkTracesExportTimeout = 5 * time.Second
const splunkTracesOTLPPath = "/v2/trace/otlp"

// TracesExporter forwards OTLP traces to an external traces backend.
type TracesExporter interface {
	ExportTraces(ctx context.Context, td ptrace.Traces) error
}

// AgentTraceRoute is the standard AO SDK's request-scoped project/stream
// destination. It never changes the destination of another application's batch.
type AgentTraceRoute struct {
	ProjectID     string
	AgentStreamID string
}

// AgentTracesExporter forwards a batch to its SDK-supplied AO destination.
type AgentTracesExporter interface {
	ExportAgentTraces(context.Context, ptrace.Traces, AgentTraceRoute) (ptraceotlp.ExportResponse, error)
}

var agentTraceIDPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
var agentTraceRealmPattern = regexp.MustCompile(`^[a-z]{2,12}[0-9]+$`)
var agentTraceBearerPattern = regexp.MustCompile(`(?i)\bbearer[ \t]+[A-Za-z0-9._~+/-]+={0,2}`)

func agentTraceRoute(projectIDs, streamIDs []string) (AgentTraceRoute, error) {
	if len(projectIDs) == 0 && len(streamIDs) == 0 {
		return AgentTraceRoute{}, nil
	}
	if len(projectIDs) != 1 || len(streamIDs) != 1 ||
		!agentTraceIDPattern.MatchString(projectIDs[0]) || !agentTraceIDPattern.MatchString(streamIDs[0]) {
		return AgentTraceRoute{}, fmt.Errorf("invalid AO project/stream destination")
	}
	return AgentTraceRoute{ProjectID: projectIDs[0], AgentStreamID: streamIDs[0]}, nil
}

type tracesExportState interface {
	ExportEnabled() bool
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
	Enabled               bool                       `json:"enabled"`
	Configured            bool                       `json:"configured"`
	Realm                 string                     `json:"realm,omitempty"`
	Endpoints             []string                   `json:"endpoints,omitempty"`
	AccessTokenConfigured bool                       `json:"accessTokenConfigured"`
	AccessToken           string                     `json:"accessToken,omitempty"`
	Timeout               string                     `json:"timeout,omitempty"`
	ExportedBatches       uint64                     `json:"exportedBatches"`
	ExportedSpans         uint64                     `json:"exportedSpans"`
	FailedBatches         uint64                     `json:"failedBatches"`
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
	Shutdown(ctx context.Context)
}

// SplunkTracesExportController owns a live Splunk traces exporter and allows
// the control plane to inspect or replace it while the OTLP receivers keep
// using the same TracesExporter reference.
type SplunkTracesExportController struct {
	exportMu             sync.RWMutex
	mu                   sync.RWMutex
	config               SplunkTracesExporterConfig
	exporter             splunkTracesExporterRuntime
	lastExport           SplunkTracesExportAttempt
	hasLastExport        bool
	exportedBatches      uint64
	exportedSpans        uint64
	failedBatches        uint64
	agentTracesTransport http.RoundTripper
	connectionGeneration uint64
	agentRoutes          map[AgentTraceRoute]struct{}
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
	c.exportMu.Lock()
	c.mu.Lock()
	old := c.exporter
	normalized := normalizeSplunkTracesExporterConfig(config)
	connectionChanged := c.exporter == nil || c.config.Enabled != normalized.Enabled ||
		c.config.Realm != normalized.Realm || c.config.Endpoint != normalized.Endpoint ||
		c.config.AccessToken != normalized.AccessToken
	c.config = normalized
	c.exporter = exporter
	if connectionChanged {
		c.connectionGeneration++
		c.agentRoutes = nil
	}
	c.lastExport = SplunkTracesExportAttempt{}
	c.hasLastExport = false
	c.exportedBatches = 0
	c.exportedSpans = 0
	c.failedBatches = 0
	c.mu.Unlock()
	c.exportMu.Unlock()
	if old != nil {
		old.Shutdown(context.Background())
	}
	return nil
}

// Shutdown stops the active exporter component cleanly.
func (c *SplunkTracesExportController) Shutdown(ctx context.Context) {
	if c == nil {
		return
	}
	unlock, ok := lockRWMutexForShutdown(ctx, &c.exportMu)
	if !ok {
		return
	}
	c.mu.Lock()
	exp := c.exporter
	c.exporter = nil
	c.connectionGeneration++
	c.agentRoutes = nil
	c.mu.Unlock()
	unlock()
	if exp != nil {
		exp.Shutdown(ctx)
	}
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

// AgentConnectionSnapshot lets the resource proxy bind a resolved stream to
// the exact connection that produced it, including A-to-B-to-A transitions.
func (c *SplunkTracesExportController) AgentConnectionSnapshot() (SplunkTracesExporterConfig, uint64, bool) {
	if c == nil {
		return SplunkTracesExporterConfig{}, 0, false
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.config, c.connectionGeneration, c.config.Enabled && c.exporter != nil
}

// BindAgentTraceRoute records only stream IDs confirmed by a successful
// resource request against the same active cloud connection.
func (c *SplunkTracesExportController) BindAgentTraceRoute(route AgentTraceRoute, generation uint64) bool {
	if c == nil {
		return false
	}
	if _, err := agentTraceRoute([]string{route.ProjectID}, []string{route.AgentStreamID}); err != nil {
		return false
	}
	c.exportMu.RLock()
	defer c.exportMu.RUnlock()
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.config.Enabled || c.exporter == nil || generation != c.connectionGeneration {
		return false
	}
	if c.agentRoutes == nil {
		c.agentRoutes = make(map[AgentTraceRoute]struct{})
	}
	c.agentRoutes[normalizedAgentTraceRoute(route)] = struct{}{}
	return true
}

func normalizedAgentTraceRoute(route AgentTraceRoute) AgentTraceRoute {
	return AgentTraceRoute{ProjectID: strings.ToLower(route.ProjectID), AgentStreamID: strings.ToLower(route.AgentStreamID)}
}

// ExportEnabled reports whether exports can currently be forwarded without
// forcing receivers to clone batches when the controller is disabled.
func (c *SplunkTracesExportController) ExportEnabled() bool {
	if c == nil {
		return false
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.config.Enabled && c.exporter != nil
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
		ExportedBatches:       c.exportedBatches,
		ExportedSpans:         c.exportedSpans,
		FailedBatches:         c.failedBatches,
	}
	if c.config.Endpoint != "" {
		status.Endpoints = []string{c.config.Endpoint}
	} else if c.exporter != nil {
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
	c.exportMu.RLock()
	defer c.exportMu.RUnlock()
	c.mu.RLock()
	exporter := c.exporter
	c.mu.RUnlock()
	if exporter == nil {
		return nil
	}
	err := exporter.ExportTraces(ctx, td)
	c.recordExport(err, td.SpanCount())
	return err
}

// ExportAgentTraces uses the active cloud connection but preserves each SDK
// request's routing headers. Holding the export lock keeps a connection change
// from mixing credentials and endpoints while a batch is in flight.
func (c *SplunkTracesExportController) ExportAgentTraces(ctx context.Context, td ptrace.Traces, route AgentTraceRoute) (ptraceotlp.ExportResponse, error) {
	if _, err := agentTraceRoute([]string{route.ProjectID}, []string{route.AgentStreamID}); err != nil {
		return ptraceotlp.NewExportResponse(), err
	}
	if c == nil {
		return ptraceotlp.NewExportResponse(), fmt.Errorf("Splunk traces export is not configured")
	}
	c.exportMu.RLock()
	defer c.exportMu.RUnlock()
	c.mu.RLock()
	config := c.config
	configured := config.Enabled && c.exporter != nil
	transport := c.agentTracesTransport
	_, routeBound := c.agentRoutes[normalizedAgentTraceRoute(route)]
	c.mu.RUnlock()
	if !configured {
		return ptraceotlp.NewExportResponse(), fmt.Errorf("Splunk traces export is disabled or not configured")
	}
	if !routeBound {
		err := fmt.Errorf("AO project/stream route is unresolved for the active cloud connection")
		c.recordExport(err, td.SpanCount())
		return ptraceotlp.NewExportResponse(), err
	}
	response, err := exportAgentTraces(ctx, config, td, route, transport)
	rejected := response.PartialSuccess().RejectedSpans()
	if err == nil && rejected > 0 {
		c.recordAgentPartialExport(td.SpanCount(), rejected)
	} else {
		c.recordExport(err, td.SpanCount())
	}
	return response, err
}

func exportAgentTraces(ctx context.Context, config SplunkTracesExporterConfig, td ptrace.Traces, route AgentTraceRoute, transport http.RoundTripper) (ptraceotlp.ExportResponse, error) {
	response := ptraceotlp.NewExportResponse()
	if config.Endpoint != "" || !agentTraceRealmPattern.MatchString(config.Realm) || config.AccessToken == "" {
		return response, fmt.Errorf("agent trace forwarding requires a realm-based Studio cloud connection")
	}
	endpoint := fmt.Sprintf("https://ingest.%s.observability.splunkcloud.com%s", config.Realm, splunkTracesOTLPPath)
	body, err := (&ptrace.ProtoMarshaler{}).MarshalTraces(td)
	if err != nil {
		return response, fmt.Errorf("marshal agent traces: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return response, fmt.Errorf("create agent trace request")
	}
	req.Header.Set("Content-Type", "application/x-protobuf")
	req.Header.Set("X-SF-Token", config.AccessToken)
	req.Header.Set("projectid", route.ProjectID)
	req.Header.Set("logstreamid", route.AgentStreamID)
	client := &http.Client{
		Transport:     transport,
		Timeout:       effectiveSplunkTracesTimeout(config.Timeout),
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	resp, err := client.Do(req)
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) {
			return response, fmt.Errorf("agent trace delivery timed out")
		}
		var dnsError *net.DNSError
		if errors.As(err, &dnsError) {
			return response, fmt.Errorf("agent trace delivery DNS lookup failed")
		}
		return response, fmt.Errorf("agent trace delivery failed")
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return response, agentTraceCloudError(resp, config.AccessToken)
	}
	responseBody, err := io.ReadAll(io.LimitReader(resp.Body, (1<<20)+1))
	if err != nil || len(responseBody) > 1<<20 {
		return response, fmt.Errorf("invalid or oversized agent trace delivery response")
	}
	if len(responseBody) != 0 {
		contentType, _, _ := mime.ParseMediaType(resp.Header.Get("Content-Type"))
		switch contentType {
		case "application/x-protobuf":
			err = response.UnmarshalProto(responseBody)
		case "application/json":
			var fields map[string]json.RawMessage
			err = json.Unmarshal(responseBody, &fields)
			if err == nil && fields == nil {
				err = fmt.Errorf("response must be an OTLP object")
			}
			_, hasValid := fields["valid"]
			_, hasInvalid := fields["invalid"]
			if err == nil && (hasValid || hasInvalid) {
				response, err = splunkAgentTraceAcknowledgement(fields, td.SpanCount())
				if err != nil {
					return ptraceotlp.NewExportResponse(), fmt.Errorf("%w; %s", invalidAgentTraceResponse(resp, responseBody, config.AccessToken), err)
				}
			} else if err == nil {
				for key := range fields {
					if key != "partialSuccess" && key != "partial_success" {
						err = fmt.Errorf("unexpected OTLP response field")
					}
				}
				if err == nil {
					err = response.UnmarshalJSON(responseBody)
				}
			}
		default:
			err = fmt.Errorf("unsupported response encoding")
		}
		if err != nil {
			return ptraceotlp.NewExportResponse(), invalidAgentTraceResponse(resp, responseBody, config.AccessToken)
		}
	}
	partial := response.PartialSuccess()
	if partial.RejectedSpans() < 0 || partial.RejectedSpans() > int64(td.SpanCount()) {
		return ptraceotlp.NewExportResponse(), fmt.Errorf("invalid agent trace rejection count")
	}
	partial.SetErrorMessage(sanitizeExportErrorString(partial.ErrorMessage(), config.AccessToken))
	return response, nil
}

// Splunk AO's DiagnosticOTLPSpanExporter also recognizes the ingest JSON
// acknowledgement {"valid": N, "invalid": {...}}, including an omitted
// invalid field (official SDK test_exporter_diagnostics.py). Accept only an explicit,
// complete acknowledgement here; never silently acknowledge a rejected or
// ambiguous batch. The SDK exposes rejection categories, not a reliable OTLP
// rejected-span count, so do not invent partialSuccess counts from that map.
func splunkAgentTraceAcknowledgement(fields map[string]json.RawMessage, submitted int) (ptraceotlp.ExportResponse, error) {
	response := ptraceotlp.NewExportResponse()
	if fields["valid"] == nil {
		return response, errors.New("invalid Splunk AO acknowledgement fields")
	}
	for key := range fields {
		if key != "valid" && key != "invalid" {
			return response, errors.New("invalid Splunk AO acknowledgement fields")
		}
	}
	var valid int64
	if json.Unmarshal(fields["valid"], &valid) != nil || bytes.Equal(bytes.TrimSpace(fields["valid"]), []byte("null")) || valid < 0 {
		return response, errors.New("invalid Splunk AO valid count")
	}
	var invalid map[string]json.RawMessage
	if fields["invalid"] != nil && json.Unmarshal(fields["invalid"], &invalid) != nil {
		return response, errors.New("invalid Splunk AO rejection categories")
	}
	if len(invalid) != 0 || valid == 0 {
		return response, fmt.Errorf("Splunk AO acknowledged rejection (valid=%d; rejection categories=%d)", valid, len(invalid))
	}
	if valid != int64(submitted) {
		return response, fmt.Errorf("Splunk AO acknowledged a different span count (valid=%d; submitted=%d)", valid, submitted)
	}
	return response, nil
}

// Invalid-response diagnostics describe only the protocol shape and standard
// status fields. Never reflect arbitrary response bodies or header values: an
// intermediary can return HTML, credentials, or private payloads even on 2xx.
func invalidAgentTraceResponse(response *http.Response, body []byte, token string) error {
	contentType, _, _ := mime.ParseMediaType(response.Header.Get("Content-Type"))
	switch contentType {
	case "application/json", "application/x-protobuf", "text/plain", "text/html", "application/octet-stream", "":
	default:
		contentType = "other"
	}
	shape := "unrecognized"
	if bytes.Equal(bytes.TrimSpace(body), []byte("OK")) {
		shape = "literal-OK"
	} else if json.Valid(body) {
		shape = "JSON"
	}
	base := fmt.Sprintf("invalid agent trace delivery response (HTTP %d; content-type %q; %d bytes; shape %s)", response.StatusCode, contentType, len(body), shape)
	if contentType != "application/json" || len(body) > 4096 {
		return errors.New(base)
	}
	// Reuse the bounded, redacted standard error-field extraction without
	// exposing a nonstandard JSON payload or promoting it to an acknowledgement.
	diagnostic := &http.Response{StatusCode: response.StatusCode, Header: response.Header, Body: io.NopCloser(bytes.NewReader(body))}
	return fmt.Errorf("%s; %s", base, agentTraceCloudError(diagnostic, token))
}

func (c *SplunkTracesExportController) recordAgentPartialExport(spans int, rejected int64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.hasLastExport = true
	c.lastExport = SplunkTracesExportAttempt{Time: time.Now(), Success: false, Error: fmt.Sprintf("cloud rejected %d of %d agent spans", rejected, spans)}
	c.failedBatches++
	c.exportedSpans += uint64(int64(spans) - rejected)
}

func sanitizeExportErrorString(message, token string) string {
	if token != "" {
		message = strings.ReplaceAll(message, token, "[REDACTED]")
	}
	message = agentTraceBearerPattern.ReplaceAllString(message, "Bearer [REDACTED]")
	if len(message) > 4096 {
		message = message[:4096]
	}
	return strings.ToValidUTF8(message, "")
}

func agentTraceCloudError(response *http.Response, token string) error {
	base := fmt.Sprintf("agent trace delivery returned HTTP %d", response.StatusCode)
	body, err := io.ReadAll(io.LimitReader(response.Body, 4097))
	if err != nil || len(body) > 4096 {
		return fmt.Errorf("%s (error response unavailable or oversized)", base)
	}
	contentType, _, _ := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if contentType != "application/json" {
		return fmt.Errorf("%s (non-JSON error response, %d bytes)", base, len(body))
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(body, &fields) != nil {
		return fmt.Errorf("%s (invalid JSON error response)", base)
	}
	var details []string
	for _, name := range []string{"code", "message", "detail"} {
		var value string
		if field, ok := fields[name]; !ok || json.Unmarshal(field, &value) != nil {
			continue
		}
		value = strings.Join(strings.Fields(sanitizeExportErrorString(value, token)), " ")
		if len(value) > 512 {
			value = strings.ToValidUTF8(value[:512], "")
		}
		if value != "" {
			details = append(details, name+"="+value)
		}
	}
	if len(details) == 0 {
		return fmt.Errorf("%s (no standard JSON error detail)", base)
	}
	return fmt.Errorf("%s: %s", base, strings.Join(details, "; "))
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

func (c *SplunkTracesExportController) recordExport(err error, spans int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.hasLastExport = true
	c.lastExport = SplunkTracesExportAttempt{
		Time:    time.Now(),
		Success: err == nil,
	}
	if err != nil {
		c.failedBatches++
		c.lastExport.Error = sanitizeExportError(err, c.config.AccessToken)
		return
	}
	c.exportedBatches++
	if spans > 0 {
		c.exportedSpans += uint64(spans)
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
// the Collector otlphttpexporter with X-SF-Token auth and queue disabled for
// synchronous delivery.
type SplunkTracesExporter struct {
	endpoint string
	exp      exporter.Traces
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
	if _, err := normalizeSplunkMetricsEndpoint(endpoint); err != nil {
		return nil, fmt.Errorf("invalid Splunk traces endpoint: %w", err)
	}
	token := strings.TrimSpace(config.AccessToken)
	if token == "" {
		return nil, fmt.Errorf("splunk traces export requires SPLUNK_ACCESS_TOKEN")
	}

	factory := otlphttpexporter.NewFactory()
	cfg := factory.CreateDefaultConfig().(*otlphttpexporter.Config)
	cfg.TracesEndpoint = endpoint
	cfg.ClientConfig = confighttp.ClientConfig{
		Timeout: effectiveSplunkTracesTimeout(config.Timeout),
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
	exp, err := factory.CreateTraces(context.Background(), set, cfg)
	if err != nil {
		return nil, fmt.Errorf("create Splunk traces exporter: %w", err)
	}
	if err := exp.Start(context.Background(), minimalHost{}); err != nil {
		_ = exp.Shutdown(context.Background())
		return nil, fmt.Errorf("start Splunk traces exporter: %w", err)
	}
	return &SplunkTracesExporter{endpoint: endpoint, exp: exp}, nil
}

// Endpoint returns the configured non-secret export endpoint.
func (e *SplunkTracesExporter) Endpoint() string {
	if e == nil {
		return ""
	}
	return e.endpoint
}

// Endpoints returns all configured non-secret export endpoints.
func (e *SplunkTracesExporter) Endpoints() []string {
	if e == nil {
		return nil
	}
	return []string{e.endpoint}
}

// ExportTraces forwards traces to the Splunk ingest endpoint synchronously.
func (e *SplunkTracesExporter) ExportTraces(ctx context.Context, td ptrace.Traces) error {
	if e == nil {
		return nil
	}
	return e.exp.ConsumeTraces(ctx, td)
}

// Shutdown stops the underlying exporter component.
func (e *SplunkTracesExporter) Shutdown(ctx context.Context) {
	if e == nil {
		return
	}
	if err := e.exp.Shutdown(ctx); err != nil {
		log.Printf("[splunk-traces] shutdown error: %v", err)
	}
}

// exportTracesAsync forwards td to exporter in a background goroutine.
// One goroutine is fired per batch with no concurrency cap — intentional for
// a dev-tool workload where batches are infrequent and ingest latency is low.
func exportTracesAsync(exporter TracesExporter, td ptrace.Traces) {
	if exporter == nil {
		return
	}
	if statefulExporter, ok := exporter.(tracesExportState); ok && !statefulExporter.ExportEnabled() {
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
