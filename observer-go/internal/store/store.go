package store

import (
	"encoding/json"
	"sort"
	"strings"
	"sync"
	"time"
)

type Signal string

const (
	SignalTraces  Signal = "traces"
	SignalMetrics Signal = "metrics"
	SignalLogs    Signal = "logs"
)

type Resource struct {
	ServiceName string         `json:"serviceName,omitempty"`
	Attributes  map[string]any `json:"attributes"`
	SchemaURL   string         `json:"schemaUrl,omitempty"`
}

type Scope struct {
	Name      string `json:"name"`
	Version   string `json:"version,omitempty"`
	SchemaURL string `json:"schemaUrl,omitempty"`
}

type SpanStatus struct {
	Code    string `json:"code"`
	Message string `json:"message,omitempty"`
}

type SpanEvent struct {
	Name       string         `json:"name"`
	Timestamp  time.Time      `json:"timeUnixNano"`
	Attributes map[string]any `json:"attributes"`
}

type SpanLink struct {
	TraceID    string         `json:"traceId"`
	SpanID     string         `json:"spanId"`
	Attributes map[string]any `json:"attributes"`
}

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
}

type QuantileValue struct {
	Quantile float64 `json:"quantile"`
	Value    float64 `json:"value"`
}

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
}

type LogRecord struct {
	Timestamp      time.Time      `json:"timeUnixNano"`
	SeverityNumber int32          `json:"severityNumber,omitempty"`
	SeverityText   string         `json:"severityText,omitempty"`
	Body           string         `json:"body"`
	Attributes     map[string]any `json:"attributes"`
	TraceID        string         `json:"traceId,omitempty"`
	SpanID         string         `json:"spanId,omitempty"`
	Resource       Resource       `json:"resource"`
	Scope          Scope          `json:"scope"`
}

type TraceFilter struct {
	ServiceName      string
	SpanName         string
	Status           string
	TraceIDPrefix    string
	Limit            int
	SpanPreviewCount int
}

type MetricFilter struct {
	MetricName        string
	ServiceName       string
	ScopeName         string
	Type              string
	ResourceAttribute string
	Limit             int
	DataPointLimit    int
}

type LogFilter struct {
	ServiceName  string
	SeverityText string
	Body         string
	TraceID      string
	Limit        int
}

type TraceSummary struct {
	TraceID      string        `json:"traceId"`
	RootSpanName string        `json:"rootSpanName"`
	ServiceName  string        `json:"serviceName,omitempty"`
	SpanCount    int           `json:"spanCount"`
	DurationMs   float64       `json:"durationMs,omitempty"`
	Status       string        `json:"status"`
	Spans        []SpanPreview `json:"spans,omitempty"`
}

type SpanPreview struct {
	SpanID     string  `json:"spanId"`
	Name       string  `json:"name"`
	Kind       string  `json:"kind"`
	DurationMs float64 `json:"durationMs"`
	StatusCode string  `json:"statusCode"`
}

type TraceDetail struct {
	TraceID      string  `json:"traceId"`
	RootSpanName string  `json:"rootSpanName"`
	ServiceName  string  `json:"serviceName,omitempty"`
	SpanCount    int     `json:"spanCount"`
	DurationMs   float64 `json:"durationMs,omitempty"`
	Status       string  `json:"status"`
	Spans        []Span  `json:"spans"`
}

type MetricGroup struct {
	Name           string            `json:"name"`
	Description    string            `json:"description,omitempty"`
	Unit           string            `json:"unit,omitempty"`
	Type           string            `json:"type"`
	ServiceName    string            `json:"serviceName,omitempty"`
	ScopeName      string            `json:"scopeName,omitempty"`
	DataPointCount int               `json:"dataPointCount"`
	DataPoints     []MetricDataPoint `json:"dataPoints,omitempty"`
}

type Stats struct {
	SpanCount    int      `json:"spanCount"`
	MetricCount  int      `json:"metricCount"`
	LogCount     int      `json:"logCount"`
	TraceCount   int      `json:"traceCount"`
	ServiceNames []string `json:"serviceNames"`
}

type Store struct {
	mu      sync.RWMutex
	spans   []Span
	metrics []MetricDataPoint
	logs    []LogRecord

	subMu       sync.Mutex
	subscribers map[int]chan Signal
	nextSubID   int
}

func New() *Store {
	return &Store{
		subscribers: make(map[int]chan Signal),
	}
}

func (s *Store) AddSpans(spans []Span) {
	s.mu.Lock()
	s.spans = append(s.spans, spans...)
	s.mu.Unlock()
	s.notify(SignalTraces)
}

func (s *Store) AddMetrics(metrics []MetricDataPoint) {
	s.mu.Lock()
	s.metrics = append(s.metrics, metrics...)
	s.mu.Unlock()
	s.notify(SignalMetrics)
}

func (s *Store) AddLogs(logs []LogRecord) {
	s.mu.Lock()
	s.logs = append(s.logs, logs...)
	s.mu.Unlock()
	s.notify(SignalLogs)
}

func (s *Store) QueryTraces(f TraceFilter) []TraceSummary {
	if f.Limit <= 0 {
		f.Limit = 20
	}
	if f.SpanPreviewCount <= 0 {
		f.SpanPreviewCount = 5
	}

	s.mu.RLock()
	grouped := groupSpansByTrace(s.spans)
	s.mu.RUnlock()

	var results []TraceSummary
	for traceID, spans := range grouped {
		if f.TraceIDPrefix != "" && !strings.HasPrefix(traceID, strings.ToLower(f.TraceIDPrefix)) {
			continue
		}

		root := findRootSpan(spans)
		svcName := root.Resource.ServiceName
		status := computeTraceStatus(spans)

		if f.ServiceName != "" && !strings.EqualFold(svcName, f.ServiceName) {
			continue
		}
		if f.Status != "" && status != f.Status {
			continue
		}
		if f.SpanName != "" {
			if !anySpanNameMatches(spans, f.SpanName) {
				continue
			}
		}

		dur := computeTraceDuration(spans)
		previews := makeSpanPreviews(spans, f.SpanPreviewCount)

		results = append(results, TraceSummary{
			TraceID:      traceID,
			RootSpanName: root.Name,
			ServiceName:  svcName,
			SpanCount:    len(spans),
			DurationMs:   dur,
			Status:       status,
			Spans:        previews,
		})
	}

	sort.Slice(results, func(i, j int) bool {
		return results[i].TraceID > results[j].TraceID
	})

	if len(results) > f.Limit {
		results = results[:f.Limit]
	}
	return results
}

func (s *Store) GetTrace(traceID string, eventLimit int) *TraceDetail {
	if eventLimit <= 0 {
		eventLimit = 12
	}

	s.mu.RLock()
	grouped := groupSpansByTrace(s.spans)
	s.mu.RUnlock()

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

func (s *Store) QueryMetrics(f MetricFilter) []MetricGroup {
	if f.Limit <= 0 {
		f.Limit = 20
	}
	if f.DataPointLimit <= 0 {
		f.DataPointLimit = 3
	}

	s.mu.RLock()
	points := make([]MetricDataPoint, len(s.metrics))
	copy(points, s.metrics)
	s.mu.RUnlock()

	type groupKey struct{ name, svc, scope string }
	groups := make(map[groupKey]*MetricGroup)
	groupOrder := make([]groupKey, 0)

	for _, dp := range points {
		if f.MetricName != "" && !strings.EqualFold(dp.Name, f.MetricName) {
			continue
		}
		if f.ServiceName != "" && !strings.EqualFold(dp.Resource.ServiceName, f.ServiceName) {
			continue
		}
		if f.ScopeName != "" && !strings.EqualFold(dp.Scope.Name, f.ScopeName) {
			continue
		}
		if f.Type != "" && dp.Type != normalizeMetricType(f.Type) {
			continue
		}
		if f.ResourceAttribute != "" {
			serialized, _ := json.Marshal(dp.Resource.Attributes)
			if !strings.Contains(string(serialized), f.ResourceAttribute) {
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
		if len(g.DataPoints) < f.DataPointLimit {
			g.DataPoints = append(g.DataPoints, dp)
		}
	}

	var results []MetricGroup
	for _, key := range groupOrder {
		results = append(results, *groups[key])
	}
	if len(results) > f.Limit {
		results = results[:f.Limit]
	}
	return results
}

func (s *Store) QueryLogs(f LogFilter) []LogRecord {
	if f.Limit <= 0 {
		f.Limit = 50
	}

	s.mu.RLock()
	all := make([]LogRecord, len(s.logs))
	copy(all, s.logs)
	s.mu.RUnlock()

	var results []LogRecord
	for i := len(all) - 1; i >= 0 && len(results) < f.Limit; i-- {
		lr := all[i]
		if f.ServiceName != "" && !strings.EqualFold(lr.Resource.ServiceName, f.ServiceName) {
			continue
		}
		if f.SeverityText != "" && !strings.EqualFold(lr.SeverityText, f.SeverityText) {
			continue
		}
		if f.Body != "" && !strings.Contains(strings.ToLower(lr.Body), strings.ToLower(f.Body)) {
			continue
		}
		if f.TraceID != "" && lr.TraceID != f.TraceID {
			continue
		}
		results = append(results, lr)
	}
	return results
}

func (s *Store) Stats() Stats {
	s.mu.RLock()
	defer s.mu.RUnlock()

	traceIDs := make(map[string]struct{})
	svcSet := make(map[string]struct{})

	for _, sp := range s.spans {
		traceIDs[sp.TraceID] = struct{}{}
		if sp.Resource.ServiceName != "" {
			svcSet[sp.Resource.ServiceName] = struct{}{}
		}
	}
	for _, m := range s.metrics {
		if m.Resource.ServiceName != "" {
			svcSet[m.Resource.ServiceName] = struct{}{}
		}
	}
	for _, l := range s.logs {
		if l.Resource.ServiceName != "" {
			svcSet[l.Resource.ServiceName] = struct{}{}
		}
	}

	svcs := make([]string, 0, len(svcSet))
	for svc := range svcSet {
		svcs = append(svcs, svc)
	}
	sort.Strings(svcs)

	return Stats{
		SpanCount:    len(s.spans),
		MetricCount:  len(s.metrics),
		LogCount:     len(s.logs),
		TraceCount:   len(traceIDs),
		ServiceNames: svcs,
	}
}

func (s *Store) Subscribe() (int, <-chan Signal) {
	ch := make(chan Signal, 8)
	s.subMu.Lock()
	id := s.nextSubID
	s.nextSubID++
	s.subscribers[id] = ch
	s.subMu.Unlock()
	return id, ch
}

func (s *Store) Unsubscribe(id int) {
	s.subMu.Lock()
	delete(s.subscribers, id)
	s.subMu.Unlock()
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

func groupSpansByTrace(spans []Span) map[string][]Span {
	groups := make(map[string][]Span)
	for _, sp := range spans {
		groups[sp.TraceID] = append(groups[sp.TraceID], sp)
	}
	return groups
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
	return float64(maxEnd.Sub(minStart).Milliseconds())
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
