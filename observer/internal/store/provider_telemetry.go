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

type providerTraceContributor struct {
	span     Span
	sequence uint64
}

// Observation owner details are bounded independently from distinct-span
// observations. Contributor records have a separate global budget so every
// retained trace can still be removed exactly when its last producer exits.
type providerTraceObservation struct {
	spanIDs                       map[string]struct{}
	spanOwners                    map[string]map[string]struct{}
	spanOwnerOverflow             map[string]struct{}
	overflowOwners                map[string]struct{}
	overflowOwnerTrackingOverflow bool
	overflow                      bool
	historyUnavailable            bool
	lastRevision                  uint64
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

func isProviderAgentSpan(span Span) bool {
	return providerAgentSpanProvider(span) != ""
}

func providerAgentSpanProvider(span Span) string {
	name := strings.ToLower(strings.TrimSpace(span.Name))
	if provider := ProviderTaskBoundaryProvider(span); provider != "" {
		return provider
	}
	identity := strings.ToLower(strings.Join([]string{
		span.Resource.ServiceName,
		span.Scope.Name,
		providerTelemetryAttributeString(span.Attributes, "gen_ai.provider.name"),
		providerTelemetryAttributeString(span.Attributes, "model"),
	}, " "))
	if strings.Contains(identity, "claude") {
		if strings.HasPrefix(name, "claude_code.") ||
			providerTelemetryAttributeString(span.Attributes, "prompt.id") != "" ||
			providerTelemetryAttributeString(span.Attributes, "session.id") != "" {
			return "claude"
		}
	}
	if strings.Contains(identity, "codex") {
		if name == "session_task" || strings.HasPrefix(name, "session_task.") ||
			providerTelemetryAttributeString(span.Attributes, "turn.id") != "" ||
			providerTelemetryAttributeString(span.Attributes, "thread.id") != "" ||
			providerTelemetryAttributeString(span.Attributes, "conversation.id") != "" {
			return "codex"
		}
	}
	// OpenAI is a provider identity, not proof that an arbitrary application
	// span came from Codex. The native task name remains safe when a Codex
	// service or scope name is unavailable.
	if strings.Contains(identity, "openai") && (name == "session_task" || strings.HasPrefix(name, "session_task.")) {
		return "codex"
	}
	return ""
}

func providerTraceSpanKey(span Span) (string, bool) {
	if span.TraceID == "" || span.SpanID == "" {
		return "", false
	}
	return span.TraceID + "\x00" + span.SpanID, true
}

const providerTraceSpanLimitPerTrace = 8
const providerTraceObservedSpanIDLimit = DefaultProviderTraceSpanCap * 4
const providerTraceOwnerTrackingLimit = 64
const defaultProviderTraceContributorCap = DefaultProviderTraceSpanCap * providerTraceSpanLimitPerTrace

// captureProviderTraceSpans protects recent native Codex and Claude traces
// from unrelated traffic in the generic span ring. One shared bounded ring and
// a per-trace projection limit retention without separating providers. Must be
// called with s.mu held after incoming spans have been added to the generic
// ring.
func (s *Store) captureProviderTraceSpans(incoming []Span) {
	traceProviders := make(map[string]string)
	for _, span := range incoming {
		if span.TraceID == "" {
			continue
		}
		if _, suppressed := s.providerTraceSuppressedIDs[span.TraceID]; suppressed {
			continue
		}
		if provider := providerAgentSpanProvider(span); provider != "" {
			traceProviders[span.TraceID] = provider
			continue
		}
		if _, retained := s.providerTraceIDs[span.TraceID]; retained {
			traceProviders[span.TraceID] = "retained"
		}
	}
	if len(traceProviders) == 0 {
		return
	}
	taskHistory := s.providerTaskSpansForIncomingOwners(incoming, traceProviders)
	generic := s.spans.snapshot()
	// A provider boundary can arrive after earlier spans from the same trace.
	// Attribute every still-live recovered span before recording the incoming
	// batch, whose early entries may already have rolled out of the generic ring.
	for _, span := range generic {
		if traceProviders[span.TraceID] != "" {
			s.recordProviderTraceObservation(span)
		}
	}
	for _, span := range taskHistory {
		s.recordProviderTraceObservation(span)
	}
	for _, span := range incoming {
		if traceProviders[span.TraceID] != "" {
			s.recordProviderTraceObservation(span)
		}
	}

	ring := &s.providerTraceSpans
	retained := ring.snapshot()
	for _, span := range retained {
		s.seedProviderTraceContributor(span)
	}
	for _, span := range taskHistory {
		s.seedProviderTraceContributor(span)
	}
	for _, span := range generic {
		if traceProviders[span.TraceID] != "" {
			s.seedProviderTraceContributor(span)
		}
	}
	for _, span := range incoming {
		if traceProviders[span.TraceID] != "" {
			s.recordProviderTraceContributor(span)
		}
	}
	for traceID := range traceProviders {
		if _, suppressed := s.providerTraceSuppressedIDs[traceID]; suppressed {
			delete(traceProviders, traceID)
		}
	}
	retained = s.filterSuppressedProviderTraceSpans(retained)

	indexes := make(map[string]int, len(retained))
	for i, span := range retained {
		if key, ok := providerTraceSpanKey(span); ok {
			indexes[key] = i
		}
	}
	upsert := func(span Span) {
		if traceProviders[span.TraceID] == "" {
			return
		}
		key, ok := providerTraceSpanKey(span)
		if !ok {
			return
		}
		if winner, exists := s.latestProviderTraceContributor(key); exists {
			span = winner
		}
		span = s.withProviderTraceObservation(span)
		if index, exists := indexes[key]; exists {
			span.providerTraceRetentionTruncated = span.providerTraceRetentionTruncated || retained[index].providerTraceRetentionTruncated
			span.providerTraceObservedSpanCount = max(span.providerTraceObservedSpanCount, retained[index].providerTraceObservedSpanCount)
			span.providerTraceObservationOverflow = span.providerTraceObservationOverflow || retained[index].providerTraceObservationOverflow
			span.providerTraceObservationUnavailable = span.providerTraceObservationUnavailable || retained[index].providerTraceObservationUnavailable
			retained[index] = span
			return
		}
		indexes[key] = len(retained)
		retained = append(retained, span)
	}
	// Recover same-owner task context after the live provider projection rolls
	// over, without reintroducing history from a disconnected process.
	for _, span := range taskHistory {
		upsert(span)
	}
	// Recover earlier spans in a provider trace that arrived in another batch.
	for _, span := range generic {
		upsert(span)
	}
	// Incoming spans win and remain available even when one oversized batch
	// overwrote its own early entries in the generic ring.
	for _, span := range incoming {
		upsert(span)
	}
	perTraceLimit := min(providerTraceSpanLimitPerTrace, ring.cap)
	retained = compactProviderTraceSpans(retained, perTraceLimit)
	retained = moveProviderTracesToTail(retained, traceProviders)
	retained = retainNewestWholeProviderTraces(retained, ring.cap)
	// Reduce distinct-span contributors to the projection before enforcing the
	// live-owner budget. Otherwise one oversized trace can evict itself even
	// though its compact representation fits comfortably within the bound.
	s.pruneProviderTraceContributorKeys(retained)
	s.pruneProviderTraceContributorCapacity()
	retained = s.filterSuppressedProviderTraceSpans(retained)
	ring.clear()
	ring.push(retained)
	s.rebuildProviderTraceIndex(retained)
	s.pruneProviderTraceContributors(retained)
}

func (s *Store) providerTaskSpansForIncomingOwners(incoming []Span, touched map[string]string) []Span {
	ownersByTrace := make(map[string]map[string]struct{})
	for _, span := range incoming {
		if touched[span.TraceID] == "" {
			continue
		}
		owners := ownersByTrace[span.TraceID]
		if owners == nil {
			owners = make(map[string]struct{})
			ownersByTrace[span.TraceID] = owners
		}
		owners[span.ownerConnID] = struct{}{}
	}
	spans := make([]Span, 0)
	for _, task := range s.providerTasks.snapshot() {
		owners := ownersByTrace[task.traceID]
		if len(owners) == 0 {
			continue
		}
		for _, span := range task.spans {
			if _, sameOwner := owners[span.ownerConnID]; sameOwner {
				spans = append(spans, span)
			}
		}
	}
	return spans
}

func (s *Store) seedProviderTraceContributor(span Span) {
	s.upsertProviderTraceContributor(span)
}

func (s *Store) recordProviderTraceContributor(span Span) {
	s.upsertProviderTraceContributor(span)
}

func (s *Store) upsertProviderTraceContributor(span Span) {
	key, ok := providerTraceSpanKey(span)
	if !ok {
		return
	}
	contributors := s.providerTraceContributors[key]
	if contributors == nil {
		contributors = make(map[string]providerTraceContributor)
		s.providerTraceContributors[key] = contributors
	}
	sequence := s.providerTraceContributorSequence(span)
	previous, exists := contributors[span.ownerConnID]
	if exists && previous.sequence >= sequence {
		return
	}
	contributors[span.ownerConnID] = providerTraceContributor{span: span, sequence: sequence}
}

func (s *Store) pruneProviderTraceContributorCapacity() {
	total := 0
	latestByTrace := make(map[string]uint64)
	for key, contributors := range s.providerTraceContributors {
		traceID, _, ok := strings.Cut(key, "\x00")
		if !ok {
			continue
		}
		total += len(contributors)
		for _, contributor := range contributors {
			latestByTrace[traceID] = max(latestByTrace[traceID], contributor.sequence)
		}
	}
	for total > s.providerTraceContributorCap && len(latestByTrace) > 0 {
		oldestTraceID := ""
		var oldestSequence uint64
		for traceID, sequence := range latestByTrace {
			if oldestTraceID == "" || sequence < oldestSequence ||
				(sequence == oldestSequence && traceID < oldestTraceID) {
				oldestTraceID = traceID
				oldestSequence = sequence
			}
		}
		s.suppressProviderTrace(oldestTraceID)
		delete(latestByTrace, oldestTraceID)
		for key, contributors := range s.providerTraceContributors {
			traceID, _, _ := strings.Cut(key, "\x00")
			if traceID != oldestTraceID {
				continue
			}
			total -= len(contributors)
			delete(s.providerTraceContributors, key)
		}
	}
}

func (s *Store) suppressProviderTrace(traceID string) {
	if traceID == "" {
		return
	}
	if _, exists := s.providerTraceSuppressedIDs[traceID]; exists {
		return
	}
	for _, evicted := range s.providerTraceSuppressed.pushWithEvicted([]string{traceID}) {
		delete(s.providerTraceSuppressedIDs, evicted)
	}
	s.providerTraceSuppressedIDs[traceID] = struct{}{}
}

func (s *Store) filterSuppressedProviderTraceSpans(spans []Span) []Span {
	filtered := spans[:0]
	for _, span := range spans {
		if _, suppressed := s.providerTraceSuppressedIDs[span.TraceID]; !suppressed {
			filtered = append(filtered, span)
		}
	}
	return filtered
}

func (s *Store) providerTraceContributorSequence(span Span) uint64 {
	if span.ingestRevision > 0 {
		if span.ingestRevision > s.providerTraceContributorSeq {
			s.providerTraceContributorSeq = span.ingestRevision
		}
		return span.ingestRevision
	}
	s.providerTraceContributorSeq++
	return s.providerTraceContributorSeq
}

func (s *Store) latestProviderTraceContributor(key string) (Span, bool) {
	contributors := s.providerTraceContributors[key]
	var selected providerTraceContributor
	found := false
	for _, contributor := range contributors {
		if !found || contributor.sequence > selected.sequence {
			selected = contributor
			found = true
		}
	}
	return selected.span, found
}

func (s *Store) pruneProviderTraceContributorKeys(spans []Span) {
	retainedKeys := make(map[string]struct{}, len(spans))
	for _, span := range spans {
		if key, ok := providerTraceSpanKey(span); ok {
			retainedKeys[key] = struct{}{}
		}
	}
	for key := range s.providerTraceContributors {
		if _, retained := retainedKeys[key]; !retained {
			delete(s.providerTraceContributors, key)
		}
	}
}

func (s *Store) pruneProviderTraceContributors(spans []Span) {
	s.pruneProviderTraceContributorKeys(spans)
	s.pruneProviderTraceObservations()
}

func (s *Store) recordProviderTraceObservation(span Span) {
	if span.TraceID == "" || span.SpanID == "" {
		return
	}
	observation := s.providerTraceObservations[span.TraceID]
	if observation == nil {
		observation = &providerTraceObservation{
			spanIDs:           make(map[string]struct{}),
			spanOwners:        make(map[string]map[string]struct{}),
			spanOwnerOverflow: make(map[string]struct{}),
			overflowOwners:    make(map[string]struct{}),
		}
		s.providerTraceObservations[span.TraceID] = observation
	}
	observation.lastRevision = max(observation.lastRevision, span.ingestRevision)
	if observation.overflow || observation.historyUnavailable {
		observation.addOverflowOwner(span.ownerConnID)
		return
	}
	if _, exists := observation.spanIDs[span.SpanID]; exists {
		observation.addSpanOwner(span.SpanID, span.ownerConnID)
		return
	}
	if s.providerTraceObservedSpanIDs >= providerTraceObservedSpanIDLimit {
		s.reclaimProviderTraceObservationCapacity(span.TraceID)
		if s.providerTraceObservedSpanIDs >= providerTraceObservedSpanIDLimit {
			observation.overflow = true
			observation.addOverflowOwner(span.ownerConnID)
			return
		}
	}
	observation.spanIDs[span.SpanID] = struct{}{}
	observation.addSpanOwner(span.SpanID, span.ownerConnID)
	s.providerTraceObservedSpanIDs++
}

func (observation *providerTraceObservation) addSpanOwner(spanID, connectionID string) {
	owners := observation.spanOwners[spanID]
	if owners == nil {
		owners = make(map[string]struct{})
		observation.spanOwners[spanID] = owners
	}
	if _, exists := owners[connectionID]; exists {
		return
	}
	if len(owners) >= providerTraceOwnerTrackingLimit {
		observation.spanOwnerOverflow[spanID] = struct{}{}
		return
	}
	owners[connectionID] = struct{}{}
}

func (observation *providerTraceObservation) addOverflowOwner(connectionID string) {
	if observation.overflowOwners == nil {
		observation.overflowOwners = make(map[string]struct{})
	}
	if _, exists := observation.overflowOwners[connectionID]; exists {
		return
	}
	if len(observation.overflowOwners) >= providerTraceOwnerTrackingLimit {
		observation.overflowOwnerTrackingOverflow = true
		return
	}
	observation.overflowOwners[connectionID] = struct{}{}
}

// reclaimProviderTraceObservationCapacity sacrifices the least recently
// updated older trace before degrading a current trace. The evicted trace
// remains conservatively marked as having unavailable history through its
// observation entry, without claiming that an omitted span was observed.
func (s *Store) reclaimProviderTraceObservationCapacity(currentTraceID string) {
	oldestTraceID := ""
	var oldestRevision uint64
	for traceID, observation := range s.providerTraceObservations {
		if traceID == currentTraceID || len(observation.spanIDs) == 0 {
			continue
		}
		if oldestTraceID == "" || observation.lastRevision < oldestRevision {
			oldestTraceID = traceID
			oldestRevision = observation.lastRevision
		}
	}
	if oldestTraceID == "" {
		return
	}
	observation := s.providerTraceObservations[oldestTraceID]
	for _, owners := range observation.spanOwners {
		for connectionID := range owners {
			observation.addOverflowOwner(connectionID)
		}
	}
	if len(observation.spanOwnerOverflow) > 0 {
		observation.overflowOwnerTrackingOverflow = true
	}
	s.providerTraceObservedSpanIDs -= len(observation.spanIDs)
	clear(observation.spanIDs)
	clear(observation.spanOwners)
	clear(observation.spanOwnerOverflow)
	observation.historyUnavailable = true
}

func (s *Store) evictProviderTraceObservationConnection(connectionID string) map[string]struct{} {
	changedTraceIDs := make(map[string]struct{})
	for traceID, observation := range s.providerTraceObservations {
		for spanID, owners := range observation.spanOwners {
			if _, exists := owners[connectionID]; !exists {
				continue
			}
			delete(owners, connectionID)
			changedTraceIDs[traceID] = struct{}{}
			if len(owners) == 0 {
				delete(observation.spanOwners, spanID)
				if _, ownershipUnknown := observation.spanOwnerOverflow[spanID]; !ownershipUnknown {
					delete(observation.spanIDs, spanID)
					s.providerTraceObservedSpanIDs--
				}
			}
		}
		if _, exists := observation.overflowOwners[connectionID]; exists {
			delete(observation.overflowOwners, connectionID)
			changedTraceIDs[traceID] = struct{}{}
		}
		if (observation.overflow || observation.historyUnavailable) && len(observation.overflowOwners) == 0 &&
			!observation.overflowOwnerTrackingOverflow {
			observation.overflow = false
			observation.historyUnavailable = false
			changedTraceIDs[traceID] = struct{}{}
		}
		if len(observation.spanIDs) == 0 && !observation.overflow && !observation.historyUnavailable {
			delete(s.providerTraceObservations, traceID)
		}
	}
	return changedTraceIDs
}

func (s *Store) refreshProviderTraceObservationState(
	spans []Span,
	resetKnownOmissionTraceIDs map[string]struct{},
) []Span {
	retainedIDs := make(map[string]map[string]struct{})
	for _, span := range spans {
		if retainedIDs[span.TraceID] == nil {
			retainedIDs[span.TraceID] = make(map[string]struct{})
		}
		if span.SpanID != "" {
			retainedIDs[span.TraceID][span.SpanID] = struct{}{}
		}
	}
	for index := range spans {
		span := spans[index]
		_, resetKnownOmission := resetKnownOmissionTraceIDs[span.TraceID]
		knownOmission := span.providerTraceRetentionTruncated && !resetKnownOmission
		span.providerTraceRetentionTruncated = knownOmission
		span.providerTraceObservedSpanCount = 0
		span.providerTraceObservationOverflow = false
		span.providerTraceObservationUnavailable = false
		observation := s.providerTraceObservations[span.TraceID]
		if observation != nil {
			span.providerTraceObservedSpanCount = len(observation.spanIDs)
			span.providerTraceObservationOverflow = observation.overflow
			span.providerTraceObservationUnavailable = observation.historyUnavailable
			span.providerTraceRetentionTruncated = knownOmission || observation.overflow ||
				len(observation.spanIDs) > len(retainedIDs[span.TraceID])
		}
		spans[index] = span
	}
	return spans
}

func (s *Store) withProviderTraceObservation(span Span) Span {
	observation := s.providerTraceObservations[span.TraceID]
	if observation == nil {
		return span
	}
	span.providerTraceObservedSpanCount = max(span.providerTraceObservedSpanCount, len(observation.spanIDs))
	span.providerTraceObservationOverflow = span.providerTraceObservationOverflow || observation.overflow
	span.providerTraceObservationUnavailable = span.providerTraceObservationUnavailable || observation.historyUnavailable
	return span
}

func (s *Store) pruneProviderTraceObservations() {
	for traceID, observation := range s.providerTraceObservations {
		if _, retained := s.providerTraceIDs[traceID]; retained {
			continue
		}
		s.providerTraceObservedSpanIDs -= len(observation.spanIDs)
		delete(s.providerTraceObservations, traceID)
	}
}

func (s *Store) rebuildProviderTraceIndex(spans []Span) {
	if s.providerTraceIDs == nil {
		s.providerTraceIDs = make(map[string]struct{})
	} else {
		clear(s.providerTraceIDs)
	}
	for _, span := range spans {
		if span.TraceID != "" && span.SpanID != "" {
			s.providerTraceIDs[span.TraceID] = struct{}{}
		}
	}
}

func retainNewestWholeProviderTraces(spans []Span, capacity int) []Span {
	if capacity <= 0 {
		return nil
	}
	if len(spans) <= capacity {
		return spans
	}

	counts := make(map[string]int)
	order := make([]string, 0)
	for _, span := range spans {
		if counts[span.TraceID] == 0 {
			order = append(order, span.TraceID)
		}
		counts[span.TraceID]++
	}
	dropped := make(map[string]struct{})
	remaining := len(spans)
	for _, traceID := range order {
		if remaining <= capacity {
			break
		}
		dropped[traceID] = struct{}{}
		remaining -= counts[traceID]
	}
	retained := make([]Span, 0, remaining)
	for _, span := range spans {
		if _, drop := dropped[span.TraceID]; !drop {
			retained = append(retained, span)
		}
	}
	return retained
}

func moveProviderTracesToTail(spans []Span, touched map[string]string) []Span {
	if len(spans) == 0 || len(touched) == 0 {
		return spans
	}
	ordered := make([]Span, 0, len(spans))
	for _, span := range spans {
		if touched[span.TraceID] == "" {
			ordered = append(ordered, span)
		}
	}
	for _, span := range spans {
		if touched[span.TraceID] != "" {
			ordered = append(ordered, span)
		}
	}
	return ordered
}

func compactProviderTraceSpans(spans []Span, limit int) []Span {
	if limit <= 0 {
		return spans
	}
	byTrace := make(map[string][]int)
	observedSpanCounts := make(map[string]int)
	for index, span := range spans {
		byTrace[span.TraceID] = append(byTrace[span.TraceID], index)
		observedSpanCounts[span.TraceID] = max(observedSpanCounts[span.TraceID], span.providerTraceObservedSpanCount)
	}
	selected := make(map[int]struct{}, len(spans))
	truncatedTraceIDs := make(map[string]struct{})
	for traceID, indexes := range byTrace {
		observedSpanCounts[traceID] = max(observedSpanCounts[traceID], len(indexes))
		if len(indexes) <= limit {
			for _, index := range indexes {
				selected[index] = struct{}{}
			}
			continue
		}
		truncatedTraceIDs[traceID] = struct{}{}
		sort.SliceStable(indexes, func(i, j int) bool {
			left := spans[indexes[i]]
			right := spans[indexes[j]]
			leftPriority := providerTraceSpanRetentionPriority(left)
			rightPriority := providerTraceSpanRetentionPriority(right)
			if leftPriority != rightPriority {
				return leftPriority > rightPriority
			}
			leftTime := providerTraceSpanTime(left)
			rightTime := providerTraceSpanTime(right)
			if !leftTime.Equal(rightTime) {
				return leftTime.After(rightTime)
			}
			return indexes[i] > indexes[j]
		})
		selectedForTrace := 0
		// Status remains an exact trace property even when only representative
		// spans are retained. Reserve one representative for every status that
		// affects the aggregate before filling the remaining projection slots.
		for _, statusCode := range []string{"ERROR", "OK"} {
			for _, index := range indexes {
				if spans[index].Status.Code != statusCode {
					continue
				}
				if _, exists := selected[index]; !exists {
					selected[index] = struct{}{}
					selectedForTrace++
				}
				break
			}
		}
		for _, index := range indexes {
			if selectedForTrace == limit {
				break
			}
			if _, exists := selected[index]; exists {
				continue
			}
			selected[index] = struct{}{}
			selectedForTrace++
		}
	}
	compacted := make([]Span, 0, len(selected))
	for index, span := range spans {
		if _, ok := selected[index]; ok {
			if _, truncated := truncatedTraceIDs[span.TraceID]; truncated {
				span.providerTraceRetentionTruncated = true
			}
			span.providerTraceObservedSpanCount = observedSpanCounts[span.TraceID]
			compacted = append(compacted, span)
		}
	}
	return compacted
}

func providerTraceSpansRetentionTruncated(spans []Span) bool {
	observedSpanCount := 0
	retainedSpanIDs := make(map[string]struct{}, len(spans))
	markedTruncated := false
	for _, span := range spans {
		if span.providerTraceRetentionTruncated {
			markedTruncated = true
		}
		if span.providerTraceObservationUnavailable {
			return true
		}
		if span.providerTraceObservationOverflow {
			return true
		}
		observedSpanCount = max(observedSpanCount, span.providerTraceObservedSpanCount)
		if span.SpanID != "" {
			retainedSpanIDs[span.SpanID] = struct{}{}
		}
	}
	if !markedTruncated {
		return false
	}
	return observedSpanCount == 0 || len(retainedSpanIDs) < observedSpanCount
}

func providerTraceSpansRetentionUnknown(spans []Span) bool {
	historyUnavailable := false
	knownOmission := false
	for _, span := range spans {
		if span.providerTraceObservationOverflow {
			return false
		}
		historyUnavailable = historyUnavailable || span.providerTraceObservationUnavailable
		knownOmission = knownOmission || span.providerTraceRetentionTruncated
	}
	return historyUnavailable && !knownOmission
}

func providerTraceSpanRetentionPriority(span Span) int {
	priority := 0
	if span.ParentSpanID == "" {
		priority += 4
	}
	if ProviderTaskBoundaryProvider(span) != "" {
		priority += 2
	}
	name := strings.ToLower(strings.TrimSpace(span.Name))
	if ClassifyGenAISpan(span) == GenAISpanLLM || name == "claude_code.llm_request" {
		priority++
	}
	return priority
}

func providerTraceSpanTime(span Span) time.Time {
	if !span.EndTime.IsZero() {
		return span.EndTime
	}
	return span.StartTime
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
