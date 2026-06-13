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

// LogRecordFilter narrows log queries using explicit fields, optional time
// bounds, and a legacy free-text substring query over the summary columns.
type LogRecordFilter struct {
	ServiceName            string
	ExcludeServiceName     string
	SeverityDisplay        string
	ExcludeSeverityDisplay string
	SeverityNumber         *int32
	ExcludeSeverityNumber  *int32
	SeverityText           string
	ExcludeSeverityText    string
	BodyContains           string
	ExcludeBodyContains    string
	TraceID                string
	ExcludeTraceID         string
	SpanID                 string
	ExcludeSpanID          string
	ScopeName              string
	ExcludeScopeName       string
	TimeAfter              *time.Time
	TimeBefore             *time.Time
	TimeFrom               *time.Time
	TimeTo                 *time.Time
	Query                  string
	Limit                  int
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

// TraceSummaryFilter narrows trace summary queries using fields already present
// on TraceSummary plus optional numeric and time ranges.
type TraceSummaryFilter struct {
	Query               string
	TraceID             string
	ExcludeTraceID      string
	RootSpanName        string
	ExcludeRootSpanName string
	ServiceName         string
	ExcludeServiceName  string
	Status              string
	ExcludeStatus       string
	SpanCount           *int
	SpanCountGT         *int
	SpanCountLT         *int
	MinSpanCount        *int
	MaxSpanCount        *int
	DurationMs          *float64
	DurationMsGT        *float64
	DurationMsLT        *float64
	TimeAfter           *time.Time
	TimeBefore          *time.Time
	MinDurationMs       *float64
	MaxDurationMs       *float64
	TimeFrom            *time.Time
	TimeTo              *time.Time
	Limit               int
	SpanPreviewCap      int
}

// SpanPreview represents a preview of a span in a trace.
type SpanPreview struct {
	SpanID      string  `json:"spanId"`
	Name        string  `json:"name"`
	Kind        string  `json:"kind"`
	DurationMs  float64 `json:"durationMs"`
	StatusCode  string  `json:"statusCode"`
	ServiceName string  `json:"serviceName,omitempty"`
}

// TraceDetail represents the full details of a trace.
type TraceDetail struct {
	TraceID      string             `json:"traceId"`
	RootSpanName string             `json:"rootSpanName"`
	ServiceName  string             `json:"serviceName,omitempty"`
	SpanCount    int                `json:"spanCount"`
	DurationMs   float64            `json:"durationMs"`
	Status       string             `json:"status"`
	Spans        []Span             `json:"spans"`
	GenAI        *GenAITraceSummary `json:"genAI,omitempty"`
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

// MetricGroupFilter narrows metric group queries using exact summary fields,
// optional count and time ranges, and a legacy free-text query over the visible
// metric columns.
type MetricGroupFilter struct {
	Query                      string
	MetricName                 string
	ExcludeMetricName          string
	DescriptionContains        string
	ExcludeDescriptionContains string
	Unit                       string
	ExcludeUnit                string
	Type                       string
	ExcludeType                string
	ServiceName                string
	ExcludeServiceName         string
	ScopeName                  string
	ExcludeScopeName           string
	DataPointCount             *int
	DataPointCountGT           *int
	DataPointCountLT           *int
	MinDataPointCount          *int
	MaxDataPointCount          *int
	SeriesCount                *int
	SeriesCountGT              *int
	SeriesCountLT              *int
	TimeAfter                  *time.Time
	TimeBefore                 *time.Time
	MinSeriesCount             *int
	MaxSeriesCount             *int
	TimeFrom                   *time.Time
	TimeTo                     *time.Time
	Limit                      int
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

// ServiceStats holds per-service aggregate counts computed from the full span store.
type ServiceStats struct {
	Name              string   `json:"name"`
	TraceCount        int      `json:"traceCount"`
	SpanCount         int      `json:"spanCount"`
	ErrorCount        int      `json:"errorCount"`
	AvgDurationMs     *float64 `json:"avgDurationMs"`
	AvgClientDuration *float64 `json:"avgClientDurationMs"`
	AvgServerDuration *float64 `json:"avgServerDurationMs"`
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
	return s.QueryTraceSummariesFiltered(TraceSummaryFilter{Limit: limit, SpanPreviewCap: 8})
}

// QueryTraceSummariesFiltered returns trace summaries filtered by fields already
// surfaced on TraceSummary plus optional numeric ranges.
func (s *Store) QueryTraceSummariesFiltered(filter TraceSummaryFilter) []TraceSummary {
	if filter.Limit <= 0 {
		filter.Limit = 100
	}
	if filter.SpanPreviewCap <= 0 {
		filter.SpanPreviewCap = 8
	}

	s.mu.RLock()
	allSpans := s.spans.snapshot()
	s.mu.RUnlock()

	grouped := groupSpansByTrace(allSpans)
	if len(grouped) == 0 {
		return []TraceSummary{}
	}

	startTimes := make(map[string]time.Time, len(grouped))
	results := make([]TraceSummary, 0, minInt(len(grouped), filter.Limit))
	for traceID, spans := range grouped {
		startTime := getTraceStartTime(spans)
		if filter.TimeAfter != nil && !startTime.After(*filter.TimeAfter) {
			continue
		}
		if filter.TimeBefore != nil && !startTime.Before(*filter.TimeBefore) {
			continue
		}
		if filter.TimeFrom != nil && startTime.Before(*filter.TimeFrom) {
			continue
		}
		if filter.TimeTo != nil && startTime.After(*filter.TimeTo) {
			continue
		}
		root := findRootSpan(spans)
		dur := computeTraceDuration(spans)
		summary := TraceSummary{
			TraceID:      traceID,
			RootSpanName: root.Name,
			ServiceName:  root.Resource.ServiceName,
			SpanCount:    len(spans),
			DurationMs:   dur,
			Status:       computeTraceStatus(spans),
			Spans:        makeSpanPreviews(spans, filter.SpanPreviewCap),
		}
		if !matchesTraceSummaryFilter(summary, filter) {
			continue
		}
		startTimes[traceID] = startTime
		results = append(results, summary)
	}

	sort.Slice(results, func(i, j int) bool {
		return startTimes[results[i].TraceID].After(startTimes[results[j].TraceID])
	})

	if len(results) > filter.Limit {
		results = results[:filter.Limit]
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
		GenAI:        buildGenAITraceSummary(truncated),
	}
}

// QueryMetrics returns the latest metric groups, newest first, up to the specified limit.
// The UI path returns a bounded rolling window per series plus explicit
// series cardinality so live WebSocket payloads stay controlled.
func (s *Store) QueryMetrics(limit int) []MetricGroup {
	return s.QueryMetricGroupsFiltered(MetricGroupFilter{Limit: limit})
}

// QueryMetricGroupsFiltered returns metric groups using the same bounded
// preview shape as QueryMetrics, but with server-side filtering applied.
func (s *Store) QueryMetricGroupsFiltered(filter MetricGroupFilter) []MetricGroup {
	if filter.Limit <= 0 {
		filter.Limit = 100
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

	for _, dp := range points {
		if filter.TimeAfter != nil && !dp.Timestamp.After(*filter.TimeAfter) {
			continue
		}
		if filter.TimeBefore != nil && !dp.Timestamp.Before(*filter.TimeBefore) {
			continue
		}
		if filter.TimeFrom != nil && dp.Timestamp.Before(*filter.TimeFrom) {
			continue
		}
		if filter.TimeTo != nil && dp.Timestamp.After(*filter.TimeTo) {
			continue
		}
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

	results := make([]MetricGroup, 0, minInt(len(groupOrder), filter.Limit))
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
		if !matchesMetricGroupFilter(group, filter) {
			continue
		}
		results = append(results, group)
		if len(results) >= filter.Limit {
			break
		}
	}
	return results
}

// QueryLogs returns the latest log records, newest first, up to the specified limit.
func (s *Store) QueryLogs(limit int) []LogRecord {
	return s.QueryLogRecordsFiltered(LogRecordFilter{Limit: limit})
}

func (s *Store) QueryTraceSummaryFieldValues(field, prefix string, filter TraceSummaryFilter, limit int) []string {
	s.mu.RLock()
	count := s.spans.size()
	s.mu.RUnlock()
	if count == 0 {
		return []string{}
	}
	filter = clearTraceSummaryFieldFilter(filter, field)
	filter.Limit = count
	filter.SpanPreviewCap = 1
	summaries := s.QueryTraceSummariesFiltered(filter)
	return collectSuggestionValues(limit, prefix, summaries, func(summary TraceSummary) string {
		switch field {
		case "rootSpanName":
			return summary.RootSpanName
		case "serviceName":
			return summary.ServiceName
		default:
			return ""
		}
	})
}

func (s *Store) QueryMetricGroupFieldValues(field, prefix string, filter MetricGroupFilter, limit int) []string {
	s.mu.RLock()
	count := s.metrics.size()
	s.mu.RUnlock()
	if count == 0 {
		return []string{}
	}
	filter = clearMetricGroupFieldFilter(filter, field)
	filter.Limit = count
	groups := s.QueryMetricGroupsFiltered(filter)
	return collectSuggestionValues(limit, prefix, groups, func(group MetricGroup) string {
		switch field {
		case "metricName":
			return group.Name
		case "serviceName":
			return group.ServiceName
		case "scopeName":
			return group.ScopeName
		case "unit":
			return group.Unit
		default:
			return ""
		}
	})
}

func (s *Store) QueryLogRecordFieldValues(field, prefix string, filter LogRecordFilter, limit int) []string {
	s.mu.RLock()
	count := s.logs.size()
	s.mu.RUnlock()
	if count == 0 {
		return []string{}
	}
	filter = clearLogRecordFieldFilter(filter, field)
	filter.Limit = count
	records := s.QueryLogRecordsFiltered(filter)
	return collectSuggestionValues(limit, prefix, records, func(record LogRecord) string {
		switch field {
		case "serviceName":
			return record.Resource.ServiceName
		case "severityDisplay":
			return displayLogSeverity(record)
		case "scopeName":
			return record.Scope.Name
		default:
			return ""
		}
	})
}

// QueryLogRecordsFiltered returns log records filtered by exact fields plus
// an optional free-text query over the summary columns shown in the logs table.
func (s *Store) QueryLogRecordsFiltered(filter LogRecordFilter) []LogRecord {
	if filter.Limit <= 0 {
		filter.Limit = 100
	}

	s.mu.RLock()
	all := s.logs.snapshot()
	s.mu.RUnlock()
	if len(all) == 0 {
		return []LogRecord{}
	}

	results := make([]LogRecord, 0, minInt(len(all), filter.Limit))
	for i := len(all) - 1; i >= 0 && len(results) < filter.Limit; i-- {
		lr := all[i]
		if !matchesLogRecordFilter(lr, filter) {
			continue
		}
		results = append(results, lr)
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

// ServiceStatsAll computes per-service aggregates over all retained telemetry.
// Every service name observed across spans, metrics, and logs is included; services
// with no spans will have zero trace/span counts and nil duration fields.
// traceCount counts distinct traces that include each service (not just root service).
func (s *Store) ServiceStatsAll() []ServiceStats {
	s.mu.RLock()
	allSpans := s.spans.snapshot()
	// Collect service names from metrics and logs while holding the read lock.
	metricLogSvcs := make(map[string]struct{})
	s.metrics.iterate(func(m MetricDataPoint) {
		if m.Resource.ServiceName != "" {
			metricLogSvcs[m.Resource.ServiceName] = struct{}{}
		}
	})
	s.logs.iterate(func(l LogRecord) {
		if l.Resource.ServiceName != "" {
			metricLogSvcs[l.Resource.ServiceName] = struct{}{}
		}
	})
	s.mu.RUnlock()

	grouped := groupSpansByTrace(allSpans)

	type accum struct {
		traceIDs     map[string]struct{}
		spanCount    int
		errorCount   int
		allDurSum    float64
		allDurCount  int
		clientDurSum float64
		clientCount  int
		serverDurSum float64
		serverCount  int
	}

	acc := make(map[string]*accum)
	getAcc := func(name string) *accum {
		a := acc[name]
		if a == nil {
			a = &accum{traceIDs: make(map[string]struct{})}
			acc[name] = a
		}
		return a
	}

	for traceID, spans := range grouped {
		// Collect every service name present in this trace.
		traceServices := make(map[string]struct{})
		for _, sp := range spans {
			svc := sp.Resource.ServiceName
			if svc == "" {
				svc = "unknown"
			}
			traceServices[svc] = struct{}{}
		}
		// Increment traceCount for every service seen in this trace.
		for svc := range traceServices {
			getAcc(svc).traceIDs[traceID] = struct{}{}
		}
		// Accumulate span-level stats.
		for _, sp := range spans {
			svc := sp.Resource.ServiceName
			if svc == "" {
				svc = "unknown"
			}
			a := getAcc(svc)
			a.spanCount++
			if sp.Status.Code == "ERROR" {
				a.errorCount++
			}
			a.allDurSum += sp.DurationMs
			a.allDurCount++
			switch sp.Kind {
			case "CLIENT":
				a.clientDurSum += sp.DurationMs
				a.clientCount++
			case "SERVER":
				a.serverDurSum += sp.DurationMs
				a.serverCount++
			}
		}
	}

	// Ensure metric/log-only services appear with zero span fields.
	for svc := range metricLogSvcs {
		if _, ok := acc[svc]; !ok {
			acc[svc] = &accum{traceIDs: make(map[string]struct{})}
		}
	}

	result := make([]ServiceStats, 0, len(acc))
	for name, a := range acc {
		ss := ServiceStats{
			Name:       name,
			TraceCount: len(a.traceIDs),
			SpanCount:  a.spanCount,
			ErrorCount: a.errorCount,
		}
		if a.allDurCount > 0 {
			v := a.allDurSum / float64(a.allDurCount)
			ss.AvgDurationMs = &v
		}
		if a.clientCount > 0 {
			v := a.clientDurSum / float64(a.clientCount)
			ss.AvgClientDuration = &v
		}
		if a.serverCount > 0 {
			v := a.serverDurSum / float64(a.serverCount)
			ss.AvgServerDuration = &v
		}
		result = append(result, ss)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Name < result[j].Name })
	return result
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
	return s.QueryLogRecordsFiltered(LogRecordFilter{
		ServiceName:  serviceName,
		SeverityText: severityText,
		BodyContains: body,
		TraceID:      traceID,
		Limit:        limit,
	})
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

func matchesTraceSummaryFilter(summary TraceSummary, filter TraceSummaryFilter) bool {
	if filter.Query != "" {
		haystack := strings.ToLower(strings.Join([]string{
			summary.TraceID,
			summary.RootSpanName,
			summary.ServiceName,
			summary.Status,
		}, " "))
		if !strings.Contains(haystack, strings.ToLower(filter.Query)) {
			return false
		}
	}
	if filter.TraceID != "" && !strings.EqualFold(summary.TraceID, filter.TraceID) {
		return false
	}
	if filter.ExcludeTraceID != "" && strings.EqualFold(summary.TraceID, filter.ExcludeTraceID) {
		return false
	}
	if filter.RootSpanName != "" && !strings.EqualFold(summary.RootSpanName, filter.RootSpanName) {
		return false
	}
	if filter.ExcludeRootSpanName != "" && strings.EqualFold(summary.RootSpanName, filter.ExcludeRootSpanName) {
		return false
	}
	if filter.ServiceName != "" && !strings.EqualFold(summary.ServiceName, filter.ServiceName) {
		return false
	}
	if filter.ExcludeServiceName != "" && strings.EqualFold(summary.ServiceName, filter.ExcludeServiceName) {
		return false
	}
	if filter.Status != "" && !strings.EqualFold(summary.Status, filter.Status) {
		return false
	}
	if filter.ExcludeStatus != "" && strings.EqualFold(summary.Status, filter.ExcludeStatus) {
		return false
	}
	if filter.SpanCount != nil && summary.SpanCount != *filter.SpanCount {
		return false
	}
	if filter.SpanCountGT != nil && summary.SpanCount <= *filter.SpanCountGT {
		return false
	}
	if filter.SpanCountLT != nil && summary.SpanCount >= *filter.SpanCountLT {
		return false
	}
	if filter.MinSpanCount != nil && summary.SpanCount < *filter.MinSpanCount {
		return false
	}
	if filter.MaxSpanCount != nil && summary.SpanCount > *filter.MaxSpanCount {
		return false
	}
	if filter.DurationMs != nil && summary.DurationMs != *filter.DurationMs {
		return false
	}
	if filter.DurationMsGT != nil && summary.DurationMs <= *filter.DurationMsGT {
		return false
	}
	if filter.DurationMsLT != nil && summary.DurationMs >= *filter.DurationMsLT {
		return false
	}
	if filter.MinDurationMs != nil && summary.DurationMs < *filter.MinDurationMs {
		return false
	}
	if filter.MaxDurationMs != nil && summary.DurationMs > *filter.MaxDurationMs {
		return false
	}
	return true
}

func matchesMetricGroupFilter(group MetricGroup, filter MetricGroupFilter) bool {
	if filter.MetricName != "" && !strings.EqualFold(group.Name, filter.MetricName) {
		return false
	}
	if filter.ExcludeMetricName != "" && strings.EqualFold(group.Name, filter.ExcludeMetricName) {
		return false
	}
	if filter.DescriptionContains != "" && !strings.Contains(strings.ToLower(group.Description), strings.ToLower(filter.DescriptionContains)) {
		return false
	}
	if filter.ExcludeDescriptionContains != "" && strings.Contains(strings.ToLower(group.Description), strings.ToLower(filter.ExcludeDescriptionContains)) {
		return false
	}
	if filter.Unit != "" && !strings.EqualFold(group.Unit, filter.Unit) {
		return false
	}
	if filter.ExcludeUnit != "" && strings.EqualFold(group.Unit, filter.ExcludeUnit) {
		return false
	}
	if filter.Type != "" && !strings.EqualFold(group.Type, filter.Type) {
		return false
	}
	if filter.ExcludeType != "" && strings.EqualFold(group.Type, filter.ExcludeType) {
		return false
	}
	if filter.ServiceName != "" && !strings.EqualFold(group.ServiceName, filter.ServiceName) {
		return false
	}
	if filter.ExcludeServiceName != "" && strings.EqualFold(group.ServiceName, filter.ExcludeServiceName) {
		return false
	}
	if filter.ScopeName != "" && !strings.EqualFold(group.ScopeName, filter.ScopeName) {
		return false
	}
	if filter.ExcludeScopeName != "" && strings.EqualFold(group.ScopeName, filter.ExcludeScopeName) {
		return false
	}
	if filter.DataPointCount != nil && group.DataPointCount != *filter.DataPointCount {
		return false
	}
	if filter.DataPointCountGT != nil && group.DataPointCount <= *filter.DataPointCountGT {
		return false
	}
	if filter.DataPointCountLT != nil && group.DataPointCount >= *filter.DataPointCountLT {
		return false
	}
	if filter.MinDataPointCount != nil && group.DataPointCount < *filter.MinDataPointCount {
		return false
	}
	if filter.MaxDataPointCount != nil && group.DataPointCount > *filter.MaxDataPointCount {
		return false
	}
	if filter.SeriesCount != nil && group.SeriesCount != *filter.SeriesCount {
		return false
	}
	if filter.SeriesCountGT != nil && group.SeriesCount <= *filter.SeriesCountGT {
		return false
	}
	if filter.SeriesCountLT != nil && group.SeriesCount >= *filter.SeriesCountLT {
		return false
	}
	if filter.MinSeriesCount != nil && group.SeriesCount < *filter.MinSeriesCount {
		return false
	}
	if filter.MaxSeriesCount != nil && group.SeriesCount > *filter.MaxSeriesCount {
		return false
	}
	if filter.Query != "" {
		haystack := strings.ToLower(strings.Join([]string{
			group.Name,
			group.Description,
			group.Unit,
			group.Type,
			group.ServiceName,
			group.ScopeName,
		}, " "))
		if !strings.Contains(haystack, strings.ToLower(filter.Query)) {
			return false
		}
	}
	return true
}

func matchesLogRecordFilter(record LogRecord, filter LogRecordFilter) bool {
	if filter.ServiceName != "" && !strings.EqualFold(record.Resource.ServiceName, filter.ServiceName) {
		return false
	}
	if filter.ExcludeServiceName != "" && strings.EqualFold(record.Resource.ServiceName, filter.ExcludeServiceName) {
		return false
	}
	displaySeverity := displayLogSeverity(record)
	if filter.SeverityDisplay != "" && !strings.EqualFold(displaySeverity, filter.SeverityDisplay) {
		return false
	}
	if filter.ExcludeSeverityDisplay != "" && strings.EqualFold(displaySeverity, filter.ExcludeSeverityDisplay) {
		return false
	}
	if filter.SeverityNumber != nil && record.SeverityNumber != *filter.SeverityNumber {
		return false
	}
	if filter.ExcludeSeverityNumber != nil && record.SeverityNumber == *filter.ExcludeSeverityNumber {
		return false
	}
	if filter.SeverityText != "" && !strings.EqualFold(record.SeverityText, filter.SeverityText) {
		return false
	}
	if filter.ExcludeSeverityText != "" && strings.EqualFold(record.SeverityText, filter.ExcludeSeverityText) {
		return false
	}
	if filter.BodyContains != "" && !strings.Contains(strings.ToLower(record.Body), strings.ToLower(filter.BodyContains)) {
		return false
	}
	if filter.ExcludeBodyContains != "" && strings.Contains(strings.ToLower(record.Body), strings.ToLower(filter.ExcludeBodyContains)) {
		return false
	}
	if filter.TraceID != "" && record.TraceID != filter.TraceID {
		return false
	}
	if filter.ExcludeTraceID != "" && record.TraceID == filter.ExcludeTraceID {
		return false
	}
	if filter.SpanID != "" && record.SpanID != filter.SpanID {
		return false
	}
	if filter.ExcludeSpanID != "" && record.SpanID == filter.ExcludeSpanID {
		return false
	}
	if filter.ScopeName != "" && !strings.EqualFold(record.Scope.Name, filter.ScopeName) {
		return false
	}
	if filter.ExcludeScopeName != "" && strings.EqualFold(record.Scope.Name, filter.ExcludeScopeName) {
		return false
	}
	if filter.TimeFrom != nil && record.Timestamp.Before(*filter.TimeFrom) {
		return false
	}
	if filter.TimeTo != nil && record.Timestamp.After(*filter.TimeTo) {
		return false
	}
	if filter.TimeAfter != nil && !record.Timestamp.After(*filter.TimeAfter) {
		return false
	}
	if filter.TimeBefore != nil && !record.Timestamp.Before(*filter.TimeBefore) {
		return false
	}
	if filter.Query != "" {
		haystack := strings.ToLower(strings.Join([]string{
			displaySeverity,
			record.SeverityText,
			record.Body,
			record.Resource.ServiceName,
			record.TraceID,
			record.SpanID,
			record.Scope.Name,
		}, " "))
		if !strings.Contains(haystack, strings.ToLower(filter.Query)) {
			return false
		}
	}
	return true
}

func makeSpanPreviews(spans []Span, limit int) []SpanPreview {
	n := len(spans)
	if n > limit {
		n = limit
	}
	previews := make([]SpanPreview, n)
	for i := 0; i < n; i++ {
		previews[i] = SpanPreview{
			SpanID:      spans[i].SpanID,
			Name:        spans[i].Name,
			Kind:        spans[i].Kind,
			DurationMs:  spans[i].DurationMs,
			StatusCode:  spans[i].Status.Code,
			ServiceName: spans[i].Resource.ServiceName,
		}
	}
	return previews
}

func clearTraceSummaryFieldFilter(filter TraceSummaryFilter, field string) TraceSummaryFilter {
	switch field {
	case "traceId":
		filter.TraceID = ""
		filter.ExcludeTraceID = ""
	case "rootSpanName":
		filter.RootSpanName = ""
		filter.ExcludeRootSpanName = ""
	case "serviceName":
		filter.ServiceName = ""
		filter.ExcludeServiceName = ""
	case "status":
		filter.Status = ""
		filter.ExcludeStatus = ""
	}
	return filter
}

func clearMetricGroupFieldFilter(filter MetricGroupFilter, field string) MetricGroupFilter {
	switch field {
	case "metricName":
		filter.MetricName = ""
		filter.ExcludeMetricName = ""
	case "descriptionContains":
		filter.DescriptionContains = ""
		filter.ExcludeDescriptionContains = ""
	case "unit":
		filter.Unit = ""
		filter.ExcludeUnit = ""
	case "type":
		filter.Type = ""
		filter.ExcludeType = ""
	case "serviceName":
		filter.ServiceName = ""
		filter.ExcludeServiceName = ""
	case "scopeName":
		filter.ScopeName = ""
		filter.ExcludeScopeName = ""
	}
	return filter
}

func clearLogRecordFieldFilter(filter LogRecordFilter, field string) LogRecordFilter {
	switch field {
	case "serviceName":
		filter.ServiceName = ""
		filter.ExcludeServiceName = ""
	case "severityDisplay":
		filter.SeverityDisplay = ""
		filter.ExcludeSeverityDisplay = ""
	case "severityNumber":
		filter.SeverityNumber = nil
		filter.ExcludeSeverityNumber = nil
	case "severityText":
		filter.SeverityText = ""
		filter.ExcludeSeverityText = ""
	case "bodyContains":
		filter.BodyContains = ""
		filter.ExcludeBodyContains = ""
	case "traceId":
		filter.TraceID = ""
		filter.ExcludeTraceID = ""
	case "spanId":
		filter.SpanID = ""
		filter.ExcludeSpanID = ""
	case "scopeName":
		filter.ScopeName = ""
		filter.ExcludeScopeName = ""
	}
	return filter
}

func displayLogSeverity(record LogRecord) string {
	if text := strings.TrimSpace(record.SeverityText); text != "" {
		return text
	}
	return logSeverityNumberLabel(record.SeverityNumber)
}

func logSeverityNumberLabel(severityNumber int32) string {
	switch severityNumber {
	case 1:
		return "TRACE"
	case 2:
		return "TRACE2"
	case 3:
		return "TRACE3"
	case 4:
		return "TRACE4"
	case 5:
		return "DEBUG"
	case 6:
		return "DEBUG2"
	case 7:
		return "DEBUG3"
	case 8:
		return "DEBUG4"
	case 9:
		return "INFO"
	case 10:
		return "INFO2"
	case 11:
		return "INFO3"
	case 12:
		return "INFO4"
	case 13:
		return "WARN"
	case 14:
		return "WARN2"
	case 15:
		return "WARN3"
	case 16:
		return "WARN4"
	case 17:
		return "ERROR"
	case 18:
		return "ERROR2"
	case 19:
		return "ERROR3"
	case 20:
		return "ERROR4"
	case 21:
		return "FATAL"
	case 22:
		return "FATAL2"
	case 23:
		return "FATAL3"
	case 24:
		return "FATAL4"
	default:
		return ""
	}
}

func collectSuggestionValues[T any](limit int, prefix string, values []T, project func(T) string) []string {
	if limit <= 0 {
		limit = 20
	}
	normalizedPrefix := strings.ToLower(strings.TrimSpace(prefix))
	seen := make(map[string]struct{}, len(values))
	results := make([]string, 0, minInt(len(values), limit))
	for _, value := range values {
		candidate := strings.TrimSpace(project(value))
		if candidate == "" {
			continue
		}
		if normalizedPrefix != "" && !strings.HasPrefix(strings.ToLower(candidate), normalizedPrefix) {
			continue
		}
		key := strings.ToLower(candidate)
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		results = append(results, candidate)
	}
	sort.Slice(results, func(i, j int) bool {
		return strings.ToLower(results[i]) < strings.ToLower(results[j])
	})
	if len(results) > limit {
		return results[:limit]
	}
	return results
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
