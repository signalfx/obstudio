package store

import (
	"fmt"
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
