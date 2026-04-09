package api

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

func mustGet(t *testing.T, url string) *http.Response {
	t.Helper()

	resp, err := http.Get(url)
	if err != nil {
		t.Fatalf("GET %s failed: %v", url, err)
	}
	return resp
}

func mustNewRequest(t *testing.T, method, url string, body io.Reader) *http.Request {
	t.Helper()

	req, err := http.NewRequest(method, url, body)
	if err != nil {
		t.Fatalf("new request %s %s failed: %v", method, url, err)
	}
	return req
}

func mustDo(t *testing.T, req *http.Request) *http.Response {
	t.Helper()

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("%s %s failed: %v", req.Method, req.URL.String(), err)
	}
	return resp
}

func TestQueryTracesSuccess(t *testing.T) {
	// Create store and add test data
	s := store.New()
	span := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "test-span",
		Kind:       "internal",
		StartTime:  time.Now(),
		EndTime:    time.Now().Add(100 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{span})

	// Register handlers and create test server
	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	// Make request
	resp, err := http.Get(server.URL + "/api/query/traces")
	if err != nil {
		t.Fatalf("GET /api/query/traces failed: %v", err)
	}
	defer resp.Body.Close()

	// Verify status code
	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected status 200, got %d", resp.StatusCode)
	}

	// Verify Content-Type header
	if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("expected Content-Type application/json, got %s", ct)
	}

	// Verify CORS headers
	if origin := resp.Header.Get("Access-Control-Allow-Origin"); origin != "*" {
		t.Errorf("expected CORS origin *, got %s", origin)
	}

	// Verify Cache-Control header
	if cache := resp.Header.Get("Cache-Control"); cache != "no-store" {
		t.Errorf("expected Cache-Control no-store, got %s", cache)
	}

	// Verify response is valid JSON array
	var traces []store.TraceSummary
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &traces); err != nil {
		t.Errorf("failed to unmarshal response: %v", err)
	}

	if len(traces) != 1 {
		t.Errorf("expected 1 trace, got %d", len(traces))
	}

	if traces[0].TraceID != "trace-1" {
		t.Errorf("expected trace-1, got %s", traces[0].TraceID)
	}
}

func TestQueryTracesWithLimit(t *testing.T) {
	s := store.New()

	// Add multiple spans in different traces
	for i := 1; i <= 5; i++ {
		span := store.Span{
			TraceID:    fmt.Sprintf("trace-%d", i),
			SpanID:     fmt.Sprintf("span-%d", i),
			Name:       fmt.Sprintf("span-%d", i),
			Kind:       "internal",
			StartTime:  time.Now().Add(time.Duration(-i) * time.Second),
			EndTime:    time.Now().Add(time.Duration(-i) * time.Second).Add(100 * time.Millisecond),
			Status:     store.SpanStatus{Code: "OK"},
			Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
			Scope:      store.Scope{Name: "test-scope"},
			Attributes: map[string]any{},
		}
		s.AddSpansForConnection("", []store.Span{span})
	}

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	// Test default limit
	resp := mustGet(t, server.URL+"/api/query/traces")
	defer resp.Body.Close()
	var traces []store.TraceSummary
	body, _ := io.ReadAll(resp.Body)
	json.Unmarshal(body, &traces)

	if len(traces) != 5 {
		t.Errorf("expected 5 traces (default limit=100), got %d", len(traces))
	}

	// Test with custom limit
	resp = mustGet(t, server.URL+"/api/query/traces?limit=2")
	defer resp.Body.Close()
	body, _ = io.ReadAll(resp.Body)
	json.Unmarshal(body, &traces)

	if len(traces) != 2 {
		t.Errorf("expected 2 traces with limit=2, got %d", len(traces))
	}
}

func TestQueryTraceDetailSuccess(t *testing.T) {
	s := store.New()
	span := store.Span{
		TraceID:    "trace-123",
		SpanID:     "span-1",
		Name:       "root-span",
		Kind:       "internal",
		StartTime:  time.Now(),
		EndTime:    time.Now().Add(100 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{span})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp, err := http.Get(server.URL + "/api/query/traces/trace-123")
	if err != nil {
		t.Fatalf("GET /api/query/traces/trace-123 failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected status 200, got %d", resp.StatusCode)
	}

	var detail store.TraceDetail
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &detail); err != nil {
		t.Errorf("failed to unmarshal response: %v", err)
	}

	if detail.TraceID != "trace-123" {
		t.Errorf("expected trace-123, got %s", detail.TraceID)
	}

	if len(detail.Spans) != 1 {
		t.Errorf("expected 1 span in detail, got %d", len(detail.Spans))
	}

	// Verify CORS and Cache-Control headers
	if origin := resp.Header.Get("Access-Control-Allow-Origin"); origin != "*" {
		t.Errorf("expected CORS origin *, got %s", origin)
	}
	if cache := resp.Header.Get("Cache-Control"); cache != "no-store" {
		t.Errorf("expected Cache-Control no-store, got %s", cache)
	}
}

func TestQueryTraceDetailNotFound(t *testing.T) {
	s := store.New()

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp, err := http.Get(server.URL + "/api/query/traces/nonexistent")
	if err != nil {
		t.Fatalf("GET /api/query/traces/nonexistent failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusNotFound {
		t.Errorf("expected status 404, got %d", resp.StatusCode)
	}
}

func TestQueryMetricsSuccess(t *testing.T) {
	s := store.New()
	metric := store.MetricDataPoint{
		Name:       "http.requests",
		Type:       "sum",
		Timestamp:  time.Now(),
		Value:      42,
		Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddMetricsForConnection("", []store.MetricDataPoint{metric})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp, err := http.Get(server.URL + "/api/query/metrics")
	if err != nil {
		t.Fatalf("GET /api/query/metrics failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected status 200, got %d", resp.StatusCode)
	}

	if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("expected Content-Type application/json, got %s", ct)
	}

	var groups []store.MetricGroup
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &groups); err != nil {
		t.Errorf("failed to unmarshal response: %v", err)
	}

	if len(groups) != 1 {
		t.Errorf("expected 1 metric group, got %d", len(groups))
	}

	if groups[0].Name != "http.requests" {
		t.Errorf("expected http.requests, got %s", groups[0].Name)
	}
}

func TestQueryLogsSuccess(t *testing.T) {
	s := store.New()
	log := store.LogRecord{
		Timestamp:    time.Now(),
		Body:         "test log message",
		SeverityText: "INFO",
		Resource:     store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:        store.Scope{Name: "test-scope"},
		Attributes:   map[string]any{},
	}
	s.AddLogsForConnection("", []store.LogRecord{log})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp, err := http.Get(server.URL + "/api/query/logs")
	if err != nil {
		t.Fatalf("GET /api/query/logs failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected status 200, got %d", resp.StatusCode)
	}

	if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("expected Content-Type application/json, got %s", ct)
	}

	var logs []store.LogRecord
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &logs); err != nil {
		t.Errorf("failed to unmarshal response: %v", err)
	}

	if len(logs) != 1 {
		t.Errorf("expected 1 log, got %d", len(logs))
	}

	if logs[0].Body != "test log message" {
		t.Errorf("expected 'test log message', got %s", logs[0].Body)
	}
}

func TestQueryStatsSuccess(t *testing.T) {
	s := store.New()

	// Add one span, one metric, one log
	span := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "test-span",
		Kind:       "internal",
		StartTime:  time.Now(),
		EndTime:    time.Now().Add(100 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "svc1", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{span})

	metric := store.MetricDataPoint{
		Name:       "cpu.usage",
		Type:       "gauge",
		Timestamp:  time.Now(),
		Value:      50,
		Resource:   store.Resource{ServiceName: "svc1", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddMetricsForConnection("", []store.MetricDataPoint{metric})

	log := store.LogRecord{
		Timestamp:    time.Now(),
		Body:         "test log",
		SeverityText: "INFO",
		Resource:     store.Resource{ServiceName: "svc1", Attributes: map[string]any{}},
		Scope:        store.Scope{Name: "test-scope"},
		Attributes:   map[string]any{},
	}
	s.AddLogsForConnection("", []store.LogRecord{log})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp, err := http.Get(server.URL + "/api/query/stats")
	if err != nil {
		t.Fatalf("GET /api/query/stats failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected status 200, got %d", resp.StatusCode)
	}

	var stats store.Stats
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &stats); err != nil {
		t.Errorf("failed to unmarshal response: %v", err)
	}

	if stats.SpanCount != 1 {
		t.Errorf("expected spanCount=1, got %d", stats.SpanCount)
	}

	if stats.DataPointCount != 1 {
		t.Errorf("expected dataPointCount=1, got %d", stats.DataPointCount)
	}

	if stats.LogCount != 1 {
		t.Errorf("expected logCount=1, got %d", stats.LogCount)
	}

	if stats.TraceCount != 1 {
		t.Errorf("expected traceCount=1, got %d", stats.TraceCount)
	}

	// Verify dataPointCount field exists (renamed from metricCount)
	if stats.DataPointCount == 0 {
		t.Errorf("stats should have dataPointCount field")
	}
}

func TestClearData(t *testing.T) {
	s := store.New()

	// Add test data
	span := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "test-span",
		Kind:       "internal",
		StartTime:  time.Now(),
		EndTime:    time.Now().Add(100 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{span})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	// Verify data exists
	resp := mustGet(t, server.URL+"/api/query/stats")
	defer resp.Body.Close()
	var stats1 store.Stats
	body, _ := io.ReadAll(resp.Body)
	json.Unmarshal(body, &stats1)
	if stats1.SpanCount != 1 {
		t.Errorf("expected 1 span before clear, got %d", stats1.SpanCount)
	}

	// Delete data
	req := mustNewRequest(t, "DELETE", server.URL+"/api/data", nil)
	resp = mustDo(t, req)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("DELETE /api/data expected status 200, got %d", resp.StatusCode)
	}

	// Verify data is cleared
	resp = mustGet(t, server.URL+"/api/query/stats")
	defer resp.Body.Close()
	var stats2 store.Stats
	body, _ = io.ReadAll(resp.Body)
	json.Unmarshal(body, &stats2)

	if stats2.SpanCount != 0 {
		t.Errorf("expected 0 spans after clear, got %d", stats2.SpanCount)
	}
	if stats2.DataPointCount != 0 {
		t.Errorf("expected 0 dataPoints after clear, got %d", stats2.DataPointCount)
	}
	if stats2.LogCount != 0 {
		t.Errorf("expected 0 logs after clear, got %d", stats2.LogCount)
	}
}

func TestCORSHeaders(t *testing.T) {
	s := store.New()

	// Add some data
	span := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "test-span",
		Kind:       "internal",
		StartTime:  time.Now(),
		EndTime:    time.Now().Add(100 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{span})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	endpoints := []string{
		"/api/query/traces",
		"/api/query/metrics",
		"/api/query/logs",
		"/api/query/stats",
	}

	for _, endpoint := range endpoints {
		resp := mustGet(t, server.URL+endpoint)
		defer resp.Body.Close()

		if origin := resp.Header.Get("Access-Control-Allow-Origin"); origin != "*" {
			t.Errorf("%s: expected CORS origin *, got %s", endpoint, origin)
		}

		if cache := resp.Header.Get("Cache-Control"); cache != "no-store" {
			t.Errorf("%s: expected Cache-Control no-store, got %s", endpoint, cache)
		}

		if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
			t.Errorf("%s: expected Content-Type application/json, got %s", endpoint, ct)
		}
	}
}

func TestQueryIntParsingValid(t *testing.T) {
	s := store.New()

	// Add multiple spans to test limit parameter
	for i := 1; i <= 10; i++ {
		span := store.Span{
			TraceID:    fmt.Sprintf("trace-%d", i),
			SpanID:     fmt.Sprintf("span-%d", i),
			Name:       fmt.Sprintf("span-%d", i),
			Kind:       "internal",
			StartTime:  time.Now(),
			EndTime:    time.Now().Add(100 * time.Millisecond),
			Status:     store.SpanStatus{Code: "OK"},
			Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
			Scope:      store.Scope{Name: "test-scope"},
			Attributes: map[string]any{},
		}
		s.AddSpansForConnection("", []store.Span{span})
	}

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	// Test valid int parsing
	resp := mustGet(t, server.URL+"/api/query/traces?limit=5")
	defer resp.Body.Close()
	var traces []store.TraceSummary
	body, _ := io.ReadAll(resp.Body)
	json.Unmarshal(body, &traces)

	if len(traces) != 5 {
		t.Errorf("expected 5 traces with limit=5, got %d", len(traces))
	}
}

// TestQueryIntDirect tests the queryInt function directly to verify default,
// parsing, negative, and clamping behaviour without relying on fixture sizes.
func TestQueryIntDirect(t *testing.T) {
	tests := []struct {
		name     string
		url      string
		key      string
		def      int
		expected int
	}{
		{"empty param returns default", "/api?", "limit", 100, 100},
		{"missing key returns default", "/api?other=5", "limit", 100, 100},
		{"valid int returns parsed value", "/api?limit=42", "limit", 100, 42},
		{"zero returns zero", "/api?limit=0", "limit", 100, 0},
		{"negative returns default", "/api?limit=-5", "limit", 100, 100},
		{"non-numeric returns default", "/api?limit=abc", "limit", 100, 100},
		{"exceeds maxLimit returns maxLimit (10000)", "/api?limit=99999", "limit", 100, 10_000},
		{"exactly maxLimit returns maxLimit", "/api?limit=10000", "limit", 100, 10_000},
		{"just below maxLimit returns value", "/api?limit=9999", "limit", 100, 9999},
		{"float returns default", "/api?limit=3.14", "limit", 100, 100},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			req, err := http.NewRequest("GET", tc.url, nil)
			if err != nil {
				t.Fatalf("failed to create request: %v", err)
			}
			got := queryInt(req, tc.key, tc.def)
			if got != tc.expected {
				t.Errorf("queryInt(%q, %q, %d) = %d, want %d", tc.url, tc.key, tc.def, got, tc.expected)
			}
		})
	}
}

// TestQueryIntViaHTTPEndpoint verifies limit actually constrains results through the HTTP handler.
func TestQueryIntViaHTTPEndpoint(t *testing.T) {
	s := store.New()

	// Add 10 distinct traces so there is enough data to actually test limiting.
	for i := 1; i <= 10; i++ {
		span := store.Span{
			TraceID:    fmt.Sprintf("trace-%02d", i),
			SpanID:     fmt.Sprintf("span-%02d", i),
			Name:       fmt.Sprintf("span-%d", i),
			Kind:       "internal",
			StartTime:  time.Now().Add(time.Duration(i) * time.Millisecond),
			EndTime:    time.Now().Add(time.Duration(i)*time.Millisecond + 100*time.Millisecond),
			Status:     store.SpanStatus{Code: "OK"},
			Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
			Scope:      store.Scope{Name: "test-scope"},
			Attributes: map[string]any{},
		}
		s.AddSpansForConnection("", []store.Span{span})
	}

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	// limit=3 should return exactly 3 traces out of 10.
	resp, err := http.Get(server.URL + "/api/query/traces?limit=3")
	if err != nil {
		t.Fatalf("GET failed: %v", err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	var traces []store.TraceSummary
	json.Unmarshal(body, &traces)
	if len(traces) != 3 {
		t.Errorf("expected 3 traces with limit=3, got %d", len(traces))
	}

	// invalid limit should fall back to default (100), returning all 10.
	resp, err = http.Get(server.URL + "/api/query/traces?limit=abc")
	if err != nil {
		t.Fatalf("GET failed: %v", err)
	}
	body, _ = io.ReadAll(resp.Body)
	resp.Body.Close()
	var traces2 []store.TraceSummary
	json.Unmarshal(body, &traces2)
	if len(traces2) != 10 {
		t.Errorf("expected 10 traces with invalid limit (default 100), got %d", len(traces2))
	}

	// negative limit should fall back to default (100), returning all 10.
	resp, err = http.Get(server.URL + "/api/query/traces?limit=-1")
	if err != nil {
		t.Fatalf("GET failed: %v", err)
	}
	body, _ = io.ReadAll(resp.Body)
	resp.Body.Close()
	var traces3 []store.TraceSummary
	json.Unmarshal(body, &traces3)
	if len(traces3) != 10 {
		t.Errorf("expected 10 traces with negative limit (default 100), got %d", len(traces3))
	}
}

func TestOptionsPreflight(t *testing.T) {
	s := store.New()

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	req := mustNewRequest(t, "OPTIONS", server.URL+"/api/", nil)
	resp := mustDo(t, req)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusNoContent {
		t.Errorf("expected status 204, got %d", resp.StatusCode)
	}

	if origin := resp.Header.Get("Access-Control-Allow-Origin"); origin != "*" {
		t.Errorf("expected CORS origin *, got %s", origin)
	}

	methods := resp.Header.Get("Access-Control-Allow-Methods")
	if methods == "" {
		t.Errorf("expected Access-Control-Allow-Methods header, got empty")
	}

	headers := resp.Header.Get("Access-Control-Allow-Headers")
	if headers == "" {
		t.Errorf("expected Access-Control-Allow-Headers header, got empty")
	}
}

func TestContentTypeApplicationJSON(t *testing.T) {
	s := store.New()

	span := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "test-span",
		Kind:       "internal",
		StartTime:  time.Now(),
		EndTime:    time.Now().Add(100 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{span})

	metric := store.MetricDataPoint{
		Name:       "test.metric",
		Type:       "gauge",
		Timestamp:  time.Now(),
		Value:      42,
		Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddMetricsForConnection("", []store.MetricDataPoint{metric})

	log := store.LogRecord{
		Timestamp:    time.Now(),
		Body:         "test log",
		SeverityText: "INFO",
		Resource:     store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:        store.Scope{Name: "test-scope"},
		Attributes:   map[string]any{},
	}
	s.AddLogsForConnection("", []store.LogRecord{log})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	endpoints := []string{
		"/api/query/traces",
		"/api/query/traces/trace-1",
		"/api/query/metrics",
		"/api/query/logs",
		"/api/query/stats",
	}

	for _, endpoint := range endpoints {
		resp := mustGet(t, server.URL+endpoint)
		defer resp.Body.Close()

		ct := resp.Header.Get("Content-Type")
		if ct != "application/json" {
			t.Errorf("%s: expected Content-Type application/json, got %s", endpoint, ct)
		}
	}
}

func TestMultipleTraces(t *testing.T) {
	s := store.New()

	// Add spans for multiple traces
	trace1Span := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1-root",
		Name:       "root-1",
		Kind:       "internal",
		StartTime:  time.Now().Add(-2 * time.Second),
		EndTime:    time.Now().Add(-2 * time.Second).Add(500 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "service-1", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "scope-1"},
		Attributes: map[string]any{},
	}

	trace2Span := store.Span{
		TraceID:    "trace-2",
		SpanID:     "span-2-root",
		Name:       "root-2",
		Kind:       "server",
		StartTime:  time.Now().Add(-1 * time.Second),
		EndTime:    time.Now().Add(-1 * time.Second).Add(300 * time.Millisecond),
		Status:     store.SpanStatus{Code: "ERROR", Message: "test error"},
		Resource:   store.Resource{ServiceName: "service-2", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "scope-2"},
		Attributes: map[string]any{},
	}

	s.AddSpansForConnection("", []store.Span{trace1Span, trace2Span})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	// Query traces - should return both, newest first
	resp := mustGet(t, server.URL+"/api/query/traces?limit=10")
	defer resp.Body.Close()
	var traces []store.TraceSummary
	body, _ := io.ReadAll(resp.Body)
	json.Unmarshal(body, &traces)

	if len(traces) != 2 {
		t.Errorf("expected 2 traces, got %d", len(traces))
	}

	// Verify trace 2 comes first (newest)
	if traces[0].TraceID != "trace-2" {
		t.Errorf("expected trace-2 first (newest), got %s", traces[0].TraceID)
	}
	if traces[1].TraceID != "trace-1" {
		t.Errorf("expected trace-1 second, got %s", traces[1].TraceID)
	}

	// Verify status computation
	if traces[0].Status != "error" {
		t.Errorf("expected trace-2 status 'error', got %s", traces[0].Status)
	}
	if traces[1].Status != "ok" {
		t.Errorf("expected trace-1 status 'ok', got %s", traces[1].Status)
	}
}

func TestClearDataResponse(t *testing.T) {
	s := store.New()

	span := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "test-span",
		Kind:       "internal",
		StartTime:  time.Now(),
		EndTime:    time.Now().Add(100 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{span})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	req := mustNewRequest(t, "DELETE", server.URL+"/api/data", nil)
	resp := mustDo(t, req)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected status 200, got %d", resp.StatusCode)
	}

	var result map[string]string
	body, _ := io.ReadAll(resp.Body)
	json.Unmarshal(body, &result)

	if result["status"] != "cleared" {
		t.Errorf("expected status 'cleared', got %s", result["status"])
	}

	if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("expected Content-Type application/json, got %s", ct)
	}
}

func TestTraceDetailEventLimit(t *testing.T) {
	s := store.New()

	// Create a span with many events
	events := make([]store.SpanEvent, 20)
	for i := 0; i < 20; i++ {
		events[i] = store.SpanEvent{
			Name:       fmt.Sprintf("event-%d", i),
			Timestamp:  time.Now().Add(time.Duration(i) * time.Millisecond),
			Attributes: map[string]any{},
		}
	}

	span := store.Span{
		TraceID:    "trace-123",
		SpanID:     "span-1",
		Name:       "test-span",
		Kind:       "internal",
		StartTime:  time.Now(),
		EndTime:    time.Now().Add(100 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Events:     events,
		Resource:   store.Resource{ServiceName: "test-service", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{span})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	// Query with default eventLimit (12)
	resp := mustGet(t, server.URL+"/api/query/traces/trace-123")
	defer resp.Body.Close()
	var detail store.TraceDetail
	body, _ := io.ReadAll(resp.Body)
	json.Unmarshal(body, &detail)

	if len(detail.Spans[0].Events) != 12 {
		t.Errorf("expected 12 events with default limit, got %d", len(detail.Spans[0].Events))
	}

	// Query with custom eventLimit
	resp = mustGet(t, server.URL+"/api/query/traces/trace-123?eventLimit=5")
	defer resp.Body.Close()
	var detail2 store.TraceDetail
	body, _ = io.ReadAll(resp.Body)
	json.Unmarshal(body, &detail2)

	if len(detail2.Spans[0].Events) != 5 {
		t.Errorf("expected 5 events with eventLimit=5, got %d", len(detail2.Spans[0].Events))
	}
}
