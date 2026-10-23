package otlp

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
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
	Enabled bool
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
	Endpoint           string `json:"endpoint"`
	Index              string `json:"index"`
	TokenConfigured    bool   `json:"tokenConfigured"`
	Token              string `json:"token,omitempty"`
	Timeout            string `json:"timeout,omitempty"`
	ExportedBatches    uint64 `json:"exportedBatches"`
	ExportedRecords    uint64 `json:"exportedRecords"`
	FailedBatches      uint64 `json:"failedBatches"`
	LastExportError    string `json:"lastExportError,omitempty"`
	LastExportSuccess  string `json:"lastExportSuccess,omitempty"`
}

// SplunkHECLogsExporter posts OTLP logs to Splunk HEC as HEC JSON events.
type SplunkHECLogsExporter struct {
	config SplunkHECLogsExporterConfig
	client *http.Client

	mu                sync.Mutex
	exportedBatches   uint64
	exportedRecords   uint64
	failedBatches     uint64
	lastExportError   string
	lastExportSuccess time.Time
}

// hecEvent is one HEC JSON event. Splunk applies index, source, sourcetype and
// host from these fields.
type hecEvent struct {
	Time       float64        `json:"time"`
	Host       string         `json:"host,omitempty"`
	Source     string         `json:"source,omitempty"`
	Sourcetype string         `json:"sourcetype,omitempty"`
	Index      string         `json:"index,omitempty"`
	Event      any            `json:"event"`
	Fields     map[string]any `json:"fields,omitempty"`
}

func NewSplunkHECLogsExporter(config SplunkHECLogsExporterConfig) (*SplunkHECLogsExporter, error) {
	config = normalizeSplunkHECLogsExporterConfig(config)
	if config.Endpoint == "" {
		return nil, fmt.Errorf("splunk hec logs endpoint is empty")
	}
	parsed, err := url.Parse(config.Endpoint)
	if err != nil {
		return nil, fmt.Errorf("invalid splunk hec logs endpoint: %w", err)
	}
	if parsed.Scheme == "" || parsed.Host == "" {
		return nil, fmt.Errorf("splunk hec logs endpoint must include scheme and host")
	}
	if strings.TrimSpace(config.Token) == "" {
		return nil, fmt.Errorf("splunk hec logs token is empty")
	}

	transport := http.DefaultTransport.(*http.Transport).Clone()
	if config.InsecureSkipVerify {
		transport.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}
	}
	return &SplunkHECLogsExporter{
		config: config,
		client: &http.Client{Timeout: config.Timeout, Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }},
	}, nil
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
		Index:           e.config.Index,
		TokenConfigured: e.config.Token != "",
		Token:           redactConfiguredToken(e.config.Token),
		Timeout:         e.config.Timeout.String(),
		ExportedBatches: e.exportedBatches,
		ExportedRecords: e.exportedRecords,
		FailedBatches:   e.failedBatches,
		LastExportError: e.lastExportError,
	}
	if !e.lastExportSuccess.IsZero() {
		status.LastExportSuccess = e.lastExportSuccess.UTC().Format(time.RFC3339)
	}
	return status
}

// ExportLogs converts logs to HEC events and posts them in one request.
func (e *SplunkHECLogsExporter) ExportLogs(ctx context.Context, ld plog.Logs) error {
	if e == nil {
		return nil
	}
	events := e.convertToHECEvents(ld)
	if len(events) == 0 {
		return nil
	}

	var payload bytes.Buffer
	encoder := json.NewEncoder(&payload)
	for i := range events {
		if err := encoder.Encode(events[i]); err != nil {
			return fmt.Errorf("encode hec event: %w", err)
		}
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, e.config.Endpoint, &payload)
	if err != nil {
		return fmt.Errorf("build hec request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Splunk "+e.config.Token)
	req.Header.Set("X-Splunk-Request-Channel", e.config.Channel)

	response, err := e.client.Do(req)
	if err != nil {
		e.recordExport(fmt.Errorf("%s", sanitizeExportErrorString(err.Error(), e.config.Token)), 0)
		return fmt.Errorf("post to splunk hec: %s", sanitizeExportErrorString(err.Error(), e.config.Token))
	}
	defer response.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(response.Body, 4<<10))

	if response.StatusCode < 200 || response.StatusCode >= 300 {
		exportErr := fmt.Errorf("splunk hec returned %d: %s", response.StatusCode,
			sanitizeExportErrorString(strings.TrimSpace(string(body)), e.config.Token))
		e.recordExport(exportErr, 0)
		return exportErr
	}
	var result struct {
		Code *int `json:"code"`
	}
	if err := json.Unmarshal(body, &result); err != nil || result.Code == nil || *result.Code != 0 {
		exportErr := fmt.Errorf("splunk hec did not accept the log batch")
		e.recordExport(exportErr, 0)
		return exportErr
	}
	e.recordExport(nil, len(events))
	return nil
}

// SplunkHECLogsExportController keeps receiver wiring stable across connection edits.
type SplunkHECLogsExportController struct {
	mu          sync.RWMutex
	config      SplunkHECLogsExporterConfig
	exporter    *SplunkHECLogsExporter
	version     string
	configError string
}

func NewSplunkHECLogsExportController(config SplunkHECLogsExporterConfig) *SplunkHECLogsExportController {
	config = normalizeSplunkHECLogsExporterConfig(config)
	c := &SplunkHECLogsExportController{config: config, version: newRequestChannel()}
	if config.Enabled {
		exporter, err := NewSplunkHECLogsExporter(config)
		if err != nil {
			c.configError = err.Error()
		} else {
			c.exporter = exporter
		}
	}
	return c
}

func (c *SplunkHECLogsExportController) Config() SplunkHECLogsExporterConfig {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.config
}

// SetEnabled preserves export activity while pausing or resuming forwarding.
func (c *SplunkHECLogsExportController) SetEnabled(enabled bool) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if enabled && c.exporter == nil {
		exporter, err := NewSplunkHECLogsExporter(c.config)
		if err != nil {
			return err
		}
		c.exporter = exporter
	}
	c.config.Enabled = enabled
	c.version = newRequestChannel()
	return nil
}

func (c *SplunkHECLogsExportController) Apply(config SplunkHECLogsExporterConfig, exporter *SplunkHECLogsExporter) {
	c.mu.Lock()
	previous := c.exporter
	c.config, c.exporter, c.configError, c.version = config, exporter, "", newRequestChannel()
	c.mu.Unlock()
	if previous != nil {
		previous.client.CloseIdleConnections()
	}
}

func (c *SplunkHECLogsExportController) Status() SplunkHECLogsExportStatus {
	c.mu.RLock()
	defer c.mu.RUnlock()
	status := c.exporter.Status()
	status.Version, status.Source, status.Sourcetype = c.version, c.config.Source, c.config.Sourcetype
	status.Endpoint, status.Index = c.config.Endpoint, c.config.Index
	status.Token, status.TokenConfigured = "", strings.TrimSpace(c.config.Token) != ""
	status.Configured = status.TokenConfigured && status.Endpoint != ""
	status.InsecureSkipVerify = c.config.InsecureSkipVerify
	status.Enabled = c.config.Enabled && c.exporter != nil
	if c.configError != "" {
		status.LastExportError = c.configError
	}
	return status
}

func (c *SplunkHECLogsExportController) ExportEnabled() bool { return c.Status().Enabled }

func (c *SplunkHECLogsExportController) ExportLogs(ctx context.Context, logs plog.Logs) error {
	c.mu.RLock()
	exporter, enabled := c.exporter, c.config.Enabled
	c.mu.RUnlock()
	if exporter == nil || !enabled {
		return nil
	}
	return exporter.ExportLogs(ctx, logs)
}

func (e *SplunkHECLogsExporter) recordExport(err error, records int) {
	e.mu.Lock()
	defer e.mu.Unlock()
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

func (e *SplunkHECLogsExporter) convertToHECEvents(ld plog.Logs) []hecEvent {
	events := make([]hecEvent, 0, ld.LogRecordCount())
	resourceLogs := ld.ResourceLogs()
	for i := 0; i < resourceLogs.Len(); i++ {
		resource := resourceLogs.At(i).Resource().Attributes()
		scopeLogs := resourceLogs.At(i).ScopeLogs()
		for j := 0; j < scopeLogs.Len(); j++ {
			records := scopeLogs.At(j).LogRecords()
			for k := 0; k < records.Len(); k++ {
				events = append(events, e.convertRecord(resource, records.At(k)))
			}
		}
	}
	return events
}

func (e *SplunkHECLogsExporter) convertRecord(resource pcommon.Map, record plog.LogRecord) hecEvent {
	recordAttrs := record.Attributes()
	event := hecEvent{
		// A log record attribute wins over the resource attribute, which wins
		// over the configured default, matching Splunk Connect for OTLP.
		Index:      firstNonEmpty(attributeString(recordAttrs, splunkIndexAttribute), attributeString(resource, splunkIndexAttribute), e.config.Index),
		Source:     firstNonEmpty(attributeString(recordAttrs, splunkSourceAttribute), attributeString(resource, splunkSourceAttribute), e.config.Source),
		Sourcetype: firstNonEmpty(attributeString(recordAttrs, splunkSourcetypeAttribute), attributeString(resource, splunkSourcetypeAttribute), e.config.Sourcetype),
		Host:       firstNonEmpty(attributeString(recordAttrs, hostNameAttribute), attributeString(resource, hostNameAttribute)),
		Event:      record.Body().AsString(),
		Fields:     map[string]any{},
	}

	timestamp := record.Timestamp()
	if timestamp == 0 {
		timestamp = record.ObservedTimestamp()
	}
	if timestamp != 0 {
		event.Time = float64(timestamp.AsTime().UnixNano()) / float64(time.Second)
	} else {
		event.Time = float64(time.Now().UnixNano()) / float64(time.Second)
	}

	if text := record.SeverityText(); text != "" {
		event.Fields[severityTextField] = text
	}
	if number := record.SeverityNumber(); number != plog.SeverityNumberUnspecified {
		event.Fields[severityNumberField] = int32(number)
	}
	copyAttributesToFields(resource, event.Fields)
	copyAttributesToFields(recordAttrs, event.Fields)
	if len(event.Fields) == 0 {
		event.Fields = nil
	}
	return event
}

// copyAttributesToFields maps attributes to HEC indexed fields, skipping the
// ones already represented as HEC event metadata.
func copyAttributesToFields(attrs pcommon.Map, fields map[string]any) {
	for key, value := range attrs.All() {
		switch key {
		case splunkIndexAttribute, splunkSourceAttribute, splunkSourcetypeAttribute, hostNameAttribute:
			continue
		}
		fields[key] = value.AsString()
	}
}

func attributeString(attrs pcommon.Map, key string) string {
	if value, ok := attrs.Get(key); ok {
		return strings.TrimSpace(value.AsString())
	}
	return ""
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func exportLogsAsync(exporter LogsExporter, ld plog.Logs) {
	if exporter == nil {
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
