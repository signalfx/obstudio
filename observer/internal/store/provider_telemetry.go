package store

import (
	"sort"
	"strings"
	"time"
)

// ProviderUsageLogKind identifies provider-native records that carry
// authoritative request token accounting.
type ProviderUsageLogKind string

// ProviderUsageMetricKind identifies provider-native metrics that carry
// authoritative token accounting.
type ProviderUsageMetricKind string

// ProviderRepositoryCorrelation associates a provider task or session with
// the repository in which it ran. It contains no prompt or tool content.
type ProviderRepositoryCorrelation struct {
	Provider       string    `json:"provider"`
	ConversationID string    `json:"conversationId,omitempty"`
	TaskID         string    `json:"taskId,omitempty"`
	RepositoryName string    `json:"repositoryName"`
	RepositoryPath string    `json:"repositoryPath,omitempty"`
	WorkspacePath  string    `json:"workspacePath,omitempty"`
	Mode           string    `json:"mode"`
	Source         string    `json:"source"`
	ObservedAt     time.Time `json:"observedAt"`
}

const (
	ProviderUsageLogUnknown ProviderUsageLogKind = ""
	ProviderUsageLogCodex   ProviderUsageLogKind = "codex"
	ProviderUsageLogClaude  ProviderUsageLogKind = "claude"

	ProviderUsageMetricUnknown ProviderUsageMetricKind = ""
	ProviderUsageMetricClaude  ProviderUsageMetricKind = "claude"
)

type providerTaskTrace struct {
	taskKey            string
	traceID            string
	boundarySpanID     string
	completedAt        time.Time
	spans              []Span
	retentionTruncated bool
}

// ClassifyProviderUsageLog recognizes the raw Codex and Claude events retained
// for exact token accounting. Token fields are interpreted by the MCP layer.
func ClassifyProviderUsageLog(record LogRecord) ProviderUsageLogKind {
	eventName := normalizedProviderTelemetryString(record.Attributes["event.name"])
	eventKind := normalizedProviderTelemetryString(record.Attributes["event.kind"])
	body := strings.ToLower(strings.TrimSpace(record.Body))
	if (eventName == "codex.sse_event" || body == "codex.sse_event") && eventKind == "response.completed" {
		return ProviderUsageLogCodex
	}
	if eventName != "api_request" && eventName != "claude_code.api_request" && body != "claude_code.api_request" {
		return ProviderUsageLogUnknown
	}
	identity := strings.ToLower(strings.Join([]string{
		record.Resource.ServiceName,
		record.Scope.Name,
		providerTelemetryAttributeString(record.Attributes, "model"),
		eventName,
		body,
	}, " "))
	if strings.Contains(identity, "claude") {
		return ProviderUsageLogClaude
	}
	return ProviderUsageLogUnknown
}

// ClassifyProviderUsageMetric recognizes raw provider token metrics retained
// for exact accounting. Metric values and token-type semantics are interpreted
// by the MCP layer.
func ClassifyProviderUsageMetric(point MetricDataPoint) ProviderUsageMetricKind {
	if strings.EqualFold(strings.TrimSpace(point.Name), "claude_code.token.usage") {
		return ProviderUsageMetricClaude
	}
	return ProviderUsageMetricUnknown
}

// ProviderRepositoryCorrelationFromLog recognizes Obstudio's correlation-only
// lifecycle event. The raw log remains in the generic log ring.
func ProviderRepositoryCorrelationFromLog(record LogRecord) (ProviderRepositoryCorrelation, bool) {
	eventName := normalizedProviderTelemetryString(record.Attributes["event.name"])
	body := strings.ToLower(strings.TrimSpace(record.Body))
	if eventName != "obstudio.repository_correlation" && body != "obstudio.repository_correlation" {
		return ProviderRepositoryCorrelation{}, false
	}

	provider := normalizedProviderTelemetryString(record.Attributes["gen_ai.provider.name"])
	switch provider {
	case "openai", "codex":
		provider = "codex"
	case "anthropic", "claude", "claude-code", "claude_code":
		provider = "claude"
	default:
		return ProviderRepositoryCorrelation{}, false
	}
	mode := normalizedProviderTelemetryString(record.Attributes["obstudio.repository_correlation.mode"])
	if mode != "name" && mode != "path" {
		return ProviderRepositoryCorrelation{}, false
	}
	repositoryName := providerTelemetryAttributeString(record.Attributes, "repository.name")
	if repositoryName == "" {
		return ProviderRepositoryCorrelation{}, false
	}
	correlation := ProviderRepositoryCorrelation{
		Provider:       provider,
		ConversationID: providerTelemetryAttributeString(record.Attributes, "conversation.id"),
		TaskID:         providerTelemetryAttributeString(record.Attributes, "task.id"),
		RepositoryName: repositoryName,
		Mode:           mode,
		Source:         providerTelemetryAttributeString(record.Attributes, "obstudio.repository_correlation.source"),
		ObservedAt:     LogEventTimestamp(record),
	}
	if correlation.ConversationID == "" {
		correlation.ConversationID = providerTelemetryAttributeString(record.Attributes, "session.id")
	}
	if correlation.TaskID == "" {
		correlation.TaskID = providerTelemetryAttributeString(record.Attributes, "turn.id")
	}
	if mode == "path" {
		correlation.RepositoryPath = providerTelemetryAttributeString(record.Attributes, "repository.path")
		correlation.WorkspacePath = providerTelemetryAttributeString(record.Attributes, "workspace.path")
		if correlation.RepositoryPath == "" && correlation.WorkspacePath == "" {
			return ProviderRepositoryCorrelation{}, false
		}
	}
	if correlation.ConversationID == "" && correlation.TaskID == "" {
		return ProviderRepositoryCorrelation{}, false
	}
	if correlation.Source == "" {
		correlation.Source = "provider_lifecycle_hook"
	}
	return correlation, true
}

func retainedProviderTraceIDs(spans []Span) map[string]struct{} {
	traceIDs := make(map[string]struct{})
	for _, span := range spans {
		if span.TraceID != "" && isProviderAgentSpan(span) {
			traceIDs[span.TraceID] = struct{}{}
		}
	}
	return traceIDs
}

func isProviderAgentSpan(span Span) bool {
	name := strings.ToLower(strings.TrimSpace(span.Name))
	if ProviderTaskBoundaryProvider(span) != "" {
		return true
	}
	identity := strings.ToLower(strings.Join([]string{
		span.Resource.ServiceName,
		span.Scope.Name,
		providerTelemetryAttributeString(span.Attributes, "gen_ai.provider.name"),
		providerTelemetryAttributeString(span.Attributes, "model"),
	}, " "))
	if strings.Contains(identity, "claude") {
		return strings.HasPrefix(name, "claude_code.") ||
			providerTelemetryAttributeString(span.Attributes, "prompt.id") != "" ||
			providerTelemetryAttributeString(span.Attributes, "session.id") != ""
	}
	if strings.Contains(identity, "codex") || strings.Contains(identity, "openai") {
		return name == "session_task" || strings.HasPrefix(name, "session_task.") ||
			providerTelemetryAttributeString(span.Attributes, "turn.id") != "" ||
			providerTelemetryAttributeString(span.Attributes, "thread.id") != "" ||
			providerTelemetryAttributeString(span.Attributes, "conversation.id") != ""
	}
	return false
}

func retainedProviderSpans(spans []Span) []Span {
	traceIDs := retainedProviderTraceIDs(spans)
	retained := make([]Span, 0)
	for _, span := range spans {
		if _, ok := traceIDs[span.TraceID]; !ok {
			continue
		}
		span.ownerConnID = ""
		retained = append(retained, span)
	}
	return retained
}

func retainedProviderLogs(logs []LogRecord) []LogRecord {
	retained := make([]LogRecord, 0)
	for _, record := range logs {
		if ClassifyProviderUsageLog(record) == ProviderUsageLogUnknown {
			continue
		}
		record.ownerConnID = ""
		retained = append(retained, record)
	}
	return retained
}

func retainedProviderUsageMetrics(metrics []MetricDataPoint) []MetricDataPoint {
	retained := make([]MetricDataPoint, 0)
	for _, point := range metrics {
		if ClassifyProviderUsageMetric(point) == ProviderUsageMetricUnknown {
			continue
		}
		point.ownerConnID = ""
		retained = append(retained, point)
	}
	return retained
}

func providerUsageMetricPointTime(point MetricDataPoint) time.Time {
	if !point.Timestamp.IsZero() {
		return point.Timestamp
	}
	return point.StartTime
}

func providerUsageLogRecordTime(record LogRecord) time.Time {
	return LogEventTimestamp(record)
}

// captureCompletedProviderTasks stores one compact live-telemetry snapshot per
// completed provider task before the generic span ring can overwrite it.
// Caller must hold s.mu.
func (s *Store) captureCompletedProviderTasks(incoming []Span) {
	completedTasks := make(map[string]Span)
	completedTraceIDs := make(map[string]struct{})
	incomingTraceIDs := make(map[string]struct{})
	previousTasks := make(map[string]providerTaskTrace)
	for _, span := range incoming {
		if span.TraceID != "" {
			incomingTraceIDs[span.TraceID] = struct{}{}
		}
		if isProviderTaskBoundarySpan(span) && span.TraceID != "" && span.SpanID != "" {
			completedTasks[providerTaskStorageKey(span.TraceID, span.SpanID)] = span
			completedTraceIDs[span.TraceID] = struct{}{}
		}
	}
	retainedTaskSnapshot := s.providerTasks.snapshot()
	for _, task := range retainedTaskSnapshot {
		previousTasks[task.taskKey] = task
		if _, hasLateSpan := incomingTraceIDs[task.traceID]; !hasLateSpan {
			continue
		}
		for _, span := range task.spans {
			if span.SpanID != task.boundarySpanID && !isProviderTaskBoundarySpan(span) {
				continue
			}
			completedTasks[task.taskKey] = span
			completedTraceIDs[task.traceID] = struct{}{}
			break
		}
	}
	if len(completedTasks) == 0 {
		return
	}

	spansByTraceID := make(map[string][]Span, len(completedTraceIDs))
	spanIndexes := make(map[string]map[string]int, len(completedTraceIDs))
	addSpan := func(span Span, replace bool) {
		if _, wanted := completedTraceIDs[span.TraceID]; !wanted {
			return
		}
		indexes := spanIndexes[span.TraceID]
		if indexes == nil {
			indexes = make(map[string]int)
			spanIndexes[span.TraceID] = indexes
		}
		if index, exists := indexes[span.SpanID]; exists {
			if replace {
				spansByTraceID[span.TraceID][index] = span
			}
			return
		}
		indexes[span.SpanID] = len(spansByTraceID[span.TraceID])
		spansByTraceID[span.TraceID] = append(spansByTraceID[span.TraceID], span)
	}
	// Incoming spans win when a provider re-exports a corrected/final version
	// with the same span ID. Merge them before the generic ring snapshot, which
	// can still contain the earlier copy.
	for _, span := range incoming {
		addSpan(span, true)
	}
	// A single oversized OTLP batch can overwrite its own early spans in the
	// generic ring, so merge both the incoming batch and retained ring.
	for _, span := range s.spans.snapshot() {
		addSpan(span, false)
	}
	// Retained tasks preserve earlier boundaries in a long-lived provider trace
	// after the generic span ring has evicted them.
	for _, task := range retainedTaskSnapshot {
		for _, span := range task.spans {
			addSpan(span, false)
		}
	}

	taskKeys := make([]string, 0, len(completedTasks))
	for taskKey := range completedTasks {
		taskKeys = append(taskKeys, taskKey)
	}
	sort.Slice(taskKeys, func(i, j int) bool {
		left := completedTasks[taskKeys[i]].EndTime
		right := completedTasks[taskKeys[j]].EndTime
		if left.Equal(right) {
			return taskKeys[i] < taskKeys[j]
		}
		return left.Before(right)
	})
	compactByTraceID := make(map[string]map[string][]Span, len(spansByTraceID))
	for traceID, spans := range spansByTraceID {
		compactByTraceID[traceID] = compactProviderTaskSpansByBoundary(spans)
	}
	newTasks := make([]providerTaskTrace, 0, len(taskKeys))
	for _, taskKey := range taskKeys {
		boundary := completedTasks[taskKey]
		compact := compactByTraceID[boundary.TraceID][boundary.SpanID]
		if len(compact) == 0 {
			continue
		}
		newTasks = append(newTasks, providerTaskTrace{
			taskKey:            taskKey,
			traceID:            boundary.TraceID,
			boundarySpanID:     boundary.SpanID,
			completedAt:        boundary.EndTime,
			spans:              compact,
			retentionTruncated: previousTasks[taskKey].retentionTruncated,
		})
	}
	if len(newTasks) == 0 {
		return
	}

	// Upsert by task boundary so provider retransmissions do not consume bounded
	// retention slots or evict unrelated completed tasks.
	replacedTaskKeys := make(map[string]struct{}, len(newTasks))
	for _, task := range newTasks {
		replacedTaskKeys[task.taskKey] = struct{}{}
	}
	retained := make([]providerTaskTrace, 0, s.providerTasks.size())
	for _, task := range retainedTaskSnapshot {
		if _, replaced := replacedTaskKeys[task.taskKey]; replaced {
			continue
		}
		retained = append(retained, task)
	}
	retained = append(retained, newTasks...)
	sort.SliceStable(retained, func(i, j int) bool {
		if retained[i].completedAt.Equal(retained[j].completedAt) {
			return retained[i].taskKey < retained[j].taskKey
		}
		return retained[i].completedAt.Before(retained[j].completedAt)
	})
	retained, truncated := boundProviderTaskRetention(
		retained,
		s.providerTasks.cap,
		DefaultProviderTaskSpanCap,
	)
	if truncated {
		s.providerTaskHistoryEvicted = true
	}
	s.providerTasks.clear()
	s.providerTasks.push(retained)
}

func boundProviderTaskRetention(tasks []providerTaskTrace, taskLimit, spanLimit int) ([]providerTaskTrace, bool) {
	truncated := false
	if taskLimit <= 0 || spanLimit <= 0 {
		return nil, len(tasks) > 0
	}
	if len(tasks) > taskLimit {
		tasks = tasks[len(tasks)-taskLimit:]
		truncated = true
	}

	remaining := spanLimit
	keptReversed := make([]providerTaskTrace, 0, len(tasks))
	for index := len(tasks) - 1; index >= 0; index-- {
		task := tasks[index]
		if remaining == 0 {
			truncated = true
			continue
		}
		if len(task.spans) > remaining {
			task.spans = truncateProviderTaskSpans(task.spans, task.boundarySpanID, remaining)
			task.retentionTruncated = true
			truncated = true
		}
		remaining -= len(task.spans)
		keptReversed = append(keptReversed, task)
	}
	kept := make([]providerTaskTrace, len(keptReversed))
	for index := range keptReversed {
		kept[len(keptReversed)-1-index] = keptReversed[index]
	}
	return kept, truncated
}

func truncateProviderTaskSpans(spans []Span, boundarySpanID string, limit int) []Span {
	if limit <= 0 {
		return nil
	}
	if len(spans) <= limit {
		return spans
	}
	truncated := make([]Span, 0, limit)
	for _, span := range spans {
		if span.SpanID == boundarySpanID {
			truncated = append(truncated, span)
			break
		}
	}
	for _, span := range spans {
		if len(truncated) == limit {
			break
		}
		if span.SpanID == boundarySpanID {
			continue
		}
		truncated = append(truncated, span)
	}
	return truncated
}

func compactProviderTaskSpansByBoundary(spans []Span) map[string][]Span {
	if len(spans) == 0 {
		return nil
	}
	byID := make(map[string]Span, len(spans))
	for _, span := range spans {
		byID[span.SpanID] = span
	}
	boundaryAssignments := providerTaskBoundaryAssignments(byID)

	keptBoundaryBySpanID := make(map[string]string)
	for _, span := range spans {
		boundarySpanID := boundaryAssignments[span.SpanID]
		if !isProviderAccountingSpan(span) || boundarySpanID == "" {
			continue
		}
		for current := span; current.SpanID != ""; {
			if _, seen := keptBoundaryBySpanID[current.SpanID]; seen {
				break
			}
			keptBoundaryBySpanID[current.SpanID] = boundarySpanID
			if current.SpanID == boundarySpanID {
				break
			}
			parent, ok := byID[current.ParentSpanID]
			if !ok {
				break
			}
			current = parent
		}
	}

	compactByBoundary := make(map[string][]Span)
	for _, span := range spans {
		boundarySpanID := keptBoundaryBySpanID[span.SpanID]
		if boundarySpanID == "" {
			continue
		}
		span.ownerConnID = ""
		compactByBoundary[boundarySpanID] = append(compactByBoundary[boundarySpanID], span)
	}
	return compactByBoundary
}

func providerTaskBoundaryAssignments(spansByID map[string]Span) map[string]string {
	resolved := make(map[string]string, len(spansByID))
	state := make(map[string]uint8, len(spansByID))
	for spanID, span := range spansByID {
		if spanID != "" && isProviderTaskBoundarySpan(span) {
			resolved[spanID] = spanID
			state[spanID] = 2
		}
	}

	for startID := range spansByID {
		if startID == "" || state[startID] == 2 {
			continue
		}
		path := make([]string, 0)
		currentID := startID
		nearestID := ""
		for currentID != "" {
			if state[currentID] == 2 {
				nearestID = resolved[currentID]
				break
			}
			if state[currentID] == 1 {
				break
			}
			span, retained := spansByID[currentID]
			if !retained {
				break
			}
			state[currentID] = 1
			path = append(path, currentID)
			currentID = span.ParentSpanID
		}
		for _, spanID := range path {
			resolved[spanID] = nearestID
			state[spanID] = 2
		}
	}
	return resolved
}

func providerTaskStorageKey(traceID, boundarySpanID string) string {
	return traceID + "\x00" + boundarySpanID
}

func isProviderAccountingSpan(span Span) bool {
	if isProviderTaskBoundarySpan(span) || IsGenAIEvaluationOnlySpan(span) {
		return true
	}
	if providerTelemetryAttributeString(span.Attributes, "cwd") != "" ||
		providerTelemetryAttributeString(span.Attributes, "working_directory") != "" ||
		providerTelemetryAttributeString(span.Attributes, "workspace.path") != "" {
		return true
	}
	name := strings.ToLower(strings.TrimSpace(span.Name))
	if strings.HasPrefix(name, "claude_code.") && (strings.Contains(name, "llm") || strings.Contains(name, "api_request")) {
		return true
	}
	if isProviderAgentSpan(span) && ClassifyGenAISpan(span) == GenAISpanLLM {
		return true
	}
	for key := range span.Attributes {
		if strings.Contains(strings.ToLower(key), "token") {
			return true
		}
	}
	return false
}

func isProviderTaskBoundarySpan(span Span) bool {
	return ProviderTaskBoundaryProvider(span) != ""
}

// ProviderTaskBoundaryProvider recognizes completed native provider task
// boundaries without trusting a generic span name by itself.
func ProviderTaskBoundaryProvider(span Span) string {
	name := strings.ToLower(strings.TrimSpace(span.Name))
	identity := strings.ToLower(strings.Join([]string{
		span.Resource.ServiceName,
		span.Scope.Name,
		providerTelemetryAttributeString(span.Attributes, "gen_ai.provider.name"),
		providerTelemetryAttributeString(span.Attributes, "gen_ai.system"),
		providerTelemetryAttributeString(span.Attributes, "model"),
	}, " "))
	switch name {
	case "session_task", "session_task.turn":
		if providerTelemetryAttributeString(span.Attributes, "turn.id") == "" &&
			providerTelemetryAttributeString(span.Attributes, "turn_id") == "" {
			return ""
		}
		if strings.Contains(identity, "codex") || strings.Contains(identity, "openai") {
			return "codex"
		}
	case "claude_code.interaction":
		if providerTelemetryAttributeString(span.Attributes, "prompt.id") == "" &&
			providerTelemetryAttributeString(span.Attributes, "prompt_id") == "" {
			return ""
		}
		if strings.Contains(identity, "claude") || strings.Contains(identity, "anthropic") {
			return "claude"
		}
	}
	return ""
}

func normalizedProviderTelemetryString(value any) string {
	text, ok := value.(string)
	if !ok {
		return ""
	}
	return strings.ToLower(strings.TrimSpace(text))
}

func providerTelemetryAttributeString(attributes map[string]any, key string) string {
	value, ok := attributes[key].(string)
	if !ok {
		return ""
	}
	return strings.TrimSpace(value)
}
