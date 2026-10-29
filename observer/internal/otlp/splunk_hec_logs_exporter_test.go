package otlp

import (
	"compress/gzip"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
)

func TestHECLogsStatusResolvesOnlyKnownSplunkCloudWebOrigins(t *testing.T) {
	for _, test := range []struct{ endpoint, wantHost string }{
		{"https://http-inputs-stack.splunkcloud.com/services/collector", "stack.splunkcloud.com"},
		{"https://http-inputs.stack.splunkcloud.com/services/collector", "stack.splunkcloud.com"},
		{"https://prd-p-test.splunkcloud.com:8088/services/collector/event", "prd-p-test.splunkcloud.com"},
		{"https://stack.splunkcloud.com:443/services/collector", "stack.splunkcloud.com"},
		{"https://enterprise.example:8088/services/collector", ""},
		{"http://stack.splunkcloud.com:8088/services/collector", ""},
		{"https://stack.splunkcloud.com:9090/services/collector", ""},
		{"https://stack.splunkcloud.com.evil.example/services/collector", ""},
		{"https://user:password@stack.splunkcloud.com/services/collector", ""},
	} {
		t.Run(test.endpoint, func(t *testing.T) {
			index := `studio" | stats count`
			c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: test.endpoint, Token: "test", Index: index})
			searchURL := c.Status().SearchURL
			if test.wantHost == "" {
				if searchURL != "" {
					t.Fatalf("guessed an unknown Web origin: %s", searchURL)
				}
				return
			}
			parsed, err := url.Parse(searchURL)
			if err != nil || parsed.Scheme != "https" || parsed.Host != test.wantHost || parsed.Path != "/en-US/app/search/search" {
				t.Fatalf("search URL = %s, error %v", searchURL, err)
			}
			if got := parsed.Query().Get("q"); got != `search index="studio\" | stats count" earliest=-1h` {
				t.Fatalf("index escaping = %q", got)
			}
		})
	}
	if got := splunkPlatformSearchURL("https://stack.splunkcloud.com/services/collector", ""); got != "" {
		t.Fatalf("empty index search = %s", got)
	}
}

type hecEvent struct {
	Time   float64        `json:"time"`
	Index  string         `json:"index"`
	Event  any            `json:"event"`
	Fields map[string]any `json:"fields"`
}

func hecRequestBody(t *testing.T, r *http.Request) io.Reader {
	t.Helper()
	if r.Header.Get("Content-Encoding") != "gzip" {
		return r.Body
	}
	reader, err := gzip.NewReader(r.Body)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = reader.Close() })
	return reader
}

type capturedHECRequest struct {
	authorization string
	channel       string
	contentType   string
	events        []map[string]any
}

// hecTestServer captures HEC requests and replies with status.
func hecTestServer(t *testing.T, status int, body string) (*httptest.Server, *[]capturedHECRequest) {
	t.Helper()
	captured := make([]capturedHECRequest, 0, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		request := capturedHECRequest{authorization: r.Header.Get("Authorization"), channel: r.Header.Get("X-Splunk-Request-Channel"), contentType: r.Header.Get("Content-Type")}
		decoder := json.NewDecoder(hecRequestBody(t, r))
		for {
			var event map[string]any
			err := decoder.Decode(&event)
			if err == io.EOF {
				break
			}
			if err != nil {
				t.Error(err)
				break
			}
			request.events = append(request.events, event)
		}
		captured = append(captured, request)
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(server.Close)
	return server, &captured
}

func logsWithRecord(resourceAttrs, recordAttrs map[string]string, body string) plog.Logs {
	ld := plog.NewLogs()
	rl := ld.ResourceLogs().AppendEmpty()
	for key, value := range resourceAttrs {
		rl.Resource().Attributes().PutStr(key, value)
	}
	sl := rl.ScopeLogs().AppendEmpty()
	record := sl.LogRecords().AppendEmpty()
	record.Body().SetStr(body)
	record.SetTimestamp(pcommon.NewTimestampFromTime(time.Unix(1761000000, 0)))
	record.SetSeverityText("ERROR")
	record.SetSeverityNumber(plog.SeverityNumberError)
	for key, value := range recordAttrs {
		record.Attributes().PutStr(key, value)
	}
	return ld
}

func newTestHECExporter(t *testing.T, endpoint string, config SplunkHECLogsExporterConfig) *SplunkHECLogsExporter {
	t.Helper()
	config.Endpoint = endpoint
	if config.Token == "" {
		config.Token = "test-token-value"
	}
	exporter, err := NewSplunkHECLogsExporter(config)
	if err != nil {
		t.Fatalf("NewSplunkHECLogsExporter: %v", err)
	}
	t.Cleanup(func() { exporter.Shutdown(context.Background()) })
	return exporter
}

// The channel header is required by ack-enabled tokens and ignored by others,
// so it must be sent on every request regardless of configuration.
func TestHECLogsExportAlwaysSendsRequestChannel(t *testing.T) {
	server, captured := hecTestServer(t, http.StatusOK, `{"text":"Success","code":0}`)
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true, Index: "studio"})

	if err := exporter.ExportLogs(context.Background(), logsWithRecord(nil, nil, "hello")); err != nil {
		t.Fatalf("ExportLogs: %v", err)
	}
	if len(*captured) != 1 {
		t.Fatalf("expected 1 request, got %d", len(*captured))
	}
	request := (*captured)[0]
	if request.channel == "" {
		t.Fatal("X-Splunk-Request-Channel header was not sent")
	}
	if request.channel != exporter.Channel() {
		t.Errorf("channel header %q does not match exporter channel %q", request.channel, exporter.Channel())
	}
	if request.authorization != "Splunk test-token-value" {
		t.Errorf("authorization = %q, want %q", request.authorization, "Splunk test-token-value")
	}
	if request.contentType != "application/json" {
		t.Errorf("content-type = %q, want application/json", request.contentType)
	}
}

func TestHECLogsExportGeneratesStableChannelPerExporter(t *testing.T) {
	server, captured := hecTestServer(t, http.StatusOK, `{"text":"Success","code":0}`)
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true})

	for i := 0; i < 3; i++ {
		if err := exporter.ExportLogs(context.Background(), logsWithRecord(nil, nil, "hello")); err != nil {
			t.Fatalf("ExportLogs: %v", err)
		}
	}
	if len(*captured) != 3 {
		t.Fatalf("expected 3 requests, got %d", len(*captured))
	}
	first := (*captured)[0].channel
	for i, request := range *captured {
		if request.channel != first {
			t.Errorf("request %d channel = %q, want stable %q", i, request.channel, first)
		}
	}
}

func TestHECLogsExportHonorsConfiguredChannel(t *testing.T) {
	server, captured := hecTestServer(t, http.StatusOK, `{"text":"Success","code":0}`)
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{
		Enabled: true, Channel: "6e34e87a-4834-4798-b118-a7c76225fea7",
	})

	if err := exporter.ExportLogs(context.Background(), logsWithRecord(nil, nil, "hello")); err != nil {
		t.Fatalf("ExportLogs: %v", err)
	}
	if got := (*captured)[0].channel; got != "6e34e87a-4834-4798-b118-a7c76225fea7" {
		t.Errorf("channel = %q, want configured value", got)
	}
}

func TestHECLogsExportEventEnvelope(t *testing.T) {
	server, captured := hecTestServer(t, http.StatusOK, `{"text":"Success","code":0}`)
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{
		Enabled: true, Index: "studio", Source: "otel", Sourcetype: "otel:logs",
	})

	ld := logsWithRecord(map[string]string{"host.name": "laptop-1", "service.name": "orders", "trace_id": "resource-must-not-replace-record-id"}, nil, "payment declined")
	record := ld.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords().At(0)
	record.SetTraceID(pcommon.TraceID{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16})
	record.SetSpanID(pcommon.SpanID{1, 2, 3, 4, 5, 6, 7, 8})
	record.Attributes().PutStr("trace_id", "attribute-must-not-replace-record-id")
	if err := exporter.ExportLogs(context.Background(), ld); err != nil {
		t.Fatalf("ExportLogs: %v", err)
	}

	events := (*captured)[0].events
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	event := events[0]
	if event["event"] != "payment declined" {
		t.Errorf("event = %v, want body string", event["event"])
	}
	if event["index"] != "studio" {
		t.Errorf("index = %v, want studio", event["index"])
	}
	if event["sourcetype"] != "otel:logs" {
		t.Errorf("sourcetype = %v, want otel:logs", event["sourcetype"])
	}
	if event["host"] != "laptop-1" {
		t.Errorf("host = %v, want laptop-1 from host.name", event["host"])
	}
	if got, want := event["time"], float64(1761000000); got != want {
		t.Errorf("time = %v, want %v epoch seconds", got, want)
	}

	fields, ok := event["fields"].(map[string]any)
	if !ok {
		t.Fatalf("fields missing or wrong type: %v", event["fields"])
	}
	if fields["otel.log.severity.text"] != "ERROR" {
		t.Errorf("severity text field = %v, want ERROR", fields["otel.log.severity.text"])
	}
	if got, want := fields["otel.log.severity.number"], float64(plog.SeverityNumberError); got != want {
		t.Errorf("severity number field = %v, want %v", got, want)
	}
	if fields["service.name"] != "orders" {
		t.Errorf("service.name field = %v, want orders", fields["service.name"])
	}
	if fields["trace_id"] != "0102030405060708090a0b0c0d0e0f10" || fields["span_id"] != "0102030405060708" {
		t.Fatalf("trace correlation fields = %v", fields)
	}
	// host.name becomes the HEC host, so it must not be duplicated as a field.
	if _, exists := fields["host.name"]; exists {
		t.Error("host.name should not be duplicated into fields")
	}
}

func TestHECLogsExportAttributeOnlyAndEmptyRecords(t *testing.T) {
	server, captured := hecTestServer(t, http.StatusOK, `{"code":0}`)
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true})
	logs := logsWithRecord(nil, map[string]string{"message": "attribute-only event", "provider": "test"}, "")
	records := logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords()
	records.AppendEmpty()
	records.AppendEmpty().Body().SetStr("normal event afterward")
	if err := exporter.ExportLogs(context.Background(), logs); err != nil {
		t.Fatal(err)
	}
	events := (*captured)[0].events
	if len(events) != 3 {
		t.Fatalf("events = %v", events)
	}
	attributes := events[0]["event"].(map[string]any)["attributes"].(map[string]any)
	if attributes["message"] != "attribute-only event" || attributes["provider"] != "test" {
		t.Fatalf("attribute-only event = %v", events[0])
	}
	if _, ok := events[1]["event"].(map[string]any); !ok || events[2]["event"] != "normal event afterward" {
		t.Fatalf("empty/normal events = %v", events)
	}
	for _, event := range events {
		fields, _ := event["fields"].(map[string]any)
		if fields["trace_id"] != nil || fields["span_id"] != nil {
			t.Fatalf("empty IDs should be omitted: %v", fields)
		}
	}
}

func TestHECLogsExportIndexPrecedence(t *testing.T) {
	tests := []struct {
		name          string
		configIndex   string
		resourceAttrs map[string]string
		recordAttrs   map[string]string
		want          string
	}{
		{
			name:        "falls back to configured index",
			configIndex: "studio",
			want:        "studio",
		},
		{
			name:          "resource attribute overrides configured index",
			configIndex:   "studio",
			resourceAttrs: map[string]string{"com.splunk.index": "from_resource"},
			want:          "from_resource",
		},
		{
			name:          "record attribute overrides resource attribute",
			configIndex:   "studio",
			resourceAttrs: map[string]string{"com.splunk.index": "from_resource"},
			recordAttrs:   map[string]string{"com.splunk.index": "from_record"},
			want:          "from_record",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server, captured := hecTestServer(t, http.StatusOK, `{"text":"Success","code":0}`)
			exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{
				Enabled: true, Index: test.configIndex,
			})
			ld := logsWithRecord(test.resourceAttrs, test.recordAttrs, "hello")
			if err := exporter.ExportLogs(context.Background(), ld); err != nil {
				t.Fatalf("ExportLogs: %v", err)
			}
			if got := (*captured)[0].events[0]["index"]; got != test.want {
				t.Errorf("index = %v, want %v", got, test.want)
			}
			if _, exists := (*captured)[0].events[0]["fields"].(map[string]any)["com.splunk.index"]; exists {
				t.Error("com.splunk.index should not be duplicated into fields")
			}
		})
	}
}

func TestHECLogsExportErrorRedactsToken(t *testing.T) {
	server, _ := hecTestServer(t, http.StatusBadRequest,
		`{"text":"Data channel is missing.","code":28,"token":"super-secret-token"}`)
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{
		Enabled: true, Token: "super-secret-token",
	})

	err := exporter.ExportLogs(context.Background(), logsWithRecord(nil, nil, "hello"))
	if err == nil {
		t.Fatal("expected an error for HTTP 400")
	}
	if strings.Contains(err.Error(), "super-secret-token") {
		t.Errorf("error leaks the token: %v", err)
	}
	if !strings.Contains(err.Error(), "400") {
		t.Errorf("error should report the status code: %v", err)
	}

	status := exporter.Status()
	if status.FailedBatches != 1 {
		t.Errorf("FailedBatches = %d, want 1", status.FailedBatches)
	}
	if strings.Contains(status.Token, "super-secret-token") {
		t.Errorf("status leaks the token: %q", status.Token)
	}
}

func TestHECLogsExportCountsRecords(t *testing.T) {
	server, _ := hecTestServer(t, http.StatusOK, `{"text":"Success","code":0}`)
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true})

	ld := plog.NewLogs()
	sl := ld.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty()
	for i := 0; i < 5; i++ {
		sl.LogRecords().AppendEmpty().Body().SetStr("record")
	}
	if err := exporter.ExportLogs(context.Background(), ld); err != nil {
		t.Fatalf("ExportLogs: %v", err)
	}

	status := exporter.Status()
	if status.ExportedBatches != 1 {
		t.Errorf("ExportedBatches = %d, want 1", status.ExportedBatches)
	}
	if status.ExportedRecords != 5 {
		t.Errorf("ExportedRecords = %d, want 5", status.ExportedRecords)
	}
}

func TestHECLogsExportSkipsEmptyLogs(t *testing.T) {
	server, captured := hecTestServer(t, http.StatusOK, `{"text":"Success","code":0}`)
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true})

	if err := exporter.ExportLogs(context.Background(), plog.NewLogs()); err != nil {
		t.Fatalf("ExportLogs: %v", err)
	}
	if len(*captured) != 0 {
		t.Errorf("expected no request for empty logs, got %d", len(*captured))
	}
}

func TestExportLogsAsyncSkipsDisabledExporter(t *testing.T) {
	server, captured := hecTestServer(t, http.StatusOK, `{"text":"Success","code":0}`)
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: false})

	exportLogsAsync(exporter, logsWithRecord(nil, nil, "hello"))
	time.Sleep(150 * time.Millisecond)
	if len(*captured) != 0 {
		t.Errorf("disabled exporter should not post, got %d requests", len(*captured))
	}
}

func TestNewSplunkHECLogsExporterValidation(t *testing.T) {
	tests := []struct {
		name   string
		config SplunkHECLogsExporterConfig
	}{
		{name: "empty endpoint", config: SplunkHECLogsExporterConfig{Token: "t"}},
		{name: "endpoint without scheme", config: SplunkHECLogsExporterConfig{Endpoint: "splunk:8088", Token: "t"}},
		{name: "empty token", config: SplunkHECLogsExporterConfig{Endpoint: "https://splunk:8088/services/collector"}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, err := NewSplunkHECLogsExporter(test.config); err == nil {
				t.Error("expected a validation error")
			}
		})
	}
}

func TestHECLogsExportRejectsUnacceptedResponses(t *testing.T) {
	for _, body := range []string{`{"code":4}`, `{}`, `not-json`} {
		t.Run(body, func(t *testing.T) {
			server, _ := hecTestServer(t, http.StatusOK, body)
			exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true})
			if err := exporter.ExportLogs(context.Background(), logsWithRecord(nil, nil, "test")); err == nil {
				t.Fatal("unaccepted HEC response reported success")
			}
			if exporter.Status().ExportedRecords != 0 || exporter.Status().FailedBatches != 1 {
				t.Fatal("incorrect success/failure counters")
			}
		})
	}
}

func TestHECLogsExportDoesNotFollowCredentialRedirects(t *testing.T) {
	var redirected bool
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { redirected = true }))
	defer target.Close()
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL, http.StatusTemporaryRedirect)
	}))
	defer source.Close()
	exporter := newTestHECExporter(t, source.URL, SplunkHECLogsExporterConfig{Enabled: true})
	if err := exporter.ExportLogs(context.Background(), logsWithRecord(nil, nil, "test")); err == nil || redirected {
		t.Fatal("redirect was followed or reported as success")
	}
}

func TestHECUpstreamConfigurationValidationDoesNotStartOrSend(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { requests.Add(1) }))
	defer server.Close()
	valid := SplunkHECLogsExporterConfig{Endpoint: server.URL + "/services/collector", Token: "test", Enabled: true}
	if err := ValidateSplunkHECLogsExporterConfig(valid); err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 0 {
		t.Fatal("configuration validation performed network IO")
	}
	valid.Token = ""
	if err := ValidateSplunkHECLogsExporterConfig(valid); err == nil {
		t.Fatal("empty token was accepted")
	}
	valid.Token, valid.Endpoint = "test", "file:///tmp/hec"
	if err := ValidateSplunkHECLogsExporterConfig(valid); err == nil {
		t.Fatal("non-HTTP endpoint was accepted")
	}
}
