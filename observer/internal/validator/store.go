package validator

import (
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

type Store struct {
	mu       sync.RWMutex
	status   RuntimeStatus
	message  string
	updated  time.Time
	entities map[string]Entity
	stats    weaverStats

	lastError          string
	hasResult          bool
	stale              bool
	activeRunID        string
	resultRunID        string
	lastRunStartedAt   time.Time
	lastRunCompletedAt time.Time
	lastTelemetryAt    time.Time

	subMu       sync.Mutex
	subscribers map[int]chan Signal
	nextSubID   int
}

func NewStore() *Store {
	return &Store{
		status:      StatusDisabled,
		message:     "Validator unavailable",
		entities:    make(map[string]Entity),
		subscribers: make(map[int]chan Signal),
	}
}

func (s *Store) SetRuntimeStatus(status RuntimeStatus, message string) {
	s.mu.Lock()
	s.status = status
	s.message = message
	if status == StatusDisabled {
		s.lastError = ""
		s.hasResult = false
		s.stale = false
		s.activeRunID = ""
		s.resultRunID = ""
		s.lastRunStartedAt = time.Time{}
		s.lastRunCompletedAt = time.Time{}
		s.lastTelemetryAt = time.Time{}
		s.entities = make(map[string]Entity)
		s.stats = weaverStats{}
	}
	s.updated = time.Now()
	s.mu.Unlock()
	s.notify(SignalValidation)
}

func (s *Store) SetStats(stats weaverStats) {
	s.mu.Lock()
	s.stats = stats
	s.hasResult = true
	s.updated = time.Now()
	s.mu.Unlock()
	s.notify(SignalValidation)
}

func (s *Store) UpsertEntity(entity Entity) {
	s.mu.Lock()
	s.entities[entity.Key] = entity
	s.hasResult = true
	s.updated = time.Now()
	s.mu.Unlock()
	s.notify(SignalValidation)
}

func (s *Store) StartRun(runID string, startedAt time.Time) Summary {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.status == StatusDisabled {
		return s.summaryLocked()
	}
	if s.status == StatusRunning && s.activeRunID != "" {
		return s.summaryLocked()
	}

	s.status = StatusRunning
	s.message = "Validation running"
	s.lastError = ""
	s.activeRunID = runID
	s.lastRunStartedAt = startedAt
	s.updated = startedAt

	summary := s.summaryLocked()
	go s.notify(SignalValidation)
	return summary
}

func (s *Store) CompleteRun(runID string, entities map[string]Entity, stats weaverStats, completedAt time.Time) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.activeRunID != runID {
		return false
	}

	if entities == nil {
		entities = make(map[string]Entity)
	}

	s.entities = entities
	s.stats = stats
	s.hasResult = true
	s.stale = !s.lastTelemetryAt.IsZero() && s.lastTelemetryAt.After(s.lastRunStartedAt)
	s.status = StatusReady
	if s.stale {
		s.message = "Validation complete, but new telemetry has arrived"
	} else {
		s.message = "Validation complete"
	}
	s.lastError = ""
	s.resultRunID = runID
	s.activeRunID = ""
	s.lastRunCompletedAt = completedAt
	s.updated = completedAt

	go s.notify(SignalValidation)
	return true
}

func (s *Store) FailRun(runID, message string, completedAt time.Time) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.activeRunID != runID {
		return false
	}

	s.activeRunID = ""
	s.status = StatusError
	s.message = message
	s.lastError = message
	s.lastRunCompletedAt = completedAt
	if s.hasResult {
		s.stale = true
	}
	s.updated = completedAt

	go s.notify(SignalValidation)
	return true
}

func (s *Store) MarkTelemetryChanged(changedAt time.Time) {
	s.mu.Lock()
	s.lastTelemetryAt = changedAt
	if s.hasResult {
		s.stale = true
		if s.status == StatusReady {
			s.message = "New telemetry since last validation"
		}
	}
	s.updated = changedAt
	s.mu.Unlock()
	s.notify(SignalValidation)
}

func (s *Store) Clear() {
	s.mu.Lock()
	s.entities = make(map[string]Entity)
	s.stats = weaverStats{}
	s.lastError = ""
	s.hasResult = false
	s.stale = false
	s.activeRunID = ""
	s.resultRunID = ""
	s.lastRunStartedAt = time.Time{}
	s.lastRunCompletedAt = time.Time{}
	s.lastTelemetryAt = time.Time{}
	if s.status == StatusDisabled {
		s.message = "Validator unavailable"
	} else {
		s.status = StatusIdle
		s.message = "Validation has not been run yet"
	}
	s.updated = time.Now()
	s.mu.Unlock()
	s.notify(SignalValidation)
}

func (s *Store) Summary() Summary {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.summaryLocked()
}

func (s *Store) Snapshot(limit int) Snapshot {
	findings := s.QueryFindings(Query{Limit: limit})
	return Snapshot{
		Summary:  s.Summary(),
		Findings: findings,
		Issues:   buildIssues(findings),
	}
}

func (s *Store) QueryFindings(q Query) []Finding {
	s.mu.RLock()
	findings := make([]Finding, 0, len(s.entities))
	for _, entity := range s.entities {
		findings = append(findings, entity.Findings...)
	}
	s.mu.RUnlock()

	filtered := findings[:0]
	for _, finding := range findings {
		if q.ServiceName != "" && !strings.EqualFold(finding.Signal.ServiceName, q.ServiceName) {
			continue
		}
		if q.SignalType != "" && !strings.EqualFold(finding.Signal.Type, q.SignalType) {
			continue
		}
		if q.Severity != "" && !strings.EqualFold(string(finding.Severity), q.Severity) {
			continue
		}
		if q.RuleID != "" && !strings.EqualFold(finding.RuleID, q.RuleID) {
			continue
		}
		if q.TraceID != "" && finding.Signal.TraceID != q.TraceID {
			continue
		}
		if q.SpanID != "" && finding.Signal.SpanID != q.SpanID {
			continue
		}
		if q.MetricName != "" && !strings.EqualFold(finding.Signal.MetricName, q.MetricName) {
			continue
		}
		if q.LogBody != "" && !strings.Contains(strings.ToLower(finding.Signal.LogBody), strings.ToLower(q.LogBody)) {
			continue
		}
		filtered = append(filtered, finding)
	}

	sort.Slice(filtered, func(i, j int) bool {
		if filtered[i].UpdatedAt.Equal(filtered[j].UpdatedAt) {
			if filtered[i].EntityKey == filtered[j].EntityKey {
				return filtered[i].RuleID < filtered[j].RuleID
			}
			return filtered[i].EntityKey < filtered[j].EntityKey
		}
		return filtered[i].UpdatedAt.After(filtered[j].UpdatedAt)
	})

	if q.Limit > 0 && len(filtered) > q.Limit {
		filtered = filtered[:q.Limit]
	}
	if len(filtered) == 0 {
		return []Finding{}
	}
	return append([]Finding(nil), filtered...)
}

func (s *Store) QueryIssues(q Query) []Issue {
	return buildIssues(s.QueryFindings(q))
}

func buildIssues(findings []Finding) []Issue {
	type groupedIssue struct {
		issue      Issue
		entityKeys map[string]struct{}
	}

	issues := make(map[string]*groupedIssue)

	for _, finding := range findings {
		key := issueKey(finding)
		if key == "" {
			continue
		}

		existing, ok := issues[key]
		if !ok {
			issues[key] = &groupedIssue{
				issue: Issue{
					Key:                 key,
					Severity:            finding.Severity,
					Message:             finding.Message,
					SignalType:          normalizeSignalType(finding.Signal.Type),
					TargetLabel:         issueTargetLabel(finding),
					ServiceName:         finding.Signal.ServiceName,
					ScopeName:           finding.Signal.ScopeName,
					Count:               0,
					ViolationCount:      0,
					ImprovementCount:    0,
					InformationCount:    0,
					AffectedEntityCount: 1,
					FirstSeen:           finding.UpdatedAt,
					LastSeen:            finding.UpdatedAt,
					Findings:            []Finding{finding},
				},
				entityKeys: map[string]struct{}{finding.EntityKey: {}},
			}
			continue
		}

		existing.issue.Findings = append(existing.issue.Findings, finding)
		existing.issue.Severity = maxSeverity(existing.issue.Severity, finding.Severity)
		if finding.UpdatedAt.Before(existing.issue.FirstSeen) {
			existing.issue.FirstSeen = finding.UpdatedAt
		}
		if finding.UpdatedAt.Equal(existing.issue.LastSeen) || finding.UpdatedAt.After(existing.issue.LastSeen) {
			existing.issue.LastSeen = finding.UpdatedAt
			existing.issue.Message = finding.Message
		}
		existing.entityKeys[finding.EntityKey] = struct{}{}
		existing.issue.AffectedEntityCount = len(existing.entityKeys)
	}

	result := make([]Issue, 0, len(issues))
	for _, grouped := range issues {
		grouped.issue.Findings = sortValidationFindings(grouped.issue.Findings)
		grouped.issue.Count, grouped.issue.ViolationCount, grouped.issue.ImprovementCount, grouped.issue.InformationCount = distinctIssueCounts(grouped.issue.Findings)
		grouped.issue.TargetLabel = issueDisplayTarget(grouped.issue)
		result = append(result, grouped.issue)
	}

	sort.Slice(result, func(i, j int) bool {
		if result[i].ViolationCount != result[j].ViolationCount {
			return result[i].ViolationCount > result[j].ViolationCount
		}
		if result[i].ImprovementCount != result[j].ImprovementCount {
			return result[i].ImprovementCount > result[j].ImprovementCount
		}
		if result[i].InformationCount != result[j].InformationCount {
			return result[i].InformationCount > result[j].InformationCount
		}
		if result[i].Count != result[j].Count {
			return result[i].Count > result[j].Count
		}
		if result[i].ServiceName != result[j].ServiceName {
			return result[i].ServiceName < result[j].ServiceName
		}
		if result[i].TargetLabel != result[j].TargetLabel {
			return result[i].TargetLabel < result[j].TargetLabel
		}
		return result[i].LastSeen.After(result[j].LastSeen)
	})

	return result
}

func distinctIssueCounts(findings []Finding) (total int, violations int, improvements int, information int) {
	seen := make(map[string]struct{}, len(findings))
	for _, finding := range findings {
		key := findingVariantKey(finding)
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		total += 1
		switch finding.Severity {
		case SeverityViolation:
			violations += 1
		case SeverityImprovement:
			improvements += 1
		case SeverityInformation:
			information += 1
		}
	}
	return total, violations, improvements, information
}

func findingVariantKey(finding Finding) string {
	parts := []string{string(finding.Severity), finding.RuleID, finding.Message}
	if len(finding.Context) > 0 {
		keys := make([]string, 0, len(finding.Context))
		for key := range finding.Context {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			parts = append(parts, key+"="+fmt.Sprint(finding.Context[key]))
		}
	}
	return strings.Join(parts, "\x1f")
}

func issueDisplayTarget(issue Issue) string {
	switch issue.SignalType {
	case "resource":
		if attributeName, ok := uniqueFindingContextValue(issue.Findings, "attribute_name"); ok {
			return attributeName
		}
	case "log":
		if issue.TargetLabel == "Log records" {
			if body, ok := uniqueLogBody(issue.Findings); ok {
				return body
			}
		}
	}
	return issue.TargetLabel
}

func uniqueFindingContextValue(findings []Finding, key string) (string, bool) {
	var value string
	for _, finding := range findings {
		if finding.Context == nil {
			continue
		}
		raw, ok := finding.Context[key]
		if !ok {
			continue
		}
		stringValue := stringifyContextValue(raw)
		if stringValue == "" {
			continue
		}
		if value == "" {
			value = stringValue
			continue
		}
		if value != stringValue {
			return "", false
		}
	}
	return value, value != ""
}

func uniqueLogBody(findings []Finding) (string, bool) {
	var body string
	for _, finding := range findings {
		if finding.Signal.LogBody == "" {
			continue
		}
		if body == "" {
			body = finding.Signal.LogBody
			continue
		}
		if body != finding.Signal.LogBody {
			return "", false
		}
	}
	return body, body != ""
}

func sortValidationFindings(findings []Finding) []Finding {
	sorted := append([]Finding(nil), findings...)
	sort.Slice(sorted, func(i, j int) bool {
		if severityRank(sorted[j].Severity) != severityRank(sorted[i].Severity) {
			return severityRank(sorted[j].Severity) > severityRank(sorted[i].Severity)
		}
		if sorted[i].Signal.ServiceName != sorted[j].Signal.ServiceName {
			return sorted[i].Signal.ServiceName < sorted[j].Signal.ServiceName
		}
		leftLabel := formatSignalLabel(sorted[i])
		rightLabel := formatSignalLabel(sorted[j])
		if leftLabel != rightLabel {
			return leftLabel < rightLabel
		}
		return sorted[j].UpdatedAt.After(sorted[i].UpdatedAt)
	})
	return sorted
}

func issueKey(finding Finding) string {
	signalType := normalizeSignalType(finding.Signal.Type)
	serviceName := finding.Signal.ServiceName
	scopeName := finding.Signal.ScopeName

	switch signalType {
	case "span":
		return "span:" + serviceName + ":" + finding.RuleID + ":" + finding.Signal.SpanName
	case "metric":
		return "metric:" + serviceName + ":" + scopeName + ":" + finding.Signal.MetricName
	case "log":
		if isBodySpecificLogRule(finding) {
			return "log:" + serviceName + ":" + scopeName + ":" + finding.RuleID + ":" + finding.Signal.LogBody
		}
		return "log:" + serviceName + ":" + scopeName + ":" + finding.RuleID
	case "resource":
		return "resource:" + serviceName + ":" + finding.RuleID
	default:
		return signalType + ":" + serviceName + ":" + scopeName + ":" + finding.RuleID + ":" + issueTargetLabel(finding)
	}
}

func issueTargetLabel(finding Finding) string {
	switch normalizeSignalType(finding.Signal.Type) {
	case "span":
		if finding.Signal.SpanName != "" {
			return finding.Signal.SpanName
		}
		return "Unnamed span"
	case "metric":
		if finding.Signal.MetricName != "" {
			return finding.Signal.MetricName
		}
		return "Unnamed metric"
	case "log":
		if isBodySpecificLogRule(finding) && finding.Signal.LogBody != "" {
			return finding.Signal.LogBody
		}
		if finding.Signal.ServiceName != "" {
			return finding.Signal.ServiceName + " logs"
		}
		if finding.Signal.ScopeName != "" {
			return finding.Signal.ScopeName + " logs"
		}
		return "Log records"
	case "resource":
		if finding.Signal.ServiceName != "" {
			return finding.Signal.ServiceName
		}
		return "Resource"
	default:
		return formatSignalLabel(finding)
	}
}

func formatSignalLabel(finding Finding) string {
	switch normalizeSignalType(finding.Signal.Type) {
	case "span":
		if finding.Signal.SpanName != "" {
			return finding.Signal.SpanName
		}
		if finding.Signal.SpanID != "" {
			return finding.Signal.SpanID
		}
		return "span"
	case "metric":
		if finding.Signal.MetricName != "" {
			return finding.Signal.MetricName
		}
		return "metric"
	case "log":
		if finding.Signal.LogBody != "" {
			return finding.Signal.LogBody
		}
		return "log"
	case "resource":
		if finding.Signal.ServiceName != "" {
			return finding.Signal.ServiceName
		}
		return "resource"
	default:
		if finding.Signal.Type != "" {
			return finding.Signal.Type
		}
		return "signal"
	}
}

func normalizeSignalType(signalType string) string {
	switch strings.ToLower(signalType) {
	case "span_event":
		return "span"
	default:
		return strings.ToLower(signalType)
	}
}

func isBodySpecificLogRule(finding Finding) bool {
	if normalizeSignalType(finding.Signal.Type) != "log" {
		return false
	}
	parts := make([]string, 0, 2+len(finding.Context)*2)
	parts = append(parts, finding.RuleID, finding.Message)
	for key, value := range finding.Context {
		parts = append(parts, key, stringifyContextValue(value))
	}
	haystack := strings.ToLower(strings.Join(parts, " "))
	return strings.Contains(haystack, "log body") ||
		strings.Contains(haystack, "log.body") ||
		strings.Contains(haystack, "body") ||
		strings.Contains(haystack, "message")
}

func stringifyContextValue(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	default:
		return fmt.Sprint(value)
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

func (s *Store) summaryLocked() Summary {
	severityCounts := map[string]int{
		string(SeverityInformation): 0,
		string(SeverityImprovement): 0,
		string(SeverityViolation):   0,
	}
	highestCounts := map[string]int{
		string(SeverityInformation): 0,
		string(SeverityImprovement): 0,
		string(SeverityViolation):   0,
	}
	signalCounts := make(map[string]int)
	totalAdvisories := 0

	for _, entity := range s.entities {
		if entity.HighestSeverity != "" {
			highestCounts[string(entity.HighestSeverity)]++
		}
		if entity.Signal.Type != "" {
			signalCounts[entity.Signal.Type]++
		}
		for _, finding := range entity.Findings {
			severityCounts[string(finding.Severity)]++
			totalAdvisories++
		}
	}

	if len(s.stats.AdviceLevelCounts) > 0 {
		for key, value := range s.stats.AdviceLevelCounts {
			severityCounts[key] = value
		}
	}
	if len(s.stats.HighestAdviceLevelCounts) > 0 {
		for key, value := range s.stats.HighestAdviceLevelCounts {
			highestCounts[key] = value
		}
	}
	if len(s.stats.TotalEntitiesByType) > 0 {
		signalCounts = cloneIntMap(s.stats.TotalEntitiesByType)
	}

	totalEntities := len(s.entities)
	if s.stats.TotalEntities > 0 {
		totalEntities = s.stats.TotalEntities
	}
	if s.stats.TotalAdvisories > 0 {
		totalAdvisories = s.stats.TotalAdvisories
	}

	needsRun := false
	switch s.status {
	case StatusIdle, StatusError:
		needsRun = true
	case StatusReady:
		needsRun = s.stale
	}

	return Summary{
		Enabled:               s.status != StatusDisabled,
		Ready:                 s.status == StatusReady && !s.stale,
		Status:                s.status,
		Message:               s.message,
		LastError:             s.lastError,
		HasResult:             s.hasResult,
		Stale:                 s.stale,
		NeedsRun:              needsRun,
		ActiveRunID:           s.activeRunID,
		ResultRunID:           s.resultRunID,
		LastRunStartedAt:      s.lastRunStartedAt,
		LastRunCompletedAt:    s.lastRunCompletedAt,
		LastTelemetryAt:       s.lastTelemetryAt,
		TotalEntities:         totalEntities,
		TotalAdvisories:       totalAdvisories,
		NoAdviceCount:         s.stats.NoAdviceCount,
		SeverityCounts:        severityCounts,
		HighestSeverityCounts: highestCounts,
		SignalCounts:          signalCounts,
		UpdatedAt:             s.updated,
	}
}

func cloneIntMap(values map[string]int) map[string]int {
	if len(values) == 0 {
		return map[string]int{}
	}
	out := make(map[string]int, len(values))
	for key, value := range values {
		out[key] = value
	}
	return out
}
