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
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
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
	"go.uber.org/multierr"
	"go.uber.org/zap"
)

const defaultSplunkHECLogsExportTimeout = 10 * time.Second

const (
	splunkIndexAttribute      = "com.splunk.index"
	splunkSourceAttribute     = "com.splunk.source"
	splunkSourcetypeAttribute = "com.splunk.sourcetype"
	hostNameAttribute         = "host.name"
	severityTextField         = "otel.log.severity.text"
	severityNumberField       = "otel.log.severity.number"
)

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
	Token              string `json:"token,omitempty"`
	Timeout            string `json:"timeout,omitempty"`
	ExportedBatches    uint64 `json:"exportedBatches"`
	ExportedRecords    uint64 `json:"exportedRecords"`
	FailedBatches      uint64 `json:"failedBatches"`
	LastExportError    string `json:"lastExportError,omitempty"`
	LastExportSuccess  string `json:"lastExportSuccess,omitempty"`
	LastHTTPStatus     int    `json:"lastHTTPStatus,omitempty"`
	LastHECCode        int    `json:"lastHECCode,omitempty"`
	QueuedRecords      int    `json:"queuedRecords"`
	DroppedRecords     uint64 `json:"droppedRecords"`
}

// SplunkHECLogsExporter posts OTLP logs to Splunk HEC as HEC JSON events.
type SplunkHECLogsExporter struct {
	config    SplunkHECLogsExporterConfig
	exp       exporter.Logs
	transport *http.Transport

	mu                sync.Mutex
	exportedBatches   uint64
	exportedRecords   uint64
	failedBatches     uint64
	lastExportError   string
	lastExportSuccess time.Time
	lastHTTPStatus    int
	lastHECCode       int
}

type hecResponseMiddleware struct {
	component.StartFunc
	component.ShutdownFunc
	exporter *SplunkHECLogsExporter
}

type hecAttemptKey struct{}
type hecAttempt struct {
	requests   atomic.Int32
	retryAfter atomic.Int64
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
	if strings.TrimSpace(config.Token) == "" {
		return nil, fmt.Errorf("splunk hec logs token is empty")
	}
	cfg := splunkhecexporter.NewFactory().CreateDefaultConfig().(*splunkhecexporter.Config)
	cfg.ClientConfig.Endpoint = config.Endpoint
	cfg.ClientConfig.Timeout = config.Timeout
	cfg.ClientConfig.TLS.InsecureSkipVerify = config.InsecureSkipVerify
	cfg.ClientConfig.Middlewares = []configmiddleware.Config{{ID: hecMiddlewareID}}
	cfg.Token, cfg.Index, cfg.Source, cfg.SourceType = configopaque.String(config.Token), config.Index, config.Source, config.Sourcetype
	// One stable Collector helper queue lives in the Studio controller so edits do not discard it.
	cfg.QueueSettings = configoptional.None[exporterhelper.QueueBatchConfig]()
	cfg.BackOffConfig.Enabled = false
	cfg.MaxContentLengthLogs, cfg.MaxEventSize = 0, maxQueuedHECBytes
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
	config = normalizeSplunkHECLogsExporterConfig(config)
	cfg, err := hecExporterConfig(config)
	if err != nil {
		return nil, err
	}
	e := &SplunkHECLogsExporter{config: config}
	exp, err := splunkhecexporter.NewFactory().CreateLogs(context.Background(), hecExporterSettings(), cfg)
	if err != nil {
		return nil, fmt.Errorf("create Splunk HEC exporter: %w", err)
	}
	e.exp = exp
	if err := exp.Start(context.Background(), hecExportHost{middleware: &hecResponseMiddleware{exporter: e}}); err != nil {
		_ = exp.Shutdown(context.Background())
		return nil, fmt.Errorf("start Splunk HEC exporter: %w", err)
	}
	return e, nil
}

func (e *SplunkHECLogsExporter) Shutdown(ctx context.Context) {
	if e == nil {
		return
	}
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
	if attempt, ok := req.Context().Value(hecAttemptKey{}).(*hecAttempt); ok {
		attempt.requests.Add(1)
	}
	req.Header.Set("Authorization", "Splunk "+e.config.Token)
	req.Header.Set("X-Splunk-Request-Channel", e.config.Channel)
	response, err := next.RoundTrip(req)
	if err != nil {
		if req.Context().Err() == context.Canceled {
			return nil, req.Context().Err()
		}
		err = errors.New(sanitizeExportErrorString(err.Error(), e.config.Token))
		e.recordExport(err, 0)
		return nil, err
	}
	body, readErr := io.ReadAll(io.LimitReader(response.Body, 4097))
	_ = response.Body.Close()
	if req.Context().Err() == context.Canceled {
		return nil, req.Context().Err()
	}
	var result struct {
		Code *int `json:"code"`
	}
	parseErr := json.Unmarshal(body, &result)
	code := 0
	if result.Code != nil {
		code = *result.Code
	}
	if readErr != nil || len(body) > 4096 || parseErr != nil || result.Code == nil || code != 0 || response.StatusCode < 200 || response.StatusCode >= 300 {
		err = fmt.Errorf("splunk hec returned %d (code %d): %s", response.StatusCode, code, sanitizeExportErrorString(strings.TrimSpace(string(body)), e.config.Token))
		e.recordExport(err, 0, response.StatusCode, code)
		permanent := response.StatusCode >= 300 && response.StatusCode < 400 || response.StatusCode == 413
		if response.StatusCode == 400 || response.StatusCode >= 200 && response.StatusCode < 300 {
			switch code {
			case 6, 12, 13:
				permanent = true
			case 7:
				_, override := e.hecRequestRecords(req)
				permanent = override
			}
		}
		if permanent {
			return nil, consumererror.NewPermanent(err)
		}
		if response.StatusCode == 429 || response.StatusCode == 503 {
			retryAfter := response.Header.Get("Retry-After")
			seconds, _ := strconv.Atoi(retryAfter)
			delay := time.Duration(seconds) * time.Second
			if retryAt, err := http.ParseTime(retryAfter); err == nil {
				delay = max(0, time.Until(retryAt))
			}
			if attempt, ok := req.Context().Value(hecAttemptKey{}).(*hecAttempt); ok {
				for previous := attempt.retryAfter.Load(); int64(delay) > previous; previous = attempt.retryAfter.Load() {
					if attempt.retryAfter.CompareAndSwap(previous, int64(delay)) {
						break
					}
				}
			}
			return nil, exporterhelper.NewThrottleRetry(err, delay)
		}
		return nil, err
	}
	records, _ := e.hecRequestRecords(req)
	e.recordExport(nil, records)
	response.Body = io.NopCloser(bytes.NewReader(body))
	return response, nil
}

func (e *SplunkHECLogsExporter) hecRequestRecords(req *http.Request) (int, bool) {
	if req.GetBody == nil {
		return 0, false
	}
	body, err := req.GetBody()
	if err != nil {
		return 0, false
	}
	defer body.Close()
	var reader io.Reader = body
	if req.Header.Get("Content-Encoding") == "gzip" {
		zipped, err := gzip.NewReader(body)
		if err != nil {
			return 0, false
		}
		defer zipped.Close()
		reader = zipped
	}
	decoder := json.NewDecoder(reader)
	count, override := 0, false
	for {
		var event struct {
			Index string `json:"index"`
		}
		if decoder.Decode(&event) != nil {
			return count, override
		}
		count++
		override = override || event.Index != e.config.Index
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

// Endpoint returns the configured non-secret export endpoint.
func (e *SplunkHECLogsExporter) Endpoint() string {
	if e == nil {
		return ""
	}
	return e.config.Endpoint
}

// Channel returns the request channel sent with every batch.
func (e *SplunkHECLogsExporter) Channel() string {
	if e == nil {
		return ""
	}
	return e.config.Channel
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
		Enabled:         e.config.Enabled,
		Configured:      e.config.Endpoint != "" && e.config.Token != "",
		Endpoint:        e.config.Endpoint,
		SearchURL:       splunkPlatformSearchURL(e.config.Endpoint, e.config.Index),
		Index:           e.config.Index,
		TokenConfigured: e.config.Token != "",
		Token:           redactConfiguredToken(e.config.Token),
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

// ExportLogs synchronously invokes the upstream exporter. Queueing and retries
// are provided by the controller's Collector exporter helper.
func (e *SplunkHECLogsExporter) ExportLogs(ctx context.Context, ld plog.Logs) error {
	if e == nil || ld.LogRecordCount() == 0 {
		return nil
	}
	attempt := &hecAttempt{}
	err := e.exp.ConsumeLogs(context.WithValue(ctx, hecAttemptKey{}, attempt), prepareHECLogs(ld))
	if err == nil {
		return nil
	}
	clean := errors.New(sanitizeExportErrorString(err.Error(), e.config.Token))
	if ctx.Err() != context.Canceled && attempt.requests.Load() == 0 {
		e.recordExport(clean, 0)
	}
	remaining := plog.NewLogs()
	allPermanent, partialsOnly := true, true
	for _, failure := range multierr.Errors(err) {
		if consumererror.IsPermanent(failure) {
			continue
		}
		allPermanent = false
		var partial consumererror.Logs
		if !errors.As(failure, &partial) {
			partialsOnly = false
			continue
		}
		for _, resource := range partial.Data().ResourceLogs().All() {
			resource.CopyTo(remaining.ResourceLogs().AppendEmpty())
		}
	}
	var result error = clean
	if allPermanent {
		result = consumererror.NewPermanent(clean)
	} else if delay := time.Duration(attempt.retryAfter.Load()); delay > 0 {
		result = exporterhelper.NewThrottleRetry(clean, delay)
	}
	if partialsOnly && !allPermanent {
		return consumererror.NewLogs(result, remaining)
	}
	return result
}

func (e *SplunkHECLogsExporter) recordExport(err error, records int, result ...int) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.lastHTTPStatus, e.lastHECCode = 0, 0
	if len(result) > 0 {
		e.lastHTTPStatus = result[0]
	}
	if len(result) > 1 {
		e.lastHECCode = result[1]
	}
	if err != nil {
		e.failedBatches++
		e.lastExportError = err.Error()
		return
	}
	e.exportedBatches++
	e.exportedRecords += uint64(records)
	e.lastExportError = ""
	e.lastExportSuccess = time.Now()
}

// Preserve attribute-only events and receipt timestamps before passing pdata
// to the upstream translator; never mutate the locally stored/caller data.
func prepareHECLogs(logs plog.Logs) plog.Logs {
	copy := plog.NewLogs()
	logs.CopyTo(copy)
	now := pcommon.NewTimestampFromTime(time.Now())
	for _, resource := range copy.ResourceLogs().All() {
		resource.Resource().Attributes().Remove("com.splunk.hec.token")
		sanitizeHECMap(resource.Resource().Attributes())
		for _, scope := range resource.ScopeLogs().All() {
			for _, record := range scope.LogRecords().All() {
				sanitizeHECMap(record.Attributes())
				if record.Timestamp() == 0 && record.ObservedTimestamp() == 0 {
					record.SetObservedTimestamp(now)
				}
				if record.Body().AsString() == "" {
					_ = record.Body().SetEmptyMap().PutEmptyMap("attributes").FromRaw(record.Attributes().AsRaw())
				}
				sanitizeHECValue(record.Body())
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
	cloned := plog.NewLogs()
	ld.CopyTo(cloned)
	go func() {
		if err := exporter.ExportLogs(context.Background(), cloned); err != nil {
			log.Printf("[splunk-export] logs export failed: %v", err)
		}
	}()
}
