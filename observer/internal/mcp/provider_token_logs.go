package mcp

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

var (
	codexInputTokenLogKeys = []string{
		"input_token_count",
		"input_tokens",
	}
	codexCachedInputTokenLogKeys = []string{
		"cached_token_count",
		"cached_input_token_count",
		"cached_input_tokens",
	}
	codexCacheCreationInputTokenLogKeys = []string{
		"cache_creation_input_token_count",
		"cache_write_input_token_count",
		"cache_creation_input_tokens",
		"cache_write_input_tokens",
	}
	codexOutputTokenLogKeys = []string{
		"output_token_count",
		"output_tokens",
	}
	codexReasoningOutputTokenLogKeys = []string{
		"reasoning_token_count",
		"reasoning_output_token_count",
		"reasoning_output_tokens",
	}
	codexProviderTotalTokenLogKeys = []string{
		"total_token_count",
		"tool_token_count",
		"total_tokens",
	}
	claudeInputTokenLogKeys = []string{
		"input_tokens",
	}
	claudeCachedInputTokenLogKeys = []string{
		"cache_read_tokens",
		"cache_read_input_tokens",
	}
	claudeCacheCreationInputTokenLogKeys = []string{
		"cache_creation_tokens",
		"cache_creation_input_tokens",
	}
	claudeOutputTokenLogKeys = []string{
		"output_tokens",
	}
	claudeReasoningOutputTokenLogKeys = []string{
		"reasoning_output_tokens",
		"reasoning_tokens",
		"thinking_tokens",
	}
	claudeProviderTotalTokenLogKeys = []string{
		"total_token_count",
		"total_tokens",
	}
)

type providerLogTokenEvent struct {
	log            store.LogRecord
	timestamp      time.Time
	provider       string
	boundarySpanID string
	taskID         string
	taskKind       string
	fallbackTask   bool
	traceID        string
	turnID         string
	promptID       string
	conversationID string
	skillNames     []string
	dedupeKey      string
	stableIdentity bool
	model          string
	record         tokenUsageRecord
	normalization  string
	source         string
}

type providerLogTaskBuild struct {
	task                     tokenUsageTask
	records                  []tokenUsageRecord
	latest                   time.Time
	sessionHistoryIncomplete bool
}

type providerTraceMetadata struct {
	traceID                     string
	boundarySpanID              string
	provider                    string
	nativeTrace                 bool
	taskComplete                bool
	taskTotal                   *int64
	taskRecord                  *tokenUsageRecord
	taskRecords                 []tokenUsageRecord
	taskRequestCount            int
	taskUsageSource             string
	taskNormalization           string
	rootSpanName                string
	serviceName                 string
	repositoryName              string
	repositoryPath              string
	workspacePath               string
	repositoryCorrelationStatus string
	repositoryCorrelationSource string
	turnID                      string
	promptID                    string
	conversationID              string
	skillNames                  []string
	modelNames                  []string
	spanCount                   int
	startTime                   time.Time
	endTime                     time.Time
	evaluationSpanIDs           map[string]struct{}
	taskRetentionTruncated      bool
}

type providerTraceIndex struct {
	byTraceID            map[string]providerTraceMetadata
	tasks                []*providerTraceMetadata
	tasksByTraceID       map[string][]*providerTraceMetadata
	taskBySpan           map[string]*providerTraceMetadata
	taskByTurn           map[string]*providerTraceMetadata
	taskByPrompt         map[string]*providerTraceMetadata
	tasksByConversation  map[string][]*providerTraceMetadata
	evaluationIdentities map[string]struct{}
}

func buildProviderLogTasks(
	logs []store.LogRecord,
	spansByTraceID map[string][]store.Span,
	args map[string]any,
	unavailableThrough time.Time,
) []providerLogTaskBuild {
	// Span-specific filtering explicitly selects the legacy span path.
	if strArg(args, "spanName") != "" {
		return nil
	}

	serviceName := strings.TrimSpace(strArg(args, "serviceName"))
	providerFilter := strings.ToLower(strings.TrimSpace(strArg(args, "provider")))
	exactTraceID := strings.ToLower(strings.TrimSpace(strArg(args, "traceId")))
	exactTaskID := strings.TrimSpace(strArg(args, "taskId"))
	exactConversationID := conversationIDArg(args)
	skillName := strings.TrimSpace(strArg(args, "skillName"))
	taskIDPrefix := strings.ToLower(strings.TrimSpace(strArg(args, "traceIdPrefix")))
	traceIndex := buildProviderTraceIndex(spansByTraceID)
	groups := make(map[string][]providerLogTokenEvent)
	groupOrder := make([]string, 0)
	seenByGroup := make(map[string]map[string]providerLogTokenEvent)
	conflictingDuplicates := make(map[string]struct{})

	for _, logRecord := range logs {
		event, ok := providerTokenEvent(logRecord)
		if !ok || (providerFilter != "" && event.provider != providerFilter) {
			continue
		}
		if traceIndex.referencesEvaluationIdentity(event) {
			continue
		}
		event = traceIndex.correlate(event)
		metadata := traceIndex.metadataForEvent(event)
		event = enrichProviderTokenEvent(event, metadata)
		if isEvaluationProviderEvent(event, metadata) {
			continue
		}
		if serviceName != "" && !strings.EqualFold(logRecord.Resource.ServiceName, serviceName) && !strings.EqualFold(metadata.serviceName, serviceName) {
			continue
		}
		if exactTraceID != "" && event.traceID != exactTraceID {
			continue
		}
		if exactTaskID != "" && !strings.EqualFold(event.taskID, exactTaskID) {
			continue
		}
		if exactConversationID != "" && !strings.EqualFold(event.conversationID, exactConversationID) {
			continue
		}
		if skillName != "" && !containsFold(event.skillNames, skillName) {
			continue
		}
		if taskIDPrefix != "" &&
			!strings.HasPrefix(strings.ToLower(event.taskID), taskIDPrefix) &&
			!strings.HasPrefix(strings.ToLower(event.conversationID), taskIDPrefix) &&
			!strings.HasPrefix(event.traceID, taskIDPrefix) {
			continue
		}
		groupKey := providerTraceKey(event.provider, event.taskID)
		seen, exists := seenByGroup[groupKey]
		if !exists {
			seen = make(map[string]providerLogTokenEvent)
			seenByGroup[groupKey] = seen
			groupOrder = append(groupOrder, groupKey)
		}
		if previous, duplicate := seen[event.dedupeKey]; duplicate {
			if !sameProviderTokenRecord(previous.record, event.record) {
				conflictingDuplicates[groupKey] = struct{}{}
			}
			continue
		}
		seen[event.dedupeKey] = event
		groups[groupKey] = append(groups[groupKey], event)
	}

	built := make([]providerLogTaskBuild, 0, len(groups))
	for _, groupKey := range groupOrder {
		events := groups[groupKey]
		if len(events) == 0 {
			continue
		}
		sort.SliceStable(events, func(i, j int) bool {
			if events[i].timestamp.Equal(events[j].timestamp) {
				return events[i].log.ID < events[j].log.ID
			}
			return events[i].timestamp.Before(events[j].timestamp)
		})
		providerEventCount := len(events)
		metadata := traceIndex.metadataForEvent(events[0])
		events, usageReconciled := reconcileProviderTaskEvents(
			events,
			metadata,
			providerLogWindowComplete(metadata, unavailableThrough),
		)
		if _, conflicting := conflictingDuplicates[groupKey]; conflicting &&
			(len(events) == 0 || !strings.Contains(events[0].source, "span")) {
			usageReconciled = false
			if len(events) > 0 {
				events[0].normalization += "; conflicting retransmissions with the same provider request identity were counted once and not treated as exact"
			}
		}

		records := make([]tokenUsageRecord, 0, len(events))
		models := make(map[string]struct{})
		skills := make(map[string]struct{})
		for _, event := range events {
			records = append(records, event.record)
			if event.model != "" {
				models[event.model] = struct{}{}
			}
			for _, name := range event.skillNames {
				skills[name] = struct{}{}
			}
		}
		for _, model := range metadata.modelNames {
			models[model] = struct{}{}
		}
		var aggregate tokenUsageAccumulator
		aggregate.addTask(records)
		first := events[0]
		last := events[len(events)-1]
		status := aggregate.status()
		correlationStatus := providerTaskCorrelationStatus(first, metadata, usageReconciled)
		startTime := first.timestamp
		endTime := last.timestamp
		if correlationStatus == "trace_correlated" {
			if !metadata.startTime.IsZero() {
				startTime = metadata.startTime
			}
			if !metadata.endTime.IsZero() {
				endTime = metadata.endTime
			}
		}
		service := first.log.Resource.ServiceName
		if service == "" {
			service = metadata.serviceName
		}
		normalization := first.normalization
		if first.source == "claude_request_spans" {
			normalization += "; a completed interaction boundary does not prove that every child request span has arrived"
		}
		built = append(built, providerLogTaskBuild{
			task: tokenUsageTask{
				TaskID:                      first.taskID,
				TaskKind:                    first.taskKind,
				TraceID:                     first.traceID,
				RootSpanName:                metadata.rootSpanName,
				TurnID:                      first.turnID,
				PromptID:                    first.promptID,
				ConversationID:              first.conversationID,
				ServiceName:                 service,
				RepositoryName:              metadata.repositoryName,
				RepositoryPath:              metadata.repositoryPath,
				WorkspacePath:               metadata.workspacePath,
				RepositoryCorrelationStatus: metadata.repositoryCorrelationStatus,
				RepositoryCorrelationSource: metadata.repositoryCorrelationSource,
				StartTime:                   formatTokenUsageTime(startTime),
				EndTime:                     formatTokenUsageTime(endTime),
				MeasurementSource:           first.source,
				Normalization:               normalization,
				Status:                      status,
				AccountingStatus:            providerTaskAccountingStatus(status, correlationStatus),
				CorrelationStatus:           correlationStatus,
				Provider:                    first.provider,
				SkillNames:                  sortedSet(skills),
				ModelNames:                  sortedSet(models),
				RequestCount:                len(events),
				ProviderEventCount:          providerEventCount,
				TraceSpanCount:              metadata.spanCount,
				TraceComplete:               metadata.taskComplete,
				Usage:                       aggregate.values(),
				Coverage:                    aggregate.coverage,
			},
			records: records,
			latest:  endTime,
		})
	}

	return sortProviderTaskBuilds(built)
}

func sameProviderTokenRecord(left, right tokenUsageRecord) bool {
	return left.observed == right.observed &&
		left.recognized == right.recognized &&
		tokenUsageFingerprint(left.usage) == tokenUsageFingerprint(right.usage)
}

func sortProviderTaskBuilds(built []providerLogTaskBuild) []providerLogTaskBuild {
	sort.SliceStable(built, func(i, j int) bool {
		if built[i].latest.Equal(built[j].latest) {
			if built[i].task.Provider == built[j].task.Provider {
				return built[i].task.TaskID < built[j].task.TaskID
			}
			return built[i].task.Provider < built[j].task.Provider
		}
		return built[i].latest.After(built[j].latest)
	})
	return built
}

func limitProviderTaskBuilds(built []providerLogTaskBuild, args map[string]any) []providerLogTaskBuild {
	limit := tokenUsageLimit(args)
	if len(built) > limit {
		built = built[:limit]
	}
	return built
}

func mergeProviderSpanGroups(primary, retained map[string][]store.Span) map[string][]store.Span {
	merged := make(map[string][]store.Span, len(primary)+len(retained))
	for traceID, spans := range primary {
		merged[traceID] = append([]store.Span(nil), spans...)
	}
	for traceID, spans := range retained {
		existing := merged[traceID]
		seen := make(map[string]struct{}, len(existing)+len(spans))
		for _, span := range existing {
			seen[span.SpanID] = struct{}{}
		}
		for _, span := range spans {
			if _, duplicate := seen[span.SpanID]; duplicate {
				continue
			}
			seen[span.SpanID] = struct{}{}
			existing = append(existing, span)
		}
		merged[traceID] = existing
	}
	return merged
}

func buildProviderSpanTasks(spansByTraceID map[string][]store.Span, args map[string]any, excludedTaskKeys map[string]struct{}) []providerLogTaskBuild {
	if strArg(args, "spanName") != "" {
		return nil
	}
	serviceName := strings.TrimSpace(strArg(args, "serviceName"))
	providerFilter := strings.ToLower(strings.TrimSpace(strArg(args, "provider")))
	exactTraceID := strings.ToLower(strings.TrimSpace(strArg(args, "traceId")))
	exactTaskID := strings.TrimSpace(strArg(args, "taskId"))
	exactConversationID := conversationIDArg(args)
	skillName := strings.TrimSpace(strArg(args, "skillName"))
	taskIDPrefix := strings.ToLower(strings.TrimSpace(strArg(args, "traceIdPrefix")))
	traceIndex := buildProviderTraceIndex(spansByTraceID)
	built := make([]providerLogTaskBuild, 0, len(traceIndex.tasks))

	for _, taskMetadata := range traceIndex.tasks {
		metadata := *taskMetadata
		traceID := metadata.traceID
		if !metadata.nativeTrace || !metadata.taskComplete || metadata.provider == "" {
			continue
		}
		if providerFilter != "" && metadata.provider != providerFilter {
			continue
		}
		if serviceName != "" && !strings.EqualFold(metadata.serviceName, serviceName) {
			continue
		}
		if exactTraceID != "" && traceID != exactTraceID {
			continue
		}
		taskID, taskKind := providerSpanTaskIdentity(metadata)
		if _, excluded := excludedTaskKeys[providerTraceKey(metadata.provider, taskID)]; excluded {
			continue
		}
		if exactTaskID != "" && !strings.EqualFold(taskID, exactTaskID) {
			continue
		}
		if exactConversationID != "" && !strings.EqualFold(metadata.conversationID, exactConversationID) {
			continue
		}
		if skillName != "" && !containsFold(metadata.skillNames, skillName) {
			continue
		}
		if taskIDPrefix != "" &&
			!strings.HasPrefix(strings.ToLower(taskID), taskIDPrefix) &&
			!strings.HasPrefix(strings.ToLower(metadata.conversationID), taskIDPrefix) &&
			!strings.HasPrefix(traceID, taskIDPrefix) {
			continue
		}

		records := append([]tokenUsageRecord(nil), metadata.taskRecords...)
		if len(records) == 0 {
			records = []tokenUsageRecord{{provider: metadata.provider}}
		} else if metadata.taskRetentionTruncated && metadata.taskUsageSource == "claude_request_spans" {
			records = append(records, tokenUsageRecord{observed: true, provider: metadata.provider})
		}
		var aggregate tokenUsageAccumulator
		aggregate.addTask(records)
		status := aggregate.status()
		correlationStatus := "trace_correlated"
		if metadata.taskUsageSource == "claude_request_spans" {
			correlationStatus = "trace_request_window_incomplete"
		} else if metadata.provider == "codex" && (metadata.taskRecord == nil || metadata.taskRecord.usage.ProviderTotalTokens == nil) {
			correlationStatus = "trace_usage_mismatch"
		}
		source := metadata.taskUsageSource
		if source == "" {
			source = metadata.provider + "_task_span"
		}
		normalization := metadata.taskNormalization
		if normalization == "" {
			normalization = "completed provider task boundary with no recognized token usage"
		}
		if metadata.taskRetentionTruncated {
			normalization += "; compact provider task retention omitted accounting spans beyond its bounded span budget"
		}
		if metadata.taskUsageSource == "claude_request_spans" {
			normalization += "; a completed interaction boundary does not prove that every child request span has arrived"
		}
		requestCount := metadata.taskRequestCount
		if requestCount == 0 {
			requestCount = len(records)
		}
		built = append(built, providerLogTaskBuild{
			task: tokenUsageTask{
				TaskID:                      taskID,
				TaskKind:                    taskKind,
				TraceID:                     traceID,
				RootSpanName:                metadata.rootSpanName,
				TurnID:                      metadata.turnID,
				PromptID:                    metadata.promptID,
				ConversationID:              metadata.conversationID,
				ServiceName:                 metadata.serviceName,
				RepositoryName:              metadata.repositoryName,
				RepositoryPath:              metadata.repositoryPath,
				WorkspacePath:               metadata.workspacePath,
				RepositoryCorrelationStatus: metadata.repositoryCorrelationStatus,
				RepositoryCorrelationSource: metadata.repositoryCorrelationSource,
				StartTime:                   formatTokenUsageTime(metadata.startTime),
				EndTime:                     formatTokenUsageTime(metadata.endTime),
				MeasurementSource:           source,
				Normalization:               normalization,
				Status:                      status,
				AccountingStatus:            providerTaskAccountingStatus(status, correlationStatus),
				CorrelationStatus:           correlationStatus,
				Provider:                    metadata.provider,
				SkillNames:                  metadata.skillNames,
				ModelNames:                  metadata.modelNames,
				RequestCount:                requestCount,
				ProviderEventCount:          0,
				TraceSpanCount:              metadata.spanCount,
				TraceComplete:               true,
				Usage:                       aggregate.values(),
				Coverage:                    aggregate.coverage,
			},
			records: records,
			latest:  metadata.endTime,
		})
	}
	return sortProviderTaskBuilds(built)
}

func providerSpanTaskIdentity(metadata providerTraceMetadata) (string, string) {
	if metadata.provider == "codex" && metadata.turnID != "" {
		return metadata.turnID, "turn"
	}
	if metadata.provider == "claude" && metadata.promptID != "" {
		return metadata.promptID, "prompt"
	}
	if metadata.conversationID != "" {
		return metadata.conversationID, "conversation"
	}
	return metadata.traceID, "trace"
}

func combineProviderTaskBuilds(logTasks, spanTasks, metricTasks []providerLogTaskBuild, args map[string]any) []providerLogTaskBuild {
	logTasks, spanTasks, metricTasks = selectClaudeMetricFallbacks(logTasks, spanTasks, metricTasks)
	combined := make([]providerLogTaskBuild, 0, len(logTasks)+len(spanTasks)+len(metricTasks))
	combined = append(combined, logTasks...)
	combined = append(combined, spanTasks...)
	combined = append(combined, metricTasks...)
	if conversationIDArg(args) == "" {
		return sortProviderTaskBuilds(combined)
	}

	completedConversations := make(map[string]struct{})
	for _, built := range combined {
		if !built.task.TraceComplete || built.task.ConversationID == "" {
			continue
		}
		completedConversations[providerTraceKey(built.task.Provider, built.task.ConversationID)] = struct{}{}
	}
	if len(completedConversations) == 0 {
		return sortProviderTaskBuilds(combined)
	}

	filtered := make([]providerLogTaskBuild, 0, len(combined))
	for _, built := range combined {
		if !built.task.TraceComplete && built.task.ConversationID != "" {
			key := providerTraceKey(built.task.Provider, built.task.ConversationID)
			if _, hasCompletedTask := completedConversations[key]; hasCompletedTask {
				continue
			}
		}
		filtered = append(filtered, built)
	}
	return sortProviderTaskBuilds(filtered)
}

func selectClaudeMetricFallbacks(
	logTasks, spanTasks, metricTasks []providerLogTaskBuild,
) ([]providerLogTaskBuild, []providerLogTaskBuild, []providerLogTaskBuild) {
	type richerSessionState struct {
		allExact bool
	}
	richerSessions := make(map[string]richerSessionState)
	for _, tasks := range [][]providerLogTaskBuild{logTasks, spanTasks} {
		for _, built := range tasks {
			if built.task.Provider != "claude" || built.task.ConversationID == "" {
				continue
			}
			key := providerTraceKey("claude", built.task.ConversationID)
			state, exists := richerSessions[key]
			if !exists {
				state.allExact = true
			}
			state.allExact = state.allExact && built.task.AccountingStatus == "exact"
			richerSessions[key] = state
		}
	}
	exactMetricSessions := make(map[string]struct{})
	incompleteMetricSessions := make(map[string]struct{})
	for _, built := range metricTasks {
		if built.task.Provider != "claude" || built.task.ConversationID == "" {
			continue
		}
		key := providerTraceKey("claude", built.task.ConversationID)
		if built.task.AccountingStatus == "exact" {
			exactMetricSessions[key] = struct{}{}
		}
		if built.sessionHistoryIncomplete {
			incompleteMetricSessions[key] = struct{}{}
		}
	}
	filterRicher := func(tasks []providerLogTaskBuild) []providerLogTaskBuild {
		filtered := make([]providerLogTaskBuild, 0, len(tasks))
		for _, built := range tasks {
			key := providerTraceKey(built.task.Provider, built.task.ConversationID)
			if built.task.Provider == "claude" && built.task.ConversationID != "" {
				if _, exactMetric := exactMetricSessions[key]; exactMetric {
					if state := richerSessions[key]; !state.allExact {
						continue
					}
				}
				if _, incompleteHistory := incompleteMetricSessions[key]; incompleteHistory {
					built.task.AccountingStatus = "partial"
					built.task.Normalization += "; cumulative metric evidence shows that this session predates retained Observer history, so the selected per-request subtotal may omit earlier prompts"
				}
			}
			filtered = append(filtered, built)
		}
		return filtered
	}
	filteredMetrics := make([]providerLogTaskBuild, 0, len(metricTasks))
	for _, built := range metricTasks {
		key := providerTraceKey(built.task.Provider, built.task.ConversationID)
		if built.task.Provider == "claude" && built.task.ConversationID != "" {
			if richer, exists := richerSessions[key]; exists {
				if built.task.AccountingStatus != "exact" || richer.allExact {
					continue
				}
			}
		}
		filteredMetrics = append(filteredMetrics, built)
	}
	return filterRicher(logTasks), filterRicher(spanTasks), filteredMetrics
}

func providerTasksMeasurementSource(tasks []providerLogTaskBuild) string {
	hasLogs := false
	hasSpans := false
	hasMetrics := false
	for _, built := range tasks {
		if built.task.ProviderEventCount > 0 {
			hasLogs = true
		}
		if built.task.ProviderMetricCount > 0 {
			hasMetrics = true
		}
		if strings.Contains(built.task.MeasurementSource, "span") {
			hasSpans = true
		}
	}
	sourceCount := 0
	for _, present := range []bool{hasLogs, hasSpans, hasMetrics} {
		if present {
			sourceCount++
		}
	}
	if sourceCount > 1 {
		return "provider_telemetry"
	}
	if hasMetrics {
		return "provider_metrics"
	}
	if hasSpans {
		return "provider_spans"
	}
	return "provider_logs"
}

func groupProviderSpansByTraceID(spans []store.Span) map[string][]store.Span {
	result := make(map[string][]store.Span)
	spanIndexes := make(map[string]map[string]int)
	for _, span := range spans {
		if span.TraceID == "" {
			continue
		}
		group := result[span.TraceID]
		if span.SpanID != "" {
			indexes := spanIndexes[span.TraceID]
			if indexes == nil {
				indexes = make(map[string]int)
				spanIndexes[span.TraceID] = indexes
			}
			if index, duplicate := indexes[span.SpanID]; duplicate {
				group[index] = span
				result[span.TraceID] = group
				continue
			}
			indexes[span.SpanID] = len(group)
		}
		result[span.TraceID] = append(group, span)
	}
	return result
}

func buildProviderTraceIndex(spansByTraceID map[string][]store.Span) providerTraceIndex {
	index := providerTraceIndex{
		byTraceID:            make(map[string]providerTraceMetadata, len(spansByTraceID)),
		tasksByTraceID:       make(map[string][]*providerTraceMetadata),
		taskBySpan:           make(map[string]*providerTraceMetadata),
		taskByTurn:           make(map[string]*providerTraceMetadata),
		taskByPrompt:         make(map[string]*providerTraceMetadata),
		tasksByConversation:  make(map[string][]*providerTraceMetadata),
		evaluationIdentities: make(map[string]struct{}),
	}
	for traceID, spans := range spansByTraceID {
		normalizedTraceID := strings.ToLower(traceID)
		groups, boundaryOrder, spanAssignments := providerTaskSpanGroups(spans)
		traceMetadata := buildProviderTraceMetadata(normalizedTraceID, spans)
		for _, span := range spans {
			if _, evaluationOnly := traceMetadata.evaluationSpanIDs[span.SpanID]; !evaluationOnly {
				continue
			}
			provider := providerTaskBoundaryProvider(span)
			if provider == "" {
				provider = traceMetadata.provider
			}
			index.addEvaluationIdentity(normalizedTraceID, provider, "turn", firstStringAttribute(span.Attributes, "turn.id", "turn_id"))
			index.addEvaluationIdentity(normalizedTraceID, provider, "prompt", firstStringAttribute(span.Attributes, "prompt.id", "prompt_id"))
			index.addEvaluationIdentity(normalizedTraceID, provider, "conversation", firstStringAttribute(span.Attributes, "conversation.id", "thread.id", "session.id"))
		}
		if len(boundaryOrder) > 1 {
			clearProviderTaskMetadata(&traceMetadata)
		}
		index.byTraceID[normalizedTraceID] = traceMetadata
		tasksByBoundarySpanID := make(map[string]*providerTraceMetadata, len(boundaryOrder))

		for _, boundarySpanID := range boundaryOrder {
			if _, evaluationOnly := traceMetadata.evaluationSpanIDs[boundarySpanID]; evaluationOnly {
				continue
			}
			metadata := buildProviderTraceMetadata(normalizedTraceID, groups[boundarySpanID])
			// Keep full-trace evaluation ancestry so logs attached to a nested
			// provider boundary cannot fall back onto the enclosing agent task.
			metadata.evaluationSpanIDs = traceMetadata.evaluationSpanIDs
			metadata.boundarySpanID = boundarySpanID
			task := &metadata
			index.tasks = append(index.tasks, task)
			index.tasksByTraceID[normalizedTraceID] = append(index.tasksByTraceID[normalizedTraceID], task)
			tasksByBoundarySpanID[boundarySpanID] = task
			if metadata.turnID != "" {
				addUniqueProviderTask(index.taskByTurn, providerTraceKey(metadata.provider, metadata.turnID), task)
			}
			if metadata.promptID != "" {
				addUniqueProviderTask(index.taskByPrompt, providerTraceKey(metadata.provider, metadata.promptID), task)
			}
			if metadata.conversationID != "" && metadata.nativeTrace {
				key := providerTraceKey(metadata.provider, metadata.conversationID)
				index.tasksByConversation[key] = append(index.tasksByConversation[key], task)
			}
		}
		for spanID, assignedBoundary := range spanAssignments {
			if task := tasksByBoundarySpanID[assignedBoundary]; task != nil {
				index.taskBySpan[providerSpanKey(normalizedTraceID, spanID)] = task
			}
		}
		if len(index.tasksByTraceID[normalizedTraceID]) == 1 {
			index.byTraceID[normalizedTraceID] = *index.tasksByTraceID[normalizedTraceID][0]
		}
	}
	return index
}

func providerTaskSpanGroups(spans []store.Span) (map[string][]store.Span, []string, map[string]string) {
	groups := make(map[string][]store.Span)
	boundaryOrder := make([]string, 0)
	boundaryIDs := make(map[string]struct{})
	parentByID := make(map[string]string, len(spans))
	for _, span := range spans {
		parentByID[span.SpanID] = span.ParentSpanID
		if providerTaskBoundaryProvider(span) != "" && span.SpanID != "" {
			boundaryIDs[span.SpanID] = struct{}{}
			boundaryOrder = append(boundaryOrder, span.SpanID)
			groups[span.SpanID] = []store.Span{span}
		}
	}
	assignments := newSpanAncestryIndex(parentByID).nearestAncestorOrSelf(boundaryIDs)
	for _, span := range spans {
		boundaryID := assignments[span.SpanID]
		if boundaryID == "" {
			continue
		}
		if span.SpanID != boundaryID {
			groups[boundaryID] = append(groups[boundaryID], span)
		}
	}
	return groups, boundaryOrder, assignments
}

func buildProviderTraceMetadata(traceID string, spans []store.Span) providerTraceMetadata {
	metadata := providerTraceMetadata{
		traceID:           traceID,
		spanCount:         len(spans),
		evaluationSpanIDs: make(map[string]struct{}),
	}
	if len(spans) == 0 {
		return metadata
	}
	root := spans[0]
	metadata.startTime = spans[0].StartTime
	metadata.endTime = spans[0].EndTime
	parentByID := make(map[string]string, len(spans))
	evaluationRoots := make(map[string]struct{})
	skillSet := make(map[string]struct{})
	repositoryIdentities := make([]providerRepositoryIdentity, 0)
	boundaryProvider := ""
	boundarySpanName := ""
	for _, span := range spans {
		parentByID[span.SpanID] = span.ParentSpanID
		metadata.taskRetentionTruncated = metadata.taskRetentionTruncated || store.ProviderTaskSpanRetentionTruncated(span)
		if provider := providerTaskBoundaryProvider(span); provider != "" {
			metadata.nativeTrace = true
			metadata.taskComplete = true
			boundaryProvider = provider
			boundarySpanName = span.Name
			record := tokenUsageFromSpan(span)
			record.provider = provider
			metadata.taskRecord = &record
			metadata.taskRecords = []tokenUsageRecord{record}
			metadata.taskRequestCount = 1
			if record.observed || record.recognized {
				switch provider {
				case "codex":
					metadata.taskUsageSource = "codex_task_span"
					metadata.taskNormalization = "completed Codex task span; input includes cached input and cached/reasoning values are breakdowns"
				case "claude":
					metadata.taskUsageSource = "claude_interaction_span"
					metadata.taskNormalization = "completed Claude interaction span; input includes provider cache components and output is not adjusted"
				}
			}
			metadata.taskTotal = record.usage.ProviderTotalTokens
		} else if isNativeProviderSpanName(span.Name) {
			metadata.nativeTrace = true
		}
		if span.StartTime.Before(metadata.startTime) {
			metadata.startTime = span.StartTime
		}
		if span.EndTime.After(metadata.endTime) {
			metadata.endTime = span.EndTime
		}
		if span.ParentSpanID == "" && (root.ParentSpanID != "" || span.StartTime.Before(root.StartTime)) {
			root = span
		} else if root.ParentSpanID != "" && span.StartTime.Before(root.StartTime) {
			root = span
		}
		if store.IsGenAIEvaluationOnlySpan(span) {
			evaluationRoots[span.SpanID] = struct{}{}
		}
	}
	metadata.evaluationSpanIDs = newSpanAncestryIndex(parentByID).idsInBranches(evaluationRoots)
	for _, span := range spans {
		if _, excluded := metadata.evaluationSpanIDs[span.SpanID]; excluded {
			continue
		}
		if metadata.turnID == "" {
			metadata.turnID = firstStringAttribute(span.Attributes, "turn.id", "turn_id")
		}
		if metadata.promptID == "" {
			metadata.promptID = firstStringAttribute(span.Attributes, "prompt.id", "prompt_id")
		}
		if metadata.conversationID == "" {
			metadata.conversationID = firstStringAttribute(span.Attributes, "conversation.id", "thread.id", "session.id")
		}
		if cwd := firstStringAttribute(span.Attributes, "cwd", "working_directory", "workspace.path"); cwd != "" {
			repositoryIdentities = appendUniqueProviderRepositoryIdentity(
				repositoryIdentities,
				repositoryIdentityFromWorkingDirectory(cwd),
			)
		}
		addSkillNames(skillSet, span.Attributes)
		addSkillNames(skillSet, span.Resource.Attributes)
	}
	metadata.rootSpanName = root.Name
	if boundarySpanName != "" {
		metadata.rootSpanName = boundarySpanName
	}
	metadata.serviceName = root.Resource.ServiceName
	if len(repositoryIdentities) == 1 {
		identity := repositoryIdentities[0]
		metadata.repositoryName = identity.repositoryName
		metadata.repositoryPath = identity.repositoryPath
		metadata.workspacePath = identity.workspacePath
		metadata.repositoryCorrelationStatus = "task_correlated"
		metadata.repositoryCorrelationSource = "provider_task_span"
	} else if len(repositoryIdentities) > 1 {
		metadata.repositoryCorrelationStatus = "ambiguous"
	}
	metadata.provider = boundaryProvider
	if metadata.provider == "" {
		metadata.provider = providerTraceProvider(spans, root)
	}
	metadata.modelNames = modelNames(providerAgentMetadataSpans(spans, metadata.evaluationSpanIDs))
	if metadata.provider == "claude" && metadata.taskComplete {
		agentSpans := providerClaudeAgentSpans(spans, metadata.evaluationSpanIDs)
		metadata.taskRequestCount = providerClaudeRequestSpanCount(agentSpans)
		if metadata.taskRecord != nil && metadata.taskRecord.recognized {
			metadata.skillNames = sortedSet(skillSet)
			return metadata
		}
		selected, _ := selectTokenUsageSpans(agentSpans)
		records := make([]tokenUsageRecord, 0, len(selected))
		for _, span := range selected {
			record := tokenUsageFromSpan(span)
			record.provider = "claude"
			records = append(records, record)
		}
		if len(records) > 0 {
			var aggregate tokenUsageAccumulator
			aggregate.addTask(records)
			aggregatedRecord := tokenUsageRecord{
				observed:   aggregate.coverage.ObservedRecordCount > 0,
				recognized: aggregate.coverage.RecognizedRecordCount > 0,
				provider:   "claude",
				usage:      aggregate.values(),
			}
			metadata.taskRecord = &aggregatedRecord
			metadata.taskRecords = records
			metadata.taskRequestCount = len(records)
			metadata.taskUsageSource = "claude_request_spans"
			metadata.taskNormalization = "completed Claude interaction boundary with de-duplicated request-span usage; input includes provider cache components"
		}
	}
	metadata.skillNames = sortedSet(skillSet)
	return metadata
}

func providerClaudeAgentSpans(spans []store.Span, evaluationSpanIDs map[string]struct{}) []store.Span {
	selected := make([]store.Span, 0, len(spans))
	for _, span := range spans {
		if _, excluded := evaluationSpanIDs[span.SpanID]; excluded {
			continue
		}
		if store.IsGenAISpan(span) || strings.HasPrefix(strings.ToLower(strings.TrimSpace(span.Name)), "claude_code.") {
			selected = append(selected, span)
		}
	}
	return selected
}

func providerClaudeRequestSpanCount(spans []store.Span) int {
	parentByID := make(map[string]string, len(spans))
	requestIDs := make(map[string]struct{})
	for _, span := range spans {
		parentByID[span.SpanID] = span.ParentSpanID
		name := strings.ToLower(strings.TrimSpace(span.Name))
		if store.ClassifyGenAISpan(span) == store.GenAISpanLLM ||
			(strings.HasPrefix(name, "claude_code.") && (strings.Contains(name, "llm") || strings.Contains(name, "api_request"))) {
			requestIDs[span.SpanID] = struct{}{}
		}
	}
	withDescendants := newSpanAncestryIndex(parentByID).candidatesWithDescendants(requestIDs)
	count := 0
	for spanID := range requestIDs {
		if _, hasDescendant := withDescendants[spanID]; !hasDescendant {
			count++
		}
	}
	return count
}

func clearProviderTaskMetadata(metadata *providerTraceMetadata) {
	metadata.boundarySpanID = ""
	metadata.taskComplete = false
	metadata.taskTotal = nil
	metadata.taskRecord = nil
	metadata.taskRecords = nil
	metadata.taskRequestCount = 0
	metadata.taskUsageSource = ""
	metadata.taskNormalization = ""
	metadata.turnID = ""
	metadata.promptID = ""
	metadata.conversationID = ""
	metadata.skillNames = nil
	metadata.modelNames = nil
}

func providerAgentMetadataSpans(spans []store.Span, evaluationSpanIDs map[string]struct{}) []store.Span {
	selected := filterAgentTaskSpans(spans)
	selectedIDs := make(map[string]struct{}, len(selected))
	for _, span := range selected {
		selectedIDs[span.SpanID] = struct{}{}
	}
	for _, span := range spans {
		if providerTaskBoundaryProvider(span) == "" {
			continue
		}
		if _, excluded := evaluationSpanIDs[span.SpanID]; excluded {
			continue
		}
		if _, exists := selectedIDs[span.SpanID]; exists {
			continue
		}
		selected = append(selected, span)
	}
	return selected
}

func (index providerTraceIndex) correlate(event providerLogTokenEvent) providerLogTokenEvent {
	task := index.taskForEvent(event)
	if task == nil {
		return event
	}
	event.traceID = task.traceID
	event.boundarySpanID = task.boundarySpanID
	return event
}

func (index providerTraceIndex) metadataForEvent(event providerLogTokenEvent) providerTraceMetadata {
	if task := index.taskForEvent(event); task != nil {
		return *task
	}
	traceID := strings.ToLower(strings.TrimSpace(event.traceID))
	metadata := index.byTraceID[traceID]
	if len(index.tasksByTraceID[traceID]) > 0 {
		clearProviderTaskMetadata(&metadata)
	}
	return metadata
}

func (index providerTraceIndex) referencesEvaluationIdentity(event providerLogTokenEvent) bool {
	traceID := strings.ToLower(strings.TrimSpace(event.traceID))
	if traceID == "" {
		return false
	}
	if event.turnID != "" {
		return index.hasEvaluationIdentity(traceID, event.provider, "turn", event.turnID)
	}
	if event.promptID != "" {
		return index.hasEvaluationIdentity(traceID, event.provider, "prompt", event.promptID)
	}
	return index.hasEvaluationIdentity(traceID, event.provider, "conversation", event.conversationID)
}

func (index providerTraceIndex) addEvaluationIdentity(traceID, provider, kind, id string) {
	if id == "" {
		return
	}
	index.evaluationIdentities[providerEvaluationIdentityKey(traceID, provider, kind, id)] = struct{}{}
}

func (index providerTraceIndex) hasEvaluationIdentity(traceID, provider, kind, id string) bool {
	if id == "" {
		return false
	}
	_, excluded := index.evaluationIdentities[providerEvaluationIdentityKey(traceID, provider, kind, id)]
	return excluded
}

func (index providerTraceIndex) taskForEvent(event providerLogTokenEvent) *providerTraceMetadata {
	traceID := strings.ToLower(strings.TrimSpace(event.traceID))
	if traceID != "" && event.boundarySpanID != "" {
		if task := index.taskBySpan[providerSpanKey(traceID, event.boundarySpanID)]; task != nil {
			return task
		}
	}
	if traceID != "" && event.log.SpanID != "" {
		if task := index.taskBySpan[providerSpanKey(traceID, event.log.SpanID)]; task != nil {
			return task
		}
	}
	if event.turnID != "" {
		if task := index.taskByTurn[providerTraceKey(event.provider, event.turnID)]; task != nil {
			return task
		}
	}
	if event.promptID != "" {
		if task := index.taskByPrompt[providerTraceKey(event.provider, event.promptID)]; task != nil {
			return task
		}
	}
	if traceID != "" {
		if task := providerTaskAtTime(index.tasksByTraceID[traceID], traceID, event.timestamp); task != nil {
			return task
		}
	}
	if event.conversationID != "" {
		candidates := index.tasksByConversation[providerTraceKey(event.provider, event.conversationID)]
		if task := providerTaskAtTime(candidates, traceID, event.timestamp); task != nil {
			return task
		}
	}
	return nil
}

func providerTaskAtTime(candidates []*providerTraceMetadata, traceID string, timestamp time.Time) *providerTraceMetadata {
	if timestamp.IsZero() {
		return nil
	}
	var matched *providerTraceMetadata
	var matchedDuration time.Duration
	ambiguous := false
	for _, candidate := range candidates {
		if candidate == nil || (traceID != "" && candidate.traceID != traceID) {
			continue
		}
		if candidate.startTime.IsZero() || candidate.endTime.IsZero() ||
			timestamp.Before(candidate.startTime) || timestamp.After(candidate.endTime) {
			continue
		}
		duration := candidate.endTime.Sub(candidate.startTime)
		if matched == nil || duration < matchedDuration {
			matched = candidate
			matchedDuration = duration
			ambiguous = false
			continue
		}
		if duration == matchedDuration && candidate != matched {
			ambiguous = true
		}
	}
	if ambiguous {
		return nil
	}
	return matched
}

func addUniqueProviderTask(values map[string]*providerTraceMetadata, key string, task *providerTraceMetadata) {
	if key == "" || task == nil {
		return
	}
	if existing, ok := values[key]; !ok {
		values[key] = task
	} else if existing != task {
		values[key] = nil
	}
}

func providerSpanKey(traceID, spanID string) string {
	return strings.ToLower(strings.TrimSpace(traceID)) + "\x00" + strings.ToLower(strings.TrimSpace(spanID))
}

func providerTraceKey(provider, id string) string {
	return provider + "\x00" + strings.ToLower(strings.TrimSpace(id))
}

func providerEvaluationIdentityKey(traceID, provider, kind, id string) string {
	return strings.Join([]string{
		strings.ToLower(strings.TrimSpace(traceID)),
		strings.ToLower(strings.TrimSpace(provider)),
		kind,
		strings.ToLower(strings.TrimSpace(id)),
	}, "\x00")
}

func providerTraceProvider(spans []store.Span, root store.Span) string {
	rootName := strings.ToLower(strings.TrimSpace(root.Name))
	if strings.HasPrefix(rootName, "claude_code.") {
		return "claude"
	}
	if rootName == "session_task" || strings.HasPrefix(rootName, "session_task.") {
		return "codex"
	}
	for _, span := range spans {
		identity := strings.ToLower(strings.Join([]string{
			span.Resource.ServiceName,
			span.Scope.Name,
			firstStringAttribute(span.Attributes, "gen_ai.provider.name", "model"),
		}, " "))
		if strings.Contains(identity, "claude") || strings.Contains(identity, "anthropic") {
			return "claude"
		}
		if strings.Contains(identity, "codex") || strings.Contains(identity, "openai") {
			return "codex"
		}
	}
	return ""
}

func providerTaskBoundaryProvider(span store.Span) string {
	return store.ProviderTaskBoundaryProvider(span)
}

func isNativeProviderSpanName(name string) bool {
	name = strings.ToLower(strings.TrimSpace(name))
	return strings.HasPrefix(name, "claude_code.") ||
		name == "session_task" ||
		strings.HasPrefix(name, "session_task.")
}

func enrichProviderTokenEvent(event providerLogTokenEvent, metadata providerTraceMetadata) providerLogTokenEvent {
	if event.turnID == "" {
		event.turnID = metadata.turnID
	}
	if event.promptID == "" {
		event.promptID = metadata.promptID
	}
	if event.conversationID == "" {
		event.conversationID = metadata.conversationID
	}
	skillSet := make(map[string]struct{})
	for _, name := range append(event.skillNames, metadata.skillNames...) {
		if name != "" {
			skillSet[name] = struct{}{}
		}
	}
	event.skillNames = sortedSet(skillSet)
	switch {
	case event.provider == "codex" && event.turnID != "":
		event.taskID = event.turnID
		event.taskKind = "turn"
		event.fallbackTask = false
	case event.provider == "claude" && event.promptID != "":
		event.taskID = event.promptID
		event.taskKind = "prompt"
		event.fallbackTask = false
	case event.fallbackTask && event.conversationID != "":
		event.taskID = event.conversationID
		event.taskKind = "conversation"
		event.fallbackTask = false
	case event.fallbackTask && event.traceID != "":
		event.taskID = event.traceID
		event.taskKind = "trace"
	}
	return event
}

func isEvaluationProviderEvent(event providerLogTokenEvent, metadata providerTraceMetadata) bool {
	for key := range event.log.Attributes {
		if strings.HasPrefix(strings.ToLower(key), "gen_ai.evaluation.") {
			return true
		}
	}
	if event.log.SpanID == "" {
		return false
	}
	_, excluded := metadata.evaluationSpanIDs[event.log.SpanID]
	return excluded
}

func addSkillNames(values map[string]struct{}, attributes map[string]any) {
	for _, key := range []string{"skill.name", "claude_code.skill.name", "gen_ai.agent.skill.name"} {
		switch value := attributes[key].(type) {
		case string:
			if trimmed := strings.TrimSpace(value); trimmed != "" {
				values[trimmed] = struct{}{}
			}
		case []string:
			for _, item := range value {
				if trimmed := strings.TrimSpace(item); trimmed != "" {
					values[trimmed] = struct{}{}
				}
			}
		case []any:
			for _, item := range value {
				if text, ok := item.(string); ok {
					if trimmed := strings.TrimSpace(text); trimmed != "" {
						values[trimmed] = struct{}{}
					}
				}
			}
		}
	}
}

func containsFold(values []string, want string) bool {
	for _, value := range values {
		if strings.EqualFold(value, want) {
			return true
		}
	}
	return false
}

func reconcileProviderTaskEvents(
	events []providerLogTokenEvent,
	metadata providerTraceMetadata,
	logWindowComplete bool,
) ([]providerLogTokenEvent, bool) {
	if len(events) == 0 {
		return events, true
	}
	if events[0].provider == "claude" {
		return reconcileClaudeTaskEvents(events, metadata, logWindowComplete)
	}
	if events[0].provider != "codex" {
		return events, true
	}
	events = dropCodexMetadataCompanions(events)
	if metadata.taskTotal == nil {
		return events, false
	}

	totals := make([]*int64, 0, len(events))
	for _, event := range events {
		totals = append(totals, event.record.usage.EffectiveTotalTokens)
	}
	if summed := addKnownTokens(totals...); summed != nil && *summed == *metadata.taskTotal {
		return events, true
	}
	for index := len(events) - 1; index >= 0; index-- {
		total := events[index].record.usage.EffectiveTotalTokens
		if total == nil || *total != *metadata.taskTotal {
			continue
		}
		selected := events[index]
		selected.normalization += "; selected the provider record matching the completed Codex turn total instead of adding earlier cumulative or startup records"
		return []providerLogTokenEvent{selected}, true
	}
	if metadata.taskRecord != nil && metadata.taskRecord.usage.EffectiveTotalTokens != nil {
		selected := events[len(events)-1]
		selected.timestamp = metadata.endTime
		selected.record = *metadata.taskRecord
		selected.source = metadata.taskUsageSource
		selected.normalization = metadata.taskNormalization + "; retained provider logs did not reconcile and were not added to the task span"
		if selected.model == "" && len(metadata.modelNames) > 0 {
			selected.model = metadata.modelNames[0]
		}
		return []providerLogTokenEvent{selected}, true
	}
	return events, false
}

func reconcileClaudeTaskEvents(
	events []providerLogTokenEvent,
	metadata providerTraceMetadata,
	logWindowComplete bool,
) ([]providerLogTokenEvent, bool) {
	if !metadata.taskComplete || metadata.provider != "claude" {
		return events, true
	}
	stableIdentities := providerEventsHaveStableIdentity(events)
	if metadata.taskRetentionTruncated && metadata.taskUsageSource == "claude_request_spans" {
		if !logWindowComplete || !stableIdentities {
			events[0].normalization += "; compact task-span retention was incomplete and retained provider logs could not prove the full request window"
		}
		return markIdentifierlessClaudeEventsUncertain(events, logWindowComplete && stableIdentities)
	}
	if len(metadata.taskRecords) == 0 {
		reconciled := logWindowComplete
		if metadata.taskRequestCount > 0 {
			reconciled = len(events) == metadata.taskRequestCount
		}
		return markIdentifierlessClaudeEventsUncertain(events, reconciled && stableIdentities)
	}
	var eventAggregate tokenUsageAccumulator
	eventRecords := make([]tokenUsageRecord, 0, len(events))
	for _, event := range events {
		eventRecords = append(eventRecords, event.record)
	}
	eventAggregate.addTask(eventRecords)
	var spanAggregate tokenUsageAccumulator
	spanAggregate.addTask(metadata.taskRecords)
	eventTotal := eventAggregate.values().EffectiveTotalTokens
	spanTotal := spanAggregate.values().EffectiveTotalTokens
	requestCountMatches := metadata.taskUsageSource != "claude_request_spans" || len(events) == metadata.taskRequestCount
	if eventTotal != nil && spanTotal != nil && *eventTotal == *spanTotal && requestCountMatches && stableIdentities {
		return events, true
	}
	if spanTotal == nil {
		reconciled := logWindowComplete
		if metadata.taskRequestCount > 0 {
			reconciled = len(events) == metadata.taskRequestCount
		}
		return markIdentifierlessClaudeEventsUncertain(events, reconciled && stableIdentities)
	}

	reconciled := make([]providerLogTokenEvent, 0, len(metadata.taskRecords))
	for index, record := range metadata.taskRecords {
		selected := events[len(events)-1]
		selected.timestamp = metadata.endTime.Add(time.Duration(index-len(metadata.taskRecords)+1) * time.Nanosecond)
		selected.record = record
		selected.source = metadata.taskUsageSource
		selected.normalization = metadata.taskNormalization + "; retained provider logs did not reconcile and were not added to the task spans"
		if selected.model == "" && len(metadata.modelNames) > 0 {
			selected.model = metadata.modelNames[0]
		}
		reconciled = append(reconciled, selected)
	}
	return reconciled, true
}

func providerEventsHaveStableIdentity(events []providerLogTokenEvent) bool {
	if len(events) == 0 {
		return false
	}
	for _, event := range events {
		if !event.stableIdentity {
			return false
		}
	}
	return true
}

func markIdentifierlessClaudeEventsUncertain(events []providerLogTokenEvent, reconciled bool) ([]providerLogTokenEvent, bool) {
	if reconciled || len(events) == 0 || providerEventsHaveStableIdentity(events) {
		return events, reconciled
	}
	events[0].normalization += "; provider request identity was absent, so retained records could include indistinguishable OTLP retransmissions"
	return events, false
}

func providerLogWindowComplete(metadata providerTraceMetadata, unavailableThrough time.Time) bool {
	if unavailableThrough.IsZero() {
		return true
	}
	return !metadata.startTime.IsZero() && metadata.startTime.After(unavailableThrough)
}

func dropCodexMetadataCompanions(events []providerLogTokenEvent) []providerLogTokenEvent {
	usageKeys := make(map[string]struct{})
	for _, event := range events {
		if !event.record.observed || event.timestamp.IsZero() || event.conversationID == "" {
			continue
		}
		usageKeys[codexCompanionKey(event)] = struct{}{}
	}
	if len(usageKeys) == 0 {
		return events
	}
	filtered := make([]providerLogTokenEvent, 0, len(events))
	for _, event := range events {
		if !event.record.observed && !event.timestamp.IsZero() && event.conversationID != "" {
			if _, duplicate := usageKeys[codexCompanionKey(event)]; duplicate {
				continue
			}
		}
		filtered = append(filtered, event)
	}
	return filtered
}

func codexCompanionKey(event providerLogTokenEvent) string {
	return strings.Join([]string{
		strings.ToLower(event.conversationID),
		event.timestamp.UTC().Format(time.RFC3339Nano),
	}, "\x00")
}

func providerTaskCorrelationStatus(event providerLogTokenEvent, metadata providerTraceMetadata, usageReconciled bool) string {
	if event.traceID != "" && metadata.spanCount > 0 {
		if !metadata.taskComplete {
			return "trace_incomplete"
		}
		if metadata.provider != event.provider {
			return "trace_provider_mismatch"
		}
		if event.source == "claude_request_spans" {
			return "trace_request_window_incomplete"
		}
		if !usageReconciled {
			if metadata.taskRetentionTruncated {
				return "trace_retention_incomplete"
			}
			return "trace_usage_mismatch"
		}
		return "trace_correlated"
	}
	if event.traceID != "" {
		return "trace_id"
	}
	if !event.fallbackTask {
		return "provider_task"
	}
	return "uncorrelated"
}

func providerTaskAccountingStatus(status, correlationStatus string) string {
	if correlationStatus == "trace_retention_incomplete" || correlationStatus == "trace_request_window_incomplete" {
		return "partial"
	}
	switch status {
	case "measured":
		if correlationStatus == "trace_correlated" {
			return "exact"
		}
		return "uncorrelated"
	case "partial":
		return "partial"
	default:
		return "unknown"
	}
}

func providerTokenEvent(logRecord store.LogRecord) (providerLogTokenEvent, bool) {
	if isCodexTokenEvent(logRecord) {
		return codexTokenEvent(logRecord), true
	}
	if isClaudeTokenEvent(logRecord) {
		return claudeTokenEvent(logRecord), true
	}
	return providerLogTokenEvent{}, false
}

func isCodexTokenEvent(logRecord store.LogRecord) bool {
	return store.ClassifyProviderUsageLog(logRecord) == store.ProviderUsageLogCodex
}

func isClaudeTokenEvent(logRecord store.LogRecord) bool {
	return store.ClassifyProviderUsageLog(logRecord) == store.ProviderUsageLogClaude
}

func codexTokenEvent(logRecord store.LogRecord) providerLogTokenEvent {
	attrs := logRecord.Attributes
	timestamp := providerLogTimestamp(logRecord)
	input, _ := firstTokenAttribute(attrs, codexInputTokenLogKeys)
	cached, _ := firstTokenAttribute(attrs, codexCachedInputTokenLogKeys)
	cacheCreation, _ := firstTokenAttribute(attrs, codexCacheCreationInputTokenLogKeys)
	output, _ := firstTokenAttribute(attrs, codexOutputTokenLogKeys)
	reasoning, _ := firstTokenAttribute(attrs, codexReasoningOutputTokenLogKeys)
	providerTotal, _ := firstTokenAttribute(attrs, codexProviderTotalTokenLogKeys)
	usage := normalizedTokenUsage(input, cached, cacheCreation, output, reasoning, providerTotal)
	record := tokenUsageRecord{
		observed: hasAnyTokenAttribute(
			attrs,
			codexInputTokenLogKeys,
			codexCachedInputTokenLogKeys,
			codexCacheCreationInputTokenLogKeys,
			codexOutputTokenLogKeys,
			codexReasoningOutputTokenLogKeys,
			codexProviderTotalTokenLogKeys,
		),
		recognized: hasRecognizedTokenValue(usage),
		provider:   "codex",
		usage:      usage,
	}
	turnID := firstStringAttribute(attrs, "turn.id", "turn_id")
	conversationID := firstStringAttribute(attrs, "conversation.id", "thread.id", "session.id")
	taskID := turnID
	taskKind := "turn"
	if taskID == "" {
		taskID = conversationID
		taskKind = "conversation"
	}
	fallbackTask := taskID == ""
	if taskID == "" {
		taskID = fallbackProviderTaskID(logRecord, timestamp)
	}
	skills := make(map[string]struct{})
	addSkillNames(skills, attrs)
	addSkillNames(skills, logRecord.Resource.Attributes)
	dedupeKey, stableIdentity := providerEventDedupeKey("codex", logRecord, timestamp, record)
	return providerLogTokenEvent{
		log:            logRecord,
		timestamp:      timestamp,
		provider:       "codex",
		taskID:         taskID,
		taskKind:       taskKind,
		fallbackTask:   fallbackTask,
		traceID:        strings.ToLower(strings.TrimSpace(logRecord.TraceID)),
		turnID:         turnID,
		conversationID: conversationID,
		skillNames:     sortedSet(skills),
		dedupeKey:      dedupeKey,
		stableIdentity: stableIdentity,
		model:          firstStringAttribute(attrs, "model", "gen_ai.response.model", "gen_ai.request.model"),
		record:         record,
		normalization:  "input includes cached input; cached and reasoning values are provider breakdowns and are not added again",
		source:         "codex_response_completed_logs",
	}
}

func claudeTokenEvent(logRecord store.LogRecord) providerLogTokenEvent {
	attrs := logRecord.Attributes
	timestamp := providerLogTimestamp(logRecord)
	uncachedInput, _ := firstTokenAttribute(attrs, claudeInputTokenLogKeys)
	cached, _ := firstTokenAttribute(attrs, claudeCachedInputTokenLogKeys)
	cacheCreation, _ := firstTokenAttribute(attrs, claudeCacheCreationInputTokenLogKeys)
	input := addKnownTokens(uncachedInput, cached, cacheCreation)
	output, _ := firstTokenAttribute(attrs, claudeOutputTokenLogKeys)
	reasoning, _ := firstTokenAttribute(attrs, claudeReasoningOutputTokenLogKeys)
	providerTotal, _ := firstTokenAttribute(attrs, claudeProviderTotalTokenLogKeys)
	usage := normalizedTokenUsage(input, cached, cacheCreation, output, reasoning, providerTotal)
	record := tokenUsageRecord{
		observed: hasAnyTokenAttribute(
			attrs,
			claudeInputTokenLogKeys,
			claudeCachedInputTokenLogKeys,
			claudeCacheCreationInputTokenLogKeys,
			claudeOutputTokenLogKeys,
			claudeReasoningOutputTokenLogKeys,
			claudeProviderTotalTokenLogKeys,
		),
		recognized: hasRecognizedTokenValue(usage),
		provider:   "claude",
		usage:      usage,
	}
	promptID := firstStringAttribute(attrs, "prompt.id", "prompt_id")
	taskID := promptID
	taskKind := "prompt"
	conversationID := firstStringAttribute(attrs, "session.id", "conversation.id")
	if taskID == "" {
		taskID = conversationID
		taskKind = "session"
	}
	fallbackTask := taskID == ""
	if taskID == "" {
		taskID = fallbackProviderTaskID(logRecord, timestamp)
		taskKind = "request"
	}
	skills := make(map[string]struct{})
	addSkillNames(skills, attrs)
	addSkillNames(skills, logRecord.Resource.Attributes)
	dedupeKey, stableIdentity := providerEventDedupeKey("claude", logRecord, timestamp, record)
	return providerLogTokenEvent{
		log:            logRecord,
		timestamp:      timestamp,
		provider:       "claude",
		taskID:         taskID,
		taskKind:       taskKind,
		fallbackTask:   fallbackTask,
		traceID:        strings.ToLower(strings.TrimSpace(logRecord.TraceID)),
		promptID:       promptID,
		conversationID: conversationID,
		skillNames:     sortedSet(skills),
		dedupeKey:      dedupeKey,
		stableIdentity: stableIdentity,
		model:          firstStringAttribute(attrs, "model", "gen_ai.response.model", "gen_ai.request.model"),
		record:         record,
		normalization:  "input is derived from uncached input plus cache-read and cache-creation input; output is not adjusted",
		source:         "claude_api_request_logs",
	}
}

func normalizedTokenUsage(input, cached, cacheCreation, output, reasoning, providerTotal *int64) tokenUsageValues {
	derivedTotal := addKnownTokens(input, output)
	effectiveTotal := providerTotal
	if effectiveTotal == nil {
		effectiveTotal = derivedTotal
	}
	return tokenUsageValues{
		InputTokens:              input,
		CachedInputTokens:        cached,
		CacheCreationInputTokens: cacheCreation,
		OutputTokens:             output,
		ReasoningOutputTokens:    reasoning,
		ProviderTotalTokens:      providerTotal,
		DerivedTotalTokens:       derivedTotal,
		EffectiveTotalTokens:     effectiveTotal,
	}
}

func providerEventDedupeKey(provider string, logRecord store.LogRecord, timestamp time.Time, record tokenUsageRecord) (string, bool) {
	attrs := logRecord.Attributes
	identifierKeys := []string{"request.id", "request_id", "client_request_id", "client.request.id"}
	if provider == "codex" {
		identifierKeys = append([]string{"response.id", "response_id", "event.id", "event.sequence"}, identifierKeys...)
	}
	for _, key := range identifierKeys {
		if value := firstStringAttribute(attrs, key); value != "" {
			return key + ":" + value, true
		}
		if value, ok := nonNegativeInt64(attrs[key]); ok {
			return key + ":" + fmt.Sprint(value), true
		}
	}
	if logRecord.ID != "" {
		return "observer.log.id:" + logRecord.ID, false
	}
	return fmt.Sprintf("fallback:%d:%s:%s", timestamp.UnixNano(), firstStringAttribute(attrs, "model"), tokenUsageFingerprint(record.usage)), false
}

func tokenUsageFingerprint(usage tokenUsageValues) string {
	values := []*int64{
		usage.InputTokens,
		usage.CachedInputTokens,
		usage.CacheCreationInputTokens,
		usage.OutputTokens,
		usage.ReasoningOutputTokens,
		usage.ProviderTotalTokens,
	}
	parts := make([]string, len(values))
	for i, value := range values {
		if value == nil {
			parts[i] = "?"
		} else {
			parts[i] = fmt.Sprint(*value)
		}
	}
	return strings.Join(parts, ",")
}

func fallbackProviderTaskID(logRecord store.LogRecord, timestamp time.Time) string {
	if logRecord.ID != "" {
		return logRecord.ID
	}
	return fmt.Sprintf("event-%d", timestamp.UnixNano())
}

func providerLogTimestamp(logRecord store.LogRecord) time.Time {
	return store.LogEventTimestamp(logRecord)
}

func hasAnyTokenAttribute(attrs map[string]any, keyGroups ...[]string) bool {
	for _, keys := range keyGroups {
		for _, key := range keys {
			if _, exists := attrs[key]; exists {
				return true
			}
		}
	}
	for key := range attrs {
		normalized := strings.ToLower(strings.TrimSpace(key))
		if strings.HasSuffix(normalized, "_token_count") || strings.HasSuffix(normalized, ".token_count") {
			return true
		}
	}
	return false
}

func firstStringAttribute(attrs map[string]any, keys ...string) string {
	for _, key := range keys {
		if value := stringAttribute(attrs, key); value != "" {
			return value
		}
	}
	return ""
}

func stringAttribute(attrs map[string]any, key string) string {
	value, ok := attrs[key].(string)
	if !ok {
		return ""
	}
	return strings.TrimSpace(value)
}

func formatTokenUsageTime(value time.Time) string {
	if value.IsZero() || value.UnixNano() <= 0 {
		return ""
	}
	return value.UTC().Format("2006-01-02T15:04:05.000000000Z")
}
