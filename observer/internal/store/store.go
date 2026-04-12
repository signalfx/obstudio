// Package store implements an in-memory telemetry store with per-connection tracking.
package store

import (
	"encoding/json"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Signal represents a store update event type.
type Signal string

const (
	// SignalTraces indicates traces were added or removed.
	SignalTraces Signal = "traces"
	// SignalMetrics indicates metrics were added or removed.
	SignalMetrics Signal = "metrics"
	// SignalLogs indicates logs were added or removed.
	SignalLogs Signal = "logs"
)

// Default ring buffer capacities.
const (
	DefaultSpanCap   = 10_000
	DefaultMetricCap = 10_000
	DefaultLogCap    = 10_000

	metricSeriesWindow = 8
)

// Resource represents the resource associated with telemetry.
type Resource struct {
	ServiceName string         `json:"serviceName,omitempty"`
	Attributes  map[string]any `json:"attributes"`
	SchemaURL   string         `json:"schemaUrl,omitempty"`
}

// Scope represents the instrumentation scope.
type Scope struct {
	Name      string `json:"name"`
	Version   string `json:"version,omitempty"`
	SchemaURL string `json:"schemaUrl,omitempty"`
}

// SpanStatus represents the completion status of a span.
type SpanStatus struct {
	Code    string `json:"code"`
	Message string `json:"message,omitempty"`
}

// SpanEvent represents an event that occurred during a span.
type SpanEvent struct {
	Name       string         `json:"name"`
	Timestamp  time.Time      `json:"timeUnixNano"`
	Attributes map[string]any `json:"attributes"`
}

// SpanLink represents a link to another span.
type SpanLink struct {
	TraceID    string         `json:"traceId"`
	SpanID     string         `json:"spanId"`
	Attributes map[string]any `json:"attributes"`
}

// Span represents an OpenTelemetry trace span.
type Span struct {
	TraceID      string         `json:"traceId"`
	SpanID       string         `json:"spanId"`
	ParentSpanID string         `json:"parentSpanId,omitempty"`
	Name         string         `json:"name"`
	Kind         string         `json:"kind"`
	StartTime    time.Time      `json:"startTimeUnixNano"`
	EndTime      time.Time      `json:"endTimeUnixNano"`
	DurationMs   float64        `json:"durationMs"`
	Status       SpanStatus     `json:"status"`
	Attributes   map[string]any `json:"attributes"`
	Events       []SpanEvent    `json:"events"`
	Links        []SpanLink     `json:"links"`
	Resource     Resource       `json:"resource"`
	Scope        Scope          `json:"scope"`

	ownerConnID string `json:"-"`
}

// QuantileValue represents a quantile value in summary metrics.
type QuantileValue struct {
	Quantile float64 `json:"quantile"`
	Value    float64 `json:"value"`
}

// MetricDataPoint represents a single metric measurement.
type MetricDataPoint struct {
	Name        string         `json:"name"`
	Description string         `json:"description,omitempty"`
	Unit        string         `json:"unit,omitempty"`
	Type        string         `json:"type"`
	Timestamp   time.Time      `json:"timeUnixNano"`
	StartTime   time.Time      `json:"startTimeUnixNano,omitempty"`
	Attributes  map[string]any `json:"attributes"`
	Resource    Resource       `json:"resource"`
	Scope       Scope          `json:"scope"`
	Flags       int            `json:"flags,omitempty"`

	Value       float64 `json:"value,omitempty"`
	IsMonotonic bool    `json:"isMonotonic,omitempty"`
	Temporality string  `json:"temporality,omitempty"`

	Count          uint64          `json:"count,omitempty"`
	Sum            float64         `json:"sum,omitempty"`
	Min            float64         `json:"min,omitempty"`
	Max            float64         `json:"max,omitempty"`
	BucketCounts   []uint64        `json:"bucketCounts,omitempty"`
	ExplicitBounds []float64       `json:"explicitBounds,omitempty"`
	Quantiles      []QuantileValue `json:"quantiles,omitempty"`

	ownerConnID string `json:"-"`
}

// LogRecord represents an OpenTelemetry log record.
type LogRecord struct {
	ID             string         `json:"id"`
	Timestamp      time.Time      `json:"timeUnixNano"`
	SeverityNumber int32          `json:"severityNumber,omitempty"`
	SeverityText   string         `json:"severityText,omitempty"`
	Body           string         `json:"body"`
	Attributes     map[string]any `json:"attributes"`
	TraceID        string         `json:"traceId,omitempty"`
	SpanID         string         `json:"spanId,omitempty"`
	Resource       Resource       `json:"resource"`
	Scope          Scope          `json:"scope"`

	ownerConnID string `json:"-"`
}

// TraceSummary represents a summary of a single trace.
type TraceSummary struct {
	TraceID      string        `json:"traceId"`
	RootSpanName string        `json:"rootSpanName"`
	ServiceName  string        `json:"serviceName,omitempty"`
	SpanCount    int           `json:"spanCount"`
	DurationMs   float64       `json:"durationMs"`
	Status       string        `json:"status"`
	Spans        []SpanPreview `json:"spans,omitempty"`
}

// SpanPreview represents a preview of a span in a trace.
type SpanPreview struct {
	SpanID     string  `json:"spanId"`
	Name       string  `json:"name"`
	Kind       string  `json:"kind"`
	DurationMs float64 `json:"durationMs"`
	StatusCode string  `json:"statusCode"`
}

// TraceDetail represents the full details of a trace.
type TraceDetail struct {
	TraceID      string  `json:"traceId"`
	RootSpanName string  `json:"rootSpanName"`
	ServiceName  string  `json:"serviceName,omitempty"`
	SpanCount    int     `json:"spanCount"`
	DurationMs   float64 `json:"durationMs"`
	Status       string  `json:"status"`
	Spans        []Span  `json:"spans"`
}

// MetricGroup represents a group of metric data points with the same name.
type MetricGroup struct {
	Name           string            `json:"name"`
	Description    string            `json:"description,omitempty"`
	Unit           string            `json:"unit,omitempty"`
	Type           string            `json:"type"`
	ServiceName    string            `json:"serviceName,omitempty"`
	ScopeName      string            `json:"scopeName,omitempty"`
	SeriesCount    int               `json:"seriesCount,omitempty"`
	DataPointCount int               `json:"dataPointCount"`
	DataPoints     []MetricDataPoint `json:"dataPoints,omitempty"`
}

// Stats represents aggregated statistics about stored telemetry.
type Stats struct {
	SpanCount       int      `json:"spanCount"`
	DataPointCount  int      `json:"dataPointCount"`
	MetricNameCount int      `json:"metricNameCount"`
	LogCount        int      `json:"logCount"`
	TraceCount      int      `json:"traceCount"`
	ServiceNames    []string `json:"serviceNames"`
}

// Endpoints holds the addresses the collector is listening on.
type Endpoints struct {
	OTLPHTTP string `json:"otlpHttp,omitempty"`
	OTLPgRPC string `json:"otlpGrpc,omitempty"`
	REST     string `json:"rest,omitempty"`
}

// TelemetrySnapshot is a point-in-time copy of the in-memory telemetry buffers.
type TelemetrySnapshot struct {
	Spans   []Span            `json:"spans"`
	Metrics []MetricDataPoint `json:"metrics"`
	Logs    []LogRecord       `json:"logs"`
}

// Store is the in-memory telemetry store.
type Store struct {
	mu      sync.RWMutex
	spans   ringBuffer[Span]
	metrics ringBuffer[MetricDataPoint]
	logs    ringBuffer[LogRecord]

	lastIngest time.Time
	sessionGap time.Duration

	endpoints Endpoints

	nextLogID uint64

	subMu       sync.Mutex
	subscribers map[int]chan Signal
	nextSubID   int

	invalidateMu sync.RWMutex
	invalidate   func()

	changeMu sync.RWMutex
	change   func(time.Time)
}

// ringBuffer is a fixed-capacity circular buffer. When full, the oldest
// items are silently overwritten. This bounds memory usage.
type ringBuffer[T any] struct {
	items []T
	head  int // next write position
	count int // number of items currently stored
	cap   int
}

func newRingBuffer[T any](capacity int) ringBuffer[T] {
	return ringBuffer[T]{items: make([]T, capacity), cap: capacity}
}

// push appends items, overwriting the oldest when at capacity.
func (rb *ringBuffer[T]) push(items []T) {
	for _, item := range items {
		rb.items[rb.head] = item
		rb.head = (rb.head + 1) % rb.cap
		if rb.count < rb.cap {
			rb.count++
		}
	}
}

// snapshot returns a copy of the stored items in insertion order (oldest first).
func (rb *ringBuffer[T]) snapshot() []T {
	if rb.count == 0 {
		return nil
	}
	out := make([]T, rb.count)
	start := 0
	if rb.count == rb.cap {
		start = rb.head // oldest item is at head when full
	}
	for i := 0; i < rb.count; i++ {
		out[i] = rb.items[(start+i)%rb.cap]
	}
	return out
}

// clear resets the buffer.
func (rb *ringBuffer[T]) clear() {
	rb.head = 0
	rb.count = 0
}

// size returns the number of items currently stored.
func (rb *ringBuffer[T]) size() int {
	return rb.count
}

// iterate calls fn for each stored item in insertion order (oldest first).
// It does not allocate a copy.
func (rb *ringBuffer[T]) iterate(fn func(T)) {
	if rb.count == 0 {
		return
	}
	start := 0
	if rb.count == rb.cap {
		start = rb.head
	}
	for i := 0; i < rb.count; i++ {
		fn(rb.items[(start+i)%rb.cap])
	}
}

// SetEndpoints updates the endpoints where the collector is listening.
func (s *Store) SetEndpoints(e Endpoints) {
	s.mu.Lock()
	s.endpoints = e
	s.mu.Unlock()
}

// Endpoints returns the addresses where the collector is listening.
func (s *Store) Endpoints() Endpoints {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.endpoints
}

// SetInvalidateCallback installs a callback invoked when the store is cleared,
// reset, or evicted in a way that invalidates derived state such as validation.
func (s *Store) SetInvalidateCallback(fn func()) {
	s.invalidateMu.Lock()
	s.invalidate = fn
	s.invalidateMu.Unlock()
}

// SetChangeCallback installs a callback invoked when new telemetry is ingested.
func (s *Store) SetChangeCallback(fn func(time.Time)) {
	s.changeMu.Lock()
	s.change = fn
	s.changeMu.Unlock()
}

// New creates a new Store with default configuration.
func New() *Store {
	return &Store{
		spans:       newRingBuffer[Span](DefaultSpanCap),
		metrics:     newRingBuffer[MetricDataPoint](DefaultMetricCap),
		logs:        newRingBuffer[LogRecord](DefaultLogCap),
		subscribers: make(map[int]chan Signal),
		sessionGap:  30 * time.Second,
	}
}

// AddSpansForConnection adds spans with an associated connection ID for later eviction.
func (s *Store) AddSpansForConnection(connID string, spans []Span) {
	s.mu.Lock()
	reset := s.checkSessionReset()
	if connID != "" {
		for i := range spans {
			spans[i].ownerConnID = connID
		}
	}
	s.spans.push(spans)
	changedAt := time.Now()
	s.lastIngest = changedAt
	s.mu.Unlock()
	if reset {
		s.runInvalidateCallback()
	}
	s.runChangeCallback(changedAt)
	if reset {
		s.notify(SignalTraces)
		s.notify(SignalMetrics)
		s.notify(SignalLogs)
		return
	}
	s.notify(SignalTraces)
}

// AddMetricsForConnection adds metrics with an associated connection ID for later eviction.
func (s *Store) AddMetricsForConnection(connID string, metrics []MetricDataPoint) {
	s.mu.Lock()
	reset := s.checkSessionReset()
	if connID != "" {
		for i := range metrics {
			metrics[i].ownerConnID = connID
		}
	}
	s.metrics.push(metrics)
	changedAt := time.Now()
	s.lastIngest = changedAt
	s.mu.Unlock()
	if reset {
		s.runInvalidateCallback()
	}
	s.runChangeCallback(changedAt)
	if reset {
		s.notify(SignalTraces)
		s.notify(SignalMetrics)
		s.notify(SignalLogs)
		return
	}
	s.notify(SignalMetrics)
}

// AddLogsForConnection adds logs with an associated connection ID for later eviction.
func (s *Store) AddLogsForConnection(connID string, logs []LogRecord) {
	s.mu.Lock()
	reset := s.checkSessionReset()
	if connID != "" {
		for i := range logs {
			logs[i].ownerConnID = connID
		}
	}
	for i := range logs {
		if logs[i].ID == "" {
			s.nextLogID++
			logs[i].ID = "log-" + strconv.FormatUint(s.nextLogID, 10)
		}
	}
	s.logs.push(logs)
	changedAt := time.Now()
	s.lastIngest = changedAt
	s.mu.Unlock()
	if reset {
		s.runInvalidateCallback()
	}
	s.runChangeCallback(changedAt)
	if reset {
		s.notify(SignalTraces)
		s.notify(SignalMetrics)
		s.notify(SignalLogs)
		return
	}
	s.notify(SignalLogs)
}

// Clear removes all stored telemetry and resets the session clock.
func (s *Store) Clear() {
	s.mu.Lock()
	s.spans.clear()
	s.metrics.clear()
	s.logs.clear()
	s.lastIngest = time.Time{}
	s.mu.Unlock()
	s.runInvalidateCallback()
	s.notify(SignalTraces)
	s.notify(SignalMetrics)
	s.notify(SignalLogs)
}

// EvictConnection removes all telemetry data associated with the given
// connection ID. This is called when a connected process exits (detected
// via PID monitoring or gRPC session close). Only data from that specific
// connection is removed; other connections' data is preserved.
func (s *Store) EvictConnection(connID string) {
	if connID == "" {
		return
	}

	s.mu.Lock()
	hasSpans := s.rebuildSpansWithoutConnection(connID)
	hasMetrics := s.rebuildMetricsWithoutConnection(connID)
	hasLogs := s.rebuildLogsWithoutConnection(connID)

	// If the store is now empty, reset the ingest clock.
	if s.spans.size() == 0 && s.metrics.size() == 0 && s.logs.size() == 0 {
		s.lastIngest = time.Time{}
	}
	s.mu.Unlock()

	if hasSpans || hasMetrics || hasLogs {
		s.runInvalidateCallback()
	}

	if hasSpans {
		s.notify(SignalTraces)
	}
	if hasMetrics {
		s.notify(SignalMetrics)
	}
	if hasLogs {
		s.notify(SignalLogs)
	}
}

// rebuildSpansWithoutConnection rebuilds the spans ring buffer, excluding
// telemetry owned by the given connection.
// Must be called with s.mu held.
func (s *Store) rebuildSpansWithoutConnection(connID string) bool {
	kept := make([]Span, 0, s.spans.size())
	removed := false
	s.spans.iterate(func(sp Span) {
		if sp.ownerConnID == connID {
			removed = true
			return
		}
		kept = append(kept, sp)
	})
	if !removed {
		return false
	}
	s.spans.clear()
	if len(kept) > 0 {
		s.spans.push(kept)
	}
	return true
}

// rebuildMetricsWithoutConnection rebuilds the metrics ring buffer, excluding
// telemetry owned by the given connection.
// Must be called with s.mu held.
func (s *Store) rebuildMetricsWithoutConnection(connID string) bool {
	kept := make([]MetricDataPoint, 0, s.metrics.size())
	removed := false
	s.metrics.iterate(func(m MetricDataPoint) {
		if m.ownerConnID == connID {
			removed = true
			return
		}
		kept = append(kept, m)
	})
	if !removed {
		return false
	}
	s.metrics.clear()
	if len(kept) > 0 {
		s.metrics.push(kept)
	}
	return true
}

// rebuildLogsWithoutConnection rebuilds the logs ring buffer, excluding
// telemetry owned by the given connection.
// Must be called with s.mu held.
func (s *Store) rebuildLogsWithoutConnection(connID string) bool {
	kept := make([]LogRecord, 0, s.logs.size())
	removed := false
	s.logs.iterate(func(l LogRecord) {
		if l.ownerConnID == connID {
			removed = true
			return
		}
		kept = append(kept, l)
	})
	if !removed {
		return false
	}
	s.logs.clear()
	if len(kept) > 0 {
		s.logs.push(kept)
	}
	return true
}

// checkSessionReset clears the store when telemetry arrives after a gap
// longer than sessionGap, indicating the instrumented app was restarted.
// Must be called with s.mu held. Returns true if a reset occurred.
func (s *Store) checkSessionReset() bool {
	if s.lastIngest.IsZero() || s.sessionGap <= 0 {
		return false
	}
	if time.Since(s.lastIngest) > s.sessionGap {
		s.spans.clear()
		s.metrics.clear()
		s.logs.clear()
		return true
	}
	return false
}

// QueryTraces returns the latest traces, newest first, up to the specified limit.
func (s *Store) QueryTraces(limit int) []TraceSummary {
	if limit <= 0 {
		limit = 100
	}

	s.mu.RLock()
	allSpans := s.spans.snapshot()
	s.mu.RUnlock()

	grouped := groupSpansByTrace(allSpans)

	var results []TraceSummary
	for traceID, spans := range grouped {
		root := findRootSpan(spans)
		dur := computeTraceDuration(spans)
		previews := makeSpanPreviews(spans, 8)

		results = append(results, TraceSummary{
			TraceID:      traceID,
			RootSpanName: root.Name,
			ServiceName:  root.Resource.ServiceName,
			SpanCount:    len(spans),
			DurationMs:   dur,
			Status:       computeTraceStatus(spans),
			Spans:        previews,
		})
	}

	// Precompute start times to avoid repeated map lookups during sort.
	startTimes := make(map[string]time.Time, len(grouped))
	for traceID, spans := range grouped {
		startTimes[traceID] = getTraceStartTime(spans)
	}

	sort.Slice(results, func(i, j int) bool {
		return startTimes[results[i].TraceID].After(startTimes[results[j].TraceID])
	})

	if len(results) > limit {
		results = results[:limit]
	}
	return results
}

// Trace returns the full details of a single trace by ID, limiting events per span.
func (s *Store) Trace(traceID string, eventLimit int) *TraceDetail {
	if eventLimit <= 0 {
		eventLimit = 12
	}

	s.mu.RLock()
	allSpans := s.spans.snapshot()
	s.mu.RUnlock()

	grouped := groupSpansByTrace(allSpans)
	spans, ok := grouped[traceID]
	if !ok {
		return nil
	}

	root := findRootSpan(spans)

	truncated := make([]Span, len(spans))
	copy(truncated, spans)
	for i := range truncated {
		if len(truncated[i].Events) > eventLimit {
			truncated[i].Events = truncated[i].Events[:eventLimit]
		}
	}

	return &TraceDetail{
		TraceID:      traceID,
		RootSpanName: root.Name,
		ServiceName:  root.Resource.ServiceName,
		SpanCount:    len(spans),
		DurationMs:   computeTraceDuration(spans),
		Status:       computeTraceStatus(spans),
		Spans:        truncated,
	}
}

// QueryMetrics returns the latest metric groups, newest first, up to the specified limit.
// The UI path returns a bounded rolling window per series plus explicit
// series cardinality so live WebSocket payloads stay controlled.
func (s *Store) QueryMetrics(limit int) []MetricGroup {
	if limit <= 0 {
		limit = 100
	}

	s.mu.RLock()
	points := s.metrics.snapshot()
	s.mu.RUnlock()

	type groupKey struct{ name, svc, scope string }
	type groupAccumulator struct {
		group      *MetricGroup
		series     map[string][]MetricDataPoint
		seriesKeys []string
	}

	groups := make(map[groupKey]*groupAccumulator)
	latestByGroup := make(map[groupKey]time.Time)

	// Keep a bounded rolling window for each series in chronological order.
	for _, dp := range points {
		key := groupKey{dp.Name, dp.Resource.ServiceName, dp.Scope.Name}
		acc, exists := groups[key]
		if !exists {
			acc = &groupAccumulator{
				group: &MetricGroup{
					Name:        dp.Name,
					Description: dp.Description,
					Unit:        dp.Unit,
					Type:        dp.Type,
					ServiceName: dp.Resource.ServiceName,
					ScopeName:   dp.Scope.Name,
				},
				series: make(map[string][]MetricDataPoint),
			}
			groups[key] = acc
		}
		acc.group.DataPointCount++
		seriesKey := metricPreviewSeriesKey(dp)
		if _, ok := acc.series[seriesKey]; !ok {
			acc.group.SeriesCount++
			acc.seriesKeys = append(acc.seriesKeys, seriesKey)
		}
		acc.series[seriesKey] = appendBoundedMetricWindow(acc.series[seriesKey], dp, metricSeriesWindow)
		if dp.Timestamp.After(latestByGroup[key]) {
			latestByGroup[key] = dp.Timestamp
		}
	}

	groupOrder := make([]groupKey, 0, len(groups))
	for key := range groups {
		groupOrder = append(groupOrder, key)
	}

	sort.Slice(groupOrder, func(i, j int) bool {
		return latestByGroup[groupOrder[i]].After(latestByGroup[groupOrder[j]])
	})

	if len(groupOrder) > limit {
		groupOrder = groupOrder[:limit]
	}

	results := make([]MetricGroup, 0, len(groupOrder))
	for _, key := range groupOrder {
		acc := groups[key]
		group := *acc.group
		group.DataPoints = make([]MetricDataPoint, 0, minInt(group.DataPointCount, group.SeriesCount*metricSeriesWindow))
		sort.Strings(acc.seriesKeys)
		for _, seriesKey := range acc.seriesKeys {
			group.DataPoints = append(group.DataPoints, acc.series[seriesKey]...)
		}
		sort.SliceStable(group.DataPoints, func(i, j int) bool {
			if group.DataPoints[i].Timestamp.Equal(group.DataPoints[j].Timestamp) {
				return metricPreviewSeriesKey(group.DataPoints[i]) < metricPreviewSeriesKey(group.DataPoints[j])
			}
			return group.DataPoints[i].Timestamp.Before(group.DataPoints[j].Timestamp)
		})
		results = append(results, group)
	}
	return results
}

// QueryLogs returns the latest log records, newest first, up to the specified limit.
func (s *Store) QueryLogs(limit int) []LogRecord {
	if limit <= 0 {
		limit = 100
	}

	s.mu.RLock()
	all := s.logs.snapshot()
	s.mu.RUnlock()

	// Return newest first.
	var results []LogRecord
	for i := len(all) - 1; i >= 0 && len(results) < limit; i-- {
		results = append(results, all[i])
	}
	return results
}

// Stats returns aggregated statistics about stored telemetry.
func (s *Store) Stats() Stats {
	s.mu.RLock()
	defer s.mu.RUnlock()

	traceIDs := make(map[string]struct{})
	svcSet := make(map[string]struct{})
	metricNames := make(map[string]struct{})

	s.spans.iterate(func(sp Span) {
		traceIDs[sp.TraceID] = struct{}{}
		if sp.Resource.ServiceName != "" {
			svcSet[sp.Resource.ServiceName] = struct{}{}
		}
	})
	s.metrics.iterate(func(m MetricDataPoint) {
		metricNames[m.Name] = struct{}{}
		if m.Resource.ServiceName != "" {
			svcSet[m.Resource.ServiceName] = struct{}{}
		}
	})
	s.logs.iterate(func(l LogRecord) {
		if l.Resource.ServiceName != "" {
			svcSet[l.Resource.ServiceName] = struct{}{}
		}
	})

	svcs := make([]string, 0, len(svcSet))
	for svc := range svcSet {
		svcs = append(svcs, svc)
	}
	sort.Strings(svcs)

	return Stats{
		SpanCount:       s.spans.size(),
		DataPointCount:  s.metrics.size(),
		MetricNameCount: len(metricNames),
		LogCount:        s.logs.size(),
		TraceCount:      len(traceIDs),
		ServiceNames:    svcs,
	}
}

// SnapshotTelemetry returns a point-in-time copy of all retained telemetry.
func (s *Store) SnapshotTelemetry() TelemetrySnapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()

	spans := s.spans.snapshot()
	metrics := s.metrics.snapshot()
	logs := s.logs.snapshot()

	return TelemetrySnapshot{
		Spans:   append([]Span(nil), spans...),
		Metrics: append([]MetricDataPoint(nil), metrics...),
		Logs:    append([]LogRecord(nil), logs...),
	}
}

// LastIngest returns the timestamp of the most recent telemetry ingest.
func (s *Store) LastIngest() time.Time {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.lastIngest
}

// Subscribe registers for updates on store changes and returns a subscription ID and channel.
func (s *Store) Subscribe() (int, <-chan Signal) {
	ch := make(chan Signal, 8)
	s.subMu.Lock()
	id := s.nextSubID
	s.nextSubID++
	s.subscribers[id] = ch
	s.subMu.Unlock()
	return id, ch
}

// Unsubscribe removes a subscriber by its subscription ID and closes
// its channel so that any goroutine ranging over it will exit.
func (s *Store) Unsubscribe(id int) {
	s.subMu.Lock()
	ch, ok := s.subscribers[id]
	delete(s.subscribers, id)
	s.subMu.Unlock()
	if ok {
		close(ch)
	}
}

func (s *Store) notify(sig Signal) {
	s.subMu.Lock()
	defer s.subMu.Unlock()
	for _, ch := range s.subscribers {
		select {
		case ch <- sig:
		default:
		}
	}
}

func (s *Store) runInvalidateCallback() {
	s.invalidateMu.RLock()
	fn := s.invalidate
	s.invalidateMu.RUnlock()
	if fn != nil {
		fn()
	}
}

func (s *Store) runChangeCallback(changedAt time.Time) {
	s.changeMu.RLock()
	fn := s.change
	s.changeMu.RUnlock()
	if fn != nil {
		fn(changedAt)
	}
}

// --- MCP query helpers (accept filters for MCP tool use) ---

// QueryTracesFiltered is used by MCP tools that need filtering.
func (s *Store) QueryTracesFiltered(serviceName, spanName, status, traceIDPrefix string, limit, spanPreviewCount int) []TraceSummary {
	if limit <= 0 {
		limit = 20
	}
	if spanPreviewCount <= 0 {
		spanPreviewCount = 5
	}

	s.mu.RLock()
	allSpans := s.spans.snapshot()
	s.mu.RUnlock()

	grouped := groupSpansByTrace(allSpans)

	var results []TraceSummary
	for traceID, spans := range grouped {
		if traceIDPrefix != "" && !strings.HasPrefix(traceID, strings.ToLower(traceIDPrefix)) {
			continue
		}
		root := findRootSpan(spans)
		svcName := root.Resource.ServiceName
		st := computeTraceStatus(spans)

		if serviceName != "" && !strings.EqualFold(svcName, serviceName) {
			continue
		}
		if status != "" && st != status {
			continue
		}
		if spanName != "" && !anySpanNameMatches(spans, spanName) {
			continue
		}

		dur := computeTraceDuration(spans)
		previews := makeSpanPreviews(spans, spanPreviewCount)

		results = append(results, TraceSummary{
			TraceID:      traceID,
			RootSpanName: root.Name,
			ServiceName:  svcName,
			SpanCount:    len(spans),
			DurationMs:   dur,
			Status:       st,
			Spans:        previews,
		})
	}

	startTimes := make(map[string]time.Time, len(grouped))
	for traceID, spans := range grouped {
		startTimes[traceID] = getTraceStartTime(spans)
	}

	sort.Slice(results, func(i, j int) bool {
		return startTimes[results[i].TraceID].After(startTimes[results[j].TraceID])
	})

	if len(results) > limit {
		results = results[:limit]
	}
	return results
}

// QueryMetricsFiltered is used by MCP tools that need filtering.
func (s *Store) QueryMetricsFiltered(metricName, serviceName, scopeName, metricType, resourceAttribute string, limit, dataPointLimit int) []MetricGroup {
	if limit <= 0 {
		limit = 20
	}
	if dataPointLimit <= 0 {
		dataPointLimit = 3
	}

	s.mu.RLock()
	points := s.metrics.snapshot()
	s.mu.RUnlock()

	type groupKey struct{ name, svc, scope string }
	groups := make(map[groupKey]*MetricGroup)
	groupOrder := make([]groupKey, 0)

	// Iterate newest-first so we keep the most recent datapoints.
	for i := len(points) - 1; i >= 0; i-- {
		dp := points[i]
		if metricName != "" && !strings.EqualFold(dp.Name, metricName) {
			continue
		}
		if serviceName != "" && !strings.EqualFold(dp.Resource.ServiceName, serviceName) {
			continue
		}
		if scopeName != "" && !strings.EqualFold(dp.Scope.Name, scopeName) {
			continue
		}
		if metricType != "" && dp.Type != normalizeMetricType(metricType) {
			continue
		}
		if resourceAttribute != "" {
			serialized, _ := json.Marshal(dp.Resource.Attributes)
			if !strings.Contains(string(serialized), resourceAttribute) {
				continue
			}
		}

		key := groupKey{dp.Name, dp.Resource.ServiceName, dp.Scope.Name}
		g, exists := groups[key]
		if !exists {
			g = &MetricGroup{
				Name:        dp.Name,
				Description: dp.Description,
				Unit:        dp.Unit,
				Type:        dp.Type,
				ServiceName: dp.Resource.ServiceName,
				ScopeName:   dp.Scope.Name,
			}
			groups[key] = g
			groupOrder = append(groupOrder, key)
		}
		g.DataPointCount++
		if len(g.DataPoints) < dataPointLimit {
			g.DataPoints = append(g.DataPoints, dp)
		}
	}

	var results []MetricGroup
	for _, key := range groupOrder {
		g := *groups[key]
		reverseSlice(g.DataPoints)
		results = append(results, g)
	}
	if len(results) > limit {
		results = results[:limit]
	}
	return results
}

// QueryLogsFiltered is used by MCP tools that need filtering.
func (s *Store) QueryLogsFiltered(serviceName, severityText, body, traceID string, limit int) []LogRecord {
	if limit <= 0 {
		limit = 50
	}

	s.mu.RLock()
	all := s.logs.snapshot()
	s.mu.RUnlock()

	var results []LogRecord
	for i := len(all) - 1; i >= 0 && len(results) < limit; i-- {
		lr := all[i]
		if serviceName != "" && !strings.EqualFold(lr.Resource.ServiceName, serviceName) {
			continue
		}
		if severityText != "" && !strings.EqualFold(lr.SeverityText, severityText) {
			continue
		}
		if body != "" && !strings.Contains(strings.ToLower(lr.Body), strings.ToLower(body)) {
			continue
		}
		if traceID != "" && lr.TraceID != traceID {
			continue
		}
		results = append(results, lr)
	}
	return results
}

func groupSpansByTrace(spans []Span) map[string][]Span {
	groups := make(map[string][]Span)
	for _, sp := range spans {
		groups[sp.TraceID] = append(groups[sp.TraceID], sp)
	}
	return groups
}

func getTraceStartTime(spans []Span) time.Time {
	if len(spans) == 0 {
		return time.Time{}
	}
	min := spans[0].StartTime
	for _, sp := range spans[1:] {
		if sp.StartTime.Before(min) {
			min = sp.StartTime
		}
	}
	return min
}

func findRootSpan(spans []Span) Span {
	for _, sp := range spans {
		if sp.ParentSpanID == "" {
			return sp
		}
	}
	if len(spans) > 0 {
		return spans[0]
	}
	return Span{Name: "unknown"}
}

func computeTraceStatus(spans []Span) string {
	hasError, hasOK := false, false
	for _, sp := range spans {
		switch sp.Status.Code {
		case "ERROR":
			hasError = true
		case "OK":
			hasOK = true
		}
	}
	if hasError && hasOK {
		return "mixed"
	}
	if hasError {
		return "error"
	}
	if hasOK {
		return "ok"
	}
	return "unset"
}

func computeTraceDuration(spans []Span) float64 {
	if len(spans) == 0 {
		return 0
	}
	minStart := spans[0].StartTime
	maxEnd := spans[0].EndTime
	for _, sp := range spans[1:] {
		if sp.StartTime.Before(minStart) {
			minStart = sp.StartTime
		}
		if sp.EndTime.After(maxEnd) {
			maxEnd = sp.EndTime
		}
	}
	return float64(maxEnd.Sub(minStart)) / float64(time.Millisecond)
}

func anySpanNameMatches(spans []Span, name string) bool {
	for _, sp := range spans {
		if strings.EqualFold(sp.Name, name) {
			return true
		}
	}
	return false
}

func makeSpanPreviews(spans []Span, limit int) []SpanPreview {
	n := len(spans)
	if n > limit {
		n = limit
	}
	previews := make([]SpanPreview, n)
	for i := 0; i < n; i++ {
		previews[i] = SpanPreview{
			SpanID:     spans[i].SpanID,
			Name:       spans[i].Name,
			Kind:       spans[i].Kind,
			DurationMs: spans[i].DurationMs,
			StatusCode: spans[i].Status.Code,
		}
	}
	return previews
}

func normalizeMetricType(t string) string {
	switch strings.ToLower(t) {
	case "counter", "sum":
		return "sum"
	case "gauge":
		return "gauge"
	case "histogram":
		return "histogram"
	case "summary":
		return "summary"
	case "exponential_histogram":
		return "exponential_histogram"
	default:
		return t
	}
}

func reverseSlice[T any](s []T) {
	for i, j := 0, len(s)-1; i < j; i, j = i+1, j-1 {
		s[i], s[j] = s[j], s[i]
	}
}

func metricPreviewSeriesKey(dp MetricDataPoint) string {
	return "resource:" + stringifyMetricAttributes(dp.Resource.Attributes) + "|point:" + stringifyMetricAttributes(dp.Attributes)
}

func stringifyMetricAttributes(attrs map[string]any) string {
	if len(attrs) == 0 {
		return ""
	}
	keys := make([]string, 0, len(attrs))
	for key := range attrs {
		keys = append(keys, key)
	}
	sort.Strings(keys)

	var b strings.Builder
	for i, key := range keys {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(key)
		b.WriteByte('=')
		b.WriteString(stringifyMetricValue(attrs[key]))
	}
	return b.String()
}

func appendBoundedMetricWindow(points []MetricDataPoint, dp MetricDataPoint, limit int) []MetricDataPoint {
	if limit <= 0 {
		return points
	}
	if len(points) == limit {
		copy(points, points[1:])
		points = points[:limit-1]
	}
	return append(points, dp)
}

func stringifyMetricValue(v any) string {
	switch val := v.(type) {
	case string:
		return val
	default:
		encoded, err := json.Marshal(val)
		if err != nil {
			return ""
		}
		return string(encoded)
	}
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
