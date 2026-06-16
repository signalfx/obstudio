package store

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

// ============================================================================
// Helper Functions for Test Data Creation
// ============================================================================

// newTestSpan creates a test span with sensible defaults
func newTestSpan(traceID, spanID, name string, startTime time.Time, durationMs float64) Span {
	return Span{
		TraceID:      traceID,
		SpanID:       spanID,
		ParentSpanID: "",
		Name:         name,
		Kind:         "INTERNAL",
		StartTime:    startTime,
		EndTime:      startTime.Add(time.Duration(durationMs) * time.Millisecond),
		DurationMs:   durationMs,
		Status:       SpanStatus{Code: "OK"},
		Attributes:   make(map[string]any),
		Events:       make([]SpanEvent, 0),
		Links:        make([]SpanLink, 0),
		Resource: Resource{
			ServiceName: "test-service",
			Attributes:  make(map[string]any),
		},
		Scope: Scope{Name: "test-scope"},
	}
}

// newTestMetric creates a test metric data point with sensible defaults
func newTestMetric(name string, value float64, timestamp time.Time) MetricDataPoint {
	return MetricDataPoint{
		Name:        name,
		Description: "test metric",
		Unit:        "1",
		Type:        "gauge",
		Timestamp:   timestamp,
		Attributes:  make(map[string]any),
		Resource: Resource{
			ServiceName: "test-service",
			Attributes:  make(map[string]any),
		},
		Scope: Scope{Name: "test-scope"},
		Value: value,
	}
}

// newTestLog creates a test log record with sensible defaults
func newTestLog(body string, timestamp time.Time) LogRecord {
	return LogRecord{
		ID:             "", // Will be auto-generated
		Timestamp:      timestamp,
		SeverityNumber: 2,
		SeverityText:   "INFO",
		Body:           body,
		Attributes:     make(map[string]any),
		Resource: Resource{
			ServiceName: "test-service",
			Attributes:  make(map[string]any),
		},
		Scope: Scope{Name: "test-scope"},
	}
}

func timePointer(ts time.Time) *time.Time {
	return &ts
}

// ============================================================================
// Ring Buffer Tests
// ============================================================================

func TestRingBuffer_Push_Empty(t *testing.T) {
	rb := newRingBuffer[int](3)
	if rb.size() != 0 {
		t.Errorf("expected size 0, got %d", rb.size())
	}
}

func TestRingBuffer_Push_UnderCapacity(t *testing.T) {
	rb := newRingBuffer[int](5)
	rb.push([]int{1, 2, 3})
	if rb.size() != 3 {
		t.Errorf("expected size 3, got %d", rb.size())
	}
	snap := rb.snapshot()
	if len(snap) != 3 || snap[0] != 1 || snap[1] != 2 || snap[2] != 3 {
		t.Errorf("expected [1,2,3], got %v", snap)
	}
}

func TestRingBuffer_Push_AtCapacity(t *testing.T) {
	rb := newRingBuffer[int](3)
	rb.push([]int{1, 2, 3})
	if rb.size() != 3 {
		t.Errorf("expected size 3, got %d", rb.size())
	}
	snap := rb.snapshot()
	if len(snap) != 3 || snap[0] != 1 || snap[1] != 2 || snap[2] != 3 {
		t.Errorf("expected [1,2,3], got %v", snap)
	}
}

func TestRingBuffer_Push_OverCapacity(t *testing.T) {
	rb := newRingBuffer[int](3)
	rb.push([]int{1, 2, 3, 4, 5})
	if rb.size() != 3 {
		t.Errorf("expected size 3, got %d", rb.size())
	}
	snap := rb.snapshot()
	// Should contain [3, 4, 5] (oldest items overwritten)
	if len(snap) != 3 || snap[0] != 3 || snap[1] != 4 || snap[2] != 5 {
		t.Errorf("expected [3,4,5], got %v", snap)
	}
}

func TestRingBuffer_Push_WrapAround(t *testing.T) {
	rb := newRingBuffer[int](3)
	rb.push([]int{1, 2, 3})
	rb.push([]int{4})
	rb.push([]int{5})
	snap := rb.snapshot()
	// Should contain [3, 4, 5]
	if len(snap) != 3 || snap[0] != 3 || snap[1] != 4 || snap[2] != 5 {
		t.Errorf("expected [3,4,5], got %v", snap)
	}
}

func TestRingBuffer_Snapshot_Empty(t *testing.T) {
	rb := newRingBuffer[int](3)
	snap := rb.snapshot()
	if snap != nil {
		t.Errorf("expected nil, got %v", snap)
	}
}

func TestRingBuffer_Clear(t *testing.T) {
	rb := newRingBuffer[int](3)
	rb.push([]int{1, 2, 3})
	rb.clear()
	if rb.size() != 0 {
		t.Errorf("expected size 0 after clear, got %d", rb.size())
	}
	snap := rb.snapshot()
	if snap != nil {
		t.Errorf("expected nil after clear, got %v", snap)
	}
}

func TestRingBuffer_Size(t *testing.T) {
	rb := newRingBuffer[int](5)
	if rb.size() != 0 {
		t.Errorf("expected size 0 initially, got %d", rb.size())
	}
	rb.push([]int{1, 2})
	if rb.size() != 2 {
		t.Errorf("expected size 2, got %d", rb.size())
	}
	rb.push([]int{3, 4, 5, 6, 7, 8})
	if rb.size() != 5 {
		t.Errorf("expected size 5 after overflow, got %d", rb.size())
	}
}

func TestRingBuffer_Iterate_Empty(t *testing.T) {
	rb := newRingBuffer[int](3)
	count := 0
	rb.iterate(func(i int) {
		count++
	})
	if count != 0 {
		t.Errorf("expected 0 iterations on empty buffer, got %d", count)
	}
}

func TestRingBuffer_Iterate_UnderCapacity(t *testing.T) {
	rb := newRingBuffer[int](5)
	rb.push([]int{10, 20, 30})
	var result []int
	rb.iterate(func(i int) {
		result = append(result, i)
	})
	if len(result) != 3 || result[0] != 10 || result[1] != 20 || result[2] != 30 {
		t.Errorf("expected [10,20,30], got %v", result)
	}
}

func TestRingBuffer_Iterate_OverCapacity(t *testing.T) {
	rb := newRingBuffer[int](3)
	rb.push([]int{1, 2, 3, 4, 5})
	var result []int
	rb.iterate(func(i int) {
		result = append(result, i)
	})
	if len(result) != 3 || result[0] != 3 || result[1] != 4 || result[2] != 5 {
		t.Errorf("expected [3,4,5], got %v", result)
	}
}

// ============================================================================
// AddSpansForConnection Tests
// ============================================================================

func TestAddSpansForConnection_StoresWithOwnerConnID(t *testing.T) {
	s := New()
	now := time.Now()
	span := newTestSpan("trace-1", "span-1", "test", now, 10)

	s.AddSpansForConnection("conn-1", []Span{span})

	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span, got %d", stats.SpanCount)
	}
}

func TestAddSpansForConnection_EmptyConnID(t *testing.T) {
	s := New()
	now := time.Now()
	span := newTestSpan("trace-1", "span-1", "test", now, 10)

	s.AddSpansForConnection("", []Span{span})

	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span, got %d", stats.SpanCount)
	}
}

func TestAddSpansForConnection_MultipleSpans(t *testing.T) {
	s := New()
	now := time.Now()
	spans := []Span{
		newTestSpan("trace-1", "span-1", "test1", now, 10),
		newTestSpan("trace-1", "span-2", "test2", now.Add(10*time.Millisecond), 20),
	}

	s.AddSpansForConnection("conn-1", spans)

	stats := s.Stats()
	if stats.SpanCount != 2 {
		t.Errorf("expected 2 spans, got %d", stats.SpanCount)
	}
}

// ============================================================================
// AddMetricsForConnection Tests
// ============================================================================

func TestAddMetricsForConnection_StoresWithOwnerConnID(t *testing.T) {
	s := New()
	now := time.Now()
	metric := newTestMetric("cpu.usage", 42.5, now)

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{metric})

	stats := s.Stats()
	if stats.DataPointCount != 1 {
		t.Errorf("expected 1 metric, got %d", stats.DataPointCount)
	}
}

func TestAddMetricsForConnection_EmptyConnID(t *testing.T) {
	s := New()
	now := time.Now()
	metric := newTestMetric("cpu.usage", 42.5, now)

	s.AddMetricsForConnection("", []MetricDataPoint{metric})

	stats := s.Stats()
	if stats.DataPointCount != 1 {
		t.Errorf("expected 1 metric, got %d", stats.DataPointCount)
	}
}

func TestAddMetricsForConnection_MultipleMetrics(t *testing.T) {
	s := New()
	now := time.Now()
	metrics := []MetricDataPoint{
		newTestMetric("cpu.usage", 42.5, now),
		newTestMetric("memory.usage", 80.0, now.Add(100*time.Millisecond)),
	}

	s.AddMetricsForConnection("conn-1", metrics)

	stats := s.Stats()
	if stats.DataPointCount != 2 {
		t.Errorf("expected 2 metrics, got %d", stats.DataPointCount)
	}
	if stats.MetricNameCount != 2 {
		t.Errorf("expected 2 metric names, got %d", stats.MetricNameCount)
	}
}

// ============================================================================
// AddLogsForConnection Tests
// ============================================================================

func TestAddLogsForConnection_StoresWithOwnerConnID(t *testing.T) {
	s := New()
	now := time.Now()
	log := newTestLog("test message", now)

	s.AddLogsForConnection("conn-1", []LogRecord{log})

	stats := s.Stats()
	if stats.LogCount != 1 {
		t.Errorf("expected 1 log, got %d", stats.LogCount)
	}
}

func TestAddLogsForConnection_AutoGeneratesID(t *testing.T) {
	s := New()
	now := time.Now()
	log1 := newTestLog("message 1", now)
	log2 := newTestLog("message 2", now.Add(100*time.Millisecond))

	s.AddLogsForConnection("conn-1", []LogRecord{log1})
	s.AddLogsForConnection("conn-1", []LogRecord{log2})

	logs := s.QueryLogs(10)
	if len(logs) != 2 {
		t.Errorf("expected 2 logs, got %d", len(logs))
	}
	if logs[0].ID == "" {
		t.Error("expected auto-generated ID for log")
	}
	if logs[0].ID == logs[1].ID {
		t.Error("expected different IDs for different logs")
	}
}

func TestAddLogsForConnection_PreservesExistingID(t *testing.T) {
	s := New()
	now := time.Now()
	log := newTestLog("message", now)
	log.ID = "custom-id"

	s.AddLogsForConnection("conn-1", []LogRecord{log})

	logs := s.QueryLogs(10)
	if len(logs) != 1 {
		t.Errorf("expected 1 log, got %d", len(logs))
	}
	if logs[0].ID != "custom-id" {
		t.Errorf("expected custom-id, got %s", logs[0].ID)
	}
}

// ============================================================================
// EvictConnection Tests
// ============================================================================

func TestEvictConnection_RemovesOnlyTargetConnection(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "test", now, 10)
	span2 := newTestSpan("trace-2", "span-2", "test", now.Add(100*time.Millisecond), 10)

	s.AddSpansForConnection("conn-1", []Span{span1})
	s.AddSpansForConnection("conn-2", []Span{span2})

	stats := s.Stats()
	if stats.SpanCount != 2 {
		t.Errorf("expected 2 spans initially, got %d", stats.SpanCount)
	}

	s.EvictConnection("conn-1")

	stats = s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span after eviction, got %d", stats.SpanCount)
	}
}

func TestEvictConnection_PreservesOtherConnections(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "test", now, 10)
	span2 := newTestSpan("trace-2", "span-2", "test", now.Add(100*time.Millisecond), 10)
	metric1 := newTestMetric("cpu", 42.5, now)
	metric2 := newTestMetric("memory", 80.0, now.Add(100*time.Millisecond))

	s.AddSpansForConnection("conn-1", []Span{span1})
	s.AddSpansForConnection("conn-2", []Span{span2})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{metric1})
	s.AddMetricsForConnection("conn-2", []MetricDataPoint{metric2})

	s.EvictConnection("conn-1")

	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span, got %d", stats.SpanCount)
	}
	if stats.DataPointCount != 1 {
		t.Errorf("expected 1 metric, got %d", stats.DataPointCount)
	}
}

func TestEvictConnection_NoOpForUnknownConnID(t *testing.T) {
	s := New()
	now := time.Now()
	span := newTestSpan("trace-1", "span-1", "test", now, 10)

	s.AddSpansForConnection("conn-1", []Span{span})

	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span, got %d", stats.SpanCount)
	}

	s.EvictConnection("unknown-conn")

	stats = s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span after no-op eviction, got %d", stats.SpanCount)
	}
}

func TestEvictConnection_EvictMultipleTypes(t *testing.T) {
	s := New()
	now := time.Now()

	span := newTestSpan("trace-1", "span-1", "test", now, 10)
	metric := newTestMetric("cpu", 42.5, now)
	log := newTestLog("test message", now)

	s.AddSpansForConnection("conn-1", []Span{span})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{metric})
	s.AddLogsForConnection("conn-1", []LogRecord{log})

	stats := s.Stats()
	if stats.SpanCount != 1 || stats.DataPointCount != 1 || stats.LogCount != 1 {
		t.Error("expected 1 of each type initially")
	}

	s.EvictConnection("conn-1")

	stats = s.Stats()
	if stats.SpanCount != 0 || stats.DataPointCount != 0 || stats.LogCount != 0 {
		t.Error("expected 0 of all types after eviction")
	}
}

func TestEvictConnection_EmptyConnIDNoOp(t *testing.T) {
	s := New()
	now := time.Now()
	span := newTestSpan("trace-1", "span-1", "test", now, 10)

	s.AddSpansForConnection("conn-1", []Span{span})

	s.EvictConnection("")

	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span after empty conn eviction, got %d", stats.SpanCount)
	}
}

// ============================================================================
// Session Reset Tests
// ============================================================================

func TestSessionReset_GapGreaterThan30sClears(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "test", now, 10)
	s.AddSpansForConnection("conn-1", []Span{span1})

	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span, got %d", stats.SpanCount)
	}

	// Manually set last ingest to > 30s ago
	s.mu.Lock()
	s.lastIngest = time.Now().Add(-35 * time.Second)
	s.mu.Unlock()

	// Add new span after gap > 30s
	span2 := newTestSpan("trace-2", "span-2", "test", now.Add(40*time.Second), 10)
	s.AddSpansForConnection("conn-1", []Span{span2})

	stats = s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span after reset, got %d", stats.SpanCount)
	}
	if stats.TraceCount != 1 {
		t.Errorf("expected 1 trace, got %d", stats.TraceCount)
	}
}

func TestSessionReset_GapLessThan30sDoesNotClear(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "test", now, 10)
	s.AddSpansForConnection("conn-1", []Span{span1})

	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span, got %d", stats.SpanCount)
	}

	// Manually set last ingest to < 30s ago
	s.mu.Lock()
	s.lastIngest = time.Now().Add(-10 * time.Second)
	s.mu.Unlock()

	// Add new span after gap < 30s
	span2 := newTestSpan("trace-2", "span-2", "test", now.Add(15*time.Second), 10)
	s.AddSpansForConnection("conn-1", []Span{span2})

	stats = s.Stats()
	if stats.SpanCount != 2 {
		t.Errorf("expected 2 spans (not cleared), got %d", stats.SpanCount)
	}
	if stats.TraceCount != 2 {
		t.Errorf("expected 2 traces, got %d", stats.TraceCount)
	}
}

// ============================================================================
// Subscribe/Unsubscribe Tests
// ============================================================================

func TestSubscribe_ReturnsChannelAndID(t *testing.T) {
	s := New()
	id, ch := s.Subscribe()

	if id != 0 {
		t.Errorf("expected first subscriber ID to be 0, got %d", id)
	}
	if ch == nil {
		t.Error("expected non-nil channel")
	}
}

func TestSubscribe_MultipleSubscribers(t *testing.T) {
	s := New()
	id1, ch1 := s.Subscribe()
	id2, ch2 := s.Subscribe()

	if id1 == id2 {
		t.Errorf("expected different IDs, got %d and %d", id1, id2)
	}
	if ch1 == ch2 {
		t.Error("expected different channels")
	}
}

func TestSubscriber_ReceivesSignals(t *testing.T) {
	s := New()
	_, ch := s.Subscribe()

	now := time.Now()
	span := newTestSpan("trace-1", "span-1", "test", now, 10)

	s.AddSpansForConnection("conn-1", []Span{span})

	// Wait for signal
	select {
	case sig := <-ch:
		if sig != SignalTraces {
			t.Errorf("expected SignalTraces, got %v", sig)
		}
	case <-time.After(1 * time.Second):
		t.Error("expected to receive signal")
	}
}

func TestUnsubscribe_ClosesChannel(t *testing.T) {
	s := New()
	id, ch := s.Subscribe()

	s.Unsubscribe(id)

	// Channel should be closed
	select {
	case _, ok := <-ch:
		if ok {
			t.Error("expected channel to be closed")
		}
	case <-time.After(1 * time.Second):
		t.Error("expected channel to close immediately")
	}
}

func TestUnsubscribe_NoOpForUnknownID(t *testing.T) {
	s := New()
	// Should not panic
	s.Unsubscribe(999)
}

// ============================================================================
// QueryTraces Tests
// ============================================================================

func TestQueryTraces_GroupsByTraceID(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "root", now, 10)
	span2 := newTestSpan("trace-1", "span-2", "child", now.Add(5*time.Millisecond), 5)
	span2.ParentSpanID = "span-1"

	s.AddSpansForConnection("conn-1", []Span{span1, span2})

	results := s.QueryTraces(10)
	if len(results) != 1 {
		t.Errorf("expected 1 trace, got %d", len(results))
	}
	if results[0].TraceID != "trace-1" {
		t.Errorf("expected trace-1, got %s", results[0].TraceID)
	}
	if results[0].SpanCount != 2 {
		t.Errorf("expected 2 spans in trace, got %d", results[0].SpanCount)
	}
}

func TestQueryTraces_SortsNewestFirst(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "root", now, 10)
	span2 := newTestSpan("trace-2", "span-1", "root", now.Add(100*time.Millisecond), 10)

	s.AddSpansForConnection("conn-1", []Span{span1})
	s.AddSpansForConnection("conn-1", []Span{span2})

	results := s.QueryTraces(10)
	if len(results) != 2 {
		t.Errorf("expected 2 traces, got %d", len(results))
	}
	if results[0].TraceID != "trace-2" {
		t.Errorf("expected newest trace first, got %s", results[0].TraceID)
	}
}

func TestQueryTraces_RespectsLimit(t *testing.T) {
	s := New()
	now := time.Now()

	for i := 0; i < 5; i++ {
		span := newTestSpan(fmt.Sprintf("trace-%d", i), "span-1", "root", now.Add(time.Duration(i)*100*time.Millisecond), 10)
		s.AddSpansForConnection("conn-1", []Span{span})
	}

	results := s.QueryTraces(3)
	if len(results) != 3 {
		t.Errorf("expected 3 traces, got %d", len(results))
	}
}

func TestQueryTraces_DefaultLimitIs100(t *testing.T) {
	s := New()
	now := time.Now()

	span := newTestSpan("trace-1", "span-1", "root", now, 10)
	s.AddSpansForConnection("conn-1", []Span{span})

	results := s.QueryTraces(0)
	if len(results) != 1 {
		t.Errorf("expected 1 trace with default limit, got %d", len(results))
	}
}

func TestQueryTraces_RootSpanDetection(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "child", now, 10)
	span1.ParentSpanID = "span-0"
	span2 := newTestSpan("trace-1", "span-2", "root", now.Add(5*time.Millisecond), 15)
	span2.ParentSpanID = ""

	s.AddSpansForConnection("conn-1", []Span{span1, span2})

	results := s.QueryTraces(10)
	if len(results) != 1 {
		t.Fatalf("expected 1 trace, got %d", len(results))
	}
	if results[0].RootSpanName != "root" {
		t.Errorf("expected root span name 'root', got %s", results[0].RootSpanName)
	}
}

func TestQueryTraces_ZeroDurationIsIncludedInJSON(t *testing.T) {
	s := New()
	now := time.Now()

	span := newTestSpan("trace-1", "span-1", "root", now, 0)
	s.AddSpansForConnection("conn-1", []Span{span})

	results := s.QueryTraces(10)
	if len(results) != 1 {
		t.Fatalf("expected 1 trace summary, got %d", len(results))
	}
	if results[0].DurationMs != 0 {
		t.Fatalf("expected zero duration in summary, got %f", results[0].DurationMs)
	}

	summaryJSON, err := json.Marshal(results[0])
	if err != nil {
		t.Fatalf("marshal summary: %v", err)
	}
	if !strings.Contains(string(summaryJSON), `"durationMs":0`) {
		t.Fatalf("expected summary JSON to include zero duration, got %s", summaryJSON)
	}

	detail := s.Trace("trace-1", 10)
	if detail == nil {
		t.Fatal("expected trace detail")
	}
	if detail.DurationMs != 0 {
		t.Fatalf("expected zero duration in detail, got %f", detail.DurationMs)
	}

	detailJSON, err := json.Marshal(detail)
	if err != nil {
		t.Fatalf("marshal detail: %v", err)
	}
	if !strings.Contains(string(detailJSON), `"durationMs":0`) {
		t.Fatalf("expected detail JSON to include zero duration, got %s", detailJSON)
	}
}

// ============================================================================
// Trace Tests
// ============================================================================

func TestTrace_ReturnsNilForNotFound(t *testing.T) {
	s := New()
	result := s.Trace("unknown-trace", 10)
	if result != nil {
		t.Error("expected nil for unknown trace")
	}
}

func TestTrace_TruncatesEvents(t *testing.T) {
	s := New()
	now := time.Now()

	span := newTestSpan("trace-1", "span-1", "root", now, 10)
	// Add many events
	for i := 0; i < 20; i++ {
		span.Events = append(span.Events, SpanEvent{
			Name:       fmt.Sprintf("event-%d", i),
			Timestamp:  now.Add(time.Duration(i) * time.Millisecond),
			Attributes: make(map[string]any),
		})
	}

	s.AddSpansForConnection("conn-1", []Span{span})

	result := s.Trace("trace-1", 5)
	if result == nil {
		t.Fatal("expected trace to be found")
	}
	if len(result.Spans) != 1 {
		t.Errorf("expected 1 span, got %d", len(result.Spans))
	}
	if len(result.Spans[0].Events) != 5 {
		t.Errorf("expected 5 events after truncation, got %d", len(result.Spans[0].Events))
	}
}

func TestTrace_DefaultEventLimit(t *testing.T) {
	s := New()
	now := time.Now()

	span := newTestSpan("trace-1", "span-1", "root", now, 10)
	s.AddSpansForConnection("conn-1", []Span{span})

	result := s.Trace("trace-1", 0)
	if result == nil {
		t.Fatal("expected trace to be found")
	}
	// Default eventLimit is 12
}

func TestTrace_NonGenAITraceOmitsGenAIProjection(t *testing.T) {
	s := New()
	now := time.Now()

	span := newTestSpan("trace-1", "span-1", "GET /health", now, 10)
	s.AddSpansForConnection("conn-1", []Span{span})

	result := s.Trace("trace-1", 0)
	if result == nil {
		t.Fatal("expected trace to be found")
	}
	if result.GenAI != nil {
		t.Fatalf("expected no GenAI projection for non-GenAI trace, got %#v", result.GenAI)
	}
}

func TestQueryTraceSummariesFiltered_MarksGenAITraces(t *testing.T) {
	s := New()
	now := time.Now()

	plain := newTestSpan("trace-plain", "plain-root", "GET /health", now, 10)

	genai := newTestSpan("trace-genai", "workflow", "assistant_v3_turn", now.Add(100*time.Millisecond), 20)
	genai.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	genai.Attributes["gen_ai.workflow.name"] = "assistant_v3_turn"

	s.AddSpansForConnection("conn-1", []Span{plain, genai})

	results := s.QueryTraceSummariesFiltered(TraceSummaryFilter{Limit: 10})
	if len(results) != 2 {
		t.Fatalf("expected 2 traces, got %d", len(results))
	}

	byTraceID := make(map[string]TraceSummary)
	for _, result := range results {
		byTraceID[result.TraceID] = result
	}
	if byTraceID["trace-genai"].IsGenAI != true {
		t.Fatalf("expected GenAI trace summary to be marked")
	}
	if byTraceID["trace-plain"].IsGenAI {
		t.Fatalf("expected non-GenAI trace summary to stay unmarked")
	}
}

func TestTrace_IncludesBackendGenAIProjection(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai", "workflow", "invoke_workflow", now, 3000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	httpSpan := newTestSpan("trace-genai", "http", "POST /assistant", now.Add(10*time.Millisecond), 2900)
	httpSpan.ParentSpanID = "workflow"

	agent := newTestSpan("trace-genai", "agent", "invoke_agent", now.Add(20*time.Millisecond), 2500)
	agent.ParentSpanID = "http"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "Triage Agent"

	llm := newTestSpan("trace-genai", "llm", "chat", now.Add(30*time.Millisecond), 1200)
	llm.ParentSpanID = "agent"
	llm.Attributes["gen_ai.operation.name"] = "chat"
	llm.Attributes["gen_ai.request.model"] = "gpt-5.5"
	llm.Attributes["gen_ai.usage.input_tokens"] = "120"
	llm.Attributes["gen_ai.usage.output_tokens"] = 30
	llm.Attributes["ai.usage.input_tokens"] = 999
	llm.Attributes["llm.token_count.completion"] = 888
	llm.Attributes["gen_ai.security.prompt_injection.detected"] = true
	llm.Events = []SpanEvent{
		{
			Name:      "gen_ai.evaluation.result",
			Timestamp: now.Add(35 * time.Millisecond),
			Attributes: map[string]any{
				"gen_ai.evaluation.name":        "faithfulness",
				"gen_ai.evaluation.score.label": "fail",
				"assistant.evaluation.outcome":  "failed",
			},
		},
	}

	tool := newTestSpan("trace-genai", "tool", "execute_tool", now.Add(40*time.Millisecond), 200)
	tool.ParentSpanID = "agent"
	tool.Attributes["gen_ai.operation.name"] = "execute_tool"
	tool.Attributes["gen_ai.tool.name"] = "lookup_context"
	tool.Attributes["gen_ai.privacy.pii.detected"] = true
	tool.Events = []SpanEvent{
		{
			Name:      "gen_ai.evaluation.result",
			Timestamp: now.Add(45 * time.Millisecond),
			Attributes: map[string]any{
				"gen_ai.evaluation.name":   "toxicity",
				"gen_ai.evaluation.passed": true,
			},
		},
	}

	summarizer := newTestSpan("trace-genai", "summarizer", "invoke_agent", now.Add(60*time.Millisecond), 700)
	summarizer.ParentSpanID = "workflow"
	summarizer.Links = []SpanLink{{TraceID: "trace-genai", SpanID: "tool"}}
	summarizer.Attributes["gen_ai.operation.name"] = "invoke_agent"
	summarizer.Attributes["gen_ai.agent.name"] = "Summarizer Agent"

	s.AddSpansForConnection("conn-1", []Span{workflow, httpSpan, agent, llm, tool, summarizer})

	result := s.Trace("trace-genai", 0)
	if result == nil {
		t.Fatal("expected trace to be found")
	}
	if result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}

	genAI := result.GenAI
	if !genAI.IsGenAI {
		t.Fatal("expected GenAI projection to be marked GenAI")
	}
	if genAI.Tokens != (GenAITokenUsage{Input: 120, Output: 30, Total: 150}) {
		t.Fatalf("unexpected token rollup: %#v", genAI.Tokens)
	}
	if genAI.LLMCalls != 1 || genAI.ToolCalls != 1 {
		t.Fatalf("expected 1 llm and 1 tool call, got llm=%d tool=%d", genAI.LLMCalls, genAI.ToolCalls)
	}
	if got := strings.Join(genAI.ModelNames, ","); got != "gpt-5.5" {
		t.Fatalf("unexpected model names: %s", got)
	}

	nodeNames := make([]string, 0, len(genAI.FlowNodes))
	nodesByID := make(map[string]GenAIFlowNode)
	for _, node := range genAI.FlowNodes {
		nodeNames = append(nodeNames, node.Name)
		nodesByID[node.SpanID] = node
	}
	if strings.Join(nodeNames, "|") != "Budget Guru|Triage Agent|chat gpt-5.5|lookup_context|Summarizer Agent" {
		t.Fatalf("unexpected flow nodes: %v", nodeNames)
	}

	workflowNode := nodesByID["workflow"]
	if strings.Join(workflowNode.DescendantSpanIDs, ",") != "http,agent,llm,tool,summarizer" {
		t.Fatalf("unexpected workflow descendants: %v", workflowNode.DescendantSpanIDs)
	}
	if workflowNode.DescendantLLMCalls != 1 || workflowNode.DescendantToolCalls != 1 {
		t.Fatalf("expected workflow to roll up child LLM/tool spans, got llm=%d tool=%d", workflowNode.DescendantLLMCalls, workflowNode.DescendantToolCalls)
	}
	if strings.Join(workflowNode.DescendantLLMSpanIDs, ",") != "llm" {
		t.Fatalf("unexpected workflow llm span ids: %v", workflowNode.DescendantLLMSpanIDs)
	}
	if strings.Join(workflowNode.DescendantToolSpanIDs, ",") != "tool" {
		t.Fatalf("unexpected workflow tool span ids: %v", workflowNode.DescendantToolSpanIDs)
	}
	if strings.Join(workflowNode.DescendantSecurityRiskSpanIDs, ",") != "llm" {
		t.Fatalf("unexpected workflow security risk span ids: %v", workflowNode.DescendantSecurityRiskSpanIDs)
	}
	if strings.Join(workflowNode.DescendantPrivacyRiskSpanIDs, ",") != "tool" {
		t.Fatalf("unexpected workflow privacy risk span ids: %v", workflowNode.DescendantPrivacyRiskSpanIDs)
	}
	if workflowNode.DescendantEvaluationCount != 2 || workflowNode.DescendantEvaluationFailedCount != 1 {
		t.Fatalf("unexpected workflow evaluation rollup: count=%d failed=%d", workflowNode.DescendantEvaluationCount, workflowNode.DescendantEvaluationFailedCount)
	}
	if strings.Join(workflowNode.DescendantEvaluationFailedSpanIDs, ",") != "llm" {
		t.Fatalf("unexpected workflow failed evaluation span ids: %v", workflowNode.DescendantEvaluationFailedSpanIDs)
	}

	agentNode := nodesByID["agent"]
	if agentNode.ParentFlowSpanID != "workflow" {
		t.Fatalf("expected agent to attach to workflow through non-GenAI http span, got %q", agentNode.ParentFlowSpanID)
	}
	if strings.Join(agentNode.DescendantSpanIDs, ",") != "llm,tool" {
		t.Fatalf("unexpected agent descendants: %v", agentNode.DescendantSpanIDs)
	}
	if agentNode.DescendantLLMCalls != 1 || agentNode.DescendantToolCalls != 1 {
		t.Fatalf("unexpected descendant call rollups: llm=%d tool=%d", agentNode.DescendantLLMCalls, agentNode.DescendantToolCalls)
	}
	if strings.Join(agentNode.DescendantLLMSpanIDs, ",") != "llm" {
		t.Fatalf("unexpected llm span ids: %v", agentNode.DescendantLLMSpanIDs)
	}
	if strings.Join(agentNode.DescendantToolSpanIDs, ",") != "tool" {
		t.Fatalf("unexpected tool span ids: %v", agentNode.DescendantToolSpanIDs)
	}
	if strings.Join(agentNode.DescendantSecurityRiskSpanIDs, ",") != "llm" {
		t.Fatalf("unexpected security risk span ids: %v", agentNode.DescendantSecurityRiskSpanIDs)
	}
	if strings.Join(agentNode.DescendantPrivacyRiskSpanIDs, ",") != "tool" {
		t.Fatalf("unexpected privacy risk span ids: %v", agentNode.DescendantPrivacyRiskSpanIDs)
	}
	if agentNode.DescendantEvaluationCount != 2 || agentNode.DescendantEvaluationFailedCount != 1 {
		t.Fatalf("unexpected agent evaluation rollup: count=%d failed=%d", agentNode.DescendantEvaluationCount, agentNode.DescendantEvaluationFailedCount)
	}
	if strings.Join(agentNode.DescendantEvaluationFailedSpanIDs, ",") != "llm" {
		t.Fatalf("unexpected agent failed evaluation span ids: %v", agentNode.DescendantEvaluationFailedSpanIDs)
	}

	llmNode := nodesByID["llm"]
	if llmNode.ParentFlowSpanID != "agent" {
		t.Fatalf("expected llm to attach to agent, got %q", llmNode.ParentFlowSpanID)
	}
	if llmNode.TokenUsage != (GenAITokenUsage{Input: 120, Output: 30, Total: 150}) {
		t.Fatalf("unexpected llm token usage: %#v", llmNode.TokenUsage)
	}
	if strings.Join(llmNode.DescendantSecurityRiskSpanIDs, ",") != "llm" {
		t.Fatalf("unexpected llm security risk span ids: %v", llmNode.DescendantSecurityRiskSpanIDs)
	}
	if llmNode.DescendantEvaluationCount != 1 || llmNode.DescendantEvaluationFailedCount != 1 {
		t.Fatalf("unexpected llm evaluation rollup: count=%d failed=%d", llmNode.DescendantEvaluationCount, llmNode.DescendantEvaluationFailedCount)
	}
	if strings.Join(llmNode.DescendantEvaluationFailedSpanIDs, ",") != "llm" {
		t.Fatalf("unexpected llm failed evaluation span ids: %v", llmNode.DescendantEvaluationFailedSpanIDs)
	}

	toolNode := nodesByID["tool"]
	if toolNode.ParentFlowSpanID != "agent" {
		t.Fatalf("expected tool to attach to agent, got %q", toolNode.ParentFlowSpanID)
	}
	if strings.Join(toolNode.DescendantPrivacyRiskSpanIDs, ",") != "tool" {
		t.Fatalf("unexpected tool privacy risk span ids: %v", toolNode.DescendantPrivacyRiskSpanIDs)
	}
	if toolNode.DescendantEvaluationCount != 1 || toolNode.DescendantEvaluationFailedCount != 0 || len(toolNode.DescendantEvaluationFailedSpanIDs) != 0 {
		t.Fatalf("unexpected tool evaluation rollup: count=%d failed=%d ids=%v", toolNode.DescendantEvaluationCount, toolNode.DescendantEvaluationFailedCount, toolNode.DescendantEvaluationFailedSpanIDs)
	}

	edges := make([]string, 0, len(genAI.FlowEdges))
	for _, edge := range genAI.FlowEdges {
		edges = append(edges, edge.Source+"->"+edge.Target)
	}
	if strings.Join(edges, "|") != "workflow->agent|agent->llm|agent->tool|tool->summarizer" {
		t.Fatalf("unexpected flow edges: %v", edges)
	}
}

func TestTrace_IncludesRetrievalFlowNode(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-retrieval", "workflow", "invoke_workflow", now, 3000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	agent := newTestSpan("trace-genai-retrieval", "agent", "invoke_agent", now.Add(10*time.Millisecond), 2500)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "Research Agent"

	retrieval := newTestSpan("trace-genai-retrieval", "retrieval", "retrieval vector_store", now.Add(20*time.Millisecond), 300)
	retrieval.ParentSpanID = "agent"
	retrieval.Attributes["gen_ai.operation.name"] = "retrieval"
	retrieval.Attributes["gen_ai.retrieval.source"] = "vector_store"

	s.AddSpansForConnection("conn-1", []Span{workflow, agent, retrieval})

	result := s.Trace("trace-genai-retrieval", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}

	var retrievalNode GenAIFlowNode
	for _, node := range result.GenAI.FlowNodes {
		if node.SpanID == "retrieval" {
			retrievalNode = node
			break
		}
	}
	if retrievalNode.SpanID == "" {
		t.Fatalf("expected retrieval flow node, got %#v", result.GenAI.FlowNodes)
	}
	if retrievalNode.Kind != GenAISpanRetrieval {
		t.Fatalf("expected retrieval kind, got %q", retrievalNode.Kind)
	}
	if retrievalNode.Name != "retrieval vector_store" {
		t.Fatalf("unexpected retrieval node name: %q", retrievalNode.Name)
	}

	edges := make([]string, 0, len(result.GenAI.FlowEdges))
	for _, edge := range result.GenAI.FlowEdges {
		edges = append(edges, edge.Source+"->"+edge.Target)
	}
	if strings.Join(edges, "|") != "workflow->agent|agent->retrieval" {
		t.Fatalf("unexpected retrieval flow edges: %v", edges)
	}
}

func TestTrace_GenAILangGraphStepsRollUpAndChatStaysLLM(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-langgraph", "workflow", "invoke_workflow_assistant_v3_turn", now, 1000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "assistant_v3_turn"
	workflow.Attributes["gen_ai.request.model"] = "gpt-5.5"

	agent := newTestSpan("trace-genai-langgraph", "agent", "invoke_agent LangGraph", now.Add(10*time.Millisecond), 900)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "LangGraph"

	middleware := newTestSpan("trace-genai-langgraph", "middleware", "step SkillsMiddleware.before_agent", now.Add(20*time.Millisecond), 20)
	middleware.ParentSpanID = "agent"
	middleware.Attributes["gen_ai.agent.name"] = "LangGraph"
	middleware.Attributes["gen_ai.step.name"] = "SkillsMiddleware.before_agent"
	middleware.Attributes["gen_ai.step.type"] = "chain"

	modelStep := newTestSpan("trace-genai-langgraph", "model-step", "step model", now.Add(40*time.Millisecond), 600)
	modelStep.ParentSpanID = "agent"
	modelStep.Attributes["gen_ai.agent.name"] = "LangGraph"
	modelStep.Attributes["gen_ai.step.name"] = "model"
	modelStep.Attributes["gen_ai.step.type"] = "chain"
	modelStep.Attributes["gen_ai.step.status"] = "failed"
	modelStep.Attributes["gen_ai.request.model"] = "gpt-5.5"
	modelStep.Attributes["gen_ai.usage.input_tokens"] = 100
	modelStep.Attributes["gen_ai.usage.output_tokens"] = 5

	llm := newTestSpan("trace-genai-langgraph", "llm", "chat unknown_model", now.Add(50*time.Millisecond), 500)
	llm.ParentSpanID = "model-step"
	llm.Status = SpanStatus{Code: "ERROR", Message: "authentication failed"}
	llm.Attributes["gen_ai.agent.name"] = "LangGraph"
	llm.Attributes["gen_ai.operation.name"] = "chat"
	llm.Attributes["gen_ai.request.model"] = "unknown_model"
	llm.Attributes["gen_ai.response.model"] = "gpt-5.5"
	llm.Attributes["gen_ai.provider.name"] = "azure"
	llm.Attributes["error.type"] = "AuthenticationError"

	s.AddSpansForConnection("conn-1", []Span{workflow, agent, middleware, modelStep, llm})

	result := s.Trace("trace-genai-langgraph", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}
	if result.GenAI.LLMCalls != 1 {
		t.Fatalf("expected chat span to count as an LLM call, got %d", result.GenAI.LLMCalls)
	}

	nodeNames := make([]string, 0, len(result.GenAI.FlowNodes))
	nodesByID := make(map[string]GenAIFlowNode)
	for _, node := range result.GenAI.FlowNodes {
		nodeNames = append(nodeNames, node.Name)
		nodesByID[node.SpanID] = node
	}
	if strings.Join(nodeNames, "|") != "assistant_v3_turn|LangGraph|chat gpt-5.5" {
		t.Fatalf("unexpected flow nodes: %v", nodeNames)
	}
	if _, ok := nodesByID["middleware"]; ok {
		t.Fatalf("expected middleware step to roll up instead of becoming a flow node: %#v", nodesByID["middleware"])
	}
	if _, ok := nodesByID["model-step"]; ok {
		t.Fatalf("expected model step wrapper to roll up instead of becoming a flow node: %#v", nodesByID["model-step"])
	}

	llmNode := nodesByID["llm"]
	if llmNode.Kind != GenAISpanLLM {
		t.Fatalf("expected chat span to be an LLM node, got %q", llmNode.Kind)
	}
	if strings.Join(llmNode.ModelNames, "|") != "gpt-5.5" {
		t.Fatalf("expected real response model without placeholder request model, got %v", llmNode.ModelNames)
	}
	if llmNode.ParentFlowSpanID != "agent" {
		t.Fatalf("expected chat span to attach to the LangGraph agent through skipped step spans, got %q", llmNode.ParentFlowSpanID)
	}

	edges := make([]string, 0, len(result.GenAI.FlowEdges))
	for _, edge := range result.GenAI.FlowEdges {
		edges = append(edges, edge.Source+"->"+edge.Target)
	}
	if strings.Join(edges, "|") != "workflow->agent|agent->llm" {
		t.Fatalf("unexpected flow edges: %v", edges)
	}
}

func TestTrace_GenAIModelNamesPreferResponseThenRequest(t *testing.T) {
	s := New()
	now := time.Now()

	llm := newTestSpan("trace-genai-model-preference", "llm", "chat", now, 100)
	llm.Attributes["gen_ai.operation.name"] = "chat"
	llm.Attributes["gen_ai.provider.name"] = "azure"
	llm.Attributes["gen_ai.request.model"] = "assistant-prod-deployment"
	llm.Attributes["gen_ai.response.model"] = "gpt-5.5"

	s.AddSpansForConnection("conn-1", []Span{llm})

	result := s.Trace("trace-genai-model-preference", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}
	if strings.Join(result.GenAI.ModelNames, "|") != "gpt-5.5|assistant-prod-deployment" {
		t.Fatalf("expected trace model names to prefer response then request, got %v", result.GenAI.ModelNames)
	}
	if len(result.GenAI.FlowNodes) != 1 {
		t.Fatalf("expected one flow node, got %#v", result.GenAI.FlowNodes)
	}
	node := result.GenAI.FlowNodes[0]
	if node.Name != "chat gpt-5.5" {
		t.Fatalf("expected node title to use response model, got %q", node.Name)
	}
	if strings.Join(node.ModelNames, "|") != "gpt-5.5|assistant-prod-deployment" {
		t.Fatalf("expected node model names to keep response then request, got %v", node.ModelNames)
	}
}

func TestTrace_GenAIEvaluationOnlySpanRollsUpWithoutFlowNode(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-eval", "workflow", "invoke_workflow", now, 3000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	agent := newTestSpan("trace-genai-eval", "agent", "invoke_agent", now.Add(10*time.Millisecond), 2500)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "Research Agent"

	evaluation := newTestSpan("trace-genai-eval", "eval", "evaluate groundedness", now.Add(20*time.Millisecond), 300)
	evaluation.ParentSpanID = "agent"
	evaluation.Attributes["gen_ai.evaluation.name"] = "groundedness"
	evaluation.Attributes["gen_ai.request.model"] = "gpt-5.5"
	evaluation.Attributes["gen_ai.workflow.name"] = "assistant_v3_turn"
	evaluation.Attributes["assistant.evaluation.outcome"] = "failed"
	evaluation.Events = []SpanEvent{
		{
			Name:      "gen_ai.evaluation.result",
			Timestamp: now.Add(25 * time.Millisecond),
			Attributes: map[string]any{
				"gen_ai.evaluation.name":        "groundedness",
				"gen_ai.evaluation.score.label": "fail",
				"assistant.evaluation.outcome":  "failed",
			},
		},
	}

	s.AddSpansForConnection("conn-1", []Span{workflow, agent, evaluation})

	result := s.Trace("trace-genai-eval", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}
	if result.GenAI.LLMCalls != 0 {
		t.Fatalf("expected eval-only span not to count as LLM call, got %d", result.GenAI.LLMCalls)
	}

	nodeNames := make([]string, 0, len(result.GenAI.FlowNodes))
	nodesByID := make(map[string]GenAIFlowNode)
	for _, node := range result.GenAI.FlowNodes {
		nodeNames = append(nodeNames, node.Name)
		nodesByID[node.SpanID] = node
	}
	if strings.Join(nodeNames, "|") != "Budget Guru|Research Agent" {
		t.Fatalf("unexpected flow nodes: %v", nodeNames)
	}

	agentNode := nodesByID["agent"]
	if agentNode.DescendantEvaluationCount != 1 || agentNode.DescendantEvaluationFailedCount != 1 {
		t.Fatalf("unexpected agent evaluation rollup: count=%d failed=%d", agentNode.DescendantEvaluationCount, agentNode.DescendantEvaluationFailedCount)
	}
	if strings.Join(agentNode.DescendantEvaluationFailedSpanIDs, ",") != "eval" {
		t.Fatalf("unexpected failed evaluation span ids: %v", agentNode.DescendantEvaluationFailedSpanIDs)
	}
}

func TestTrace_GenAIProjectionUsesFullEventsWhenPayloadEventsAreTruncated(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-eval-events", "workflow", "invoke_workflow", now, 3000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	agent := newTestSpan("trace-genai-eval-events", "agent", "invoke_agent", now.Add(10*time.Millisecond), 2500)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "Research Agent"

	evaluation := newTestSpan("trace-genai-eval-events", "eval", "evaluate groundedness", now.Add(20*time.Millisecond), 300)
	evaluation.ParentSpanID = "agent"
	evaluation.Attributes["gen_ai.evaluation.name"] = "groundedness"
	for i := 0; i < 20; i++ {
		evaluation.Events = append(evaluation.Events, SpanEvent{
			Name:      "gen_ai.evaluation.result",
			Timestamp: now.Add(time.Duration(25+i) * time.Millisecond),
			Attributes: map[string]any{
				"gen_ai.evaluation.name":        "groundedness",
				"gen_ai.evaluation.score.label": "fail",
			},
		})
	}

	s.AddSpansForConnection("conn-1", []Span{workflow, agent, evaluation})

	result := s.Trace("trace-genai-eval-events", 1)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}
	var payloadEval Span
	for _, span := range result.Spans {
		if span.SpanID == "eval" {
			payloadEval = span
			break
		}
	}
	if payloadEval.SpanID == "" {
		t.Fatal("expected eval span in payload")
	}
	if got := len(payloadEval.Events); got != 1 {
		t.Fatalf("expected payload events to stay truncated, got %d", got)
	}

	var agentNode GenAIFlowNode
	for _, node := range result.GenAI.FlowNodes {
		if node.SpanID == "agent" {
			agentNode = node
			break
		}
	}
	if agentNode.SpanID == "" {
		t.Fatal("expected agent node")
	}
	if agentNode.DescendantEvaluationCount != 20 || agentNode.DescendantEvaluationFailedCount != 20 {
		t.Fatalf("expected GenAI rollup to use full event set, got count=%d failed=%d", agentNode.DescendantEvaluationCount, agentNode.DescendantEvaluationFailedCount)
	}
}

func TestTrace_GenAIProjectionCapsSpanListsButNotCounts(t *testing.T) {
	t.Setenv("MAX_FLOW_NODE_SPAN_LIST_SIZE", "1")

	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-cap", "workflow", "invoke_workflow", now, 3000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	agent := newTestSpan("trace-genai-cap", "agent", "invoke_agent", now.Add(10*time.Millisecond), 2500)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "Triage Agent"

	spans := []Span{workflow, agent}
	for i := 0; i < 3; i++ {
		llm := newTestSpan("trace-genai-cap", fmt.Sprintf("llm-%d", i), "chat", now.Add(time.Duration(20+i)*time.Millisecond), 100)
		llm.ParentSpanID = "agent"
		llm.Attributes["gen_ai.operation.name"] = "chat"
		llm.Attributes["gen_ai.request.model"] = "gpt-5.5"
		llm.Attributes["gen_ai.usage.input_tokens"] = 10
		llm.Attributes["gen_ai.usage.output_tokens"] = 1
		llm.Attributes["gen_ai.security.prompt_injection.detected"] = true
		spans = append(spans, llm)
	}

	s.AddSpansForConnection("conn-1", spans)

	result := s.Trace("trace-genai-cap", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}

	var agentNode GenAIFlowNode
	for _, node := range result.GenAI.FlowNodes {
		if node.SpanID == "agent" {
			agentNode = node
			break
		}
	}
	if agentNode.SpanID == "" {
		t.Fatal("expected agent node")
	}
	if got := len(agentNode.DescendantSpanIDs); got != 1 {
		t.Fatalf("expected capped descendant span ID list, got %d ids: %v", got, agentNode.DescendantSpanIDs)
	}
	if got := len(agentNode.DescendantLLMSpanIDs); got != 1 {
		t.Fatalf("expected capped LLM span ID list, got %d ids: %v", got, agentNode.DescendantLLMSpanIDs)
	}
	if got := len(agentNode.DescendantSecurityRiskSpanIDs); got != 1 {
		t.Fatalf("expected capped risk span ID list, got %d ids: %v", got, agentNode.DescendantSecurityRiskSpanIDs)
	}
	if agentNode.DescendantLLMCalls != 3 {
		t.Fatalf("expected uncapped LLM call count, got %d", agentNode.DescendantLLMCalls)
	}
	if agentNode.DescendantSecurityRiskCount != 3 || agentNode.DescendantRiskCount != 3 {
		t.Fatalf("expected uncapped risk counts, got security=%d total=%d", agentNode.DescendantSecurityRiskCount, agentNode.DescendantRiskCount)
	}
	if agentNode.DescendantTokenUsage != (GenAITokenUsage{Input: 30, Output: 3, Total: 33}) {
		t.Fatalf("expected uncapped token usage, got %#v", agentNode.DescendantTokenUsage)
	}
}

func TestTrace_GenAITokenUsagePreservesExplicitZeroValues(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-zero", "workflow", "invoke_workflow", now, 1000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	llm := newTestSpan("trace-genai-zero", "llm", "chat", now.Add(10*time.Millisecond), 500)
	llm.ParentSpanID = "workflow"
	llm.Attributes["gen_ai.operation.name"] = "chat"
	llm.Attributes["gen_ai.request.model"] = "gpt-5.5"
	llm.Attributes["gen_ai.usage.input_tokens"] = 12
	llm.Attributes["gen_ai.usage.output_tokens"] = 0
	llm.Attributes["gen_ai.usage.total_tokens"] = 0
	llm.Attributes["llm.token_count.completion"] = 888

	s.AddSpansForConnection("conn-1", []Span{workflow, llm})

	result := s.Trace("trace-genai-zero", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}
	if result.GenAI.Tokens != (GenAITokenUsage{Input: 12, Output: 0, Total: 0}) {
		t.Fatalf("unexpected token usage: %#v", result.GenAI.Tokens)
	}

	foundLLMNode := false
	for _, node := range result.GenAI.FlowNodes {
		if node.SpanID == "llm" && node.TokenUsage != (GenAITokenUsage{Input: 12, Output: 0, Total: 0}) {
			t.Fatalf("unexpected llm token usage: %#v", node.TokenUsage)
		}
		if node.SpanID == "llm" {
			foundLLMNode = true
		}
	}
	if !foundLLMNode {
		t.Fatal("expected llm flow node")
	}
}

func TestTrace_GroupsRepeatedLeafLLMNodes(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-loop", "workflow", "invoke_workflow", now, 3000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	agent := newTestSpan("trace-genai-loop", "agent", "invoke_agent", now.Add(10*time.Millisecond), 2500)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "LangGraph"

	spans := []Span{workflow, agent}
	for i := 0; i < genAIFlowGroupThreshold+1; i++ {
		spanID := fmt.Sprintf("llm-%d", i)
		llm := newTestSpan("trace-genai-loop", spanID, "chat", now.Add(time.Duration(20+i)*time.Millisecond), float64(100+i))
		llm.ParentSpanID = "agent"
		llm.Attributes["gen_ai.operation.name"] = "chat"
		llm.Attributes["gen_ai.request.model"] = "gpt-5.5"
		llm.Attributes["gen_ai.usage.input_tokens"] = 10
		llm.Attributes["gen_ai.usage.output_tokens"] = 1
		if i == 0 {
			llm.Attributes["gen_ai.security.prompt_injection.detected"] = true
		}
		spans = append(spans, llm)
	}

	s.AddSpansForConnection("conn-1", spans)

	result := s.Trace("trace-genai-loop", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}

	genAI := result.GenAI
	if genAI.LLMCalls != genAIFlowGroupThreshold+1 {
		t.Fatalf("unexpected llm calls: %d", genAI.LLMCalls)
	}
	if len(genAI.FlowNodes) != 3 {
		t.Fatalf("expected workflow, agent, grouped llm nodes; got %d nodes: %#v", len(genAI.FlowNodes), genAI.FlowNodes)
	}

	groupNode := GenAIFlowNode{}
	for _, node := range genAI.FlowNodes {
		if node.Kind == GenAISpanLLM {
			groupNode = node
			break
		}
	}
	if !groupNode.Grouped {
		t.Fatalf("expected llm node to be grouped: %#v", groupNode)
	}
	if groupNode.CallCount != genAIFlowGroupThreshold+1 {
		t.Fatalf("unexpected grouped call count: %d", groupNode.CallCount)
	}
	if groupNode.Name != "chat gpt-5.5 x9" {
		t.Fatalf("unexpected grouped node name: %q", groupNode.Name)
	}
	if strings.Join(groupNode.GroupedSpanIDs, ",") != "llm-0,llm-1,llm-2,llm-3,llm-4,llm-5,llm-6,llm-7,llm-8" {
		t.Fatalf("unexpected grouped span ids: %v", groupNode.GroupedSpanIDs)
	}
	if groupNode.TokenUsage != (GenAITokenUsage{Input: 90, Output: 9, Total: 99}) {
		t.Fatalf("unexpected grouped token usage: %#v", groupNode.TokenUsage)
	}
	if groupNode.DurationMs != 108 || groupNode.MaxDurationMs != 108 || groupNode.AvgDurationMs != 104 {
		t.Fatalf("unexpected grouped durations: duration=%v max=%v avg=%v", groupNode.DurationMs, groupNode.MaxDurationMs, groupNode.AvgDurationMs)
	}
	if strings.Join(groupNode.DescendantSecurityRiskSpanIDs, ",") != "llm-0" {
		t.Fatalf("unexpected grouped risk span ids: %v", groupNode.DescendantSecurityRiskSpanIDs)
	}

	edges := make([]string, 0, len(genAI.FlowEdges))
	for _, edge := range genAI.FlowEdges {
		edges = append(edges, edge.Source+"->"+edge.Target)
	}
	if len(edges) != 2 || edges[0] != "workflow->agent" || !strings.HasPrefix(edges[1], "agent->group:agent:llm:chat:chat_gpt-5.5") {
		t.Fatalf("unexpected grouped flow edges: %v", edges)
	}
}

func TestTrace_GroupsRepeatedLeafNodesUsesUniqueIDsForDifferentModels(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-model-groups", "workflow", "invoke_workflow", now, 3000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	agent := newTestSpan("trace-genai-model-groups", "agent", "invoke_agent", now.Add(10*time.Millisecond), 2500)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "LangGraph"

	spans := []Span{workflow, agent}
	models := []string{"gpt-5.5", "claude-4"}
	for modelIndex, model := range models {
		for i := 0; i < genAIFlowGroupThreshold+1; i++ {
			spanID := fmt.Sprintf("llm-%d-%d", modelIndex, i)
			llm := newTestSpan("trace-genai-model-groups", spanID, "chat", now.Add(time.Duration(20+modelIndex*20+i)*time.Millisecond), float64(100+i))
			llm.ParentSpanID = "agent"
			llm.Attributes["gen_ai.request.model"] = model
			spans = append(spans, llm)
		}
	}

	s.AddSpansForConnection("conn-1", spans)

	result := s.Trace("trace-genai-model-groups", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}

	groupIDs := make(map[string]struct{})
	groupCount := 0
	for _, node := range result.GenAI.FlowNodes {
		if node.Kind != GenAISpanLLM || !node.Grouped {
			continue
		}
		groupCount++
		if _, exists := groupIDs[node.SpanID]; exists {
			t.Fatalf("duplicate grouped node id %q in %#v", node.SpanID, result.GenAI.FlowNodes)
		}
		groupIDs[node.SpanID] = struct{}{}
	}
	if groupCount != len(models) {
		t.Fatalf("expected one grouped LLM node per model, got %d nodes: %#v", groupCount, result.GenAI.FlowNodes)
	}
}

func TestTrace_GroupsRepeatedLeafNodesPreservesSpanLinkEdges(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-group-links", "workflow", "invoke_workflow", now, 3000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	agent := newTestSpan("trace-genai-group-links", "agent", "invoke_agent", now.Add(10*time.Millisecond), 2500)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "LangGraph"

	tool := newTestSpan("trace-genai-group-links", "tool", "execute_tool", now.Add(15*time.Millisecond), 100)
	tool.ParentSpanID = "agent"
	tool.Attributes["gen_ai.operation.name"] = "execute_tool"
	tool.Attributes["gen_ai.tool.name"] = "lookup_context"

	spans := []Span{workflow, agent, tool}
	for i := 0; i < genAIFlowGroupThreshold+1; i++ {
		spanID := fmt.Sprintf("llm-%d", i)
		llm := newTestSpan("trace-genai-group-links", spanID, "chat", now.Add(time.Duration(20+i)*time.Millisecond), float64(100+i))
		llm.ParentSpanID = "agent"
		llm.Links = []SpanLink{{TraceID: "trace-genai-group-links", SpanID: "tool"}}
		llm.Attributes["gen_ai.operation.name"] = "chat"
		llm.Attributes["gen_ai.request.model"] = "gpt-5.5"
		llm.Attributes["gen_ai.usage.input_tokens"] = 10
		llm.Attributes["gen_ai.usage.output_tokens"] = 1
		spans = append(spans, llm)
	}

	s.AddSpansForConnection("conn-1", spans)

	result := s.Trace("trace-genai-group-links", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}

	edges := make([]string, 0, len(result.GenAI.FlowEdges))
	for _, edge := range result.GenAI.FlowEdges {
		edges = append(edges, edge.Source+"->"+edge.Target)
	}
	if len(edges) != 3 || edges[0] != "workflow->agent" || edges[1] != "agent->tool" || !strings.HasPrefix(edges[2], "tool->group:agent:llm:chat:chat_gpt-5.5") {
		t.Fatalf("unexpected grouped flow edges: %v", edges)
	}
}

func TestTrace_GroupsRepeatedLLMToolCycles(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-cycle", "workflow", "invoke_workflow", now, 8000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	agent := newTestSpan("trace-genai-cycle", "agent", "invoke_agent", now.Add(10*time.Millisecond), 7000)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "LangGraph"

	llm1 := newTestSpan("trace-genai-cycle", "llm-1", "chat", now.Add(20*time.Millisecond), 1000)
	llm1.ParentSpanID = "agent"
	llm1.Attributes["gen_ai.operation.name"] = "chat"
	llm1.Attributes["gen_ai.request.model"] = "gpt-5.5"
	llm1.Attributes["gen_ai.usage.input_tokens"] = 10
	llm1.Attributes["gen_ai.usage.output_tokens"] = 2

	tool1 := newTestSpan("trace-genai-cycle", "tool-1", "execute_tool", now.Add(30*time.Millisecond), 200)
	tool1.ParentSpanID = "agent"
	tool1.Links = []SpanLink{{TraceID: "trace-genai-cycle", SpanID: "llm-1"}}
	tool1.Attributes["gen_ai.operation.name"] = "execute_tool"
	tool1.Attributes["gen_ai.tool.name"] = "lookup_context"
	tool1.Attributes["gen_ai.privacy.pii.detected"] = true

	llm2 := newTestSpan("trace-genai-cycle", "llm-2", "chat", now.Add(40*time.Millisecond), 900)
	llm2.ParentSpanID = "agent"
	llm2.Links = []SpanLink{{TraceID: "trace-genai-cycle", SpanID: "tool-1"}}
	llm2.Attributes["gen_ai.operation.name"] = "chat"
	llm2.Attributes["gen_ai.request.model"] = "gpt-5.5"
	llm2.Attributes["gen_ai.usage.input_tokens"] = 12
	llm2.Attributes["gen_ai.usage.output_tokens"] = 3

	tool2 := newTestSpan("trace-genai-cycle", "tool-2", "execute_tool", now.Add(50*time.Millisecond), 300)
	tool2.ParentSpanID = "agent"
	tool2.Links = []SpanLink{{TraceID: "trace-genai-cycle", SpanID: "llm-2"}}
	tool2.Attributes["gen_ai.operation.name"] = "execute_tool"
	tool2.Attributes["gen_ai.tool.name"] = "lookup_context"

	summarizer := newTestSpan("trace-genai-cycle", "summarizer", "invoke_agent", now.Add(60*time.Millisecond), 600)
	summarizer.ParentSpanID = "workflow"
	summarizer.Links = []SpanLink{{TraceID: "trace-genai-cycle", SpanID: "tool-2"}}
	summarizer.Attributes["gen_ai.operation.name"] = "invoke_agent"
	summarizer.Attributes["gen_ai.agent.name"] = "Summarizer Agent"

	s.AddSpansForConnection("conn-1", []Span{workflow, agent, llm1, tool1, llm2, tool2, summarizer})

	result := s.Trace("trace-genai-cycle", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}

	genAI := result.GenAI
	if genAI.LLMCalls != 2 || genAI.ToolCalls != 2 {
		t.Fatalf("unexpected call rollup: llm=%d tool=%d", genAI.LLMCalls, genAI.ToolCalls)
	}

	nodesByKind := make(map[GenAISpanKind]GenAIFlowNode)
	for _, node := range genAI.FlowNodes {
		nodesByKind[node.Kind] = node
	}
	loopNode := nodesByKind[GenAISpanLoop]
	if !loopNode.Grouped {
		t.Fatalf("expected loop node to be grouped: %#v", loopNode)
	}
	if loopNode.CallCount != 2 {
		t.Fatalf("expected two loop iterations, got %d", loopNode.CallCount)
	}
	if loopNode.Name != "chat gpt-5.5 + lookup_context loop x2" {
		t.Fatalf("unexpected loop node name: %q", loopNode.Name)
	}
	if strings.Join(loopNode.GroupedSpanIDs, ",") != "llm-1,tool-1,llm-2,tool-2" {
		t.Fatalf("unexpected loop span ids: %v", loopNode.GroupedSpanIDs)
	}
	if loopNode.DescendantLLMCalls != 2 || loopNode.DescendantToolCalls != 2 {
		t.Fatalf("unexpected loop descendant calls: llm=%d tool=%d", loopNode.DescendantLLMCalls, loopNode.DescendantToolCalls)
	}
	if strings.Join(loopNode.DescendantLLMSpanIDs, ",") != "llm-1,llm-2" {
		t.Fatalf("unexpected loop llm span ids: %v", loopNode.DescendantLLMSpanIDs)
	}
	if strings.Join(loopNode.DescendantToolSpanIDs, ",") != "tool-1,tool-2" {
		t.Fatalf("unexpected loop tool span ids: %v", loopNode.DescendantToolSpanIDs)
	}
	if loopNode.TokenUsage != (GenAITokenUsage{Input: 22, Output: 5, Total: 27}) {
		t.Fatalf("unexpected loop token rollup: %#v", loopNode.TokenUsage)
	}
	if strings.Join(loopNode.DescendantPrivacyRiskSpanIDs, ",") != "tool-1" {
		t.Fatalf("unexpected loop privacy risk span ids: %v", loopNode.DescendantPrivacyRiskSpanIDs)
	}

	edges := make([]string, 0, len(genAI.FlowEdges))
	for _, edge := range genAI.FlowEdges {
		edges = append(edges, edge.Source+"->"+edge.Target)
	}
	if len(edges) != 3 || edges[0] != "workflow->agent" || !strings.HasPrefix(edges[1], "agent->group:agent:loop:") || !strings.HasPrefix(edges[2], "group:agent:loop:") || !strings.HasSuffix(edges[2], "->summarizer") {
		t.Fatalf("unexpected loop flow edges: %v", edges)
	}
}

func TestTrace_GroupedLoopPreservesExternalLinksFromCollapsedMembers(t *testing.T) {
	s := New()
	now := time.Now()

	workflow := newTestSpan("trace-genai-loop-link", "workflow", "invoke_workflow", now, 8000)
	workflow.Attributes["gen_ai.operation.name"] = "invoke_workflow"
	workflow.Attributes["gen_ai.workflow.name"] = "Budget Guru"

	agent := newTestSpan("trace-genai-loop-link", "agent", "invoke_agent", now.Add(10*time.Millisecond), 7000)
	agent.ParentSpanID = "workflow"
	agent.Attributes["gen_ai.operation.name"] = "invoke_agent"
	agent.Attributes["gen_ai.agent.name"] = "LangGraph"

	primer := newTestSpan("trace-genai-loop-link", "primer", "execute_tool", now.Add(15*time.Millisecond), 100)
	primer.ParentSpanID = "agent"
	primer.Attributes["gen_ai.operation.name"] = "execute_tool"
	primer.Attributes["gen_ai.tool.name"] = "load_context"

	llm1 := newTestSpan("trace-genai-loop-link", "llm-1", "chat", now.Add(20*time.Millisecond), 1000)
	llm1.ParentSpanID = "agent"
	llm1.Attributes["gen_ai.operation.name"] = "chat"
	llm1.Attributes["gen_ai.request.model"] = "gpt-5.5"

	tool1 := newTestSpan("trace-genai-loop-link", "tool-1", "execute_tool", now.Add(30*time.Millisecond), 200)
	tool1.ParentSpanID = "agent"
	tool1.Links = []SpanLink{{TraceID: "trace-genai-loop-link", SpanID: "primer"}}
	tool1.Attributes["gen_ai.operation.name"] = "execute_tool"
	tool1.Attributes["gen_ai.tool.name"] = "lookup_context"

	llm2 := newTestSpan("trace-genai-loop-link", "llm-2", "chat", now.Add(40*time.Millisecond), 900)
	llm2.ParentSpanID = "agent"
	llm2.Attributes["gen_ai.operation.name"] = "chat"
	llm2.Attributes["gen_ai.request.model"] = "gpt-5.5"

	tool2 := newTestSpan("trace-genai-loop-link", "tool-2", "execute_tool", now.Add(50*time.Millisecond), 300)
	tool2.ParentSpanID = "agent"
	tool2.Links = []SpanLink{{TraceID: "trace-genai-loop-link", SpanID: "primer"}}
	tool2.Attributes["gen_ai.operation.name"] = "execute_tool"
	tool2.Attributes["gen_ai.tool.name"] = "lookup_context"

	s.AddSpansForConnection("conn-1", []Span{workflow, agent, primer, llm1, tool1, llm2, tool2})

	result := s.Trace("trace-genai-loop-link", 0)
	if result == nil || result.GenAI == nil {
		t.Fatal("expected GenAI projection")
	}

	edges := make([]string, 0, len(result.GenAI.FlowEdges))
	for _, edge := range result.GenAI.FlowEdges {
		edges = append(edges, edge.Source+"->"+edge.Target)
	}
	if len(edges) != 3 || edges[0] != "workflow->agent" || edges[1] != "agent->primer" || !strings.HasPrefix(edges[2], "primer->group:agent:loop:") {
		t.Fatalf("unexpected loop flow edges: %v", edges)
	}
}

// ============================================================================
// Compute Status Tests
// ============================================================================

func TestComputeTraceStatus_AllOK(t *testing.T) {
	span1 := newTestSpan("trace-1", "span-1", "test", time.Now(), 10)
	span1.Status.Code = "OK"
	span2 := newTestSpan("trace-1", "span-2", "test", time.Now(), 10)
	span2.Status.Code = "OK"

	status := computeTraceStatus([]Span{span1, span2})
	if status != "ok" {
		t.Errorf("expected 'ok', got '%s'", status)
	}
}

func TestComputeTraceStatus_AllError(t *testing.T) {
	span1 := newTestSpan("trace-1", "span-1", "test", time.Now(), 10)
	span1.Status.Code = "ERROR"
	span2 := newTestSpan("trace-1", "span-2", "test", time.Now(), 10)
	span2.Status.Code = "ERROR"

	status := computeTraceStatus([]Span{span1, span2})
	if status != "error" {
		t.Errorf("expected 'error', got '%s'", status)
	}
}

func TestComputeTraceStatus_Mixed(t *testing.T) {
	span1 := newTestSpan("trace-1", "span-1", "test", time.Now(), 10)
	span1.Status.Code = "OK"
	span2 := newTestSpan("trace-1", "span-2", "test", time.Now(), 10)
	span2.Status.Code = "ERROR"

	status := computeTraceStatus([]Span{span1, span2})
	if status != "mixed" {
		t.Errorf("expected 'mixed', got '%s'", status)
	}
}

func TestComputeTraceStatus_Unset(t *testing.T) {
	span := newTestSpan("trace-1", "span-1", "test", time.Now(), 10)
	span.Status.Code = ""

	status := computeTraceStatus([]Span{span})
	if status != "unset" {
		t.Errorf("expected 'unset', got '%s'", status)
	}
}

// ============================================================================
// Compute Duration Tests
// ============================================================================

func TestComputeTraceDuration_SingleSpan(t *testing.T) {
	now := time.Now()
	span := newTestSpan("trace-1", "span-1", "test", now, 100)

	duration := computeTraceDuration([]Span{span})
	if duration != 100.0 {
		t.Errorf("expected 100ms, got %f", duration)
	}
}

func TestComputeTraceDuration_MinStartToMaxEnd(t *testing.T) {
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "test", now, 50)
	span2 := newTestSpan("trace-1", "span-2", "test", now.Add(200*time.Millisecond), 150)

	duration := computeTraceDuration([]Span{span1, span2})
	// span1 starts at now, span2 ends at now+350ms, so duration should be ~350ms
	expected := float64(span2.EndTime.Sub(span1.StartTime).Milliseconds())
	if duration != expected {
		t.Errorf("expected %fms, got %f", expected, duration)
	}
}

func TestComputeTraceDuration_Empty(t *testing.T) {
	duration := computeTraceDuration([]Span{})
	if duration != 0 {
		t.Errorf("expected 0ms for empty slice, got %f", duration)
	}
}

func TestComputeTraceDuration_PreservesSubMillisecondPrecision(t *testing.T) {
	now := time.Now()
	span := newTestSpan("trace-1", "span-1", "test", now, 0)
	span.EndTime = span.StartTime.Add(700 * time.Microsecond)

	duration := computeTraceDuration([]Span{span})
	if duration != 0.7 {
		t.Errorf("expected 0.7ms, got %f", duration)
	}
}

// ============================================================================
// QueryMetrics Tests
// ============================================================================

func TestQueryMetrics_GroupsByNameServiceScope(t *testing.T) {
	s := New()
	now := time.Now()

	m1 := newTestMetric("cpu", 42.5, now)
	m2 := newTestMetric("cpu", 45.0, now.Add(100*time.Millisecond))

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m1})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m2})

	results := s.QueryMetrics(10)
	if len(results) != 1 {
		t.Errorf("expected 1 metric group, got %d", len(results))
	}
	if results[0].DataPointCount != 2 {
		t.Errorf("expected 2 data points, got %d", results[0].DataPointCount)
	}
}

func TestQueryMetrics_BoundedWindow(t *testing.T) {
	s := New()
	now := time.Now()

	for i := 0; i < 15; i++ {
		m := newTestMetric("cpu", float64(i), now.Add(time.Duration(i)*100*time.Millisecond))
		s.AddMetricsForConnection("conn-1", []MetricDataPoint{m})
	}

	results := s.QueryMetrics(10)
	if len(results) != 1 {
		t.Fatalf("expected 1 metric group, got %d", len(results))
	}
	// Window should be bounded to 8 points per series
	if len(results[0].DataPoints) > 8 {
		t.Errorf("expected max 8 data points per series, got %d", len(results[0].DataPoints))
	}
}

func TestQueryMetrics_SortsNewestFirst(t *testing.T) {
	s := New()
	now := time.Now()

	m1 := newTestMetric("cpu", 42.5, now)
	m2 := newTestMetric("memory", 80.0, now.Add(100*time.Millisecond))

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m1})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m2})

	results := s.QueryMetrics(10)
	if len(results) != 2 {
		t.Fatalf("expected 2 metric groups, got %d", len(results))
	}
	if results[0].Name != "memory" {
		t.Errorf("expected memory first (newest), got %s", results[0].Name)
	}
}

func TestQueryMetrics_RespectsLimit(t *testing.T) {
	s := New()
	now := time.Now()

	for i := 0; i < 10; i++ {
		m := newTestMetric(fmt.Sprintf("metric-%d", i), float64(i), now.Add(time.Duration(i)*100*time.Millisecond))
		s.AddMetricsForConnection("conn-1", []MetricDataPoint{m})
	}

	results := s.QueryMetrics(5)
	if len(results) != 5 {
		t.Errorf("expected 5 metric groups, got %d", len(results))
	}
}

// ============================================================================
// QueryLogs Tests
// ============================================================================

func TestQueryLogs_ReturnsNewestFirst(t *testing.T) {
	s := New()
	now := time.Now()

	log1 := newTestLog("message 1", now)
	log2 := newTestLog("message 2", now.Add(100*time.Millisecond))

	s.AddLogsForConnection("conn-1", []LogRecord{log1})
	s.AddLogsForConnection("conn-1", []LogRecord{log2})

	results := s.QueryLogs(10)
	if len(results) != 2 {
		t.Errorf("expected 2 logs, got %d", len(results))
	}
	if results[0].Body != "message 2" {
		t.Errorf("expected newest log first, got %s", results[0].Body)
	}
}

func TestQueryLogs_RespectsLimit(t *testing.T) {
	s := New()
	now := time.Now()

	for i := 0; i < 10; i++ {
		log := newTestLog(fmt.Sprintf("message %d", i), now.Add(time.Duration(i)*100*time.Millisecond))
		s.AddLogsForConnection("conn-1", []LogRecord{log})
	}

	results := s.QueryLogs(5)
	if len(results) != 5 {
		t.Errorf("expected 5 logs, got %d", len(results))
	}
}

func TestQueryLogs_DefaultLimitIs100(t *testing.T) {
	s := New()
	now := time.Now()

	log := newTestLog("message", now)
	s.AddLogsForConnection("conn-1", []LogRecord{log})

	results := s.QueryLogs(0)
	if len(results) != 1 {
		t.Errorf("expected 1 log with default limit, got %d", len(results))
	}
}

// ============================================================================
// Stats Tests
// ============================================================================

func TestStats_CorrectCounts(t *testing.T) {
	s := New()
	now := time.Now()

	span := newTestSpan("trace-1", "span-1", "root", now, 10)
	metric := newTestMetric("cpu", 42.5, now)
	log := newTestLog("message", now)

	s.AddSpansForConnection("conn-1", []Span{span})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{metric})
	s.AddLogsForConnection("conn-1", []LogRecord{log})

	stats := s.Stats()
	if stats.SpanCount != 1 {
		t.Errorf("expected 1 span, got %d", stats.SpanCount)
	}
	if stats.DataPointCount != 1 {
		t.Errorf("expected 1 metric, got %d", stats.DataPointCount)
	}
	if stats.LogCount != 1 {
		t.Errorf("expected 1 log, got %d", stats.LogCount)
	}
	if stats.TraceCount != 1 {
		t.Errorf("expected 1 trace, got %d", stats.TraceCount)
	}
	if stats.MetricNameCount != 1 {
		t.Errorf("expected 1 metric name, got %d", stats.MetricNameCount)
	}
}

func TestStats_MetricNameCount(t *testing.T) {
	s := New()
	now := time.Now()

	m1 := newTestMetric("cpu", 42.5, now)
	m2 := newTestMetric("cpu", 45.0, now.Add(100*time.Millisecond))
	m3 := newTestMetric("memory", 80.0, now.Add(200*time.Millisecond))

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m1, m2, m3})

	stats := s.Stats()
	if stats.DataPointCount != 3 {
		t.Errorf("expected 3 data points, got %d", stats.DataPointCount)
	}
	if stats.MetricNameCount != 2 {
		t.Errorf("expected 2 unique metric names, got %d", stats.MetricNameCount)
	}
}

func TestStats_ServiceNames(t *testing.T) {
	s := New()
	now := time.Now()

	span := newTestSpan("trace-1", "span-1", "root", now, 10)
	span.Resource.ServiceName = "service-a"

	metric := newTestMetric("cpu", 42.5, now)
	metric.Resource.ServiceName = "service-b"

	s.AddSpansForConnection("conn-1", []Span{span})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{metric})

	stats := s.Stats()
	if len(stats.ServiceNames) != 2 {
		t.Errorf("expected 2 service names, got %d", len(stats.ServiceNames))
	}
	if stats.ServiceNames[0] != "service-a" || stats.ServiceNames[1] != "service-b" {
		t.Errorf("expected [service-a, service-b], got %v", stats.ServiceNames)
	}
}

// ============================================================================
// QueryTracesFiltered Tests
// ============================================================================

func TestServiceStatsAll_TraceCountIncludesChildServices(t *testing.T) {
	s := New()
	now := time.Now()

	// Trace-1: root span owned by "frontend", child span owned by "payments"
	root := newTestSpan("trace-1", "span-r", "GET /checkout", now, 50)
	root.ParentSpanID = ""
	root.Resource.ServiceName = "frontend"

	child := newTestSpan("trace-1", "span-c", "charge", now.Add(5*time.Millisecond), 30)
	child.ParentSpanID = "span-r"
	child.Resource.ServiceName = "payments"

	s.AddSpansForConnection("conn-1", []Span{root, child})

	stats := s.ServiceStatsAll()
	byName := make(map[string]ServiceStats)
	for _, ss := range stats {
		byName[ss.Name] = ss
	}

	// Both services must be present and each must show traceCount=1
	fe, ok := byName["frontend"]
	if !ok {
		t.Fatal("expected frontend in service stats")
	}
	if fe.TraceCount != 1 {
		t.Errorf("frontend: want traceCount=1, got %d", fe.TraceCount)
	}
	if fe.SpanCount != 1 {
		t.Errorf("frontend: want spanCount=1, got %d", fe.SpanCount)
	}

	pay, ok := byName["payments"]
	if !ok {
		t.Fatal("expected payments in service stats")
	}
	if pay.TraceCount != 1 {
		t.Errorf("payments: want traceCount=1, got %d (child service must count the trace)", pay.TraceCount)
	}
	if pay.SpanCount != 1 {
		t.Errorf("payments: want spanCount=1, got %d", pay.SpanCount)
	}
}

func TestServiceStatsAll_SpanCountNotCappedByPreview(t *testing.T) {
	s := New()
	now := time.Now()

	// 12 spans in a single trace from "backend" — more than the 8-span preview cap.
	spans := make([]Span, 12)
	for i := range spans {
		sp := newTestSpan("trace-big", fmt.Sprintf("span-%d", i), "work", now.Add(time.Duration(i)*time.Millisecond), 5)
		if i > 0 {
			sp.ParentSpanID = "span-0"
		}
		sp.Resource.ServiceName = "backend"
		spans[i] = sp
	}
	s.AddSpansForConnection("conn-1", spans)

	stats := s.ServiceStatsAll()
	if len(stats) != 1 {
		t.Fatalf("expected 1 service, got %d", len(stats))
	}
	if stats[0].SpanCount != 12 {
		t.Errorf("want spanCount=12 (all spans, not preview cap), got %d", stats[0].SpanCount)
	}
}

func TestServiceStatsAll_ErrorCountAndDurations(t *testing.T) {
	s := New()
	now := time.Now()

	ok1 := newTestSpan("t1", "s1", "op", now, 10)
	ok1.Resource.ServiceName = "svc"
	ok1.Kind = "SERVER"

	errSpan := newTestSpan("t1", "s2", "op", now.Add(5*time.Millisecond), 20)
	errSpan.ParentSpanID = "s1"
	errSpan.Resource.ServiceName = "svc"
	errSpan.Status = SpanStatus{Code: "ERROR"}
	errSpan.Kind = "CLIENT"

	s.AddSpansForConnection("conn-1", []Span{ok1, errSpan})

	stats := s.ServiceStatsAll()
	if len(stats) != 1 {
		t.Fatalf("expected 1 service, got %d", len(stats))
	}
	ss := stats[0]
	if ss.ErrorCount != 1 {
		t.Errorf("want errorCount=1, got %d", ss.ErrorCount)
	}
	if ss.AvgDurationMs == nil || *ss.AvgDurationMs != 15.0 {
		t.Errorf("want avgDurationMs=15.0, got %v", ss.AvgDurationMs)
	}
	if ss.AvgClientDuration == nil || *ss.AvgClientDuration != 20.0 {
		t.Errorf("want avgClientDurationMs=20.0, got %v", ss.AvgClientDuration)
	}
	if ss.AvgServerDuration == nil || *ss.AvgServerDuration != 10.0 {
		t.Errorf("want avgServerDurationMs=10.0, got %v", ss.AvgServerDuration)
	}
}

func TestServiceStatsAll_IncludesMetricAndLogOnlyServices(t *testing.T) {
	s := New()
	now := time.Now()

	// One span-bearing service.
	sp := newTestSpan("trace-1", "span-1", "root", now, 10)
	sp.Resource.ServiceName = "span-svc"
	s.AddSpansForConnection("conn", []Span{sp})

	// A metric-only service.
	s.AddMetricsForConnection("conn", []MetricDataPoint{
		{Resource: Resource{ServiceName: "metric-only-svc"}, Name: "some.metric"},
	})

	// A log-only service.
	s.AddLogsForConnection("conn", []LogRecord{
		{Resource: Resource{ServiceName: "log-only-svc"}},
	})

	stats := s.ServiceStatsAll()
	names := make(map[string]ServiceStats)
	for _, ss := range stats {
		names[ss.Name] = ss
	}

	if _, ok := names["span-svc"]; !ok {
		t.Fatal("want span-svc in results")
	}
	metricSvc, ok := names["metric-only-svc"]
	if !ok {
		t.Fatal("want metric-only-svc in results")
	}
	if metricSvc.TraceCount != 0 || metricSvc.SpanCount != 0 {
		t.Errorf("metric-only-svc should have zero trace/span counts, got trace=%d span=%d", metricSvc.TraceCount, metricSvc.SpanCount)
	}
	logSvc, ok := names["log-only-svc"]
	if !ok {
		t.Fatal("want log-only-svc in results")
	}
	if logSvc.TraceCount != 0 || logSvc.SpanCount != 0 {
		t.Errorf("log-only-svc should have zero trace/span counts, got trace=%d span=%d", logSvc.TraceCount, logSvc.SpanCount)
	}
}

// ============================================================================

func TestQueryTracesFiltered_FilterByServiceName(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "root", now, 10)
	span1.Resource.ServiceName = "service-a"

	span2 := newTestSpan("trace-2", "span-1", "root", now.Add(100*time.Millisecond), 10)
	span2.Resource.ServiceName = "service-b"

	s.AddSpansForConnection("conn-1", []Span{span1})
	s.AddSpansForConnection("conn-1", []Span{span2})

	results := s.QueryTracesFiltered("service-a", "", "", "", 10, 5)
	if len(results) != 1 {
		t.Errorf("expected 1 filtered result, got %d", len(results))
	}
	if results[0].ServiceName != "service-a" {
		t.Errorf("expected service-a, got %s", results[0].ServiceName)
	}
}

func TestQueryTracesFiltered_FilterBySpanName(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "http-request", now, 10)
	span2 := newTestSpan("trace-1", "span-2", "db-query", now.Add(5*time.Millisecond), 5)
	span2.ParentSpanID = "span-1"

	span3 := newTestSpan("trace-2", "span-1", "db-query", now.Add(100*time.Millisecond), 10)

	s.AddSpansForConnection("conn-1", []Span{span1, span2})
	s.AddSpansForConnection("conn-1", []Span{span3})

	results := s.QueryTracesFiltered("", "db-query", "", "", 10, 5)
	if len(results) != 2 {
		t.Errorf("expected 2 results with db-query, got %d", len(results))
	}
}

func TestQueryTracesFiltered_FilterByStatus(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("trace-1", "span-1", "root", now, 10)
	span1.Status.Code = "OK"

	span2 := newTestSpan("trace-2", "span-1", "root", now.Add(100*time.Millisecond), 10)
	span2.Status.Code = "ERROR"

	s.AddSpansForConnection("conn-1", []Span{span1})
	s.AddSpansForConnection("conn-1", []Span{span2})

	results := s.QueryTracesFiltered("", "", "error", "", 10, 5)
	if len(results) != 1 {
		t.Errorf("expected 1 error trace, got %d", len(results))
	}
	if results[0].Status != "error" {
		t.Errorf("expected error status, got %s", results[0].Status)
	}
}

func TestQueryTracesFiltered_FilterByTraceIDPrefix(t *testing.T) {
	s := New()
	now := time.Now()

	span1 := newTestSpan("abc123trace1", "span-1", "root", now, 10)
	span2 := newTestSpan("xyz789trace2", "span-1", "root", now.Add(100*time.Millisecond), 10)

	s.AddSpansForConnection("conn-1", []Span{span1})
	s.AddSpansForConnection("conn-1", []Span{span2})

	results := s.QueryTracesFiltered("", "", "", "abc", 10, 5)
	if len(results) != 1 {
		t.Errorf("expected 1 result with prefix abc, got %d", len(results))
	}
	if results[0].TraceID[:3] != "abc" {
		t.Errorf("expected trace ID starting with abc, got %s", results[0].TraceID)
	}
}

func TestQueryTracesFiltered_RespectsLimit(t *testing.T) {
	s := New()
	now := time.Now()

	for i := 0; i < 10; i++ {
		span := newTestSpan(fmt.Sprintf("trace-%d", i), "span-1", "root", now.Add(time.Duration(i)*100*time.Millisecond), 10)
		s.AddSpansForConnection("conn-1", []Span{span})
	}

	results := s.QueryTracesFiltered("", "", "", "", 5, 5)
	if len(results) != 5 {
		t.Errorf("expected 5 results, got %d", len(results))
	}
}

func TestQueryTraceSummariesFiltered_FilterBySummaryFields(t *testing.T) {
	s := New()
	now := time.Now()

	trace1Root := newTestSpan("trace-1", "span-1", "GET /orders", now, 10)
	trace1Root.Resource.ServiceName = "checkout"
	trace1Root.Status.Code = "OK"

	trace2Root := newTestSpan("trace-2", "span-1", "POST /checkout", now.Add(100*time.Millisecond), 30)
	trace2Root.Resource.ServiceName = "payments"
	trace2Root.Status.Code = "ERROR"
	trace2Child := newTestSpan("trace-2", "span-2", "db.write", now.Add(110*time.Millisecond), 5)
	trace2Child.ParentSpanID = "span-1"
	trace2Child.Resource.ServiceName = "payments"
	trace2Child.Status.Code = "ERROR"

	s.AddSpansForConnection("conn-1", []Span{trace1Root})
	s.AddSpansForConnection("conn-1", []Span{trace2Root, trace2Child})

	spanCount := 2
	minDurationMs := 25.0
	maxDurationMs := 35.0
	results := s.QueryTraceSummariesFiltered(TraceSummaryFilter{
		TraceID:        "trace-2",
		RootSpanName:   "post /checkout",
		ServiceName:    "PAYMENTS",
		Status:         "error",
		SpanCount:      &spanCount,
		MinDurationMs:  &minDurationMs,
		MaxDurationMs:  &maxDurationMs,
		Limit:          10,
		SpanPreviewCap: 5,
	})
	if len(results) != 1 {
		t.Fatalf("expected 1 filtered result, got %d", len(results))
	}
	if results[0].TraceID != "trace-2" {
		t.Fatalf("expected trace-2, got %s", results[0].TraceID)
	}
	if results[0].SpanCount != 2 {
		t.Fatalf("expected span count 2, got %d", results[0].SpanCount)
	}
}

func TestQueryTraceSummariesFiltered_FilterByQuery(t *testing.T) {
	s := New()
	now := time.Now()

	trace1 := newTestSpan("trace-1", "span-1", "GET /orders", now, 10)
	trace1.Resource.ServiceName = "checkout"

	trace2 := newTestSpan("trace-2", "span-1", "POST /charge", now.Add(100*time.Millisecond), 20)
	trace2.Resource.ServiceName = "payments"
	trace2.Status.Code = "ERROR"

	s.AddSpansForConnection("conn-1", []Span{trace1, trace2})

	results := s.QueryTraceSummariesFiltered(TraceSummaryFilter{
		Query: "charge",
		Limit: 10,
	})
	if len(results) != 1 {
		t.Fatalf("expected 1 query-matched result, got %d", len(results))
	}
	if results[0].TraceID != "trace-2" {
		t.Fatalf("expected trace-2, got %s", results[0].TraceID)
	}
}

func TestQueryTraceSummariesFiltered_EmptyReturnsEmptySlice(t *testing.T) {
	s := New()
	results := s.QueryTraceSummariesFiltered(TraceSummaryFilter{Limit: 10})
	if results == nil {
		t.Fatalf("expected empty slice, got nil")
	}
	if len(results) != 0 {
		t.Fatalf("expected 0 results, got %d", len(results))
	}
}

func TestQueryTraceSummariesFiltered_FilterBySummaryRanges(t *testing.T) {
	s := New()
	now := time.Now()

	trace1 := newTestSpan("trace-1", "span-1", "root-a", now, 10)
	trace2Root := newTestSpan("trace-2", "span-1", "root-b", now.Add(100*time.Millisecond), 30)
	trace2Child := newTestSpan("trace-2", "span-2", "child-b", now.Add(110*time.Millisecond), 5)
	trace2Child.ParentSpanID = "span-1"
	trace3Root := newTestSpan("trace-3", "span-1", "root-c", now.Add(200*time.Millisecond), 60)
	trace3Child := newTestSpan("trace-3", "span-2", "child-c", now.Add(210*time.Millisecond), 10)
	trace3Child.ParentSpanID = "span-1"

	s.AddSpansForConnection("conn-1", []Span{trace1})
	s.AddSpansForConnection("conn-1", []Span{trace2Root, trace2Child})
	s.AddSpansForConnection("conn-1", []Span{trace3Root, trace3Child})

	minSpanCount := 2
	maxSpanCount := 2
	minDurationMs := 20.0
	maxDurationMs := 40.0
	timeFrom := now.Add(50 * time.Millisecond)
	timeTo := now.Add(150 * time.Millisecond)
	results := s.QueryTraceSummariesFiltered(TraceSummaryFilter{
		MinSpanCount:  &minSpanCount,
		MaxSpanCount:  &maxSpanCount,
		MinDurationMs: &minDurationMs,
		MaxDurationMs: &maxDurationMs,
		TimeFrom:      &timeFrom,
		TimeTo:        &timeTo,
		Limit:         10,
	})
	if len(results) != 1 {
		t.Fatalf("expected 1 ranged result, got %d", len(results))
	}
	if results[0].TraceID != "trace-2" {
		t.Fatalf("expected trace-2, got %s", results[0].TraceID)
	}
}

// ============================================================================
// QueryMetricsFiltered Tests
// ============================================================================

func TestQueryMetricsFiltered_FilterByMetricName(t *testing.T) {
	s := New()
	now := time.Now()

	m1 := newTestMetric("cpu.usage", 42.5, now)
	m2 := newTestMetric("memory.usage", 80.0, now.Add(100*time.Millisecond))

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m1})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m2})

	results := s.QueryMetricsFiltered("cpu.usage", "", "", "", "", 10, 3)
	if len(results) != 1 {
		t.Errorf("expected 1 result, got %d", len(results))
	}
	if results[0].Name != "cpu.usage" {
		t.Errorf("expected cpu.usage, got %s", results[0].Name)
	}
}

func TestQueryMetricsFiltered_FilterByServiceName(t *testing.T) {
	s := New()
	now := time.Now()

	m1 := newTestMetric("cpu", 42.5, now)
	m1.Resource.ServiceName = "service-a"

	m2 := newTestMetric("cpu", 45.0, now.Add(100*time.Millisecond))
	m2.Resource.ServiceName = "service-b"

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m1})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m2})

	results := s.QueryMetricsFiltered("", "service-a", "", "", "", 10, 3)
	if len(results) != 1 {
		t.Errorf("expected 1 result, got %d", len(results))
	}
	if results[0].ServiceName != "service-a" {
		t.Errorf("expected service-a, got %s", results[0].ServiceName)
	}
}

func TestQueryMetricsFiltered_FilterByScopeName(t *testing.T) {
	s := New()
	now := time.Now()

	m1 := newTestMetric("cpu", 42.5, now)
	m1.Scope.Name = "scope-a"

	m2 := newTestMetric("cpu", 45.0, now.Add(100*time.Millisecond))
	m2.Scope.Name = "scope-b"

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m1})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m2})

	results := s.QueryMetricsFiltered("", "", "scope-a", "", "", 10, 3)
	if len(results) != 1 {
		t.Errorf("expected 1 result, got %d", len(results))
	}
	if results[0].ScopeName != "scope-a" {
		t.Errorf("expected scope-a, got %s", results[0].ScopeName)
	}
}

func TestQueryMetricsFiltered_FilterByType(t *testing.T) {
	s := New()
	now := time.Now()

	m1 := newTestMetric("cpu", 42.5, now)
	m1.Type = "gauge"

	m2 := newTestMetric("counter", 100.0, now.Add(100*time.Millisecond))
	m2.Type = "sum"

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m1})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m2})

	results := s.QueryMetricsFiltered("", "", "", "gauge", "", 10, 3)
	if len(results) != 1 {
		t.Errorf("expected 1 gauge result, got %d", len(results))
	}
	if results[0].Type != "gauge" {
		t.Errorf("expected gauge type, got %s", results[0].Type)
	}
}

func TestQueryMetricsFiltered_RespectsLimit(t *testing.T) {
	s := New()
	now := time.Now()

	for i := 0; i < 10; i++ {
		m := newTestMetric(fmt.Sprintf("metric-%d", i), float64(i), now.Add(time.Duration(i)*100*time.Millisecond))
		s.AddMetricsForConnection("conn-1", []MetricDataPoint{m})
	}

	results := s.QueryMetricsFiltered("", "", "", "", "", 5, 3)
	if len(results) != 5 {
		t.Errorf("expected 5 results, got %d", len(results))
	}
}

func TestQueryTraceSummaryFieldValues(t *testing.T) {
	s := New()
	now := time.Now()
	s.AddSpansForConnection("", []Span{
		{
			TraceID:   "trace-1",
			SpanID:    "span-1",
			Name:      "GET /orders",
			Kind:      "internal",
			StartTime: now,
			EndTime:   now.Add(10 * time.Millisecond),
			Status:    SpanStatus{Code: "OK"},
			Resource:  Resource{ServiceName: "checkout", Attributes: map[string]any{}},
			Scope:     Scope{Name: "otel"},
		},
		{
			TraceID:   "trace-2",
			SpanID:    "span-2",
			Name:      "POST /charge",
			Kind:      "internal",
			StartTime: now.Add(time.Second),
			EndTime:   now.Add(time.Second + 5*time.Millisecond),
			Status:    SpanStatus{Code: "ERROR"},
			Resource:  Resource{ServiceName: "payments", Attributes: map[string]any{}},
			Scope:     Scope{Name: "otel"},
		},
	})

	values := s.QueryTraceSummaryFieldValues("serviceName", "pa", TraceSummaryFilter{}, 10)
	if len(values) != 1 || values[0] != "payments" {
		t.Fatalf("expected [payments], got %v", values)
	}
}

func TestQueryMetricGroupsFiltered_FilterByQueryAndSummaryFields(t *testing.T) {
	s := New()
	now := time.Now()

	m1 := newTestMetric("http.server.duration", 12, now)
	m1.Description = "Request duration"
	m1.Unit = "ms"
	m1.Type = "histogram"
	m1.Resource.ServiceName = "checkout"
	m1.Scope.Name = "otel.http"

	m1b := newTestMetric("http.server.duration", 15, now.Add(10*time.Millisecond))
	m1b.Description = "Request duration"
	m1b.Unit = "ms"
	m1b.Type = "histogram"
	m1b.Resource.ServiceName = "checkout"
	m1b.Scope.Name = "otel.http"
	m1b.Attributes["http.method"] = "GET"

	m2 := newTestMetric("db.client.connections.usage", 5, now.Add(100*time.Millisecond))
	m2.Description = "Open connections"
	m2.Unit = "connections"
	m2.Type = "gauge"
	m2.Resource.ServiceName = "db"
	m2.Scope.Name = "otel.db"

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{m1, m1b, m2})

	dataPointCount := 2
	seriesCount := 2
	results := s.QueryMetricGroupsFiltered(MetricGroupFilter{
		Query:          "duration",
		MetricName:     "http.server.duration",
		ServiceName:    "CHECKOUT",
		ScopeName:      "otel.http",
		Type:           "histogram",
		Unit:           "ms",
		DataPointCount: &dataPointCount,
		SeriesCount:    &seriesCount,
		Limit:          10,
	})
	if len(results) != 1 {
		t.Fatalf("expected 1 filtered metric group, got %d", len(results))
	}
	if results[0].Name != "http.server.duration" {
		t.Fatalf("expected http.server.duration, got %s", results[0].Name)
	}
	if results[0].SeriesCount != 2 {
		t.Fatalf("expected series count 2, got %d", results[0].SeriesCount)
	}
}

func TestQueryMetricGroupsFiltered_FilterByCountRanges(t *testing.T) {
	s := New()
	now := time.Now()

	oneSeries := newTestMetric("metric.one", 1, now)
	oneSeries.Resource.ServiceName = "svc"
	twoSeriesA := newTestMetric("metric.two", 2, now.Add(100*time.Millisecond))
	twoSeriesA.Resource.ServiceName = "svc"
	twoSeriesB := newTestMetric("metric.two", 3, now.Add(110*time.Millisecond))
	twoSeriesB.Resource.ServiceName = "svc"
	twoSeriesB.Attributes["dim"] = "b"

	s.AddMetricsForConnection("conn-1", []MetricDataPoint{oneSeries, twoSeriesA, twoSeriesB})

	minSeriesCount := 2
	maxSeriesCount := 2
	minDataPointCount := 2
	maxDataPointCount := 2
	timeFrom := now.Add(50 * time.Millisecond)
	timeTo := now.Add(150 * time.Millisecond)
	results := s.QueryMetricGroupsFiltered(MetricGroupFilter{
		MinSeriesCount:    &minSeriesCount,
		MaxSeriesCount:    &maxSeriesCount,
		MinDataPointCount: &minDataPointCount,
		MaxDataPointCount: &maxDataPointCount,
		TimeFrom:          &timeFrom,
		TimeTo:            &timeTo,
		Limit:             10,
	})
	if len(results) != 1 {
		t.Fatalf("expected 1 ranged metric group, got %d", len(results))
	}
	if results[0].Name != "metric.two" {
		t.Fatalf("expected metric.two, got %s", results[0].Name)
	}
}

func TestQueryMetricGroupFieldValues(t *testing.T) {
	s := New()
	now := time.Now()
	s.AddMetricsForConnection("", []MetricDataPoint{
		{
			Name:      "http.server.duration",
			Unit:      "ms",
			Type:      "histogram",
			Timestamp: now,
			Resource:  Resource{ServiceName: "checkout", Attributes: map[string]any{}},
			Scope:     Scope{Name: "otel.http"},
		},
		{
			Name:      "db.client.connections.usage",
			Unit:      "connections",
			Type:      "gauge",
			Timestamp: now.Add(time.Second),
			Resource:  Resource{ServiceName: "payments", Attributes: map[string]any{}},
			Scope:     Scope{Name: "otel.db"},
		},
	})

	values := s.QueryMetricGroupFieldValues("scopeName", "", MetricGroupFilter{ServiceName: "payments"}, 10)
	if len(values) != 1 || values[0] != "otel.db" {
		t.Fatalf("expected [otel.db], got %v", values)
	}
}

// ============================================================================
// QueryLogsFiltered Tests
// ============================================================================

func TestQueryLogsFiltered_FilterBySeverityText(t *testing.T) {
	s := New()
	now := time.Now()

	log1 := newTestLog("info message", now)
	log1.SeverityText = "INFO"

	log2 := newTestLog("error message", now.Add(100*time.Millisecond))
	log2.SeverityText = "ERROR"

	s.AddLogsForConnection("conn-1", []LogRecord{log1})
	s.AddLogsForConnection("conn-1", []LogRecord{log2})

	results := s.QueryLogsFiltered("", "error", "", "", 10)
	if len(results) != 1 {
		t.Errorf("expected 1 error log, got %d", len(results))
	}
	if results[0].SeverityText != "ERROR" {
		t.Errorf("expected ERROR severity, got %s", results[0].SeverityText)
	}
}

func TestQueryLogsFiltered_FilterByBody(t *testing.T) {
	s := New()
	now := time.Now()

	log1 := newTestLog("connection timeout", now)
	log2 := newTestLog("successful request", now.Add(100*time.Millisecond))

	s.AddLogsForConnection("conn-1", []LogRecord{log1})
	s.AddLogsForConnection("conn-1", []LogRecord{log2})

	results := s.QueryLogsFiltered("", "", "timeout", "", 10)
	if len(results) != 1 {
		t.Errorf("expected 1 timeout log, got %d", len(results))
	}
	if !contains(results[0].Body, "timeout") {
		t.Errorf("expected body containing timeout, got %s", results[0].Body)
	}
}

func TestQueryLogsFiltered_FilterByTraceID(t *testing.T) {
	s := New()
	now := time.Now()

	log1 := newTestLog("message", now)
	log1.TraceID = "trace-1"

	log2 := newTestLog("message", now.Add(100*time.Millisecond))
	log2.TraceID = "trace-2"

	s.AddLogsForConnection("conn-1", []LogRecord{log1})
	s.AddLogsForConnection("conn-1", []LogRecord{log2})

	results := s.QueryLogsFiltered("", "", "", "trace-1", 10)
	if len(results) != 1 {
		t.Errorf("expected 1 log for trace-1, got %d", len(results))
	}
	if results[0].TraceID != "trace-1" {
		t.Errorf("expected trace-1, got %s", results[0].TraceID)
	}
}

func TestQueryLogsFiltered_FilterByServiceName(t *testing.T) {
	s := New()
	now := time.Now()

	log1 := newTestLog("message", now)
	log1.Resource.ServiceName = "service-a"

	log2 := newTestLog("message", now.Add(100*time.Millisecond))
	log2.Resource.ServiceName = "service-b"

	s.AddLogsForConnection("conn-1", []LogRecord{log1})
	s.AddLogsForConnection("conn-1", []LogRecord{log2})

	results := s.QueryLogsFiltered("service-a", "", "", "", 10)
	if len(results) != 1 {
		t.Errorf("expected 1 log, got %d", len(results))
	}
	if results[0].Resource.ServiceName != "service-a" {
		t.Errorf("expected service-a, got %s", results[0].Resource.ServiceName)
	}
}

func TestQueryLogsFiltered_RespectsLimit(t *testing.T) {
	s := New()
	now := time.Now()

	for i := 0; i < 10; i++ {
		log := newTestLog(fmt.Sprintf("message %d", i), now.Add(time.Duration(i)*100*time.Millisecond))
		s.AddLogsForConnection("conn-1", []LogRecord{log})
	}

	results := s.QueryLogsFiltered("", "", "", "", 5)
	if len(results) != 5 {
		t.Errorf("expected 5 results, got %d", len(results))
	}
}

func TestQueryLogRecordsFiltered_FilterByQueryAndSummaryFields(t *testing.T) {
	s := New()
	now := time.Now()

	log1 := newTestLog("checkout started", now)
	log1.SeverityText = "INFO"
	log1.Resource.ServiceName = "checkout"
	log1.TraceID = "trace-1"

	log2 := newTestLog("payment failed", now.Add(100*time.Millisecond))
	log2.SeverityText = "ERROR"
	log2.Resource.ServiceName = "payments"
	log2.TraceID = "trace-2"
	log2.SpanID = "span-2"

	s.AddLogsForConnection("conn-1", []LogRecord{log1, log2})

	results := s.QueryLogRecordsFiltered(LogRecordFilter{
		ServiceName:  "PAYMENTS",
		SeverityText: "error",
		TraceID:      "trace-2",
		SpanID:       "span-2",
		ScopeName:    "test-scope",
		Query:        "failed",
		TimeFrom:     timePointer(now.Add(50 * time.Millisecond)),
		TimeTo:       timePointer(now.Add(150 * time.Millisecond)),
		Limit:        10,
	})
	if len(results) != 1 {
		t.Fatalf("expected 1 filtered log record, got %d", len(results))
	}
	if results[0].Body != "payment failed" {
		t.Fatalf("expected payment failed, got %s", results[0].Body)
	}
}

func TestQueryLogRecordsFiltered_FilterByDisplayedSeverity(t *testing.T) {
	s := New()
	now := time.Now()

	log1 := newTestLog("warn from number", now)
	log1.SeverityText = ""
	log1.SeverityNumber = 14

	log2 := newTestLog("error from text", now.Add(100*time.Millisecond))
	log2.SeverityText = "SEVERE"
	log2.SeverityNumber = 3

	s.AddLogsForConnection("conn-1", []LogRecord{log1, log2})

	results := s.QueryLogRecordsFiltered(LogRecordFilter{
		SeverityDisplay: "warn2",
		Limit:           10,
	})
	if len(results) != 1 {
		t.Fatalf("expected 1 displayed-severity result, got %d", len(results))
	}
	if results[0].Body != "warn from number" {
		t.Fatalf("expected warn from number, got %s", results[0].Body)
	}
}

func TestQueryLogRecordsFiltered_EmptyReturnsEmptySlice(t *testing.T) {
	s := New()
	results := s.QueryLogRecordsFiltered(LogRecordFilter{Limit: 10})
	if results == nil {
		t.Fatalf("expected empty slice, got nil")
	}
	if len(results) != 0 {
		t.Fatalf("expected 0 results, got %d", len(results))
	}
}

func TestQueryLogRecordFieldValues(t *testing.T) {
	s := New()
	now := time.Now()
	s.AddLogsForConnection("", []LogRecord{
		{
			ID:             "1",
			Timestamp:      now,
			SeverityNumber: 14,
			Body:           "checkout started",
			Resource:       Resource{ServiceName: "checkout", Attributes: map[string]any{}},
			Scope:          Scope{Name: "checkout.logger"},
		},
		{
			ID:           "2",
			Timestamp:    now.Add(time.Second),
			SeverityText: "SEVERE",
			Body:         "payment failed",
			Resource:     Resource{ServiceName: "payments", Attributes: map[string]any{}},
			Scope:        Scope{Name: "payments.logger"},
		},
	})

	values := s.QueryLogRecordFieldValues("scopeName", "pay", LogRecordFilter{}, 10)
	if len(values) != 1 || values[0] != "payments.logger" {
		t.Fatalf("expected [payments.logger], got %v", values)
	}

	displayValues := s.QueryLogRecordFieldValues("severityDisplay", "war", LogRecordFilter{}, 10)
	if len(displayValues) != 1 || displayValues[0] != "WARN2" {
		t.Fatalf("expected [WARN2], got %v", displayValues)
	}
}

// ============================================================================
// AppendBoundedMetricWindow Tests
// ============================================================================

func TestAppendBoundedMetricWindow_UnderLimit(t *testing.T) {
	dp1 := newTestMetric("cpu", 42.5, time.Now())
	dp2 := newTestMetric("cpu", 45.0, time.Now().Add(100*time.Millisecond))

	window := []MetricDataPoint{dp1}
	result := appendBoundedMetricWindow(window, dp2, 8)

	if len(result) != 2 {
		t.Errorf("expected 2 items, got %d", len(result))
	}
}

func TestAppendBoundedMetricWindow_AtLimit(t *testing.T) {
	window := make([]MetricDataPoint, 0, 8)
	for i := 0; i < 8; i++ {
		dp := newTestMetric("cpu", float64(i), time.Now().Add(time.Duration(i)*100*time.Millisecond))
		window = append(window, dp)
	}

	newDp := newTestMetric("cpu", 8.0, time.Now().Add(800*time.Millisecond))
	result := appendBoundedMetricWindow(window, newDp, 8)

	if len(result) != 8 {
		t.Errorf("expected 8 items (window limit), got %d", len(result))
	}
	// Oldest should be replaced
	if result[7].Value != 8.0 {
		t.Errorf("expected newest value (8.0) at end, got %f", result[7].Value)
	}
}

func TestAppendBoundedMetricWindow_OverLimit(t *testing.T) {
	window := make([]MetricDataPoint, 0)
	for i := 0; i < 10; i++ {
		dp := newTestMetric("cpu", float64(i), time.Now().Add(time.Duration(i)*100*time.Millisecond))
		window = appendBoundedMetricWindow(window, dp, 3)
	}

	if len(window) != 3 {
		t.Errorf("expected 3 items (bounded window), got %d", len(window))
	}
}

func TestAppendBoundedMetricWindow_ZeroLimit(t *testing.T) {
	dp1 := newTestMetric("cpu", 42.5, time.Now())
	dp2 := newTestMetric("cpu", 45.0, time.Now().Add(100*time.Millisecond))

	window := []MetricDataPoint{dp1}
	result := appendBoundedMetricWindow(window, dp2, 0)

	if len(result) != 1 {
		t.Errorf("expected no change with zero limit, got %d items", len(result))
	}
}

// ============================================================================
// Integration Tests
// ============================================================================

func TestIntegration_MultipleConnectionsAndSignals(t *testing.T) {
	s := New()
	id, _ := s.Subscribe()
	defer s.Unsubscribe(id)

	now := time.Now()

	// Add data from two connections
	span1 := newTestSpan("trace-1", "span-1", "root", now, 10)
	span2 := newTestSpan("trace-2", "span-1", "root", now.Add(100*time.Millisecond), 10)

	s.AddSpansForConnection("conn-1", []Span{span1})
	s.AddSpansForConnection("conn-2", []Span{span2})

	// Verify both are stored
	stats := s.Stats()
	if stats.SpanCount != 2 || stats.TraceCount != 2 {
		t.Errorf("expected 2 spans and 2 traces, got %d spans and %d traces", stats.SpanCount, stats.TraceCount)
	}

	// Evict one connection
	s.EvictConnection("conn-1")

	// Verify only one remains
	stats = s.Stats()
	if stats.SpanCount != 1 || stats.TraceCount != 1 {
		t.Errorf("expected 1 span and 1 trace after eviction, got %d spans and %d traces", stats.SpanCount, stats.TraceCount)
	}
}

func TestIntegration_Clear(t *testing.T) {
	s := New()
	now := time.Now()

	span := newTestSpan("trace-1", "span-1", "root", now, 10)
	metric := newTestMetric("cpu", 42.5, now)
	log := newTestLog("message", now)

	s.AddSpansForConnection("conn-1", []Span{span})
	s.AddMetricsForConnection("conn-1", []MetricDataPoint{metric})
	s.AddLogsForConnection("conn-1", []LogRecord{log})

	stats := s.Stats()
	if stats.SpanCount == 0 || stats.DataPointCount == 0 || stats.LogCount == 0 {
		t.Error("expected data before clear")
	}

	s.Clear()

	stats = s.Stats()
	if stats.SpanCount != 0 || stats.DataPointCount != 0 || stats.LogCount != 0 {
		t.Errorf("expected all zeros after clear, got spans:%d metrics:%d logs:%d",
			stats.SpanCount, stats.DataPointCount, stats.LogCount)
	}
}

// ============================================================================
// Helper Functions
// ============================================================================

func contains(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
