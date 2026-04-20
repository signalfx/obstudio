package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
)

type fakeValidationRunner struct {
	summary validator.Summary
	calls   int
	onRun   func(context.Context) validator.Summary
}

func (f *fakeValidationRunner) Run(context.Context) validator.Summary {
	f.calls++
	if f.onRun != nil {
		return f.onRun(context.Background())
	}
	return f.summary
}

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

func TestQueryTracesWithSummaryFieldFilters(t *testing.T) {
	s := store.New()
	now := time.Now()

	trace1 := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "GET /orders",
		Kind:       "internal",
		StartTime:  now,
		EndTime:    now.Add(10 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	trace2Root := store.Span{
		TraceID:    "trace-2",
		SpanID:     "span-1",
		Name:       "POST /checkout",
		Kind:       "internal",
		StartTime:  now.Add(100 * time.Millisecond),
		EndTime:    now.Add(130 * time.Millisecond),
		Status:     store.SpanStatus{Code: "ERROR"},
		Resource:   store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	trace2Child := store.Span{
		TraceID:      "trace-2",
		SpanID:       "span-2",
		ParentSpanID: "span-1",
		Name:         "db.write",
		Kind:         "client",
		StartTime:    now.Add(110 * time.Millisecond),
		EndTime:      now.Add(115 * time.Millisecond),
		Status:       store.SpanStatus{Code: "ERROR"},
		Resource:     store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
		Scope:        store.Scope{Name: "test-scope"},
		Attributes:   map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{trace1})
	s.AddSpansForConnection("", []store.Span{trace2Root, trace2Child})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	query := url.Values{
		"filter[traceId]":        {"trace-2"},
		"filter[rootSpanName]":   {"post /checkout"},
		"filter[serviceName]":    {"PAYMENTS"},
		"filter[status]":         {"error"},
		"range[spanCount][gte]":  {"2"},
		"range[spanCount][lte]":  {"2"},
		"range[durationMs][gte]": {"30"},
		"range[durationMs][lte]": {"30"},
		"time[from]":             {now.Add(90 * time.Millisecond).UTC().Format(time.RFC3339Nano)},
		"time[to]":               {now.Add(140 * time.Millisecond).UTC().Format(time.RFC3339Nano)},
	}
	resp := mustGet(t, server.URL+"/api/query/traces?"+query.Encode())
	defer resp.Body.Close()

	var traces []store.TraceSummary
	if err := json.NewDecoder(resp.Body).Decode(&traces); err != nil {
		t.Fatalf("decode traces: %v", err)
	}
	if len(traces) != 1 {
		t.Fatalf("expected 1 filtered trace, got %d", len(traces))
	}
	if traces[0].TraceID != "trace-2" {
		t.Fatalf("expected trace-2, got %s", traces[0].TraceID)
	}
}

func TestQueryTracesWithServerSideQueryFilter(t *testing.T) {
	s := store.New()
	now := time.Now()

	trace1 := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "GET /orders",
		Kind:       "internal",
		StartTime:  now,
		EndTime:    now.Add(10 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	trace2 := store.Span{
		TraceID:    "trace-2",
		SpanID:     "span-1",
		Name:       "POST /charge",
		Kind:       "internal",
		StartTime:  now.Add(100 * time.Millisecond),
		EndTime:    now.Add(120 * time.Millisecond),
		Status:     store.SpanStatus{Code: "ERROR"},
		Resource:   store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{trace1, trace2})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/traces?query=charge")
	defer resp.Body.Close()

	var traces []store.TraceSummary
	if err := json.NewDecoder(resp.Body).Decode(&traces); err != nil {
		t.Fatalf("decode traces: %v", err)
	}
	if len(traces) != 1 {
		t.Fatalf("expected 1 query-filtered trace, got %d", len(traces))
	}
	if traces[0].TraceID != "trace-2" {
		t.Fatalf("expected trace-2, got %s", traces[0].TraceID)
	}
}

func TestQueryTraceFilterValues(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("", []store.Span{
		{
			TraceID:   "trace-1",
			SpanID:    "span-1",
			Name:      "GET /orders",
			Kind:      "internal",
			StartTime: now,
			EndTime:   now.Add(10 * time.Millisecond),
			Status:    store.SpanStatus{Code: "OK"},
			Resource:  store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
			Scope:     store.Scope{Name: "test-scope"},
		},
		{
			TraceID:   "trace-2",
			SpanID:    "span-2",
			Name:      "POST /charge",
			Kind:      "internal",
			StartTime: now.Add(time.Second),
			EndTime:   now.Add(time.Second + 10*time.Millisecond),
			Status:    store.SpanStatus{Code: "ERROR"},
			Resource:  store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
			Scope:     store.Scope{Name: "test-scope"},
		},
	})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/traces/filter-values?field=serviceName&prefix=pa")
	defer resp.Body.Close()

	var values []string
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &values); err != nil {
		t.Fatalf("unmarshal values: %v", err)
	}
	if len(values) != 1 || values[0] != "payments" {
		t.Fatalf("expected [payments], got %v", values)
	}
}

func TestQueryTracesWithNegatedSummaryFieldFilters(t *testing.T) {
	s := store.New()
	now := time.Now()

	trace1 := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "GET /orders",
		Kind:       "internal",
		StartTime:  now,
		EndTime:    now.Add(10 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	trace2 := store.Span{
		TraceID:    "trace-2",
		SpanID:     "span-1",
		Name:       "POST /checkout",
		Kind:       "internal",
		StartTime:  now.Add(100 * time.Millisecond),
		EndTime:    now.Add(130 * time.Millisecond),
		Status:     store.SpanStatus{Code: "ERROR"},
		Resource:   store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{trace1, trace2})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	query := url.Values{
		"filter[serviceName][neq]": {"checkout"},
		"filter[status][neq]":      {"ok"},
	}
	resp := mustGet(t, server.URL+"/api/query/traces?"+query.Encode())
	defer resp.Body.Close()

	var traces []store.TraceSummary
	if err := json.NewDecoder(resp.Body).Decode(&traces); err != nil {
		t.Fatalf("decode traces: %v", err)
	}
	if len(traces) != 1 {
		t.Fatalf("expected 1 negated trace, got %d", len(traces))
	}
	if traces[0].TraceID != "trace-2" {
		t.Fatalf("expected trace-2, got %s", traces[0].TraceID)
	}
}

func TestQueryTracesWithComplementaryRangeAndTimeFilters(t *testing.T) {
	s := store.New()
	now := time.Now()

	trace1 := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "GET /orders",
		Kind:       "internal",
		StartTime:  now,
		EndTime:    now.Add(20 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	trace2 := store.Span{
		TraceID:    "trace-2",
		SpanID:     "span-1",
		Name:       "POST /checkout",
		Kind:       "internal",
		StartTime:  now.Add(100 * time.Millisecond),
		EndTime:    now.Add(180 * time.Millisecond),
		Status:     store.SpanStatus{Code: "ERROR"},
		Resource:   store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{trace1, trace2})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	query := url.Values{
		"range[durationMs][lt]": {"50"},
		"time[before]":          {now.Add(50 * time.Millisecond).UTC().Format(time.RFC3339Nano)},
	}
	resp := mustGet(t, server.URL+"/api/query/traces?"+query.Encode())
	defer resp.Body.Close()

	var traces []store.TraceSummary
	if err := json.NewDecoder(resp.Body).Decode(&traces); err != nil {
		t.Fatalf("decode traces: %v", err)
	}
	if len(traces) != 1 {
		t.Fatalf("expected 1 complementary trace, got %d", len(traces))
	}
	if traces[0].TraceID != "trace-1" {
		t.Fatalf("expected trace-1, got %s", traces[0].TraceID)
	}
}

func TestQueryTracesWithSummaryRangeFilters(t *testing.T) {
	s := store.New()
	now := time.Now()

	trace1 := store.Span{
		TraceID:    "trace-1",
		SpanID:     "span-1",
		Name:       "trace-one",
		Kind:       "internal",
		StartTime:  now,
		EndTime:    now.Add(10 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	trace2Root := store.Span{
		TraceID:    "trace-2",
		SpanID:     "span-1",
		Name:       "trace-two",
		Kind:       "internal",
		StartTime:  now.Add(100 * time.Millisecond),
		EndTime:    now.Add(130 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	trace2Child := store.Span{
		TraceID:      "trace-2",
		SpanID:       "span-2",
		ParentSpanID: "span-1",
		Name:         "child",
		Kind:         "client",
		StartTime:    now.Add(110 * time.Millisecond),
		EndTime:      now.Add(115 * time.Millisecond),
		Status:       store.SpanStatus{Code: "OK"},
		Resource:     store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:        store.Scope{Name: "test-scope"},
		Attributes:   map[string]any{},
	}
	trace3Root := store.Span{
		TraceID:    "trace-3",
		SpanID:     "span-1",
		Name:       "trace-three",
		Kind:       "internal",
		StartTime:  now.Add(200 * time.Millisecond),
		EndTime:    now.Add(260 * time.Millisecond),
		Status:     store.SpanStatus{Code: "OK"},
		Resource:   store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
		Attributes: map[string]any{},
	}
	trace3Child := store.Span{
		TraceID:      "trace-3",
		SpanID:       "span-2",
		ParentSpanID: "span-1",
		Name:         "child",
		Kind:         "client",
		StartTime:    now.Add(210 * time.Millisecond),
		EndTime:      now.Add(220 * time.Millisecond),
		Status:       store.SpanStatus{Code: "OK"},
		Resource:     store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:        store.Scope{Name: "test-scope"},
		Attributes:   map[string]any{},
	}
	s.AddSpansForConnection("", []store.Span{trace1})
	s.AddSpansForConnection("", []store.Span{trace2Root, trace2Child})
	s.AddSpansForConnection("", []store.Span{trace3Root, trace3Child})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/traces?minSpanCount=2&maxSpanCount=2&minDurationMs=20&maxDurationMs=40")
	defer resp.Body.Close()

	var traces []store.TraceSummary
	if err := json.NewDecoder(resp.Body).Decode(&traces); err != nil {
		t.Fatalf("decode traces: %v", err)
	}
	if len(traces) != 1 {
		t.Fatalf("expected 1 ranged trace, got %d", len(traces))
	}
	if traces[0].TraceID != "trace-2" {
		t.Fatalf("expected trace-2, got %s", traces[0].TraceID)
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

func TestQueryValidationEndpoints(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	v.SetRuntimeStatus(validator.StatusReady, "ready")
	v.UpsertEntity(validator.Entity{
		Key:             "span:trace-1:span-1",
		HighestSeverity: validator.SeverityViolation,
		Signal:          validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
		UpdatedAt:       time.Now(),
		Findings: []validator.Finding{
			{
				EntityKey: "span:trace-1:span-1",
				Source:    "weaver",
				RuleID:    "missing_attribute",
				Severity:  validator.SeverityViolation,
				Message:   "missing attribute",
				Signal:    validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
				UpdatedAt: time.Now(),
			},
		},
	})

	mux := http.NewServeMux()
	Register(mux, s, v)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/validation/summary")
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var summary validator.Summary
	if err := json.NewDecoder(resp.Body).Decode(&summary); err != nil {
		t.Fatalf("decode summary: %v", err)
	}
	if !summary.Ready || summary.TotalAdvisories != 1 {
		t.Fatalf("unexpected summary: %+v", summary)
	}

	resp = mustGet(t, server.URL+"/api/query/validation/findings?serviceName=checkout")
	defer resp.Body.Close()
	var findings []validator.Finding
	if err := json.NewDecoder(resp.Body).Decode(&findings); err != nil {
		t.Fatalf("decode findings: %v", err)
	}
	if len(findings) != 1 || findings[0].RuleID != "missing_attribute" {
		t.Fatalf("unexpected findings: %+v", findings)
	}
}

func TestQueryValidationStatusEndpoint(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")

	mux := http.NewServeMux()
	Register(mux, s, v)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/validation/status")
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var summary validator.Summary
	if err := json.NewDecoder(resp.Body).Decode(&summary); err != nil {
		t.Fatalf("decode summary: %v", err)
	}
	if summary.Status != validator.StatusIdle {
		t.Fatalf("unexpected summary: %+v", summary)
	}
}

func TestAnalyzeValidationAutoRunsWhenNoResult(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
	runner := &fakeValidationRunner{
		onRun: func(context.Context) validator.Summary {
			summary := v.StartRun("run-21", time.Unix(10, 0))
			go func() {
				time.Sleep(20 * time.Millisecond)
				v.CompleteRun("run-21", map[string]validator.Entity{
					"span:trace-1:span-1": {
						Key:             "span:trace-1:span-1",
						HighestSeverity: validator.SeverityViolation,
						Signal:          validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
						UpdatedAt:       time.Unix(20, 0),
						Findings: []validator.Finding{{
							EntityKey: "span:trace-1:span-1",
							Source:    "weaver",
							RuleID:    "missing_attribute",
							Severity:  validator.SeverityViolation,
							Message:   "missing attribute",
							Signal:    validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
							UpdatedAt: time.Unix(20, 0),
						}},
					},
				}, validator.RunStats{}, time.Unix(20, 0))
			}()
			return summary
		},
	}

	mux := http.NewServeMux()
	Register(mux, s, v, runner)
	server := httptest.NewServer(mux)
	defer server.Close()

	req := mustNewRequest(t, http.MethodPost, server.URL+"/api/validation/analyze", strings.NewReader(`{"timeoutSeconds":5}`))
	req.Header.Set("Content-Type", "application/json")
	resp := mustDo(t, req)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	if runner.calls != 1 {
		t.Fatalf("expected runner to be called once, got %d", runner.calls)
	}

	var analysis validator.Analysis
	if err := json.NewDecoder(resp.Body).Decode(&analysis); err != nil {
		t.Fatalf("decode analysis: %v", err)
	}
	if analysis.AnalysisBasis != validator.AnalysisBasisFreshRun {
		t.Fatalf("unexpected analysis: %+v", analysis)
	}
	if len(analysis.Findings) != 1 {
		t.Fatalf("expected findings from fresh run, got %+v", analysis)
	}
}

func TestAnalyzeValidationReturnsStoredStaleResult(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	startedAt := time.Unix(10, 0)
	completedAt := time.Unix(20, 0)
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
	v.StartRun("run-22", startedAt)
	v.CompleteRun("run-22", map[string]validator.Entity{
		"metric:checkout::http.server.duration": {
			Key:             "metric:checkout::http.server.duration",
			HighestSeverity: validator.SeverityImprovement,
			Signal:          validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
			UpdatedAt:       completedAt,
			Findings: []validator.Finding{{
				EntityKey: "metric:checkout::http.server.duration",
				Source:    "weaver",
				RuleID:    "deprecated",
				Severity:  validator.SeverityImprovement,
				Message:   "deprecated metric",
				Signal:    validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
				UpdatedAt: completedAt,
			}},
		},
	}, validator.RunStats{}, completedAt)
	v.MarkTelemetryChanged(time.Unix(30, 0))

	mux := http.NewServeMux()
	Register(mux, s, v)
	server := httptest.NewServer(mux)
	defer server.Close()

	req := mustNewRequest(t, http.MethodPost, server.URL+"/api/validation/analyze", strings.NewReader(`{"serviceName":"checkout"}`))
	req.Header.Set("Content-Type", "application/json")
	resp := mustDo(t, req)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var analysis validator.Analysis
	if err := json.NewDecoder(resp.Body).Decode(&analysis); err != nil {
		t.Fatalf("decode analysis: %v", err)
	}
	if analysis.AnalysisBasis != validator.AnalysisBasisStaleResult {
		t.Fatalf("expected stale basis, got %+v", analysis)
	}
	if !strings.Contains(analysis.AnalysisMessage, "based on run run-22 completed at") {
		t.Fatalf("expected stale analysis message, got %+v", analysis)
	}
}

func TestRefreshValidationEndpointReturnsFreshAnalysis(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	runner := &fakeValidationRunner{
		onRun: func(context.Context) validator.Summary {
			summary := v.StartRun("run-23", time.Unix(10, 0))
			go func() {
				time.Sleep(20 * time.Millisecond)
				v.CompleteRun("run-23", map[string]validator.Entity{
					"log:checkout": {
						Key:             "log:checkout",
						HighestSeverity: validator.SeverityInformation,
						Signal:          validator.SignalRef{Type: "log", ServiceName: "checkout", LogBody: "slow query"},
						UpdatedAt:       time.Unix(20, 0),
						Findings: []validator.Finding{{
							EntityKey: "log:checkout",
							Source:    "weaver",
							RuleID:    "unstable",
							Severity:  validator.SeverityInformation,
							Message:   "unstable semantic convention",
							Signal:    validator.SignalRef{Type: "log", ServiceName: "checkout", LogBody: "slow query"},
							UpdatedAt: time.Unix(20, 0),
						}},
					},
				}, validator.RunStats{}, time.Unix(20, 0))
			}()
			return summary
		},
	}

	mux := http.NewServeMux()
	Register(mux, s, v, runner)
	server := httptest.NewServer(mux)
	defer server.Close()

	req := mustNewRequest(t, http.MethodPost, server.URL+"/api/validation/refresh", strings.NewReader(`{"timeoutSeconds":5}`))
	req.Header.Set("Content-Type", "application/json")
	resp := mustDo(t, req)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var analysis validator.Analysis
	if err := json.NewDecoder(resp.Body).Decode(&analysis); err != nil {
		t.Fatalf("decode analysis: %v", err)
	}
	if analysis.AnalysisBasis != validator.AnalysisBasisFreshRun {
		t.Fatalf("expected fresh run analysis, got %+v", analysis)
	}
}

func TestQueryHealthIncludesServerInfoAndEndpoints(t *testing.T) {
	s := store.New()
	s.SetEndpoints(store.Endpoints{
		OTLPHTTP: "http://127.0.0.1:4318",
		OTLPgRPC: "127.0.0.1:4317",
		REST:     "http://127.0.0.1:3000",
	})
	startedAt := time.Date(2026, time.April, 10, 8, 0, 0, 0, time.UTC)

	mux := http.NewServeMux()
	Register(mux, s, ServerInfo{
		Kind:       "obstudio",
		APIVersion: "v1",
		Version:    "0.0.1",
		Owner:      "extension",
		Mode:       "shared-fixed",
		StartedAt:  startedAt,
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/health")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected status 200, got %d", resp.StatusCode)
	}

	var health healthResponse
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &health); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	if health.Kind != "obstudio" {
		t.Fatalf("expected kind obstudio, got %q", health.Kind)
	}
	if health.APIVersion != "v1" {
		t.Fatalf("expected apiVersion v1, got %q", health.APIVersion)
	}
	if health.Version != "0.0.1" {
		t.Fatalf("expected version 0.0.1, got %q", health.Version)
	}
	if health.Owner != "extension" {
		t.Fatalf("expected owner extension, got %q", health.Owner)
	}
	if health.Mode != "shared-fixed" {
		t.Fatalf("expected mode shared-fixed, got %q", health.Mode)
	}
	if !health.StartedAt.Equal(startedAt) {
		t.Fatalf("expected startedAt %s, got %s", startedAt, health.StartedAt)
	}
	if health.Endpoints["rest"] != "http://127.0.0.1:3000" {
		t.Fatalf("expected rest endpoint http://127.0.0.1:3000, got %q", health.Endpoints["rest"])
	}
	if health.Endpoints["mcp"] != "http://127.0.0.1:3000/mcp" {
		t.Fatalf("expected mcp endpoint http://127.0.0.1:3000/mcp, got %q", health.Endpoints["mcp"])
	}
	if health.Endpoints["otlpHttp"] != "http://127.0.0.1:4318" {
		t.Fatalf("expected otlpHttp endpoint http://127.0.0.1:4318, got %q", health.Endpoints["otlpHttp"])
	}
	if health.Endpoints["otlpGrpc"] != "127.0.0.1:4317" {
		t.Fatalf("expected otlpGrpc endpoint 127.0.0.1:4317, got %q", health.Endpoints["otlpGrpc"])
	}
}

func TestValidationFindingsFailClosedWhenNoFreshResult(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")

	mux := http.NewServeMux()
	Register(mux, s, v)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/validation/findings")
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("expected 409, got %d", resp.StatusCode)
	}

	var payload map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		t.Fatalf("decode payload: %v", err)
	}
	if payload["nextAction"] == nil {
		t.Fatalf("expected nextAction in fail-closed payload: %+v", payload)
	}
}

func TestValidationLatestReturnsStoredStaleResult(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	startedAt := time.Unix(10, 0)
	completedAt := time.Unix(20, 0)
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
	v.StartRun("run-3", startedAt)
	v.CompleteRun("run-3", map[string]validator.Entity{
		"span:trace-1:span-1": {
			Key:             "span:trace-1:span-1",
			HighestSeverity: validator.SeverityViolation,
			Signal:          validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
			UpdatedAt:       completedAt,
			Findings: []validator.Finding{{
				EntityKey: "span:trace-1:span-1",
				Source:    "weaver",
				RuleID:    "missing_attribute",
				Severity:  validator.SeverityViolation,
				Message:   "missing attribute",
				Signal:    validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
				UpdatedAt: completedAt,
			}},
		},
	}, validator.RunStats{}, completedAt)
	v.MarkTelemetryChanged(time.Unix(30, 0))

	mux := http.NewServeMux()
	Register(mux, s, v)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/validation/latest?serviceName=checkout")
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var snapshot validator.Snapshot
	if err := json.NewDecoder(resp.Body).Decode(&snapshot); err != nil {
		t.Fatalf("decode snapshot: %v", err)
	}
	if !snapshot.Summary.Stale {
		t.Fatalf("expected stale snapshot summary, got %+v", snapshot.Summary)
	}
	if len(snapshot.Findings) != 1 {
		t.Fatalf("expected one finding, got %+v", snapshot)
	}
}

func TestValidationLatestReturnsAllFindingsByDefault(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	startedAt := time.Unix(10, 0)
	completedAt := time.Unix(20, 0)
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
	v.StartRun("run-all", startedAt)

	findings := make([]validator.Finding, 0, 250)
	for i := 0; i < 250; i++ {
		findings = append(findings, validator.Finding{
			EntityKey: "metric:checkout::jvm.thread.count",
			Source:    "weaver",
			RuleID:    fmt.Sprintf("rule-%03d", i),
			Severity:  validator.SeverityViolation,
			Message:   "validation finding",
			Signal:    validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "jvm.thread.count"},
			UpdatedAt: completedAt.Add(time.Duration(i) * time.Second),
		})
	}

	v.CompleteRun("run-all", map[string]validator.Entity{
		"metric:checkout::jvm.thread.count": {
			Key:             "metric:checkout::jvm.thread.count",
			HighestSeverity: validator.SeverityViolation,
			Signal:          validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "jvm.thread.count"},
			UpdatedAt:       completedAt,
			Findings:        findings,
		},
	}, validator.RunStats{}, completedAt)

	mux := http.NewServeMux()
	Register(mux, s, v)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/validation/latest")
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var snapshot validator.Snapshot
	if err := json.NewDecoder(resp.Body).Decode(&snapshot); err != nil {
		t.Fatalf("decode snapshot: %v", err)
	}
	if len(snapshot.Findings) != 250 {
		t.Fatalf("expected all findings without an explicit limit, got %d", len(snapshot.Findings))
	}
	if len(snapshot.Issues) != 1 {
		t.Fatalf("expected grouped issues in validation snapshot, got %d", len(snapshot.Issues))
	}
}

func TestValidationFindingsAllowsExplicitRunIDAfterStale(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	startedAt := time.Unix(10, 0)
	completedAt := time.Unix(20, 0)
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
	v.StartRun("run-9", startedAt)
	v.CompleteRun("run-9", map[string]validator.Entity{
		"metric:checkout::http.server.duration": {
			Key:             "metric:checkout::http.server.duration",
			HighestSeverity: validator.SeverityImprovement,
			Signal:          validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
			UpdatedAt:       completedAt,
			Findings: []validator.Finding{{
				EntityKey: "metric:checkout::http.server.duration",
				Source:    "weaver",
				RuleID:    "deprecated",
				Severity:  validator.SeverityImprovement,
				Message:   "deprecated metric",
				Signal:    validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
				UpdatedAt: completedAt,
			}},
		},
	}, validator.RunStats{}, completedAt)
	v.MarkTelemetryChanged(time.Unix(30, 0))

	mux := http.NewServeMux()
	Register(mux, s, v)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/validation/findings?runId=run-9")
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var findings []validator.Finding
	if err := json.NewDecoder(resp.Body).Decode(&findings); err != nil {
		t.Fatalf("decode findings: %v", err)
	}
	if len(findings) != 1 {
		t.Fatalf("expected one run-scoped finding, got %+v", findings)
	}
}

func TestValidationFindingsReturnsStoredResultWhenStaleResultExists(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	startedAt := time.Unix(10, 0)
	completedAt := time.Unix(20, 0)
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
	v.StartRun("run-12", startedAt)
	v.CompleteRun("run-12", map[string]validator.Entity{
		"metric:checkout::db.client.connections.usage": {
			Key:             "metric:checkout::db.client.connections.usage",
			HighestSeverity: validator.SeverityViolation,
			Signal:          validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "db.client.connections.usage"},
			UpdatedAt:       completedAt,
			Findings: []validator.Finding{{
				EntityKey: "metric:checkout::db.client.connections.usage",
				Source:    "weaver",
				RuleID:    "deprecated",
				Severity:  validator.SeverityViolation,
				Message:   "deprecated attribute",
				Signal:    validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "db.client.connections.usage"},
				UpdatedAt: completedAt,
			}},
		},
	}, validator.RunStats{}, completedAt)
	v.MarkTelemetryChanged(time.Unix(30, 0))

	mux := http.NewServeMux()
	Register(mux, s, v)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/validation/findings")
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var findings []validator.Finding
	if err := json.NewDecoder(resp.Body).Decode(&findings); err != nil {
		t.Fatalf("decode findings: %v", err)
	}
	if len(findings) != 1 {
		t.Fatalf("expected one retained finding, got %+v", findings)
	}
}

func TestRunValidationEndpoint(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	runner := &fakeValidationRunner{
		summary: validator.Summary{
			Enabled:          true,
			Status:           validator.StatusRunning,
			Message:          "Validation running",
			ActiveRunID:      "run-7",
			LastRunStartedAt: time.Now(),
		},
	}

	mux := http.NewServeMux()
	Register(mux, s, v, runner)
	server := httptest.NewServer(mux)
	defer server.Close()

	req := mustNewRequest(t, http.MethodPost, server.URL+"/api/validation/run", nil)
	resp := mustDo(t, req)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	if runner.calls != 1 {
		t.Fatalf("expected runner to be called once, got %d", runner.calls)
	}

	var summary validator.Summary
	if err := json.NewDecoder(resp.Body).Decode(&summary); err != nil {
		t.Fatalf("decode summary: %v", err)
	}
	if summary.ActiveRunID != "run-7" {
		t.Fatalf("unexpected run summary: %+v", summary)
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

func TestQueryMetricsWithServerSideFilters(t *testing.T) {
	s := store.New()
	now := time.Now()

	m1 := store.MetricDataPoint{
		Name:        "http.server.duration",
		Description: "Request duration",
		Unit:        "ms",
		Type:        "histogram",
		Timestamp:   now,
		Value:       42,
		Resource:    store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:       store.Scope{Name: "otel.http"},
		Attributes:  map[string]any{},
	}
	m2 := store.MetricDataPoint{
		Name:        "db.client.connections.usage",
		Description: "Open connections",
		Unit:        "connections",
		Type:        "gauge",
		Timestamp:   now.Add(100 * time.Millisecond),
		Value:       5,
		Resource:    store.Resource{ServiceName: "db", Attributes: map[string]any{}},
		Scope:       store.Scope{Name: "otel.db"},
		Attributes:  map[string]any{},
	}
	s.AddMetricsForConnection("", []store.MetricDataPoint{m1, m2})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	query := url.Values{
		"filter[descriptionContains]": {"duration"},
		"filter[metricName]":          {"http.server.duration"},
		"filter[serviceName]":         {"CHECKOUT"},
		"filter[type]":                {"histogram"},
		"filter[unit]":                {"ms"},
		"range[dataPointCount][gte]":  {"1"},
		"range[dataPointCount][lte]":  {"1"},
		"time[from]":                  {now.Add(-time.Second).UTC().Format(time.RFC3339Nano)},
		"time[to]":                    {now.Add(time.Second).UTC().Format(time.RFC3339Nano)},
	}
	resp := mustGet(t, server.URL+"/api/query/metrics?"+query.Encode())
	defer resp.Body.Close()

	var groups []store.MetricGroup
	if err := json.NewDecoder(resp.Body).Decode(&groups); err != nil {
		t.Fatalf("decode metrics: %v", err)
	}
	if len(groups) != 1 {
		t.Fatalf("expected 1 filtered metric group, got %d", len(groups))
	}
	if groups[0].Name != "http.server.duration" {
		t.Fatalf("expected http.server.duration, got %s", groups[0].Name)
	}
}

func TestQueryMetricsWithNegatedServerSideFilters(t *testing.T) {
	s := store.New()
	now := time.Now()

	s.AddMetricsForConnection("", []store.MetricDataPoint{
		{
			Name:        "http.server.duration",
			Description: "Request duration",
			Type:        "histogram",
			Unit:        "ms",
			Timestamp:   now,
			Value:       12,
			Resource:    store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
			Scope:       store.Scope{Name: "otel.http"},
			Attributes:  map[string]any{},
		},
		{
			Name:        "db.client.connections.usage",
			Description: "Open connections",
			Type:        "gauge",
			Unit:        "connections",
			Timestamp:   now.Add(100 * time.Millisecond),
			Value:       4,
			Resource:    store.Resource{ServiceName: "database", Attributes: map[string]any{}},
			Scope:       store.Scope{Name: "otel.sql"},
			Attributes:  map[string]any{},
		},
	})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	query := url.Values{
		"filter[serviceName][neq]":         {"checkout"},
		"filter[type][neq]":                {"histogram"},
		"filter[descriptionContains][neq]": {"request"},
	}
	resp := mustGet(t, server.URL+"/api/query/metrics?"+query.Encode())
	defer resp.Body.Close()

	var metrics []store.MetricGroup
	if err := json.NewDecoder(resp.Body).Decode(&metrics); err != nil {
		t.Fatalf("decode metrics: %v", err)
	}
	if len(metrics) != 1 {
		t.Fatalf("expected 1 negated metric, got %d", len(metrics))
	}
	if metrics[0].Name != "db.client.connections.usage" {
		t.Fatalf("expected db.client.connections.usage, got %s", metrics[0].Name)
	}
}

func TestQueryMetricFilterValues(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddMetricsForConnection("", []store.MetricDataPoint{
		{
			Name:        "http.server.duration",
			Description: "Request duration",
			Unit:        "ms",
			Type:        "histogram",
			Timestamp:   now,
			Resource:    store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
			Scope:       store.Scope{Name: "otel.http"},
		},
		{
			Name:        "db.client.connections.usage",
			Description: "Connections",
			Unit:        "connections",
			Type:        "gauge",
			Timestamp:   now.Add(time.Second),
			Resource:    store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
			Scope:       store.Scope{Name: "otel.db"},
		},
	})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/metrics/filter-values?field=scopeName&filter%5BserviceName%5D%5Beq%5D=payments")
	defer resp.Body.Close()

	var values []string
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &values); err != nil {
		t.Fatalf("unmarshal values: %v", err)
	}
	if len(values) != 1 || values[0] != "otel.db" {
		t.Fatalf("expected [otel.db], got %v", values)
	}
}

func TestQueryHealthReturnsServerMetadataAndEndpoints(t *testing.T) {
	s := store.New()
	s.SetEndpoints(store.Endpoints{
		REST:     "http://127.0.0.1:3000",
		OTLPHTTP: "http://127.0.0.1:4318",
		OTLPgRPC: "127.0.0.1:4317",
	})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/health")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected status 200, got %d", resp.StatusCode)
	}

	var health map[string]any
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &health); err != nil {
		t.Fatalf("failed to decode health response: %v", err)
	}

	if got := health["kind"]; got != "obstudio" {
		t.Fatalf("expected kind obstudio, got %#v", got)
	}
	if got := health["apiVersion"]; got != "v1" {
		t.Fatalf("expected apiVersion v1, got %#v", got)
	}

	endpoints, ok := health["endpoints"].(map[string]any)
	if !ok {
		t.Fatalf("expected endpoints object, got %#v", health["endpoints"])
	}
	if got := endpoints["rest"]; got != "http://127.0.0.1:3000" {
		t.Fatalf("expected rest endpoint, got %#v", got)
	}
	if got := endpoints["mcp"]; got != "http://127.0.0.1:3000/mcp" {
		t.Fatalf("expected mcp endpoint, got %#v", got)
	}
	if got := endpoints["otlpHttp"]; got != "http://127.0.0.1:4318" {
		t.Fatalf("expected otlpHttp endpoint, got %#v", got)
	}
	if got := endpoints["otlpGrpc"]; got != "127.0.0.1:4317" {
		t.Fatalf("expected otlpGrpc endpoint, got %#v", got)
	}
}

func TestQueryHealthHandlesNilStore(t *testing.T) {
	mux := http.NewServeMux()
	Register(mux, nil)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/health")
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected status 200, got %d", resp.StatusCode)
	}

	var health map[string]any
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &health); err != nil {
		t.Fatalf("failed to decode health response: %v", err)
	}

	endpoints, ok := health["endpoints"].(map[string]any)
	if !ok {
		t.Fatalf("expected endpoints object, got %#v", health["endpoints"])
	}
	if got := endpoints["rest"]; got != "" {
		t.Fatalf("expected empty rest endpoint, got %#v", got)
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

func TestQueryLogsWithServerSideFilters(t *testing.T) {
	s := store.New()
	now := time.Now()

	log1 := store.LogRecord{
		Timestamp:    now,
		Body:         "checkout started",
		SeverityText: "INFO",
		TraceID:      "trace-1",
		Resource:     store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:        store.Scope{Name: "test-scope"},
		Attributes:   map[string]any{},
	}
	log2 := store.LogRecord{
		Timestamp:    now.Add(100 * time.Millisecond),
		Body:         "payment failed",
		SeverityText: "ERROR",
		TraceID:      "trace-2",
		SpanID:       "span-2",
		Resource:     store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
		Scope:        store.Scope{Name: "test-scope"},
		Attributes:   map[string]any{},
	}
	s.AddLogsForConnection("", []store.LogRecord{log1, log2})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	query := url.Values{
		"filter[severityText]": {"error"},
		"filter[serviceName]":  {"PAYMENTS"},
		"filter[traceId]":      {"trace-2"},
		"filter[spanId]":       {"span-2"},
		"filter[scopeName]":    {"test-scope"},
		"filter[bodyContains]": {"failed"},
		"time[from]":           {now.Add(50 * time.Millisecond).UTC().Format(time.RFC3339Nano)},
		"time[to]":             {now.Add(150 * time.Millisecond).UTC().Format(time.RFC3339Nano)},
	}
	resp := mustGet(t, server.URL+"/api/query/logs?"+query.Encode())
	defer resp.Body.Close()

	var logs []store.LogRecord
	if err := json.NewDecoder(resp.Body).Decode(&logs); err != nil {
		t.Fatalf("decode logs: %v", err)
	}
	if len(logs) != 1 {
		t.Fatalf("expected 1 filtered log, got %d", len(logs))
	}
	if logs[0].Body != "payment failed" {
		t.Fatalf("expected payment failed, got %s", logs[0].Body)
	}
}

func TestQueryLogsWithNegatedServerSideFilters(t *testing.T) {
	s := store.New()
	now := time.Now()

	log1 := store.LogRecord{
		Timestamp:      now,
		Body:           "checkout started",
		SeverityNumber: 9,
		SeverityText:   "INFO",
		TraceID:        "trace-1",
		Resource:       store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:          store.Scope{Name: "test-scope"},
		Attributes:     map[string]any{},
	}
	log2 := store.LogRecord{
		Timestamp:      now.Add(100 * time.Millisecond),
		Body:           "payment failed",
		SeverityNumber: 17,
		SeverityText:   "ERROR",
		TraceID:        "trace-2",
		SpanID:         "span-2",
		Resource:       store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
		Scope:          store.Scope{Name: "test-scope"},
		Attributes:     map[string]any{},
	}
	s.AddLogsForConnection("", []store.LogRecord{log1, log2})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	query := url.Values{
		"filter[serviceName][neq]":    {"checkout"},
		"filter[severityText][neq]":   {"info"},
		"filter[severityNumber][neq]": {"9"},
		"filter[bodyContains][neq]":   {"started"},
	}
	resp := mustGet(t, server.URL+"/api/query/logs?"+query.Encode())
	defer resp.Body.Close()

	var logs []store.LogRecord
	if err := json.NewDecoder(resp.Body).Decode(&logs); err != nil {
		t.Fatalf("decode logs: %v", err)
	}
	if len(logs) != 1 {
		t.Fatalf("expected 1 negated log, got %d", len(logs))
	}
	if logs[0].Body != "payment failed" {
		t.Fatalf("expected payment failed, got %s", logs[0].Body)
	}
}

func TestQueryLogFilterValues(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddLogsForConnection("", []store.LogRecord{
		{
			ID:        "1",
			Timestamp: now,
			Body:      "checkout started",
			Resource:  store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
			Scope:     store.Scope{Name: "checkout.logger"},
		},
		{
			ID:        "2",
			Timestamp: now.Add(time.Second),
			Body:      "payment failed",
			Resource:  store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
			Scope:     store.Scope{Name: "payments.logger"},
		},
	})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	resp := mustGet(t, server.URL+"/api/query/logs/filter-values?field=scopeName&filter%5BserviceName%5D%5Beq%5D=payments")
	defer resp.Body.Close()

	var values []string
	body, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(body, &values); err != nil {
		t.Fatalf("unmarshal values: %v", err)
	}
	if len(values) != 1 || values[0] != "payments.logger" {
		t.Fatalf("expected [payments.logger], got %v", values)
	}
}

func TestQueryLogsWithComplementaryTimeFilters(t *testing.T) {
	s := store.New()
	now := time.Now()

	log1 := store.LogRecord{
		Timestamp:      now,
		Body:           "checkout started",
		SeverityNumber: 9,
		SeverityText:   "INFO",
		Resource:       store.Resource{ServiceName: "checkout", Attributes: map[string]any{}},
		Scope:          store.Scope{Name: "test-scope"},
		Attributes:     map[string]any{},
	}
	log2 := store.LogRecord{
		Timestamp:      now.Add(100 * time.Millisecond),
		Body:           "payment failed",
		SeverityNumber: 17,
		SeverityText:   "ERROR",
		Resource:       store.Resource{ServiceName: "payments", Attributes: map[string]any{}},
		Scope:          store.Scope{Name: "test-scope"},
		Attributes:     map[string]any{},
	}
	s.AddLogsForConnection("", []store.LogRecord{log1, log2})

	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()

	query := url.Values{
		"time[before]": {now.Add(50 * time.Millisecond).UTC().Format(time.RFC3339Nano)},
	}
	resp := mustGet(t, server.URL+"/api/query/logs?"+query.Encode())
	defer resp.Body.Close()

	var logs []store.LogRecord
	if err := json.NewDecoder(resp.Body).Decode(&logs); err != nil {
		t.Fatalf("decode logs: %v", err)
	}
	if len(logs) != 1 {
		t.Fatalf("expected 1 complementary log, got %d", len(logs))
	}
	if logs[0].Body != "checkout started" {
		t.Fatalf("expected checkout started, got %s", logs[0].Body)
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

func TestQueryOptionalNumericDirect(t *testing.T) {
	intReq, err := http.NewRequest("GET", "/api?spanCount=7&minSpanCount=-1&bad=abc", nil)
	if err != nil {
		t.Fatalf("failed to create int request: %v", err)
	}
	if got, ok := queryOptionalInt(intReq, "spanCount"); !ok || got != 7 {
		t.Fatalf("queryOptionalInt(spanCount) = (%d, %t), want (7, true)", got, ok)
	}
	if _, ok := queryOptionalInt(intReq, "minSpanCount"); ok {
		t.Fatalf("expected negative optional int to be ignored")
	}
	if _, ok := queryOptionalInt(intReq, "missing"); ok {
		t.Fatalf("expected missing optional int to be absent")
	}

	floatReq, err := http.NewRequest("GET", "/api?durationMs=30.5&minDurationMs=-1&bad=abc", nil)
	if err != nil {
		t.Fatalf("failed to create float request: %v", err)
	}
	if got, ok := queryOptionalFloat(floatReq, "durationMs"); !ok || got != 30.5 {
		t.Fatalf("queryOptionalFloat(durationMs) = (%f, %t), want (30.5, true)", got, ok)
	}
	if _, ok := queryOptionalFloat(floatReq, "minDurationMs"); ok {
		t.Fatalf("expected negative optional float to be ignored")
	}
	if _, ok := queryOptionalFloat(floatReq, "missing"); ok {
		t.Fatalf("expected missing optional float to be absent")
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
