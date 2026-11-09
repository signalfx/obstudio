package otlp

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"go.opentelemetry.io/collector/consumer/consumererror"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
)

func TestHECDeliveryRejectsUnacceptedSuccessfulHTTPResponses(t *testing.T) {
	for _, body := range []string{
		"not JSON",
		`{}`,
		`{"code":4,"text":"Invalid token"}`,
		`{"code":6,"invalid-event-number":1}`,
	} {
		t.Run(body, func(t *testing.T) {
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, _ = w.Write([]byte(body))
			}))
			defer remote.Close()
			exp := newTestHECExporter(t, remote.URL, SplunkHECLogsExporterConfig{Token: "test"})
			logs := logsWithRecord(nil, nil, "first")
			logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords().AppendEmpty().Body().SetStr("second")
			if err := exp.exp.ConsumeLogs(context.Background(), logs); !consumererror.IsPermanent(err) {
				t.Fatal("ambiguous or partial acceptance must reach the component as a permanent error", err)
			}
			if got := exp.Status(); got.ExportedRecords != 0 || got.ExportedBatches != 0 || got.FailedBatches != 1 {
				t.Fatal(got)
			}
		})
	}
}

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
			t.Cleanup(func() { c.Shutdown(context.Background()) })
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
	exporter, err := newSplunkHECLogsExporter(config, false)
	if err != nil {
		t.Fatalf("NewSplunkHECLogsExporter: %v", err)
	}
	t.Cleanup(func() { exporter.Shutdown(context.Background()) })
	return exporter
}

func TestHECLogsExporterRequiresTLSExceptOnLoopback(t *testing.T) {
	for _, endpoint := range []string{"https://hec.example/services/collector", "http://127.0.0.1:8088/services/collector", "http://[::1]:8088/services/collector", "http://localhost:8088/services/collector", "http://hec.example:8088/services/collector"} {
		for _, insecure := range []bool{false, true} {
			exp, err := NewSplunkHECLogsExporter(SplunkHECLogsExporterConfig{Endpoint: endpoint, Token: "test", InsecureSkipVerify: insecure})
			if strings.Contains(endpoint, "http://hec.example") {
				if err == nil || exp != nil {
					t.Fatal("remote HTTP endpoint accepted")
				}
			} else if err != nil {
				t.Fatal(endpoint, err)
			}
			exp.Shutdown(context.Background())
		}
	}
}

func TestHECLogsExportRequestHeaders(t *testing.T) {
	for _, channel := range []string{"", "6e34e87a-4834-4798-b118-a7c76225fea7"} {
		t.Run("channel="+channel, func(t *testing.T) {
			server, captured := hecTestServer(t, http.StatusOK, `{"text":"Success","code":0}`)
			exp := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true, Channel: channel})
			for range 2 {
				if err := exp.ExportLogs(context.Background(), logsWithRecord(nil, nil, "hello")); err != nil {
					t.Fatal(err)
				}
			}
			if len(*captured) != 2 {
				t.Fatalf("expected 2 requests, got %d", len(*captured))
			}
			first := (*captured)[0].channel
			if matched, _ := regexp.MatchString(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`, first); !matched {
				t.Fatalf("invalid request channel: %q", first)
			}
			if channel != "" && first != channel {
				t.Fatalf("channel = %q, want %q", first, channel)
			}
			for _, request := range *captured {
				if request.channel != first || request.authorization != "Splunk test-token-value" || request.contentType != "application/json" {
					t.Fatalf("incorrect request headers: channel=%q authorization matches=%t content-type=%q", request.channel, request.authorization == "Splunk test-token-value", request.contentType)
				}
			}
		})
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

func TestHECLogsExportUsesTheConfiguredIndex(t *testing.T) {
	tests := []struct {
		name          string
		configIndex   string
		resourceAttrs map[string]string
		recordAttrs   map[string]string
		want          string
	}{
		{
			name:        "configured index",
			configIndex: "studio",
			want:        "studio",
		},
		{
			name:          "resource index metadata",
			configIndex:   "studio",
			resourceAttrs: map[string]string{"com.splunk.index": "from_resource"},
			want:          "studio",
		},
		{
			name:          "record and resource index metadata",
			configIndex:   "studio",
			resourceAttrs: map[string]string{"com.splunk.index": "from_resource"},
			recordAttrs:   map[string]string{"com.splunk.index": "from_record"},
			want:          "studio",
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
	encoded, err := json.Marshal(status)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), "super-secret-token") {
		t.Fatal("status exposes the credential")
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

func TestHECConnectionProbeRejectsUnacceptedResponses(t *testing.T) {
	for _, body := range []string{`{"code":4}`, `{}`, `not-json`} {
		t.Run(body, func(t *testing.T) {
			server, _ := hecTestServer(t, http.StatusOK, body)
			exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true})
			if err := exporter.TestConnection(context.Background(), logsWithRecord(nil, nil, "test")); err == nil {
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

func TestHECLogsExportCountsAcceptedAndFailedRequests(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		if requests.Add(1) == 1 {
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`{"code":4,"text":"Invalid token"}`))
			return
		}
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer server.Close()
	exporter := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true})
	logs := logsWithRecord(map[string]string{"com.splunk.index": "first"}, nil, "first group")
	logsWithRecord(map[string]string{"com.splunk.index": "second"}, nil, "second group").ResourceLogs().At(0).CopyTo(logs.ResourceLogs().AppendEmpty())
	if err := exporter.ExportLogs(context.Background(), logs); err == nil {
		t.Fatal("group rejection was not reported")
	}
	status := exporter.Status()
	if requests.Load() != 2 || status.FailedBatches != 1 || status.ExportedRecords != 1 || status.ExportedBatches != 1 {
		t.Fatalf("incorrect per-send accounting: %+v", status)
	}
	if err := exporter.ExportLogs(context.Background(), logsWithRecord(nil, nil, "recovered")); err != nil {
		t.Fatal(err)
	}
	status = exporter.Status()
	if status.LastExportError != "" || status.LastHTTPStatus != 0 || status.LastHECCode != 0 || status.ExportedRecords != 2 || status.FailedBatches != 1 {
		t.Fatalf("successful attempt did not recover health: %+v", status)
	}
}

func TestHECLogsExportOmitsIncompleteResponseBodies(t *testing.T) {
	for _, statusCode := range []int{200, 403} {
		for _, oversized := range []bool{false, true} {
			t.Run(strconv.Itoa(statusCode)+"/"+strconv.FormatBool(oversized), func(t *testing.T) {
				token := "sensitive-test-token-value"
				if oversized {
					token = "sensitive-" + strings.Repeat("x", 4086)
				}
				prefix := token[:8]
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					_, _ = io.Copy(io.Discard, r.Body)
					if !oversized {
						w.Header().Set("Content-Length", "1000")
					}
					w.WriteHeader(statusCode)
					body := "token=" + prefix
					if oversized {
						body = "echo:" + token
					}
					_, _ = w.Write([]byte(body))
				}))
				defer server.Close()
				exp := newTestHECExporter(t, server.URL+"/services/collector", SplunkHECLogsExporterConfig{Token: token, Index: "studio"})
				err := exp.exp.ConsumeLogs(context.Background(), logsWithRecord(nil, nil, "one"))
				if !consumererror.IsPermanent(err) {
					t.Fatal("ambiguous success or permanent HTTP failure must not be replayed", err)
				}
				status := exp.Status()
				if strings.Contains(err.Error(), prefix) || strings.Contains(status.LastExportError, prefix) {
					t.Fatal("incomplete response exposed a credential prefix")
				}
				if status.ExportedRecords != 0 || status.FailedBatches != 1 || status.LastHTTPStatus != statusCode {
					t.Fatalf("incorrect failed response accounting: %+v", status)
				}
			})
		}

	}
}

func TestHECLogsExportSanitizesDecodedResponseText(t *testing.T) {
	for _, test := range []struct{ name, token, response, message string }{
		{"Unicode escape", "super-secret-token", `{"code":4,"text":"\u0073uper-secret-token"}`, "[REDACTED]"},
		{"quote", `secret"token`, `{"code":4,"text":"secret\"token"}`, "[REDACTED]"},
		{"backslash", `secret\token`, `{"code":4,"text":"secret\\token"}`, "[REDACTED]"},
		{"extra fields", "super-secret-token", `{"code":4,"text":"Token refused","debug":"\u0073uper-secret-token"}`, "Token refused"},
	} {
		t.Run(test.name, func(t *testing.T) {
			server, _ := hecTestServer(t, http.StatusForbidden, test.response)
			exp := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Token: test.token})
			err := exp.TestConnection(context.Background(), logsWithRecord(nil, nil, "test"))
			want := "splunk hec returned 403 (code 4): " + test.message
			if err == nil || !strings.HasSuffix(err.Error(), want) || !strings.HasSuffix(exp.Status().LastExportError, want) {
				t.Fatal("error did not use only the sanitized standard response text")
			}
		})
	}
}

func TestHECLogsExportNormalizesSupportedOTLPBodies(t *testing.T) {
	remote, captured := hecTestServer(t, 200, `{"code":0}`)
	exp := newTestHECExporter(t, remote.URL, SplunkHECLogsExporterConfig{Enabled: true, Index: "studio"})
	logs := logsWithRecord(nil, nil, "text")
	records := logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords()
	records.AppendEmpty().Body().SetInt(42)
	records.AppendEmpty().Body().SetBool(false)
	records.AppendEmpty().Body().SetDouble(3.5)
	records.AppendEmpty().Body().SetEmptySlice().AppendEmpty().SetInt(1)
	records.AppendEmpty().Body().SetEmptyBytes().FromRaw([]byte{1, 2})
	records.AppendEmpty().Body().SetEmptyMap().PutStr("key", "value")
	if err := exp.ExportLogs(context.Background(), logs); err != nil {
		t.Fatal(err)
	}
	events := (*captured)[0].events
	if len(events) != 7 || exp.Status().ExportedRecords != 7 {
		t.Fatal("valid mixed bodies were lost")
	}
	for i, want := range []any{"text", "42", "false", "3.5", "[1]", "AQI="} {
		if events[i]["event"] != want {
			t.Fatalf("event %d=%v, want %v", i, events[i]["event"], want)
		}
	}
	if value, ok := events[6]["event"].(map[string]any); !ok || value["key"] != "value" {
		t.Fatal("object body was changed")
	}
	if records.At(1).Body().Type() != pcommon.ValueTypeInt || records.At(4).Body().Type() != pcommon.ValueTypeSlice {
		t.Fatal("export changed the caller's local logs")
	}
}

func TestHECLogsExporterUsesUpstreamRequestBatching(t *testing.T) {
	const requestLimit = 4 << 20
	var requests, accepted, rejected atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Error(err)
			return
		}
		if len(body) > requestLimit {
			rejected.Add(1)
			w.WriteHeader(http.StatusRequestEntityTooLarge)
			return
		}
		var reader io.Reader = bytes.NewReader(body)
		if r.Header.Get("Content-Encoding") == "gzip" {
			zipped, err := gzip.NewReader(reader)
			if err != nil {
				t.Error(err)
				return
			}
			defer zipped.Close()
			reader = zipped
		}
		decoder := json.NewDecoder(reader)
		for {
			var event hecEvent
			if err := decoder.Decode(&event); err == io.EOF {
				break
			} else if err != nil {
				t.Error(err)
				return
			}
			accepted.Add(1)
		}
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	data := make([]byte, 256<<10)
	if _, err := rand.Read(data); err != nil {
		t.Fatal(err)
	}
	payload := base64.StdEncoding.EncodeToString(data)
	logs := logsWithRecord(nil, nil, payload)
	records := logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords()
	for i := 1; i < 12; i++ {
		records.AppendEmpty().Body().SetStr(payload)
	}
	exp := newTestHECExporter(t, remote.URL, SplunkHECLogsExporterConfig{Enabled: true})
	if err := exp.ExportLogs(context.Background(), logs); err != nil {
		t.Fatal(err)
	}
	if requests.Load() < 2 || rejected.Load() != 0 || accepted.Load() != 12 || exp.Status().ExportedRecords != 12 || exp.Status().FailedBatches != 0 {
		t.Fatalf("upstream sizing did not fit the destination: requests=%d rejected=%d accepted=%d status=%+v", requests.Load(), rejected.Load(), accepted.Load(), exp.Status())
	}
}

func TestHECLogsStatusDoesNotCreditRejectedResponses(t *testing.T) {
	for _, tc := range []struct {
		name, body string
	}{
		{"event ordinal", `{"code":7,"invalid-event-number":1}`},
		{"first event rejected", `{"code":7,"invalid-event-number":0}`},
		{"negative ordinal", `{"code":7,"invalid-event-number":-1}`},
		{"out of range ordinal", `{"code":7,"invalid-event-number":9}`},
		{"authentication failure", `{"code":4,"invalid-event-number":1}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			server, _ := hecTestServer(t, http.StatusBadRequest, tc.body)
			exp := newTestHECExporter(t, server.URL, SplunkHECLogsExporterConfig{Enabled: true})
			logs := logsWithRecord(nil, nil, "first")
			logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords().AppendEmpty().Body().SetStr("second")
			if err := exp.ExportLogs(context.Background(), logs); err == nil {
				t.Fatal("expected HEC rejection")
			}
			if got := exp.Status(); got.ExportedRecords != 0 || got.ExportedBatches != 0 || got.FailedBatches != 1 {
				t.Fatal("incorrect accepted count", got)
			}
		})
	}
}
