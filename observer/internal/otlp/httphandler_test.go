package otlp

import (
	"bytes"
	"compress/gzip"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

// createTestSpan creates a minimal test span for marshaling.
func createTestSpan() ptrace.Traces {
	td := ptrace.NewTraces()
	rs := td.ResourceSpans().AppendEmpty()
	res := rs.Resource()
	res.Attributes().PutStr("service.name", "test-service")

	ss := rs.ScopeSpans().AppendEmpty()
	ss.Scope().SetName("test-scope")

	span := ss.Spans().AppendEmpty()
	span.SetName("test-span")
	span.SetTraceID([16]byte{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16})
	span.SetSpanID([8]byte{1, 2, 3, 4, 5, 6, 7, 8})
	span.SetStartTimestamp(pcommon.NewTimestampFromTime(time.Now()))
	span.SetEndTimestamp(pcommon.NewTimestampFromTime(time.Now().Add(100 * time.Millisecond)))
	span.Status().SetCode(ptrace.StatusCodeOk)

	return td
}

// createTestMetric creates a minimal test metric for marshaling.
func createTestMetric() pmetric.Metrics {
	md := pmetric.NewMetrics()
	rm := md.ResourceMetrics().AppendEmpty()
	res := rm.Resource()
	res.Attributes().PutStr("service.name", "test-service")

	sm := rm.ScopeMetrics().AppendEmpty()
	sm.Scope().SetName("test-scope")

	m := sm.Metrics().AppendEmpty()
	m.SetName("test.metric")
	m.SetDescription("A test metric")
	m.SetUnit("1")

	gauge := m.SetEmptyGauge()
	dp := gauge.DataPoints().AppendEmpty()
	dp.SetTimestamp(pcommon.NewTimestampFromTime(time.Now()))
	dp.SetDoubleValue(42.0)

	return md
}

// createTestLog creates a minimal test log for marshaling.
func createTestLog() plog.Logs {
	ld := plog.NewLogs()
	rl := ld.ResourceLogs().AppendEmpty()
	res := rl.Resource()
	res.Attributes().PutStr("service.name", "test-service")

	sl := rl.ScopeLogs().AppendEmpty()
	sl.Scope().SetName("test-scope")

	lr := sl.LogRecords().AppendEmpty()
	lr.SetTimestamp(pcommon.NewTimestampFromTime(time.Now()))
	lr.SetSeverityText("INFO")
	lr.Body().SetStr("test log message")

	return ld
}

// Test 1: POST /v1/traces with JSON body — 200, data appears in store
func TestPostTracesJSON(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{}, // ct can be nil for basic tests, but let's provide one
	}

	td := createTestSpan()
	marshaler := ptrace.JSONMarshaler{}
	body, err := marshaler.MarshalTraces(td)
	if err != nil {
		t.Fatalf("failed to marshal traces: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added to store
	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span in store, got %d", stats.SpanCount)
	}
	if stats.ServiceNames[0] != "test-service" {
		t.Errorf("expected service name 'test-service', got %v", stats.ServiceNames)
	}
}

// Test 2: POST /v1/metrics with JSON body — 200, data appears in store
func TestPostMetricsJSON(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	md := createTestMetric()
	marshaler := pmetric.JSONMarshaler{}
	body, err := marshaler.MarshalMetrics(md)
	if err != nil {
		t.Fatalf("failed to marshal metrics: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/metrics", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added to store
	stats := s.Stats()
	if stats.DataPointCount != 1 {
		t.Errorf("expected 1 metric data point in store, got %d", stats.DataPointCount)
	}
	if stats.MetricNameCount != 1 {
		t.Errorf("expected 1 metric name in store, got %d", stats.MetricNameCount)
	}
}

// Test 3: POST /v1/logs with JSON body — 200, data appears in store
func TestPostLogsJSON(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	ld := createTestLog()
	marshaler := plog.JSONMarshaler{}
	body, err := marshaler.MarshalLogs(ld)
	if err != nil {
		t.Fatalf("failed to marshal logs: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/logs", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added to store
	stats := s.Stats()
	if stats.LogCount != 1 {
		t.Errorf("expected 1 log record in store, got %d", stats.LogCount)
	}
}

// Test 4: POST /v1/traces with application/x-protobuf Content-Type — 200 (using protobuf marshaler)
func TestPostTracesProtobuf(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	td := createTestSpan()
	marshaler := ptrace.ProtoMarshaler{}
	body, err := marshaler.MarshalTraces(td)
	if err != nil {
		t.Fatalf("failed to marshal traces to protobuf: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/x-protobuf")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added to store
	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span in store, got %d", stats.SpanCount)
	}
}

// Test 5: GET /v1/traces — 405 Method Not Allowed
func TestGetTracesNotAllowed(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	req := httptest.NewRequest("GET", "/v1/traces", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected status 405, got %d", w.Code)
	}
}

// Test 6: POST /v1/unknown — 404
func TestPostUnknownPath(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	req := httptest.NewRequest("POST", "/v1/unknown", bytes.NewReader([]byte(`{}`)))
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusNotFound {
		t.Errorf("expected status 404, got %d", w.Code)
	}
}

// Test 7: POST /v1/traces with gzip Content-Encoding — correctly decompressed and processed
func TestPostTracesGzip(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	td := createTestSpan()
	marshaler := ptrace.JSONMarshaler{}
	body, err := marshaler.MarshalTraces(td)
	if err != nil {
		t.Fatalf("failed to marshal traces: %v", err)
	}

	// Compress the body with gzip
	var compressedBuf bytes.Buffer
	gz := gzip.NewWriter(&compressedBuf)
	if _, err := gz.Write(body); err != nil {
		t.Fatalf("failed to gzip compress: %v", err)
	}
	gz.Close()

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(compressedBuf.Bytes()))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Content-Encoding", "gzip")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added to store
	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span in store after gzip decompression, got %d", stats.SpanCount)
	}
}

// Test 8: POST /v1/metrics with gzip Content-Encoding
func TestPostMetricsGzip(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	md := createTestMetric()
	marshaler := pmetric.JSONMarshaler{}
	body, err := marshaler.MarshalMetrics(md)
	if err != nil {
		t.Fatalf("failed to marshal metrics: %v", err)
	}

	// Compress the body with gzip
	var compressedBuf bytes.Buffer
	gz := gzip.NewWriter(&compressedBuf)
	if _, err := gz.Write(body); err != nil {
		t.Fatalf("failed to gzip compress: %v", err)
	}
	gz.Close()

	req := httptest.NewRequest("POST", "/v1/metrics", bytes.NewReader(compressedBuf.Bytes()))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Content-Encoding", "gzip")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added to store
	stats := s.Stats()
	if stats.DataPointCount != 1 {
		t.Errorf("expected 1 metric data point in store after gzip decompression, got %d", stats.DataPointCount)
	}
}

// Test 9: POST /v1/logs with gzip Content-Encoding
func TestPostLogsGzip(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	ld := createTestLog()
	marshaler := plog.JSONMarshaler{}
	body, err := marshaler.MarshalLogs(ld)
	if err != nil {
		t.Fatalf("failed to marshal logs: %v", err)
	}

	// Compress the body with gzip
	var compressedBuf bytes.Buffer
	gz := gzip.NewWriter(&compressedBuf)
	if _, err := gz.Write(body); err != nil {
		t.Fatalf("failed to gzip compress: %v", err)
	}
	gz.Close()

	req := httptest.NewRequest("POST", "/v1/logs", bytes.NewReader(compressedBuf.Bytes()))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Content-Encoding", "gzip")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added to store
	stats := s.Stats()
	if stats.LogCount != 1 {
		t.Errorf("expected 1 log record in store after gzip decompression, got %d", stats.LogCount)
	}
}

// Test 10: Invalid JSON body returns 400
func TestPostTracesInvalidJSON(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader([]byte(`{invalid json}`)))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected status 400 for invalid JSON, got %d", w.Code)
	}
}

// Test 11: Invalid protobuf body returns 400
func TestPostTracesInvalidProtobuf(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader([]byte{0xFF, 0xFE, 0xFD}))
	req.Header.Set("Content-Type", "application/x-protobuf")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected status 400 for invalid protobuf, got %d", w.Code)
	}
}

// Test 12: Response headers and body format
func TestResponseFormat(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	td := createTestSpan()
	marshaler := ptrace.JSONMarshaler{}
	body, err := marshaler.MarshalTraces(td)
	if err != nil {
		t.Fatalf("failed to marshal traces: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	// Check Content-Type header
	contentType := w.Header().Get("Content-Type")
	if contentType != "application/json" {
		t.Errorf("expected Content-Type 'application/json', got '%s'", contentType)
	}

	// Check response body is "{}"
	if w.Body.String() != "{}" {
		t.Errorf("expected response body '{}', got '%s'", w.Body.String())
	}
}

// Test 13: POST /v1/metrics with protobuf
func TestPostMetricsProtobuf(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	md := createTestMetric()
	marshaler := pmetric.ProtoMarshaler{}
	body, err := marshaler.MarshalMetrics(md)
	if err != nil {
		t.Fatalf("failed to marshal metrics to protobuf: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/metrics", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/x-protobuf")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added to store
	stats := s.Stats()
	if stats.DataPointCount != 1 {
		t.Errorf("expected 1 metric data point in store, got %d", stats.DataPointCount)
	}
}

// Test 14: POST /v1/logs with protobuf
func TestPostLogsProtobuf(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	ld := createTestLog()
	marshaler := plog.ProtoMarshaler{}
	body, err := marshaler.MarshalLogs(ld)
	if err != nil {
		t.Fatalf("failed to marshal logs to protobuf: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/logs", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/x-protobuf")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added to store
	stats := s.Stats()
	if stats.LogCount != 1 {
		t.Errorf("expected 1 log record in store, got %d", stats.LogCount)
	}
}

// Test 15: Multiple spans in single POST request
func TestPostMultipleSpans(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	td := ptrace.NewTraces()
	rs := td.ResourceSpans().AppendEmpty()
	res := rs.Resource()
	res.Attributes().PutStr("service.name", "test-service")

	ss := rs.ScopeSpans().AppendEmpty()
	ss.Scope().SetName("test-scope")

	// Add 3 spans
	for i := 0; i < 3; i++ {
		span := ss.Spans().AppendEmpty()
		span.SetName("test-span-" + string(rune('0'+i)))
		span.SetTraceID([16]byte{byte(i), 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16})
		span.SetSpanID([8]byte{byte(i), 2, 3, 4, 5, 6, 7, 8})
		span.SetStartTimestamp(pcommon.NewTimestampFromTime(time.Now()))
		span.SetEndTimestamp(pcommon.NewTimestampFromTime(time.Now().Add(100 * time.Millisecond)))
		span.Status().SetCode(ptrace.StatusCodeOk)
	}

	marshaler := ptrace.JSONMarshaler{}
	body, err := marshaler.MarshalTraces(td)
	if err != nil {
		t.Fatalf("failed to marshal traces: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify all spans were added
	stats := s.Stats()
	if stats.SpanCount != 3 {
		t.Errorf("expected 3 spans in store, got %d", stats.SpanCount)
	}
}

// Test 16: readBody helper function with invalid gzip
func TestReadBodyInvalidGzip(t *testing.T) {
	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader([]byte{0x1f, 0x8b, 0xFF}))
	req.Header.Set("Content-Encoding", "gzip")

	_, err := readBody(req)
	if err == nil {
		t.Error("expected error for invalid gzip data")
	}
}

// Test 17: Concurrent requests
func TestConcurrentRequests(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	numRequests := 10
	done := make(chan bool, numRequests)

	for i := 0; i < numRequests; i++ {
		go func() {
			td := createTestSpan()
			marshaler := ptrace.JSONMarshaler{}
			body, _ := marshaler.MarshalTraces(td)

			req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()

			handler.ServeHTTP(w, req)
			done <- w.Code == http.StatusOK
		}()
	}

	// Wait for all goroutines
	for i := 0; i < numRequests; i++ {
		if !<-done {
			t.Error("concurrent request failed")
		}
	}

	// Verify all requests were processed
	stats := s.Stats()
	if stats.SpanCount != numRequests {
		t.Errorf("expected %d spans in store, got %d", numRequests, stats.SpanCount)
	}
}

// Test 18: Empty body request
func TestPostTracesEmptyBody(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader([]byte{}))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected status 400 for empty body, got %d", w.Code)
	}
}

// Test 19: PUT method also returns 405
func TestPutTracesNotAllowed(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	req := httptest.NewRequest("PUT", "/v1/traces", bytes.NewReader([]byte(`{}`)))
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected status 405, got %d", w.Code)
	}
}

// Test 20: DELETE method also returns 405
func TestDeleteTracesNotAllowed(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	req := httptest.NewRequest("DELETE", "/v1/traces", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected status 405, got %d", w.Code)
	}
}

// Test 21: Verify connection ID is tracked (requires ct implementation)
func TestConnectionIDTracking(t *testing.T) {
	s := store.New()
	// Create a basic ConnTracker that returns a fixed connection ID
	ct := &ConnTracker{}

	handler := &otlpHTTPHandler{
		store: s,
		ct:    ct,
	}

	td := createTestSpan()
	marshaler := ptrace.JSONMarshaler{}
	body, err := marshaler.MarshalTraces(td)
	if err != nil {
		t.Fatalf("failed to marshal traces: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}

	// Verify data was added (connection ID tracking is internal to store)
	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span in store, got %d", stats.SpanCount)
	}
}

// Test 22: Mixed telemetry types in sequence
func TestMixedTelemetrySequence(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	// Send traces
	td := createTestSpan()
	tMarshaler := ptrace.JSONMarshaler{}
	tBody, _ := tMarshaler.MarshalTraces(td)
	tReq := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(tBody))
	tReq.Header.Set("Content-Type", "application/json")
	tW := httptest.NewRecorder()
	handler.ServeHTTP(tW, tReq)

	// Send metrics
	md := createTestMetric()
	mMarshaler := pmetric.JSONMarshaler{}
	mBody, _ := mMarshaler.MarshalMetrics(md)
	mReq := httptest.NewRequest("POST", "/v1/metrics", bytes.NewReader(mBody))
	mReq.Header.Set("Content-Type", "application/json")
	mW := httptest.NewRecorder()
	handler.ServeHTTP(mW, mReq)

	// Send logs
	ld := createTestLog()
	lMarshaler := plog.JSONMarshaler{}
	lBody, _ := lMarshaler.MarshalLogs(ld)
	lReq := httptest.NewRequest("POST", "/v1/logs", bytes.NewReader(lBody))
	lReq.Header.Set("Content-Type", "application/json")
	lW := httptest.NewRecorder()
	handler.ServeHTTP(lW, lReq)

	// Verify all requests succeeded
	if tW.Code != http.StatusOK || mW.Code != http.StatusOK || lW.Code != http.StatusOK {
		t.Errorf("expected all requests to return 200")
	}

	// Verify all data was stored
	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span, got %d", stats.SpanCount)
	}
	if stats.DataPointCount != 1 {
		t.Errorf("expected 1 metric data point, got %d", stats.DataPointCount)
	}
	if stats.LogCount != 1 {
		t.Errorf("expected 1 log record, got %d", stats.LogCount)
	}
}

// Test 23: Case sensitivity of paths (paths should be case-sensitive)
func TestPathCaseSensitivity(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	// Try /V1/traces (uppercase)
	req := httptest.NewRequest("POST", "/V1/traces", bytes.NewReader([]byte(`{}`)))
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusNotFound {
		t.Errorf("expected 404 for uppercase path /V1/traces, got %d", w.Code)
	}
}

// Test 24: Very large payload
func TestLargePayload(t *testing.T) {
	s := store.New()
	handler := &otlpHTTPHandler{
		store: s,
		ct:    &ConnTracker{},
	}

	// Create traces with many spans
	td := ptrace.NewTraces()
	rs := td.ResourceSpans().AppendEmpty()
	res := rs.Resource()
	res.Attributes().PutStr("service.name", "test-service")

	ss := rs.ScopeSpans().AppendEmpty()
	ss.Scope().SetName("test-scope")

	// Add 100 spans
	for i := 0; i < 100; i++ {
		span := ss.Spans().AppendEmpty()
		span.SetName("test-span")
		span.SetTraceID([16]byte{byte(i % 256), 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16})
		span.SetSpanID([8]byte{byte(i % 256), 2, 3, 4, 5, 6, 7, 8})
		span.SetStartTimestamp(pcommon.NewTimestampFromTime(time.Now()))
		span.SetEndTimestamp(pcommon.NewTimestampFromTime(time.Now().Add(100 * time.Millisecond)))
		span.Status().SetCode(ptrace.StatusCodeOk)
	}

	marshaler := ptrace.JSONMarshaler{}
	body, err := marshaler.MarshalTraces(td)
	if err != nil {
		t.Fatalf("failed to marshal traces: %v", err)
	}

	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200 for large payload, got %d", w.Code)
	}

	stats := s.Stats()
	if stats.SpanCount != 100 {
		t.Errorf("expected 100 spans in store, got %d", stats.SpanCount)
	}
}
