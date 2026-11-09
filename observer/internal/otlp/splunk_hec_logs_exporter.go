package otlp

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/open-telemetry/opentelemetry-collector-contrib/exporter/splunkhecexporter"
	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/config/configmiddleware"
	"go.opentelemetry.io/collector/config/configopaque"
	"go.opentelemetry.io/collector/config/configoptional"
	"go.opentelemetry.io/collector/consumer/consumererror"
	"go.opentelemetry.io/collector/exporter"
	"go.opentelemetry.io/collector/exporter/exporterhelper"
	"go.opentelemetry.io/collector/extension/extensionmiddleware"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
	metricnoop "go.opentelemetry.io/otel/metric/noop"
	tracenoop "go.opentelemetry.io/otel/trace/noop"
	"go.uber.org/zap"
)

const defaultSplunkHECLogsExportTimeout = 10 * time.Second
const maxHECQueueBytes = 16 << 20

// LogsExporter forwards OTLP logs to an external logs backend.
type LogsExporter interface {
	ExportLogs(ctx context.Context, ld plog.Logs) error
}

type logsExportState interface {
	ExportEnabled() bool
}

// SplunkHECLogsExporterConfig configures optional Splunk Platform log
// forwarding over HTTP Event Collector.
type SplunkHECLogsExporterConfig struct {
	Enabled            bool
	ConnectionVerified bool
	// Endpoint is the full HEC collector URL, e.g.
	// https://host:8088/services/collector.
	Endpoint   string
	Token      string
	Index      string
	Source     string
	Sourcetype string
	// Channel is the X-Splunk-Request-Channel GUID. One is generated when
	// empty: Splunk rejects writes from ack-enabled tokens without it, and
	// ignores it for other tokens, so it is always sent.
	Channel string
	// InsecureSkipVerify allows self-signed Splunk certificates, which both
	// Splunk Cloud trial stacks and local Splunk Enterprise present.
	InsecureSkipVerify bool
	Timeout            time.Duration
}

// SplunkHECLogsExportStatus is a redacted snapshot of outbound Splunk Platform
// log forwarding state.
type SplunkHECLogsExportStatus struct {
	SessionOnly        bool `json:"sessionOnly,omitempty"`
	lastAttempt        time.Time
	Version            string `json:"version"`
	Source             string `json:"source"`
	Sourcetype         string `json:"sourcetype"`
	InsecureSkipVerify bool   `json:"insecureSkipVerify"`
	Enabled            bool   `json:"enabled"`
	Configured         bool   `json:"configured"`
	Connected          bool   `json:"connected"`
	Endpoint           string `json:"endpoint"`
	SearchURL          string `json:"searchURL,omitempty"`
	Index              string `json:"index"`
	TokenConfigured    bool   `json:"tokenConfigured"`
	Timeout            string `json:"timeout,omitempty"`
	ExportedBatches    uint64 `json:"exportedBatches"`
	ExportedRecords    uint64 `json:"exportedRecords"`
	FailedBatches      uint64 `json:"failedBatches"`
	LastExportError    string `json:"lastExportError,omitempty"`
	LastExportSuccess  string `json:"lastExportSuccess,omitempty"`
	LastHTTPStatus     int    `json:"lastHTTPStatus,omitempty"`
	LastHECCode        int    `json:"lastHECCode,omitempty"`
}

// SplunkHECLogsExporter posts OTLP logs to Splunk HEC as HEC JSON events.
type SplunkHECLogsExporter struct {
	config    SplunkHECLogsExporterConfig
	exp       exporter.Logs
	transport *http.Transport
	lifecycle context.Context
	stop      context.CancelFunc
	buffered  bool

	mu                sync.Mutex
	exportedBatches   uint64
	exportedRecords   uint64
	failedBatches     uint64
	lastExportError   string
	lastExportSuccess time.Time
	lastAttempt       time.Time
	lastHTTPStatus    int
	lastHECCode       int
}

type hecResponseMiddleware struct {
	component.StartFunc
	component.ShutdownFunc
	exporter *SplunkHECLogsExporter
}

type hecRoundTripperFunc func(*http.Request) (*http.Response, error)

func (f hecRoundTripperFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type hecExportHost struct {
	minimalHost
	middleware *hecResponseMiddleware
}

var hecMiddlewareID = component.MustNewID("obstudio_hec_status")

func (h hecExportHost) GetExtensions() map[component.ID]component.Component {
	return map[component.ID]component.Component{hecMiddlewareID: h.middleware}
}

func hecExporterSettings() exporter.Settings {
	return exporter.Settings{ID: component.MustNewID("splunk_hec"), TelemetrySettings: component.TelemetrySettings{
		Logger: zap.NewNop(), MeterProvider: metricnoop.NewMeterProvider(), TracerProvider: tracenoop.NewTracerProvider(),
	}}
}

func hecExporterConfig(config SplunkHECLogsExporterConfig) (*splunkhecexporter.Config, error) {
	parsed, err := url.Parse(config.Endpoint)
	if err != nil || parsed.Host == "" || parsed.User != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, fmt.Errorf("invalid splunk hec logs endpoint")
	}
	if parsed.Scheme == "http" && !strings.EqualFold(strings.TrimSuffix(parsed.Hostname(), "."), "localhost") && !net.ParseIP(parsed.Hostname()).IsLoopback() {
		return nil, fmt.Errorf("remote splunk hec logs endpoints require HTTPS")
	}
	if strings.TrimSpace(config.Token) == "" {
		return nil, fmt.Errorf("splunk hec logs token is empty")
	}
	cfg := splunkhecexporter.NewFactory().CreateDefaultConfig().(*splunkhecexporter.Config)
	cfg.ClientConfig.Endpoint = config.Endpoint
	cfg.ClientConfig.Timeout = config.Timeout
	cfg.ClientConfig.TLS.InsecureSkipVerify = config.InsecureSkipVerify
	cfg.ClientConfig.Middlewares = []configmiddleware.Config{{ID: hecMiddlewareID}}
	cfg.Token, cfg.Index, cfg.Source, cfg.SourceType = configopaque.String(config.Token), config.Index, config.Source, config.Sourcetype
	queue := exporterhelper.NewDefaultQueueConfig()
	queue.QueueSize = maxHECQueueBytes
	_ = queue.Sizer.UnmarshalText([]byte("bytes"))
	cfg.QueueSettings = configoptional.Some(queue)
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return cfg, nil
}

// ValidateSplunkHECLogsExporterConfig checks configuration without starting a component.
func ValidateSplunkHECLogsExporterConfig(config SplunkHECLogsExporterConfig) error {
	_, err := hecExporterConfig(normalizeSplunkHECLogsExporterConfig(config))
	return err
}

func NewSplunkHECLogsExporter(config SplunkHECLogsExporterConfig) (*SplunkHECLogsExporter, error) {
	return newSplunkHECLogsExporter(config, true)
}

func newSplunkHECLogsExporter(config SplunkHECLogsExporterConfig, buffered bool) (*SplunkHECLogsExporter, error) {
	config = normalizeSplunkHECLogsExporterConfig(config)
	cfg, err := hecExporterConfig(config)
	if err != nil {
		return nil, err
	}
	// Connection probes must wait for a response rather than queueing work.
	if !buffered {
		cfg.QueueSettings = configoptional.None[exporterhelper.QueueBatchConfig]()
		cfg.BackOffConfig.Enabled = false
	}
	lifecycle, stop := context.WithCancel(context.Background())
	e := &SplunkHECLogsExporter{config: config, lifecycle: lifecycle, stop: stop, buffered: buffered}
	exp, err := splunkhecexporter.NewFactory().CreateLogs(context.Background(), hecExporterSettings(), cfg)
	if err != nil {
		stop()
		return nil, fmt.Errorf("create Splunk HEC exporter: %w", err)
	}
	e.exp = exp
	if err := exp.Start(context.Background(), hecExportHost{middleware: &hecResponseMiddleware{exporter: e}}); err != nil {
		stop()
		_ = exp.Shutdown(context.Background())
		return nil, fmt.Errorf("start Splunk HEC exporter: %w", err)
	}
	return e, nil
}

func (e *SplunkHECLogsExporter) Shutdown(ctx context.Context) {
	if e == nil {
		return
	}
	e.stop()
	_ = e.exp.Shutdown(ctx)
	if e.transport != nil {
		e.transport.CloseIdleConnections()
	}
}

func (m *hecResponseMiddleware) GetHTTPRoundTripper(context.Context) (extensionmiddleware.WrapHTTPRoundTripperFunc, error) {
	return func(_ context.Context, next http.RoundTripper) (http.RoundTripper, error) {
		m.exporter.transport, _ = next.(*http.Transport)
		return hecRoundTripperFunc(func(req *http.Request) (*http.Response, error) { return m.exporter.observeHECResponse(next, req) }), nil
	}, nil
}

// The upstream sender owns HTTP and encoding. This middleware preserves Studio's
// strict connection probe, redacted errors and completed-send counters.
func (e *SplunkHECLogsExporter) observeHECResponse(next http.RoundTripper, req *http.Request) (*http.Response, error) {
	if e.lifecycle.Err() != nil {
		return nil, consumererror.NewPermanent(context.Canceled)
	}
	ctx, cancel := context.WithCancel(req.Context())
	stop := context.AfterFunc(e.lifecycle, cancel)
	defer stop()
	defer cancel()
	req = req.Clone(ctx)
	req.Header.Set("Authorization", "Splunk "+e.config.Token)
	req.Header.Set("X-Splunk-Request-Channel", e.config.Channel)
	response, err := next.RoundTrip(req)
	if err != nil {
		if e.lifecycle.Err() != nil {
			return nil, consumererror.NewPermanent(context.Canceled)
		}
		err = errors.New(sanitizeExportErrorString(err.Error(), e.config.Token))
		e.recordExport(err, 0, 0, 0)
		return nil, err
	}
	body, readErr := io.ReadAll(io.LimitReader(response.Body, 4097))
	_ = response.Body.Close()
	if readErr != nil && e.lifecycle.Err() != nil {
		return nil, consumererror.NewPermanent(context.Canceled)
	}
	if readErr != nil || len(body) > 4096 {
		err := errors.New("HEC response body was incomplete or exceeded the size limit")
		e.recordExport(err, 0, response.StatusCode, 0)
		if response.StatusCode >= 200 && response.StatusCode < 400 {
			return nil, consumererror.NewPermanent(err)
		}
		response.Body = io.NopCloser(strings.NewReader(""))
		return response, nil
	}
	response.Body = io.NopCloser(bytes.NewReader(body))
	var result struct {
		Code               *int   `json:"code"`
		Text               string `json:"text"`
		InvalidEventNumber *int   `json:"invalid-event-number"`
	}
	parseErr := json.Unmarshal(body, &result)
	code := 0
	if result.Code != nil {
		code = *result.Code
	}
	if parseErr == nil && result.Code != nil && response.StatusCode >= 200 && response.StatusCode < 300 && (code == 0 || code == 24 || code == 25) {
		e.recordExport(nil, e.hecRequestRecords(req), 0, 0)
		return response, nil
	}
	message := "HEC request was not accepted"
	if parseErr == nil && result.Text != "" {
		message = sanitizeExportErrorString(strings.TrimSpace(result.Text), e.config.Token)
	}
	err = fmt.Errorf("splunk hec returned %d (code %d): %s", response.StatusCode, code, message)
	e.recordExport(err, 0, response.StatusCode, code)
	if response.StatusCode >= 200 && response.StatusCode < 400 {
		response.Body.Close()
		// The upstream HTTP classifier accepts all 2xx replies. Return HEC
		// failures to its retry sender without replaying a potentially accepted prefix.
		if response.StatusCode < 300 && parseErr == nil && result.Code != nil && (result.InvalidEventNumber == nil || *result.InvalidEventNumber == 0) && (code == 8 || code == 9) {
			return nil, err
		}
		return nil, consumererror.NewPermanent(err)
	}
	return response, nil
}

func (e *SplunkHECLogsExporter) hecRequestRecords(req *http.Request) int {
	if req.GetBody == nil {
		return 0
	}
	body, err := req.GetBody()
	if err != nil {
		return 0
	}
	defer body.Close()
	var reader io.Reader = body
	if req.Header.Get("Content-Encoding") == "gzip" {
		zipped, err := gzip.NewReader(body)
		if err != nil {
			return 0
		}
		defer zipped.Close()
		reader = zipped
	}
	decoder := json.NewDecoder(reader)
	count := 0
	for {
		var event struct{}
		if err := decoder.Decode(&event); err != nil {
			return count
		}
		count++
	}
}

func normalizeSplunkHECLogsExporterConfig(config SplunkHECLogsExporterConfig) SplunkHECLogsExporterConfig {
	config.Endpoint = strings.TrimSpace(config.Endpoint)
	config.Token = strings.TrimSpace(config.Token)
	config.Index = strings.TrimSpace(config.Index)
	config.Source = strings.TrimSpace(config.Source)
	config.Sourcetype = strings.TrimSpace(config.Sourcetype)
	config.Channel = strings.TrimSpace(config.Channel)
	if config.Channel == "" {
		config.Channel = newRequestChannel()
	}
	if config.Timeout <= 0 {
		config.Timeout = defaultSplunkHECLogsExportTimeout
	}
	return config
}

// newRequestChannel returns a random RFC 4122 version 4 UUID.
func newRequestChannel() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "00000000-0000-4000-8000-000000000000"
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	h := hex.EncodeToString(b[:])
	return fmt.Sprintf("%s-%s-%s-%s-%s", h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])
}

func (e *SplunkHECLogsExporter) ExportEnabled() bool {
	return e != nil && e.config.Enabled
}

func (e *SplunkHECLogsExporter) Status() SplunkHECLogsExportStatus {
	if e == nil {
		return SplunkHECLogsExportStatus{}
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	status := SplunkHECLogsExportStatus{
		lastAttempt:     e.lastAttempt,
		Enabled:         e.config.Enabled,
		Configured:      e.config.Endpoint != "" && e.config.Token != "",
		Endpoint:        e.config.Endpoint,
		SearchURL:       splunkPlatformSearchURL(e.config.Endpoint, e.config.Index),
		Index:           e.config.Index,
		TokenConfigured: e.config.Token != "",
		Timeout:         e.config.Timeout.String(),
		ExportedBatches: e.exportedBatches,
		ExportedRecords: e.exportedRecords,
		FailedBatches:   e.failedBatches,
		LastExportError: e.lastExportError,
		LastHTTPStatus:  e.lastHTTPStatus,
		LastHECCode:     e.lastHECCode,
	}
	if !e.lastExportSuccess.IsZero() {
		status.LastExportSuccess = e.lastExportSuccess.UTC().Format(time.RFC3339)
	}
	return status
}

// ExportLogs submits logs to the configured Collector component.
func (e *SplunkHECLogsExporter) ExportLogs(ctx context.Context, logs plog.Logs) error {
	if e == nil || logs.LogRecordCount() == 0 {
		return nil
	}
	if err := e.exp.ConsumeLogs(ctx, normalizeHECLogs(logs, e.config.Index)); err != nil {
		clean := errors.New(sanitizeExportErrorString(err.Error(), e.config.Token))
		if e.buffered {
			e.recordExport(clean, 0, 0, 0)
		}
		return clean
	}
	return nil
}

// TestConnection waits for a wire response before settings are committed.
func (e *SplunkHECLogsExporter) TestConnection(ctx context.Context, logs plog.Logs) error {
	probe, err := newSplunkHECLogsExporter(e.config, false)
	if err != nil {
		return err
	}
	defer probe.Shutdown(context.Background())
	err = probe.ExportLogs(ctx, logs)
	status := probe.Status()
	if status.LastExportError != "" {
		err = errors.New(status.LastExportError)
	}
	e.mu.Lock()
	e.exportedBatches += status.ExportedBatches
	e.exportedRecords += status.ExportedRecords
	e.failedBatches += status.FailedBatches
	e.lastExportSuccess, e.lastExportError = probe.lastExportSuccess, status.LastExportError
	e.lastHTTPStatus, e.lastHECCode = status.LastHTTPStatus, status.LastHECCode
	e.lastAttempt = status.lastAttempt
	e.mu.Unlock()
	return err
}

func (e *SplunkHECLogsExporter) recordExport(err error, records, httpStatus, hecCode int) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.lastHTTPStatus, e.lastHECCode = httpStatus, hecCode
	e.lastAttempt = time.Now()
	if err != nil {
		e.failedBatches++
		e.lastExportError = err.Error()
		return
	}
	e.exportedBatches++
	e.exportedRecords += uint64(records)
	e.lastExportSuccess, e.lastExportError = e.lastAttempt, ""
}

// Preserve attribute-only events and receipt timestamps before passing pdata
// to the upstream translator; never mutate the locally stored/caller data.
func normalizeHECLogs(logs plog.Logs, index string) plog.Logs {
	copy := plog.NewLogs()
	logs.CopyTo(copy)
	now := pcommon.NewTimestampFromTime(time.Now())
	for _, resource := range copy.ResourceLogs().All() {
		resource.Resource().Attributes().Remove("com.splunk.hec.token")
		if index != "" {
			resource.Resource().Attributes().Remove("com.splunk.index")
		}
		sanitizeHECMap(resource.Resource().Attributes())
		for _, scope := range resource.ScopeLogs().All() {
			for _, record := range scope.LogRecords().All() {
				if index != "" {
					record.Attributes().Remove("com.splunk.index")
				}
				sanitizeHECMap(record.Attributes())
				if record.Timestamp() == 0 && record.ObservedTimestamp() == 0 {
					record.SetObservedTimestamp(now)
				}
				if record.Body().AsString() == "" {
					_ = record.Body().SetEmptyMap().PutEmptyMap("attributes").FromRaw(record.Attributes().AsRaw())
				}
				sanitizeHECValue(record.Body())
				if record.Body().Type() != pcommon.ValueTypeStr && record.Body().Type() != pcommon.ValueTypeMap {
					record.Body().SetStr(record.Body().AsString())
				}
				if !record.TraceID().IsEmpty() {
					record.Attributes().PutStr("trace_id", traceIDStr(record.TraceID()))
				}
				if !record.SpanID().IsEmpty() {
					record.Attributes().PutStr("span_id", spanIDStr(record.SpanID()))
				}
			}
		}
	}
	return copy
}

func sanitizeHECMap(attrs pcommon.Map) {
	for _, value := range attrs.All() {
		sanitizeHECValue(value)
	}
}

func sanitizeHECValue(value pcommon.Value) {
	switch value.Type() {
	case pcommon.ValueTypeDouble:
		n := value.Double()
		if math.IsNaN(n) || math.IsInf(n, 0) {
			value.SetStr(strconv.FormatFloat(n, 'g', -1, 64))
		}
	case pcommon.ValueTypeMap:
		sanitizeHECMap(value.Map())
	case pcommon.ValueTypeSlice:
		for _, item := range value.Slice().All() {
			sanitizeHECValue(item)
		}
	}
}

func splunkPlatformSearchURL(endpoint, index string) string {
	endpointURL, err := url.Parse(endpoint)
	if err != nil || endpointURL.Scheme != "https" || endpointURL.User != nil || strings.TrimSpace(index) == "" {
		return ""
	}
	if port := endpointURL.Port(); port != "" && port != "443" && port != "8088" {
		return ""
	}
	host := strings.ToLower(endpointURL.Hostname())
	host = strings.TrimPrefix(strings.TrimPrefix(host, "http-inputs-"), "http-inputs.")
	stack := strings.TrimSuffix(host, ".splunkcloud.com")
	if stack == host || stack == "" || strings.Contains(stack, ".") {
		return ""
	}
	// Cloud has a known Web origin. Enterprise Web ports and reverse proxies
	// cannot be inferred from a HEC endpoint, so do not guess them.
	search := url.URL{Scheme: "https", Host: host, Path: "/en-US/app/search/search"}
	quotedIndex, _ := json.Marshal(index)
	query := url.Values{"q": {"search index=" + string(quotedIndex) + " earliest=-1h"}}
	search.RawQuery = query.Encode()
	return search.String()
}

func exportLogsAsync(exporter LogsExporter, ld plog.Logs) {
	if exporter == nil {
		return
	}
	if buffered, ok := exporter.(interface{ QueueLogs(plog.Logs) }); ok {
		buffered.QueueLogs(ld)
		return
	}
	if statefulExporter, ok := exporter.(logsExportState); ok && !statefulExporter.ExportEnabled() {
		return
	}
	if exp, ok := exporter.(*SplunkHECLogsExporter); ok {
		_ = exp.ExportLogs(context.Background(), ld)
		return
	}
	cloned := plog.NewLogs()
	ld.CopyTo(cloned)
	go func() {
		if err := exporter.ExportLogs(context.Background(), cloned); err != nil {
			log.Printf("[splunk-export] logs export failed: %v", err)
		}
	}()
}
