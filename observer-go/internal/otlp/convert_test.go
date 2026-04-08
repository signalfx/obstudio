package otlp

import (
	"bytes"
	"encoding/hex"
	"math"
	"testing"
	"time"

	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

// TestConvertTracesBasic tests conversion of a single span with all fields
func TestConvertTracesBasic(t *testing.T) {
	// Create test data
	traces := ptrace.NewTraces()
	rs := traces.ResourceSpans().AppendEmpty()
	rs.SetSchemaUrl("https://opentelemetry.io/schemas/1.20.0")

	// Set resource attributes
	res := rs.Resource()
	res.Attributes().PutStr("service.name", "test-service")
	res.Attributes().PutStr("service.version", "1.0.0")

	// Add scope
	ss := rs.ScopeSpans().AppendEmpty()
	ss.SetSchemaUrl("https://opentelemetry.io/schemas/1.20.0")
	scope := ss.Scope()
	scope.SetName("test-instrumentor")
	scope.SetVersion("2.0.0")

	// Add span
	span := ss.Spans().AppendEmpty()
	traceID := pcommon.TraceID([16]byte{0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10})
	spanID := pcommon.SpanID([8]byte{0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08})
	parentSpanID := pcommon.SpanID([8]byte{0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10, 0x11})

	span.SetTraceID(traceID)
	span.SetSpanID(spanID)
	span.SetParentSpanID(parentSpanID)
	span.SetName("test-span")
	span.SetKind(ptrace.SpanKindServer)

	startTime := time.Now()
	endTime := startTime.Add(100 * time.Millisecond)
	span.SetStartTimestamp(pcommon.NewTimestampFromTime(startTime))
	span.SetEndTimestamp(pcommon.NewTimestampFromTime(endTime))

	// Set status
	status := span.Status()
	status.SetCode(ptrace.StatusCodeOk)
	status.SetMessage("success")

	// Set attributes
	span.Attributes().PutStr("http.method", "GET")
	span.Attributes().PutInt("http.status_code", 200)

	// Convert
	result := ConvertTraces(traces)

	// Verify
	if len(result) != 1 {
		t.Fatalf("expected 1 span, got %d", len(result))
	}

	s := result[0]
	if s.TraceID != hex.EncodeToString(traceID[:]) {
		t.Errorf("traceID mismatch: expected %s, got %s", hex.EncodeToString(traceID[:]), s.TraceID)
	}
	if s.SpanID != hex.EncodeToString(spanID[:]) {
		t.Errorf("spanID mismatch: expected %s, got %s", hex.EncodeToString(spanID[:]), s.SpanID)
	}
	if s.ParentSpanID != hex.EncodeToString(parentSpanID[:]) {
		t.Errorf("parentSpanID mismatch: expected %s, got %s", hex.EncodeToString(parentSpanID[:]), s.ParentSpanID)
	}
	if s.Name != "test-span" {
		t.Errorf("name mismatch: expected test-span, got %s", s.Name)
	}
	if s.Kind != "SERVER" {
		t.Errorf("kind mismatch: expected SERVER, got %s", s.Kind)
	}
	if s.Status.Code != "OK" {
		t.Errorf("status code mismatch: expected OK, got %s", s.Status.Code)
	}
	if s.Status.Message != "success" {
		t.Errorf("status message mismatch: expected success, got %s", s.Status.Message)
	}
	if s.DurationMs != 100.0 {
		t.Errorf("duration mismatch: expected 100, got %f", s.DurationMs)
	}
	if s.Resource.ServiceName != "test-service" {
		t.Errorf("service name mismatch: expected test-service, got %s", s.Resource.ServiceName)
	}
	if s.Scope.Name != "test-instrumentor" {
		t.Errorf("scope name mismatch: expected test-instrumentor, got %s", s.Scope.Name)
	}
	if s.Attributes["http.method"] != "GET" {
		t.Errorf("http.method attribute mismatch")
	}
	if s.Attributes["http.status_code"] != int64(200) {
		t.Errorf("http.status_code attribute mismatch")
	}
}

// TestConvertTracesSpanKinds tests all span kind conversions
func TestConvertTracesSpanKinds(t *testing.T) {
	tests := []struct {
		kind     ptrace.SpanKind
		expected string
	}{
		{ptrace.SpanKindInternal, "INTERNAL"},
		{ptrace.SpanKindServer, "SERVER"},
		{ptrace.SpanKindClient, "CLIENT"},
		{ptrace.SpanKindProducer, "PRODUCER"},
		{ptrace.SpanKindConsumer, "CONSUMER"},
		{ptrace.SpanKindUnspecified, "UNSPECIFIED"},
	}

	for _, tt := range tests {
		t.Run(tt.expected, func(t *testing.T) {
			traces := ptrace.NewTraces()
			rs := traces.ResourceSpans().AppendEmpty()
			ss := rs.ScopeSpans().AppendEmpty()
			span := ss.Spans().AppendEmpty()
			span.SetKind(tt.kind)
			span.SetTraceID(pcommon.TraceID([16]byte{1}))
			span.SetSpanID(pcommon.SpanID([8]byte{1}))

			result := ConvertTraces(traces)
			if len(result) == 0 {
				t.Fatal("expected span in result")
			}
			if result[0].Kind != tt.expected {
				t.Errorf("expected kind %s, got %s", tt.expected, result[0].Kind)
			}
		})
	}
}

// TestConvertTracesStatusCodes tests all status code conversions
func TestConvertTracesStatusCodes(t *testing.T) {
	tests := []struct {
		code     ptrace.StatusCode
		expected string
	}{
		{ptrace.StatusCodeOk, "OK"},
		{ptrace.StatusCodeError, "ERROR"},
		{ptrace.StatusCodeUnset, "UNSET"},
	}

	for _, tt := range tests {
		t.Run(tt.expected, func(t *testing.T) {
			traces := ptrace.NewTraces()
			rs := traces.ResourceSpans().AppendEmpty()
			ss := rs.ScopeSpans().AppendEmpty()
			span := ss.Spans().AppendEmpty()
			span.SetTraceID(pcommon.TraceID([16]byte{1}))
			span.SetSpanID(pcommon.SpanID([8]byte{1}))
			span.Status().SetCode(tt.code)

			result := ConvertTraces(traces)
			if result[0].Status.Code != tt.expected {
				t.Errorf("expected status %s, got %s", tt.expected, result[0].Status.Code)
			}
		})
	}
}

// TestConvertTracesEvents tests span event conversion
func TestConvertTracesEvents(t *testing.T) {
	traces := ptrace.NewTraces()
	rs := traces.ResourceSpans().AppendEmpty()
	ss := rs.ScopeSpans().AppendEmpty()
	span := ss.Spans().AppendEmpty()
	span.SetTraceID(pcommon.TraceID([16]byte{1}))
	span.SetSpanID(pcommon.SpanID([8]byte{1}))

	// Add events
	evt := span.Events().AppendEmpty()
	evt.SetName("event1")
	eventTime := time.Now()
	evt.SetTimestamp(pcommon.NewTimestampFromTime(eventTime))
	evt.Attributes().PutStr("key1", "value1")
	evt.Attributes().PutInt("key2", 42)

	evt2 := span.Events().AppendEmpty()
	evt2.SetName("event2")
	evt2Event2Time := eventTime.Add(10 * time.Millisecond)
	evt2.SetTimestamp(pcommon.NewTimestampFromTime(evt2Event2Time))

	result := ConvertTraces(traces)
	if len(result) == 0 {
		t.Fatal("expected span in result")
	}

	s := result[0]
	if len(s.Events) != 2 {
		t.Errorf("expected 2 events, got %d", len(s.Events))
	}
	if s.Events[0].Name != "event1" {
		t.Errorf("event name mismatch")
	}
	if s.Events[0].Attributes["key1"] != "value1" {
		t.Errorf("event attribute mismatch")
	}
	if s.Events[0].Attributes["key2"] != int64(42) {
		t.Errorf("event attribute int mismatch")
	}
	if s.Events[1].Name != "event2" {
		t.Errorf("event 2 name mismatch")
	}
}

// TestConvertTracesLinks tests span link conversion
func TestConvertTracesLinks(t *testing.T) {
	traces := ptrace.NewTraces()
	rs := traces.ResourceSpans().AppendEmpty()
	ss := rs.ScopeSpans().AppendEmpty()
	span := ss.Spans().AppendEmpty()
	span.SetTraceID(pcommon.TraceID([16]byte{1}))
	span.SetSpanID(pcommon.SpanID([8]byte{1}))

	// Add links
	link := span.Links().AppendEmpty()
	linkedTraceID := pcommon.TraceID([16]byte{2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17})
	linkedSpanID := pcommon.SpanID([8]byte{2, 3, 4, 5, 6, 7, 8, 9})
	link.SetTraceID(linkedTraceID)
	link.SetSpanID(linkedSpanID)
	link.Attributes().PutStr("link.attr", "link.value")

	link2 := span.Links().AppendEmpty()
	linkedTraceID2 := pcommon.TraceID([16]byte{18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33})
	linkedSpanID2 := pcommon.SpanID([8]byte{18, 19, 20, 21, 22, 23, 24, 25})
	link2.SetTraceID(linkedTraceID2)
	link2.SetSpanID(linkedSpanID2)

	result := ConvertTraces(traces)
	if len(result) == 0 {
		t.Fatal("expected span in result")
	}

	s := result[0]
	if len(s.Links) != 2 {
		t.Errorf("expected 2 links, got %d", len(s.Links))
	}
	if s.Links[0].TraceID != hex.EncodeToString(linkedTraceID[:]) {
		t.Errorf("link trace ID mismatch")
	}
	if s.Links[0].SpanID != hex.EncodeToString(linkedSpanID[:]) {
		t.Errorf("link span ID mismatch")
	}
	if s.Links[0].Attributes["link.attr"] != "link.value" {
		t.Errorf("link attribute mismatch")
	}
}

// TestConvertTracesEmptyTraceID tests empty trace ID conversion
func TestConvertTracesEmptyTraceID(t *testing.T) {
	traces := ptrace.NewTraces()
	rs := traces.ResourceSpans().AppendEmpty()
	ss := rs.ScopeSpans().AppendEmpty()
	span := ss.Spans().AppendEmpty()
	// Don't set trace ID, it will be empty
	span.SetSpanID(pcommon.SpanID([8]byte{1}))

	result := ConvertTraces(traces)
	if len(result) == 0 {
		t.Fatal("expected span in result")
	}

	s := result[0]
	if s.TraceID != "" {
		t.Errorf("expected empty trace ID, got %s", s.TraceID)
	}
}

// TestConvertMetricsGaugeDouble tests gauge metric with double values
func TestConvertMetricsGaugeDouble(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	rm.SetSchemaUrl("https://opentelemetry.io/schemas/1.20.0")
	rm.Resource().Attributes().PutStr("service.name", "test-service")

	sm := rm.ScopeMetrics().AppendEmpty()
	sm.SetSchemaUrl("https://opentelemetry.io/schemas/1.20.0")
	sm.Scope().SetName("test-meter")

	m := sm.Metrics().AppendEmpty()
	m.SetName("temperature")
	m.SetDescription("Current temperature")
	m.SetUnit("C")

	gauge := m.SetEmptyGauge()
	dp := gauge.DataPoints().AppendEmpty()
	dp.SetDoubleValue(23.5)
	timestamp := time.Now()
	dp.SetTimestamp(pcommon.NewTimestampFromTime(timestamp))
	dp.Attributes().PutStr("location", "room1")

	result := ConvertMetrics(metrics)
	if len(result) == 0 {
		t.Fatal("expected metric data point")
	}

	mdp := result[0]
	if mdp.Type != "gauge" {
		t.Errorf("expected type gauge, got %s", mdp.Type)
	}
	if mdp.Name != "temperature" {
		t.Errorf("expected name temperature, got %s", mdp.Name)
	}
	if mdp.Value != 23.5 {
		t.Errorf("expected value 23.5, got %f", mdp.Value)
	}
	if mdp.Unit != "C" {
		t.Errorf("expected unit C, got %s", mdp.Unit)
	}
	if mdp.Description != "Current temperature" {
		t.Errorf("expected description, got %s", mdp.Description)
	}
	if mdp.Attributes["location"] != "room1" {
		t.Errorf("expected location attribute")
	}
}

// TestConvertMetricsGaugeInt tests gauge metric with int values
func TestConvertMetricsGaugeInt(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m := sm.Metrics().AppendEmpty()
	m.SetName("connections")

	gauge := m.SetEmptyGauge()
	dp := gauge.DataPoints().AppendEmpty()
	dp.SetIntValue(42)

	result := ConvertMetrics(metrics)
	if len(result) == 0 {
		t.Fatal("expected metric data point")
	}

	mdp := result[0]
	if mdp.Value != 42.0 {
		t.Errorf("expected value 42, got %f", mdp.Value)
	}
}

// TestConvertMetricsSum tests sum metric with temporality and monotonic
func TestConvertMetricsSum(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m := sm.Metrics().AppendEmpty()
	m.SetName("requests.total")

	sum := m.SetEmptySum()
	sum.SetAggregationTemporality(pmetric.AggregationTemporalityCumulative)
	sum.SetIsMonotonic(true)

	dp := sum.DataPoints().AppendEmpty()
	dp.SetIntValue(1000)

	result := ConvertMetrics(metrics)
	if len(result) == 0 {
		t.Fatal("expected metric data point")
	}

	mdp := result[0]
	if mdp.Type != "sum" {
		t.Errorf("expected type sum, got %s", mdp.Type)
	}
	if mdp.Temporality != "cumulative" {
		t.Errorf("expected temporality cumulative, got %s", mdp.Temporality)
	}
	if !mdp.IsMonotonic {
		t.Errorf("expected isMonotonic true")
	}
}

// TestConvertMetricsHistogram tests histogram metric conversion
func TestConvertMetricsHistogram(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m := sm.Metrics().AppendEmpty()
	m.SetName("request.duration")
	m.SetUnit("ms")

	histogram := m.SetEmptyHistogram()
	histogram.SetAggregationTemporality(pmetric.AggregationTemporalityDelta)

	dp := histogram.DataPoints().AppendEmpty()
	dp.SetCount(100)
	dp.SetSum(50000.0)
	dp.SetMin(10.0)
	dp.SetMax(500.0)

	// Set bucket bounds and counts
	boundsRaw := []float64{10.0, 50.0, 100.0}
	dp.ExplicitBounds().FromRaw(boundsRaw)

	countsRaw := []uint64{10, 50, 40}
	dp.BucketCounts().FromRaw(countsRaw)

	result := ConvertMetrics(metrics)
	if len(result) == 0 {
		t.Fatal("expected metric data point")
	}

	mdp := result[0]
	if mdp.Type != "histogram" {
		t.Errorf("expected type histogram, got %s", mdp.Type)
	}
	if mdp.Count != 100 {
		t.Errorf("expected count 100, got %d", mdp.Count)
	}
	if mdp.Sum != 50000.0 {
		t.Errorf("expected sum 50000, got %f", mdp.Sum)
	}
	if mdp.Min != 10.0 {
		t.Errorf("expected min 10, got %f", mdp.Min)
	}
	if mdp.Max != 500.0 {
		t.Errorf("expected max 500, got %f", mdp.Max)
	}
	if mdp.Temporality != "delta" {
		t.Errorf("expected temporality delta, got %s", mdp.Temporality)
	}
	if len(mdp.ExplicitBounds) != 3 {
		t.Errorf("expected 3 bounds, got %d", len(mdp.ExplicitBounds))
	}
	if len(mdp.BucketCounts) != 3 {
		t.Errorf("expected 3 bucket counts, got %d", len(mdp.BucketCounts))
	}
}

// TestConvertMetricsSummary tests summary metric conversion
func TestConvertMetricsSummary(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m := sm.Metrics().AppendEmpty()
	m.SetName("response.time")

	summary := m.SetEmptySummary()
	dp := summary.DataPoints().AppendEmpty()
	dp.SetCount(50)
	dp.SetSum(500.0)

	// Add quantiles
	qv1 := dp.QuantileValues().AppendEmpty()
	qv1.SetQuantile(0.5)
	qv1.SetValue(8.0)

	qv2 := dp.QuantileValues().AppendEmpty()
	qv2.SetQuantile(0.95)
	qv2.SetValue(25.0)

	qv3 := dp.QuantileValues().AppendEmpty()
	qv3.SetQuantile(0.99)
	qv3.SetValue(50.0)

	result := ConvertMetrics(metrics)
	if len(result) == 0 {
		t.Fatal("expected metric data point")
	}

	mdp := result[0]
	if mdp.Type != "summary" {
		t.Errorf("expected type summary, got %s", mdp.Type)
	}
	if mdp.Count != 50 {
		t.Errorf("expected count 50, got %d", mdp.Count)
	}
	if mdp.Sum != 500.0 {
		t.Errorf("expected sum 500, got %f", mdp.Sum)
	}
	if len(mdp.Quantiles) != 3 {
		t.Errorf("expected 3 quantiles, got %d", len(mdp.Quantiles))
	}
	if mdp.Quantiles[0].Quantile != 0.5 || mdp.Quantiles[0].Value != 8.0 {
		t.Errorf("quantile mismatch")
	}
	if mdp.Quantiles[1].Quantile != 0.95 || mdp.Quantiles[1].Value != 25.0 {
		t.Errorf("quantile mismatch")
	}
	if mdp.Quantiles[2].Quantile != 0.99 || mdp.Quantiles[2].Value != 50.0 {
		t.Errorf("quantile mismatch")
	}
}

// TestConvertMetricsExponentialHistogram tests exponential histogram conversion
func TestConvertMetricsExponentialHistogram(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m := sm.Metrics().AppendEmpty()
	m.SetName("request.size")

	expHist := m.SetEmptyExponentialHistogram()
	expHist.SetAggregationTemporality(pmetric.AggregationTemporalityCumulative)

	dp := expHist.DataPoints().AppendEmpty()
	dp.SetCount(200)
	dp.SetSum(100000.0)
	dp.SetMin(100.0)
	dp.SetMax(10000.0)

	result := ConvertMetrics(metrics)
	if len(result) == 0 {
		t.Fatal("expected metric data point")
	}

	mdp := result[0]
	if mdp.Type != "exponential_histogram" {
		t.Errorf("expected type exponential_histogram, got %s", mdp.Type)
	}
	if mdp.Count != 200 {
		t.Errorf("expected count 200, got %d", mdp.Count)
	}
	if mdp.Sum != 100000.0 {
		t.Errorf("expected sum 100000, got %f", mdp.Sum)
	}
	if mdp.Min != 100.0 {
		t.Errorf("expected min 100, got %f", mdp.Min)
	}
	if mdp.Max != 10000.0 {
		t.Errorf("expected max 10000, got %f", mdp.Max)
	}
	if mdp.Temporality != "cumulative" {
		t.Errorf("expected temporality cumulative, got %s", mdp.Temporality)
	}
}

// TestConvertLogsBasic tests basic log record conversion
func TestConvertLogsBasic(t *testing.T) {
	logs := plog.NewLogs()
	rl := logs.ResourceLogs().AppendEmpty()
	rl.SetSchemaUrl("https://opentelemetry.io/schemas/1.20.0")
	rl.Resource().Attributes().PutStr("service.name", "test-app")

	sl := rl.ScopeLogs().AppendEmpty()
	sl.SetSchemaUrl("https://opentelemetry.io/schemas/1.20.0")
	sl.Scope().SetName("test-logger")

	logRecord := sl.LogRecords().AppendEmpty()
	timestamp := time.Now()
	logRecord.SetTimestamp(pcommon.NewTimestampFromTime(timestamp))
	logRecord.SetSeverityNumber(plog.SeverityNumberError)
	logRecord.SetSeverityText("ERROR")
	logRecord.Body().SetStr("An error occurred")

	// Set trace context
	traceID := pcommon.TraceID([16]byte{0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10})
	spanID := pcommon.SpanID([8]byte{0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08})
	logRecord.SetTraceID(traceID)
	logRecord.SetSpanID(spanID)

	logRecord.Attributes().PutStr("user_id", "user123")

	result := ConvertLogs(logs)
	if len(result) == 0 {
		t.Fatal("expected log record")
	}

	lr := result[0]
	if lr.Body != "An error occurred" {
		t.Errorf("body mismatch: expected 'An error occurred', got '%s'", lr.Body)
	}
	if lr.SeverityText != "ERROR" {
		t.Errorf("severity text mismatch")
	}
	if lr.SeverityNumber != int32(plog.SeverityNumberError) {
		t.Errorf("severity number mismatch")
	}
	if lr.TraceID != hex.EncodeToString(traceID[:]) {
		t.Errorf("trace ID mismatch")
	}
	if lr.SpanID != hex.EncodeToString(spanID[:]) {
		t.Errorf("span ID mismatch")
	}
	if lr.Resource.ServiceName != "test-app" {
		t.Errorf("service name mismatch")
	}
	if lr.Scope.Name != "test-logger" {
		t.Errorf("scope name mismatch")
	}
	if lr.Attributes["user_id"] != "user123" {
		t.Errorf("attribute mismatch")
	}
}

// TestMapToGoMapAllTypes tests all pcommon.Value types conversion
func TestMapToGoMapAllTypes(t *testing.T) {
	m := pcommon.NewMap()

	// String
	m.PutStr("str_key", "string_value")

	// Bool
	m.PutBool("bool_key", true)

	// Int
	m.PutInt("int_key", 42)

	// Double
	m.PutDouble("double_key", 3.14)

	// Bytes
	bytesVal := pcommon.NewValueBytes()
	bytesVal.Bytes().FromRaw([]byte{0x01, 0x02, 0x03, 0x04})
	m.PutEmptyBytes("bytes_key").FromRaw([]byte{0x01, 0x02, 0x03, 0x04})

	// Slice
	sliceVal := pcommon.NewSlice()
	sliceVal.AppendEmpty().SetStr("item1")
	sliceVal.AppendEmpty().SetInt(10)
	sliceVal.AppendEmpty().SetDouble(2.71)
	m.PutEmptySlice("slice_key").FromRaw(sliceVal.AsRaw())

	// Nested map
	nestedMap := pcommon.NewMap()
	nestedMap.PutStr("nested_str", "nested_value")
	nestedMap.PutInt("nested_int", 99)
	m.PutEmptyMap("map_key").FromRaw(nestedMap.AsRaw())

	// Convert
	result := mapToGoMap(m)

	// Verify
	if result["str_key"] != "string_value" {
		t.Errorf("string value mismatch")
	}
	if result["bool_key"] != true {
		t.Errorf("bool value mismatch")
	}
	if result["int_key"] != int64(42) {
		t.Errorf("int value mismatch")
	}
	if result["double_key"] != 3.14 {
		t.Errorf("double value mismatch")
	}

	// Bytes should be hex encoded
	bytesResult := result["bytes_key"].(string)
	if bytesResult != "01020304" {
		t.Errorf("bytes value mismatch: expected 01020304, got %s", bytesResult)
	}

	// Slice
	sliceResult := result["slice_key"].([]any)
	if len(sliceResult) != 3 {
		t.Errorf("slice length mismatch")
	}
	if sliceResult[0] != "item1" {
		t.Errorf("slice item 0 mismatch")
	}
	if sliceResult[1] != int64(10) {
		t.Errorf("slice item 1 mismatch")
	}
	if sliceResult[2] != 2.71 {
		t.Errorf("slice item 2 mismatch")
	}

	// Nested map
	mapResult := result["map_key"].(map[string]any)
	if mapResult["nested_str"] != "nested_value" {
		t.Errorf("nested map string value mismatch")
	}
	if mapResult["nested_int"] != int64(99) {
		t.Errorf("nested map int value mismatch")
	}
}

// TestTemporalityString tests temporality conversion
func TestTemporalityString(t *testing.T) {
	tests := []struct {
		temporality pmetric.AggregationTemporality
		expected    string
	}{
		{pmetric.AggregationTemporalityDelta, "delta"},
		{pmetric.AggregationTemporalityCumulative, "cumulative"},
		{pmetric.AggregationTemporalityUnspecified, ""},
	}

	for _, tt := range tests {
		result := temporalityString(tt.temporality)
		if result != tt.expected {
			t.Errorf("temporality %v: expected %q, got %q", tt.temporality, tt.expected, result)
		}
	}
}

// TestMapToGoMapEmpty tests empty map conversion
func TestMapToGoMapEmpty(t *testing.T) {
	m := pcommon.NewMap()
	result := mapToGoMap(m)
	if len(result) != 0 {
		t.Errorf("expected empty map, got %d items", len(result))
	}
}

// TestConvertTracesMultipleSpans tests conversion of multiple spans
func TestConvertTracesMultipleSpans(t *testing.T) {
	traces := ptrace.NewTraces()
	rs := traces.ResourceSpans().AppendEmpty()
	rs.Resource().Attributes().PutStr("service.name", "my-service")

	ss := rs.ScopeSpans().AppendEmpty()

	// First span
	span1 := ss.Spans().AppendEmpty()
	span1.SetTraceID(pcommon.TraceID([16]byte{1}))
	span1.SetSpanID(pcommon.SpanID([8]byte{1}))
	span1.SetName("span1")

	// Second span
	span2 := ss.Spans().AppendEmpty()
	span2.SetTraceID(pcommon.TraceID([16]byte{2}))
	span2.SetSpanID(pcommon.SpanID([8]byte{2}))
	span2.SetName("span2")

	result := ConvertTraces(traces)
	if len(result) != 2 {
		t.Errorf("expected 2 spans, got %d", len(result))
	}
	if result[0].Name != "span1" {
		t.Errorf("span1 name mismatch")
	}
	if result[1].Name != "span2" {
		t.Errorf("span2 name mismatch")
	}
}

// TestConvertMetricsMultipleDataPoints tests conversion of multiple metrics
func TestConvertMetricsMultipleDataPoints(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m := sm.Metrics().AppendEmpty()
	m.SetName("metric1")

	gauge := m.SetEmptyGauge()
	dp1 := gauge.DataPoints().AppendEmpty()
	dp1.SetDoubleValue(10.0)

	dp2 := gauge.DataPoints().AppendEmpty()
	dp2.SetDoubleValue(20.0)

	result := ConvertMetrics(metrics)
	if len(result) != 2 {
		t.Errorf("expected 2 data points, got %d", len(result))
	}
	if result[0].Value != 10.0 {
		t.Errorf("dp1 value mismatch")
	}
	if result[1].Value != 20.0 {
		t.Errorf("dp2 value mismatch")
	}
}

// TestConvertLogsWithoutTraceContext tests log without trace context
func TestConvertLogsWithoutTraceContext(t *testing.T) {
	logs := plog.NewLogs()
	rl := logs.ResourceLogs().AppendEmpty()
	sl := rl.ScopeLogs().AppendEmpty()

	logRecord := sl.LogRecords().AppendEmpty()
	logRecord.SetTimestamp(pcommon.NewTimestampFromTime(time.Now()))
	logRecord.Body().SetStr("log message")

	result := ConvertLogs(logs)
	if len(result) == 0 {
		t.Fatal("expected log record")
	}

	lr := result[0]
	if lr.TraceID != "" {
		t.Errorf("expected empty trace ID, got %s", lr.TraceID)
	}
	if lr.SpanID != "" {
		t.Errorf("expected empty span ID, got %s", lr.SpanID)
	}
}

// TestSpanDurationCalculation tests that duration is calculated correctly
func TestSpanDurationCalculation(t *testing.T) {
	traces := ptrace.NewTraces()
	rs := traces.ResourceSpans().AppendEmpty()
	ss := rs.ScopeSpans().AppendEmpty()
	span := ss.Spans().AppendEmpty()
	span.SetTraceID(pcommon.TraceID([16]byte{1}))
	span.SetSpanID(pcommon.SpanID([8]byte{1}))

	startTime := time.Now()
	endTime := startTime.Add(500 * time.Millisecond)
	span.SetStartTimestamp(pcommon.NewTimestampFromTime(startTime))
	span.SetEndTimestamp(pcommon.NewTimestampFromTime(endTime))

	result := ConvertTraces(traces)
	if len(result) == 0 {
		t.Fatal("expected span")
	}

	s := result[0]
	// Duration should be in milliseconds
	if s.DurationMs != 500.0 {
		t.Errorf("expected duration 500ms, got %fms", s.DurationMs)
	}
}

// TestResourceConversion tests resource attribute extraction
func TestResourceConversion(t *testing.T) {
	traces := ptrace.NewTraces()
	rs := traces.ResourceSpans().AppendEmpty()
	rs.SetSchemaUrl("https://example.com/schema")

	res := rs.Resource()
	res.Attributes().PutStr("service.name", "my-service")
	res.Attributes().PutStr("service.version", "1.2.3")
	res.Attributes().PutStr("deployment.environment", "production")

	ss := rs.ScopeSpans().AppendEmpty()
	ss.SetSchemaUrl("https://example.com/scope-schema")
	ss.Scope().SetName("my-meter")
	ss.Scope().SetVersion("2.0.0")

	span := ss.Spans().AppendEmpty()
	span.SetTraceID(pcommon.TraceID([16]byte{1}))
	span.SetSpanID(pcommon.SpanID([8]byte{1}))

	result := ConvertTraces(traces)
	if len(result) == 0 {
		t.Fatal("expected span")
	}

	s := result[0]
	if s.Resource.ServiceName != "my-service" {
		t.Errorf("service name mismatch")
	}
	if s.Resource.SchemaURL != "https://example.com/schema" {
		t.Errorf("resource schema URL mismatch")
	}
	if s.Resource.Attributes["service.version"] != "1.2.3" {
		t.Errorf("resource attributes mismatch")
	}
	if s.Scope.Name != "my-meter" {
		t.Errorf("scope name mismatch")
	}
	if s.Scope.Version != "2.0.0" {
		t.Errorf("scope version mismatch")
	}
	if s.Scope.SchemaURL != "https://example.com/scope-schema" {
		t.Errorf("scope schema URL mismatch")
	}
}

// TestValueStringConversion tests valueString helper function
func TestValueStringConversion(t *testing.T) {
	// String value
	v1 := pcommon.NewValueStr("test")
	if valueString(v1) != "test" {
		t.Errorf("string value conversion failed")
	}

	// Non-string value should use AsString()
	v2 := pcommon.NewValueInt(42)
	if valueString(v2) != "42" {
		t.Errorf("int to string conversion failed")
	}
}

// TestConvertMetricsWithFlags tests metric data points with flags
func TestConvertMetricsWithFlags(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m := sm.Metrics().AppendEmpty()
	m.SetName("test.metric")

	gauge := m.SetEmptyGauge()
	dp := gauge.DataPoints().AppendEmpty()
	dp.SetDoubleValue(1.5)
	dp.SetFlags(0x01)

	result := ConvertMetrics(metrics)
	if len(result) == 0 {
		t.Fatal("expected metric data point")
	}

	if result[0].Flags != 0x01 {
		t.Errorf("expected flags 0x01, got %d", result[0].Flags)
	}
}

// TestConvertMetricsStartTime tests metric start time conversion
func TestConvertMetricsStartTime(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m := sm.Metrics().AppendEmpty()
	m.SetName("test.metric")

	gauge := m.SetEmptyGauge()
	dp := gauge.DataPoints().AppendEmpty()
	dp.SetDoubleValue(1.5)

	startTime := time.Now()
	timestamp := startTime.Add(10 * time.Second)

	dp.SetStartTimestamp(pcommon.NewTimestampFromTime(startTime))
	dp.SetTimestamp(pcommon.NewTimestampFromTime(timestamp))

	result := ConvertMetrics(metrics)
	if len(result) == 0 {
		t.Fatal("expected metric data point")
	}

	mdp := result[0]
	if mdp.StartTime != startTime.Truncate(time.Nanosecond) && mdp.StartTime.Nanosecond() != startTime.Nanosecond() {
		// Compare with some tolerance for time conversion
		diff := mdp.StartTime.Sub(startTime)
		if diff < -time.Microsecond || diff > time.Microsecond {
			t.Errorf("start time mismatch")
		}
	}
}

// TestConvertTracesMultipleScopesAndResources tests hierarchical structure
func TestConvertTracesMultipleScopesAndResources(t *testing.T) {
	traces := ptrace.NewTraces()

	// First resource
	rs1 := traces.ResourceSpans().AppendEmpty()
	rs1.Resource().Attributes().PutStr("service.name", "service1")

	ss1 := rs1.ScopeSpans().AppendEmpty()
	ss1.Scope().SetName("scope1")
	span1 := ss1.Spans().AppendEmpty()
	span1.SetTraceID(pcommon.TraceID([16]byte{1}))
	span1.SetSpanID(pcommon.SpanID([8]byte{1}))
	span1.SetName("span1")

	// Second resource
	rs2 := traces.ResourceSpans().AppendEmpty()
	rs2.Resource().Attributes().PutStr("service.name", "service2")

	ss2 := rs2.ScopeSpans().AppendEmpty()
	ss2.Scope().SetName("scope2")
	span2 := ss2.Spans().AppendEmpty()
	span2.SetTraceID(pcommon.TraceID([16]byte{2}))
	span2.SetSpanID(pcommon.SpanID([8]byte{2}))
	span2.SetName("span2")

	result := ConvertTraces(traces)
	if len(result) != 2 {
		t.Errorf("expected 2 spans, got %d", len(result))
	}

	if result[0].Resource.ServiceName != "service1" {
		t.Errorf("span1 service name mismatch")
	}
	if result[0].Scope.Name != "scope1" {
		t.Errorf("span1 scope name mismatch")
	}

	if result[1].Resource.ServiceName != "service2" {
		t.Errorf("span2 service name mismatch")
	}
	if result[1].Scope.Name != "scope2" {
		t.Errorf("span2 scope name mismatch")
	}
}

// TestConvertMetricsWithNaNAndInf tests special float values
func TestConvertMetricsWithNaNAndInf(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m1 := sm.Metrics().AppendEmpty()
	m1.SetName("nan.metric")
	gauge1 := m1.SetEmptyGauge()
	dp1 := gauge1.DataPoints().AppendEmpty()
	dp1.SetDoubleValue(math.NaN())

	m2 := sm.Metrics().AppendEmpty()
	m2.SetName("inf.metric")
	gauge2 := m2.SetEmptyGauge()
	dp2 := gauge2.DataPoints().AppendEmpty()
	dp2.SetDoubleValue(math.Inf(1))

	result := ConvertMetrics(metrics)
	if len(result) != 2 {
		t.Errorf("expected 2 data points, got %d", len(result))
	}

	if !math.IsNaN(result[0].Value) {
		t.Errorf("expected NaN value")
	}
	if !math.IsInf(result[1].Value, 1) {
		t.Errorf("expected +Inf value")
	}
}

// TestConvertLogsMultipleScopesAndResources tests hierarchical log structure
func TestConvertLogsMultipleScopesAndResources(t *testing.T) {
	logs := plog.NewLogs()

	// First resource
	rl1 := logs.ResourceLogs().AppendEmpty()
	rl1.Resource().Attributes().PutStr("service.name", "app1")

	sl1 := rl1.ScopeLogs().AppendEmpty()
	sl1.Scope().SetName("logger1")
	log1 := sl1.LogRecords().AppendEmpty()
	log1.Body().SetStr("log from app1")

	// Second resource
	rl2 := logs.ResourceLogs().AppendEmpty()
	rl2.Resource().Attributes().PutStr("service.name", "app2")

	sl2 := rl2.ScopeLogs().AppendEmpty()
	sl2.Scope().SetName("logger2")
	log2 := sl2.LogRecords().AppendEmpty()
	log2.Body().SetStr("log from app2")

	result := ConvertLogs(logs)
	if len(result) != 2 {
		t.Errorf("expected 2 logs, got %d", len(result))
	}

	if result[0].Body != "log from app1" {
		t.Errorf("log1 body mismatch")
	}
	if result[0].Resource.ServiceName != "app1" {
		t.Errorf("log1 service name mismatch")
	}

	if result[1].Body != "log from app2" {
		t.Errorf("log2 body mismatch")
	}
	if result[1].Resource.ServiceName != "app2" {
		t.Errorf("log2 service name mismatch")
	}
}

// TestMapToGoMapNestedStructure tests deeply nested maps and slices
func TestMapToGoMapNestedStructure(t *testing.T) {
	m := pcommon.NewMap()

	// Create a complex nested structure
	innerMap := pcommon.NewMap()
	innerMap.PutStr("key1", "value1")
	innerMap.PutInt("key2", 123)

	innerSlice := pcommon.NewSlice()
	innerSlice.AppendEmpty().SetStr("item1")
	innerSlice.AppendEmpty().SetInt(456)

	outerMap := pcommon.NewMap()
	outerMap.PutEmptyMap("nested_map").FromRaw(innerMap.AsRaw())
	outerMap.PutEmptySlice("nested_slice").FromRaw(innerSlice.AsRaw())

	m.PutEmptyMap("outer").FromRaw(outerMap.AsRaw())

	result := mapToGoMap(m)

	outer := result["outer"].(map[string]any)
	nestedMap := outer["nested_map"].(map[string]any)
	if nestedMap["key1"] != "value1" {
		t.Errorf("nested map value mismatch")
	}
	if nestedMap["key2"] != int64(123) {
		t.Errorf("nested map int value mismatch")
	}

	nestedSlice := outer["nested_slice"].([]any)
	if nestedSlice[0] != "item1" {
		t.Errorf("nested slice item 0 mismatch")
	}
	if nestedSlice[1] != int64(456) {
		t.Errorf("nested slice item 1 mismatch")
	}
}

// TestConvertMetricsHistogramWithZeroBounds tests histogram with zero bounds
func TestConvertMetricsHistogramWithZeroBounds(t *testing.T) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	m := sm.Metrics().AppendEmpty()
	m.SetName("no_bounds.histogram")

	histogram := m.SetEmptyHistogram()
	dp := histogram.DataPoints().AppendEmpty()
	dp.SetCount(5)
	dp.SetSum(100.0)

	result := ConvertMetrics(metrics)
	if len(result) == 0 {
		t.Fatal("expected metric data point")
	}

	mdp := result[0]
	if len(mdp.ExplicitBounds) != 0 {
		t.Errorf("expected 0 bounds, got %d", len(mdp.ExplicitBounds))
	}
	if len(mdp.BucketCounts) != 0 {
		t.Errorf("expected 0 bucket counts, got %d", len(mdp.BucketCounts))
	}
}

// TestConvertLogsWithNonStringBody tests log body conversion for non-string types
func TestConvertLogsWithNonStringBody(t *testing.T) {
	logs := plog.NewLogs()
	rl := logs.ResourceLogs().AppendEmpty()
	sl := rl.ScopeLogs().AppendEmpty()

	logRecord := sl.LogRecords().AppendEmpty()
	logRecord.SetTimestamp(pcommon.NewTimestampFromTime(time.Now()))
	logRecord.Body().SetInt(12345)

	result := ConvertLogs(logs)
	if len(result) == 0 {
		t.Fatal("expected log record")
	}

	lr := result[0]
	if lr.Body != "12345" {
		t.Errorf("expected body '12345', got '%s'", lr.Body)
	}
}

// BenchmarkConvertTraces benchmarks trace conversion
func BenchmarkConvertTraces(b *testing.B) {
	traces := ptrace.NewTraces()
	rs := traces.ResourceSpans().AppendEmpty()
	rs.Resource().Attributes().PutStr("service.name", "bench-service")

	ss := rs.ScopeSpans().AppendEmpty()
	ss.Scope().SetName("bench-meter")

	for i := 0; i < 100; i++ {
		span := ss.Spans().AppendEmpty()
		span.SetTraceID(pcommon.TraceID([16]byte{byte(i)}))
		span.SetSpanID(pcommon.SpanID([8]byte{byte(i)}))
		span.SetName("span")
		span.Attributes().PutStr("key", "value")
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		ConvertTraces(traces)
	}
}

// BenchmarkConvertMetrics benchmarks metrics conversion
func BenchmarkConvertMetrics(b *testing.B) {
	metrics := pmetric.NewMetrics()
	rm := metrics.ResourceMetrics().AppendEmpty()
	sm := rm.ScopeMetrics().AppendEmpty()

	for i := 0; i < 50; i++ {
		m := sm.Metrics().AppendEmpty()
		m.SetName("metric")
		gauge := m.SetEmptyGauge()
		for j := 0; j < 10; j++ {
			dp := gauge.DataPoints().AppendEmpty()
			dp.SetDoubleValue(float64(i*j))
		}
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		ConvertMetrics(metrics)
	}
}

// TestEmptyTraces tests conversion of empty traces
func TestEmptyTraces(t *testing.T) {
	traces := ptrace.NewTraces()
	result := ConvertTraces(traces)
	if len(result) != 0 {
		t.Errorf("expected empty result, got %d spans", len(result))
	}
}

// TestEmptyMetrics tests conversion of empty metrics
func TestEmptyMetrics(t *testing.T) {
	metrics := pmetric.NewMetrics()
	result := ConvertMetrics(metrics)
	if len(result) != 0 {
		t.Errorf("expected empty result, got %d data points", len(result))
	}
}

// TestEmptyLogs tests conversion of empty logs
func TestEmptyLogs(t *testing.T) {
	logs := plog.NewLogs()
	result := ConvertLogs(logs)
	if len(result) != 0 {
		t.Errorf("expected empty result, got %d logs", len(result))
	}
}

// TestByteConversionToHex tests that bytes are correctly converted to hex strings
func TestByteConversionToHex(t *testing.T) {
	m := pcommon.NewMap()
	testBytes := []byte{0xAB, 0xCD, 0xEF, 0x00, 0x12, 0x34}
	m.PutEmptyBytes("test").FromRaw(testBytes)

	result := mapToGoMap(m)
	hexStr := result["test"].(string)
	expectedHex := "abcdef001234"

	if hexStr != expectedHex {
		t.Errorf("expected hex %s, got %s", expectedHex, hexStr)
	}

	// Verify round-trip
	decoded, err := hex.DecodeString(hexStr)
	if err != nil {
		t.Fatalf("failed to decode hex: %v", err)
	}
	if !bytes.Equal(decoded, testBytes) {
		t.Errorf("bytes round-trip failed")
	}
}
