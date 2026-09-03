package mcp

import (
	"math"
	"sort"
	"strconv"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/store"
)

var (
	normalizedInputTokenKeys = []string{
		"gen_ai.usage.input_tokens",
		"gen_ai.usage.prompt_tokens",
		"llm.token_count.prompt",
		"openai.usage.prompt_tokens",
		"ai.usage.input_tokens",
		"codex.turn.token_usage.input_tokens",
		"codex.usage.input_tokens",
		"prompt_tokens",
	}
	rawInputTokenKeys    = []string{"input_tokens", "input_token_count"}
	cachedInputTokenKeys = []string{
		"gen_ai.usage.cached_input_tokens",
		"gen_ai.usage.cache_read_input_tokens",
		"gen_ai.usage.input_tokens_details.cached_tokens",
		"gen_ai.usage.prompt_tokens_details.cached_tokens",
		"openai.usage.prompt_tokens_details.cached_tokens",
		"gen_ai.usage.cache_read.input_tokens",
		"codex.turn.token_usage.cached_input_tokens",
		"codex.usage.cached_input_tokens",
		"cached_input_tokens",
		"cache_read_input_tokens",
		"cache_read_tokens",
		"cached_token_count",
	}
	cacheCreationInputTokenKeys = []string{
		"gen_ai.usage.cache_creation_input_tokens",
		"gen_ai.usage.cache_write_input_tokens",
		"gen_ai.usage.input_tokens_details.cache_write_tokens",
		"gen_ai.usage.prompt_tokens_details.cache_write_tokens",
		"codex.turn.token_usage.cache_creation_input_tokens",
		"codex.turn.token_usage.cache_write_input_tokens",
		"codex.usage.cache_creation_input_tokens",
		"codex.usage.cache_write_input_tokens",
		"cache_creation_input_tokens",
		"cache_write_input_tokens",
		"cache_write_tokens",
		"cache_creation_tokens",
		"cache_creation_input_token_count",
	}
	outputTokenKeys = []string{
		"gen_ai.usage.output_tokens",
		"gen_ai.usage.completion_tokens",
		"llm.token_count.completion",
		"openai.usage.completion_tokens",
		"ai.usage.output_tokens",
		"codex.turn.token_usage.output_tokens",
		"codex.usage.output_tokens",
		"completion_tokens",
		"output_tokens",
		"output_token_count",
	}
	reasoningOutputTokenKeys = []string{
		"gen_ai.usage.reasoning_output_tokens",
		"gen_ai.usage.reasoning_tokens",
		"gen_ai.usage.output_tokens_details.reasoning_tokens",
		"gen_ai.usage.output_tokens_details.thinking_tokens",
		"openai.usage.completion_tokens_details.reasoning_tokens",
		"codex.turn.token_usage.reasoning_output_tokens",
		"codex.usage.reasoning_output_tokens",
		"reasoning_output_tokens",
		"reasoning_tokens",
		"thinking_tokens",
		"reasoning_token_count",
	}
	providerTotalTokenKeys = []string{
		"gen_ai.usage.total_tokens",
		"llm.token_count.total",
		"openai.usage.total_tokens",
		"ai.usage.total_tokens",
		"codex.turn.token_usage.total_tokens",
		"codex.usage.total_tokens",
		"total_tokens",
		"total_token_count",
		"tool_token_count",
	}
	providerKeys = []string{
		"gen_ai.provider.name",
		"gen_ai.system",
		"llm.provider",
		"provider",
	}
	modelKeys = []string{
		"gen_ai.response.model",
		"gen_ai.request.model",
		"openai.response.model",
		"openai.request.model",
		"llm.request.model",
		"llm.model_name",
		"ai.model.id",
		"model",
	}
)

type tokenUsageValues struct {
	InputTokens              *int64 `json:"inputTokens"`
	CachedInputTokens        *int64 `json:"cachedInputTokens"`
	CacheCreationInputTokens *int64 `json:"cacheCreationInputTokens"`
	OutputTokens             *int64 `json:"outputTokens"`
	ReasoningOutputTokens    *int64 `json:"reasoningOutputTokens"`
	ProviderTotalTokens      *int64 `json:"providerTotalTokens"`
	DerivedTotalTokens       *int64 `json:"derivedTotalTokens"`
	EffectiveTotalTokens     *int64 `json:"effectiveTotalTokens"`
}

type tokenUsageFieldCounts struct {
	InputTokens              int `json:"inputTokens"`
	CachedInputTokens        int `json:"cachedInputTokens"`
	CacheCreationInputTokens int `json:"cacheCreationInputTokens"`
	OutputTokens             int `json:"outputTokens"`
	ReasoningOutputTokens    int `json:"reasoningOutputTokens"`
	ProviderTotalTokens      int `json:"providerTotalTokens"`
	DerivedTotalTokens       int `json:"derivedTotalTokens"`
}

type tokenUsageCoverage struct {
	TaskCount                int                   `json:"taskCount"`
	ObservedTaskCount        int                   `json:"observedTaskCount"`
	RecognizedTaskCount      int                   `json:"recognizedTaskCount"`
	EffectiveTotalTaskCount  int                   `json:"effectiveTotalTaskCount"`
	TraceCount               int                   `json:"traceCount"`
	ObservedTraceCount       int                   `json:"observedTraceCount"`
	RecognizedTraceCount     int                   `json:"recognizedTraceCount"`
	EffectiveTotalTraceCount int                   `json:"effectiveTotalTraceCount"`
	RecordCount              int                   `json:"recordCount"`
	ObservedRecordCount      int                   `json:"observedRecordCount"`
	RecognizedRecordCount    int                   `json:"recognizedRecordCount"`
	EffectiveTotalCount      int                   `json:"effectiveTotalCount"`
	FieldCounts              tokenUsageFieldCounts `json:"fieldCounts"`
}

type tokenUsageTrace struct {
	TraceID           string             `json:"traceId"`
	RootSpanName      string             `json:"rootSpanName"`
	ServiceName       string             `json:"serviceName,omitempty"`
	StartTime         string             `json:"startTime"`
	MeasurementSource string             `json:"measurementSource"`
	Status            string             `json:"status"`
	AccountingStatus  string             `json:"accountingStatus"`
	Providers         []string           `json:"providers"`
	ModelNames        []string           `json:"modelNames"`
	LLMCalls          int                `json:"llmCalls"`
	ToolCalls         int                `json:"toolCalls"`
	Usage             tokenUsageValues   `json:"usage"`
	Coverage          tokenUsageCoverage `json:"coverage"`
}

type tokenUsageTask struct {
	TaskID                      string             `json:"taskId"`
	TaskKind                    string             `json:"taskKind"`
	TraceID                     string             `json:"traceId,omitempty"`
	RootSpanName                string             `json:"rootSpanName,omitempty"`
	TurnID                      string             `json:"turnId,omitempty"`
	PromptID                    string             `json:"promptId,omitempty"`
	ConversationID              string             `json:"conversationId,omitempty"`
	ServiceName                 string             `json:"serviceName,omitempty"`
	RepositoryName              string             `json:"repositoryName,omitempty"`
	RepositoryPath              string             `json:"repositoryPath,omitempty"`
	WorkspacePath               string             `json:"workspacePath,omitempty"`
	RepositoryCorrelationStatus string             `json:"repositoryCorrelationStatus"`
	RepositoryCorrelationSource string             `json:"repositoryCorrelationSource,omitempty"`
	StartTime                   string             `json:"startTime"`
	EndTime                     string             `json:"endTime"`
	MeasurementSource           string             `json:"measurementSource"`
	Normalization               string             `json:"normalization"`
	Status                      string             `json:"status"`
	AccountingStatus            string             `json:"accountingStatus"`
	CorrelationStatus           string             `json:"correlationStatus"`
	Provider                    string             `json:"provider"`
	SkillNames                  []string           `json:"skillNames"`
	ModelNames                  []string           `json:"modelNames"`
	RequestCount                int                `json:"requestCount"`
	ProviderEventCount          int                `json:"providerEventCount"`
	ProviderMetricCount         int                `json:"providerMetricCount"`
	TraceSpanCount              int                `json:"traceSpanCount"`
	TraceComplete               bool               `json:"traceComplete"`
	Usage                       tokenUsageValues   `json:"usage"`
	Coverage                    tokenUsageCoverage `json:"coverage"`
}

type tokenUsageOverviewResult struct {
	Scope                       string                       `json:"scope"`
	Retention                   string                       `json:"retention"`
	MeasurementSource           string                       `json:"measurementSource"`
	Status                      string                       `json:"status"`
	AccountingStatus            string                       `json:"accountingStatus"`
	RepositoryCorrelationStatus string                       `json:"repositoryCorrelationStatus"`
	RepositoryFilter            *tokenUsageRepositoryFilter  `json:"repositoryFilter,omitempty"`
	RepositoryCoverage          tokenUsageRepositoryCoverage `json:"repositoryCoverage"`
	Providers                   []string                     `json:"providers"`
	Usage                       tokenUsageValues             `json:"usage"`
	Coverage                    tokenUsageCoverage           `json:"coverage"`
	HighestUsageTask            *tokenUsageTask              `json:"highestUsageTask"`
	Tasks                       []tokenUsageTask             `json:"tasks"`
	Traces                      []tokenUsageTrace            `json:"traces"`
}

type tokenUsageRecord struct {
	observed   bool
	recognized bool
	provider   string
	usage      tokenUsageValues
}

type tokenUsageSums struct {
	input              int64
	cachedInput        int64
	cacheCreationInput int64
	output             int64
	reasoningOutput    int64
	providerTotal      int64
	derivedTotal       int64
	effectiveTotal     int64
}

type tokenUsageOverflows struct {
	input              bool
	cachedInput        bool
	cacheCreationInput bool
	output             bool
	reasoningOutput    bool
	providerTotal      bool
	derivedTotal       bool
	effectiveTotal     bool
}

type tokenUsageAccumulator struct {
	sums      tokenUsageSums
	overflows tokenUsageOverflows
	coverage  tokenUsageCoverage
}

func (d *Dispatcher) tokenUsageOverview(args map[string]any) toolResult {
	repositoryFilter := repositoryFilterFromArgs(args)
	result := tokenUsageOverviewResult{
		Scope:                       "agent_task",
		Retention:                   "bounded in-memory telemetry ring; explicit clear, Observer exit, or ring overwrite evicts retained provider usage history",
		MeasurementSource:           "none",
		AccountingStatus:            "unknown",
		RepositoryCorrelationStatus: "unknown",
		RepositoryFilter:            repositoryFilter,
		Tasks:                       []tokenUsageTask{},
		Traces:                      []tokenUsageTrace{},
	}
	var aggregate tokenUsageAccumulator
	providerSet := make(map[string]struct{})

	logs := d.store.SnapshotProviderUsageLogs()
	providerSpansByTraceID := mergeProviderSpanGroups(
		groupProviderSpansByTraceID(d.store.SnapshotTraceQuerySpans()),
		d.store.SnapshotProviderTaskSpansByTraceID(),
	)
	logTasks := buildProviderLogTasks(
		logs,
		providerSpansByTraceID,
		args,
		d.store.ProviderUsageLogUnavailableThrough(),
	)
	excludedTaskKeys := make(map[string]struct{}, len(logTasks))
	for _, built := range logTasks {
		if built.task.TaskID != "" {
			excludedTaskKeys[providerTraceKey(built.task.Provider, built.task.TaskID)] = struct{}{}
		}
	}
	spanTasks := buildProviderSpanTasks(providerSpansByTraceID, args, excludedTaskKeys)
	metricTasks := buildProviderMetricTasks(
		d.store.SnapshotProviderUsageMetrics(),
		args,
		d.store.ProviderUsageMetricUnavailableThrough(),
	)
	correlations := d.store.SnapshotProviderRepositoryCorrelations()
	correlationWatermark := d.store.ProviderRepositoryCorrelationUnavailableThrough()
	modeResolver := memoizedRepositoryCorrelationModeResolver(d.repositoryCorrelationModeResolver)
	if repositoryFilter != nil {
		logTasks, _ = correlateAndFilterProviderTasksWithResolverAndWatermark(
			logTasks, correlations, nil, modeResolver, correlationWatermark,
		)
		spanTasks, _ = correlateAndFilterProviderTasksWithResolverAndWatermark(
			spanTasks, correlations, nil, modeResolver, correlationWatermark,
		)
		metricTasks, _ = correlateAndFilterProviderTasksWithResolverAndWatermark(
			metricTasks, correlations, nil, modeResolver, correlationWatermark,
		)
	}
	providerTasks := combineProviderTaskBuilds(logTasks, spanTasks, metricTasks, args)
	providerTasks, result.RepositoryCoverage = correlateAndFilterProviderTasksWithResolverAndWatermark(
		providerTasks,
		correlations,
		repositoryFilter,
		modeResolver,
		correlationWatermark,
	)
	result.RepositoryCorrelationStatus = repositoryCorrelationStatus(result.RepositoryCoverage)
	if len(providerTasks) > 0 {
		result.MeasurementSource = providerTasksMeasurementSource(providerTasks)
		result.HighestUsageTask = highestMeasuredProviderTask(providerTasks)
		returnedTasks := limitProviderTaskBuilds(providerTasks, args)
		result.Tasks = make([]tokenUsageTask, 0, len(returnedTasks))
		for _, built := range returnedTasks {
			result.Tasks = append(result.Tasks, built.task)
		}
		accountedTasks := make([]tokenUsageTask, 0, len(providerTasks))
		for _, built := range providerTasks {
			accountedTasks = append(accountedTasks, built.task)
			aggregate.addTask(built.records)
			providerSet[built.task.Provider] = struct{}{}
		}
		result.Providers = sortedSet(providerSet)
		result.Usage = aggregate.values()
		result.Coverage = aggregate.coverage
		result.Status = aggregate.status()
		result.AccountingStatus = providerTasksAggregateAccountingStatus(accountedTasks, aggregate)
		if d.store.ProviderTaskHistoryEvicted() && providerTaskQueryRequiresCompleteHistory(args) {
			result.AccountingStatus = "partial"
		}
		return jsonToolResult(result)
	}
	if strArg(args, "taskId") != "" || conversationIDArg(args) != "" || strArg(args, "provider") != "" || strArg(args, "skillName") != "" || repositoryFilter != nil {
		result.Status = tokenUsageStatus(result.Coverage)
		return jsonToolResult(result)
	}

	traceIDFilter := strArg(args, "traceId")
	traceIDPrefix := strArg(args, "traceIdPrefix")
	if traceIDFilter != "" {
		traceIDPrefix = traceIDFilter
	}
	summaries := d.store.QueryGenAITracesFiltered(
		strArg(args, "serviceName"),
		strArg(args, "spanName"),
		"",
		traceIDPrefix,
		tokenUsageLimit(args),
		0,
	)
	if len(summaries) > 0 {
		result.MeasurementSource = "gen_ai_spans"
	}
	result.Traces = make([]tokenUsageTrace, 0, len(summaries))
	traceIDs := make([]string, 0, len(summaries))
	for _, summary := range summaries {
		if traceIDFilter != "" && !strings.EqualFold(summary.TraceID, traceIDFilter) {
			continue
		}
		traceIDs = append(traceIDs, summary.TraceID)
	}
	spansByTraceID := d.store.SnapshotSpansByTraceIDs(traceIDs)
	for _, summary := range summaries {
		spans, ok := spansByTraceID[summary.TraceID]
		if !ok {
			continue
		}
		trace, records := buildTokenUsageTrace(summary, spans)
		result.Traces = append(result.Traces, trace)
		aggregate.addTrace(records)
		for _, provider := range trace.Providers {
			providerSet[provider] = struct{}{}
		}
	}
	result.Providers = sortedSet(providerSet)
	result.Usage = aggregate.values()
	result.Coverage = aggregate.coverage
	result.Status = aggregate.status()
	result.AccountingStatus = spanAccountingStatus(result.Status)
	return jsonToolResult(result)
}

func memoizedRepositoryCorrelationModeResolver(
	resolver RepositoryCorrelationModeResolver,
) RepositoryCorrelationModeResolver {
	if resolver == nil {
		return nil
	}
	resolved := make(map[string]string)
	return func(provider string) string {
		if mode, ok := resolved[provider]; ok {
			return mode
		}
		mode := resolver(provider)
		resolved[provider] = mode
		return mode
	}
}

func highestMeasuredProviderTask(tasks []providerLogTaskBuild) *tokenUsageTask {
	highestIndex := -1
	var highestTotal int64
	for index := range tasks {
		total := tasks[index].task.Usage.EffectiveTotalTokens
		if total == nil {
			return nil
		}
		if highestIndex == -1 || *total > highestTotal {
			highestIndex = index
			highestTotal = *total
		}
	}
	if highestIndex == -1 {
		return nil
	}
	highest := tasks[highestIndex].task
	return &highest
}

func tokenUsageLimit(args map[string]any) int {
	limit := intArg(args, "limit", 20)
	if limit <= 0 {
		return 20
	}
	if limit > 100 {
		return 100
	}
	return limit
}

func providerTaskQueryRequiresCompleteHistory(args map[string]any) bool {
	return strings.TrimSpace(strArg(args, "taskId")) == "" &&
		strings.TrimSpace(strArg(args, "traceId")) == ""
}

func conversationIDArg(args map[string]any) string {
	if conversationID := strings.TrimSpace(strArg(args, "conversationId")); conversationID != "" {
		return conversationID
	}
	return strings.TrimSpace(strArg(args, "threadId"))
}

func buildTokenUsageTrace(summary store.TraceSummary, spans []store.Span) (tokenUsageTrace, []tokenUsageRecord) {
	spans = deduplicateTokenUsageSpans(spans)
	taskSpans := filterAgentTaskSpans(spans)
	selected, source := selectTokenUsageSpans(taskSpans)
	records := make([]tokenUsageRecord, 0, len(selected))
	providerSet := make(map[string]struct{})
	for _, span := range selected {
		record := tokenUsageFromSpan(span)
		records = append(records, record)
		providerSet[record.provider] = struct{}{}
	}

	var aggregate tokenUsageAccumulator
	aggregate.addTrace(records)
	startTime := ""
	if len(spans) > 0 {
		start := spans[0].StartTime
		for _, span := range spans[1:] {
			if span.StartTime.Before(start) {
				start = span.StartTime
			}
		}
		startTime = start.UTC().Format("2006-01-02T15:04:05.000000000Z")
	}
	llmCalls, toolCalls := countAgentTaskCalls(taskSpans)
	status := aggregate.status()
	return tokenUsageTrace{
		TraceID:           summary.TraceID,
		RootSpanName:      summary.RootSpanName,
		ServiceName:       summary.ServiceName,
		StartTime:         startTime,
		MeasurementSource: source,
		Status:            status,
		AccountingStatus:  spanAccountingStatus(status),
		Providers:         sortedSet(providerSet),
		ModelNames:        modelNames(taskSpans),
		LLMCalls:          llmCalls,
		ToolCalls:         toolCalls,
		Usage:             aggregate.values(),
		Coverage:          aggregate.coverage,
	}, records
}

func deduplicateTokenUsageSpans(spans []store.Span) []store.Span {
	deduplicated := make([]store.Span, 0, len(spans))
	indexes := make(map[string]int, len(spans))
	for _, span := range spans {
		if span.SpanID == "" {
			deduplicated = append(deduplicated, span)
			continue
		}
		key := strings.ToLower(strings.TrimSpace(span.TraceID)) + "\x00" + strings.ToLower(strings.TrimSpace(span.SpanID))
		if index, duplicate := indexes[key]; duplicate {
			deduplicated[index] = span
			continue
		}
		indexes[key] = len(deduplicated)
		deduplicated = append(deduplicated, span)
	}
	return deduplicated
}

func filterAgentTaskSpans(spans []store.Span) []store.Span {
	parentByID := make(map[string]string, len(spans))
	evaluationIDs := make(map[string]struct{})
	for _, span := range spans {
		parentByID[span.SpanID] = span.ParentSpanID
		if store.IsGenAIEvaluationOnlySpan(span) {
			evaluationIDs[span.SpanID] = struct{}{}
		}
	}
	excludedIDs := newSpanAncestryIndex(parentByID).idsInBranches(evaluationIDs)

	filtered := make([]store.Span, 0, len(spans))
	for _, span := range spans {
		if !store.IsGenAISpan(span) {
			continue
		}
		if _, excluded := excludedIDs[span.SpanID]; excluded {
			continue
		}
		filtered = append(filtered, span)
	}
	return filtered
}

func selectTokenUsageSpans(spans []store.Span) ([]store.Span, string) {
	parentByID := make(map[string]string, len(spans))
	llmSpans := make([]store.Span, 0)
	llmIDs := make(map[string]struct{})
	observedLLMIDs := make(map[string]struct{})
	tokenSpans := make([]store.Span, 0)
	for _, span := range spans {
		parentByID[span.SpanID] = span.ParentSpanID
		observed := hasTokenUsageAttribute(span.Attributes)
		if observed {
			tokenSpans = append(tokenSpans, span)
		}
		if store.ClassifyGenAISpan(span) == store.GenAISpanLLM {
			llmSpans = append(llmSpans, span)
			llmIDs[span.SpanID] = struct{}{}
			if observed {
				observedLLMIDs[span.SpanID] = struct{}{}
			}
		}
	}
	ancestry := newSpanAncestryIndex(parentByID)

	if len(observedLLMIDs) > 0 {
		observedWithDescendants := ancestry.candidatesWithDescendants(observedLLMIDs)
		selected := make([]store.Span, 0, len(llmSpans))
		selectedIDs := make(map[string]struct{})
		for _, span := range llmSpans {
			_, observed := observedLLMIDs[span.SpanID]
			_, hasObservedDescendant := observedWithDescendants[span.SpanID]
			if !observed || hasObservedDescendant {
				continue
			}
			selected = append(selected, span)
			selectedIDs[span.SpanID] = struct{}{}
		}
		llmWithDescendants := ancestry.candidatesWithDescendants(llmIDs)
		withSelectedAncestor := ancestry.idsWithAncestor(selectedIDs)
		for _, span := range llmSpans {
			if _, hasDescendant := llmWithDescendants[span.SpanID]; hasDescendant {
				continue
			}
			if _, hasAncestor := withSelectedAncestor[span.SpanID]; hasAncestor {
				continue
			}
			if _, selectedAlready := selectedIDs[span.SpanID]; selectedAlready {
				continue
			}
			selected = append(selected, span)
		}
		sortSpans(selected)
		return selected, "llm_spans"
	}

	if len(tokenSpans) > 0 {
		candidateIDs := make(map[string]struct{}, len(tokenSpans))
		for _, span := range tokenSpans {
			candidateIDs[span.SpanID] = struct{}{}
		}
		candidatesWithDescendants := ancestry.candidatesWithDescendants(candidateIDs)
		selected := make([]store.Span, 0, len(tokenSpans))
		for _, span := range tokenSpans {
			if _, hasDescendant := candidatesWithDescendants[span.SpanID]; !hasDescendant {
				selected = append(selected, span)
			}
		}
		sortSpans(selected)
		return selected, "aggregate_spans"
	}
	return nil, "none"
}

type spanAncestryIndex struct {
	parentByID   map[string]string
	childrenByID map[string][]string
	childCounts  map[string]int
}

func newSpanAncestryIndex(parentByID map[string]string) spanAncestryIndex {
	index := spanAncestryIndex{
		parentByID:   parentByID,
		childrenByID: make(map[string][]string, len(parentByID)),
		childCounts:  make(map[string]int, len(parentByID)),
	}
	for spanID := range parentByID {
		if spanID != "" {
			index.childCounts[spanID] = 0
		}
	}
	for spanID, parentID := range parentByID {
		if spanID == "" || parentID == "" {
			continue
		}
		if _, retained := index.childCounts[parentID]; !retained {
			continue
		}
		index.childrenByID[parentID] = append(index.childrenByID[parentID], spanID)
		index.childCounts[parentID]++
	}
	return index
}

func (index spanAncestryIndex) candidatesWithDescendants(ids map[string]struct{}) map[string]struct{} {
	withDescendants := make(map[string]struct{})
	remainingChildren := make(map[string]int, len(index.childCounts))
	queue := make([]string, 0, len(index.childCounts))
	for spanID, count := range index.childCounts {
		remainingChildren[spanID] = count
		if count == 0 {
			queue = append(queue, spanID)
		}
	}

	descendantCandidateCounts := make(map[string]int, len(index.childCounts))
	for len(queue) > 0 {
		spanID := queue[len(queue)-1]
		queue = queue[:len(queue)-1]
		descendantCount := descendantCandidateCounts[spanID]
		_, candidate := ids[spanID]
		if candidate && descendantCount > 0 {
			withDescendants[spanID] = struct{}{}
		}

		subtreeCount := descendantCount
		if candidate {
			subtreeCount = addCappedCandidateCount(subtreeCount, 1)
		}
		parentID := index.parentByID[spanID]
		parentChildren, retained := remainingChildren[parentID]
		if !retained {
			continue
		}
		descendantCandidateCounts[parentID] = addCappedCandidateCount(descendantCandidateCounts[parentID], subtreeCount)
		parentChildren--
		remainingChildren[parentID] = parentChildren
		if parentChildren == 0 {
			queue = append(queue, parentID)
		}
	}

	// Nodes left with children form parent cycles. External descendants have
	// already been folded into their per-node counts by the leaf pass above.
	visitedCycles := make(map[string]struct{})
	for spanID, count := range remainingChildren {
		if count == 0 {
			continue
		}
		if _, visited := visitedCycles[spanID]; visited {
			continue
		}
		cycle := make([]string, 0)
		for current := spanID; current != ""; current = index.parentByID[current] {
			if remainingChildren[current] == 0 {
				break
			}
			if _, visited := visitedCycles[current]; visited {
				break
			}
			visitedCycles[current] = struct{}{}
			cycle = append(cycle, current)
		}

		cycleCandidateCount := 0
		for _, current := range cycle {
			cycleCandidateCount = addCappedCandidateCount(cycleCandidateCount, descendantCandidateCounts[current])
			if _, candidate := ids[current]; candidate {
				cycleCandidateCount = addCappedCandidateCount(cycleCandidateCount, 1)
			}
		}
		if cycleCandidateCount < 2 {
			continue
		}
		for _, current := range cycle {
			if _, candidate := ids[current]; candidate {
				withDescendants[current] = struct{}{}
			}
		}
	}
	return withDescendants
}

func (index spanAncestryIndex) idsWithAncestor(ids map[string]struct{}) map[string]struct{} {
	withAncestor := make(map[string]struct{})
	queue := make([]string, 0)
	for spanID := range ids {
		queue = append(queue, index.childrenByID[spanID]...)
	}
	for len(queue) > 0 {
		spanID := queue[len(queue)-1]
		queue = queue[:len(queue)-1]
		if _, visited := withAncestor[spanID]; visited {
			continue
		}
		withAncestor[spanID] = struct{}{}
		queue = append(queue, index.childrenByID[spanID]...)
	}
	return withAncestor
}

func (index spanAncestryIndex) idsInBranches(roots map[string]struct{}) map[string]struct{} {
	if len(roots) == 0 {
		return map[string]struct{}{}
	}
	inBranches := index.idsWithAncestor(roots)
	for rootID := range roots {
		if rootID == "" {
			continue
		}
		if _, retained := index.parentByID[rootID]; retained {
			inBranches[rootID] = struct{}{}
		}
	}
	return inBranches
}

func (index spanAncestryIndex) nearestAncestorOrSelf(ids map[string]struct{}) map[string]string {
	resolved := make(map[string]string, len(index.parentByID))
	state := make(map[string]uint8, len(index.parentByID))
	for spanID := range ids {
		if spanID == "" {
			continue
		}
		if _, retained := index.parentByID[spanID]; retained {
			resolved[spanID] = spanID
			state[spanID] = 2
		}
	}

	for startID := range index.parentByID {
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
			parentID, retained := index.parentByID[currentID]
			if !retained {
				break
			}
			state[currentID] = 1
			path = append(path, currentID)
			currentID = parentID
		}
		for _, spanID := range path {
			resolved[spanID] = nearestID
			state[spanID] = 2
		}
	}
	return resolved
}

func addCappedCandidateCount(current, additional int) int {
	if current >= 2 || additional >= 2 || current+additional >= 2 {
		return 2
	}
	return current + additional
}

func sortSpans(spans []store.Span) {
	sort.Slice(spans, func(i, j int) bool {
		if spans[i].StartTime.Equal(spans[j].StartTime) {
			return spans[i].SpanID < spans[j].SpanID
		}
		return spans[i].StartTime.Before(spans[j].StartTime)
	})
}

func tokenUsageFromSpan(span store.Span) tokenUsageRecord {
	attrs := span.Attributes
	provider := tokenProviderFromSpan(span)
	input, _ := firstTokenAttribute(attrs, normalizedInputTokenKeys)
	rawInput, _ := firstTokenAttribute(attrs, rawInputTokenKeys)
	cached, _ := firstTokenAttribute(attrs, cachedInputTokenKeys)
	cacheCreation, _ := firstTokenAttribute(attrs, cacheCreationInputTokenKeys)
	if cacheCreation == nil {
		cacheCreation = completeCacheCreationBreakdown(attrs)
	}
	if input == nil {
		if provider == "claude" {
			input = addKnownTokens(rawInput, cached, cacheCreation)
		} else {
			input = rawInput
		}
	}
	output, _ := firstTokenAttribute(attrs, outputTokenKeys)
	reasoning, _ := firstTokenAttribute(attrs, reasoningOutputTokenKeys)
	providerTotal, _ := firstTokenAttribute(attrs, providerTotalTokenKeys)
	derivedTotal := addKnownTokens(input, output)
	effectiveTotal := providerTotal
	if effectiveTotal == nil {
		effectiveTotal = derivedTotal
	}
	usage := tokenUsageValues{
		InputTokens:              input,
		CachedInputTokens:        cached,
		CacheCreationInputTokens: cacheCreation,
		OutputTokens:             output,
		ReasoningOutputTokens:    reasoning,
		ProviderTotalTokens:      providerTotal,
		DerivedTotalTokens:       derivedTotal,
		EffectiveTotalTokens:     effectiveTotal,
	}
	return tokenUsageRecord{
		observed:   hasTokenUsageAttribute(attrs),
		recognized: hasRecognizedTokenValue(usage),
		provider:   provider,
		usage:      usage,
	}
}

func tokenProviderFromSpan(span store.Span) string {
	if provider := tokenProvider(span.Attributes); provider != "unknown" {
		return provider
	}
	if provider := store.ProviderTaskBoundaryProvider(span); provider != "" {
		return provider
	}
	identity := strings.ToLower(strings.Join([]string{
		span.Resource.ServiceName,
		span.Scope.Name,
	}, " "))
	if strings.Contains(identity, "anthropic") || strings.Contains(identity, "claude") {
		return "claude"
	}
	if strings.Contains(identity, "openai") || strings.Contains(identity, "codex") {
		return "codex"
	}
	return "unknown"
}

func hasTokenUsageAttribute(attrs map[string]any) bool {
	for key := range attrs {
		lower := strings.ToLower(key)
		if (strings.HasPrefix(lower, "gen_ai.usage.") && strings.Contains(lower, "token")) || isKnownTokenKey(lower) {
			return true
		}
	}
	return false
}

func isKnownTokenKey(key string) bool {
	for _, keys := range [][]string{
		normalizedInputTokenKeys,
		rawInputTokenKeys,
		cachedInputTokenKeys,
		cacheCreationInputTokenKeys,
		outputTokenKeys,
		reasoningOutputTokenKeys,
		providerTotalTokenKeys,
		{"cache_creation.ephemeral_1h_input_tokens", "cache_creation.ephemeral_5m_input_tokens"},
	} {
		for _, known := range keys {
			if key == known {
				return true
			}
		}
	}
	return false
}

func firstTokenAttribute(attrs map[string]any, keys []string) (*int64, bool) {
	observed := false
	for _, key := range keys {
		value, ok := attrs[key]
		if !ok {
			continue
		}
		observed = true
		if token, valid := nonNegativeInt64(value); valid {
			return &token, true
		}
	}
	return nil, observed
}

func completeCacheCreationBreakdown(attrs map[string]any) *int64 {
	if cacheCreation, ok := attrs["cache_creation"].(map[string]any); ok {
		oneHour, _ := firstTokenAttribute(cacheCreation, []string{"ephemeral_1h_input_tokens"})
		fiveMinutes, _ := firstTokenAttribute(cacheCreation, []string{"ephemeral_5m_input_tokens"})
		if total := addKnownTokens(oneHour, fiveMinutes); total != nil {
			return total
		}
	}
	oneHour, _ := firstTokenAttribute(attrs, []string{"cache_creation.ephemeral_1h_input_tokens"})
	fiveMinutes, _ := firstTokenAttribute(attrs, []string{"cache_creation.ephemeral_5m_input_tokens"})
	return addKnownTokens(oneHour, fiveMinutes)
}

func nonNegativeInt64(value any) (int64, bool) {
	switch number := value.(type) {
	case int:
		return int64(number), number >= 0
	case int8:
		return int64(number), number >= 0
	case int16:
		return int64(number), number >= 0
	case int32:
		return int64(number), number >= 0
	case int64:
		return number, number >= 0
	case uint:
		if uint64(number) <= math.MaxInt64 {
			return int64(number), true
		}
	case uint8:
		return int64(number), true
	case uint16:
		return int64(number), true
	case uint32:
		return int64(number), true
	case uint64:
		if number <= math.MaxInt64 {
			return int64(number), true
		}
	case float32:
		return integralFloat64(float64(number))
	case float64:
		return integralFloat64(number)
	case string:
		parsed, err := strconv.ParseInt(strings.TrimSpace(number), 10, 64)
		return parsed, err == nil && parsed >= 0
	}
	return 0, false
}

func integralFloat64(number float64) (int64, bool) {
	if math.IsNaN(number) || math.IsInf(number, 0) || number < 0 || number >= float64(math.MaxInt64) || math.Trunc(number) != number {
		return 0, false
	}
	return int64(number), true
}

func addKnownTokens(values ...*int64) *int64 {
	if len(values) == 0 {
		return nil
	}
	var total int64
	for _, value := range values {
		if value == nil || *value > math.MaxInt64-total {
			return nil
		}
		total += *value
	}
	return &total
}

func hasRecognizedTokenValue(usage tokenUsageValues) bool {
	return usage.InputTokens != nil ||
		usage.CachedInputTokens != nil ||
		usage.CacheCreationInputTokens != nil ||
		usage.OutputTokens != nil ||
		usage.ReasoningOutputTokens != nil ||
		usage.ProviderTotalTokens != nil
}

func tokenProvider(attrs map[string]any) string {
	values := make([]string, 0, len(providerKeys)+len(modelKeys))
	for _, keys := range [][]string{providerKeys, modelKeys} {
		for _, key := range keys {
			if value, ok := attrs[key].(string); ok {
				values = append(values, strings.ToLower(strings.TrimSpace(value)))
			}
		}
	}
	for _, value := range values {
		if strings.Contains(value, "anthropic") || strings.Contains(value, "claude") {
			return "claude"
		}
		if strings.Contains(value, "openai") || strings.Contains(value, "codex") || strings.HasPrefix(value, "gpt-") {
			return "codex"
		}
	}
	return "unknown"
}

func modelNames(spans []store.Span) []string {
	models := make(map[string]struct{})
	for _, span := range spans {
		for _, key := range modelKeys {
			value, ok := span.Attributes[key].(string)
			if !ok {
				continue
			}
			for _, model := range strings.Split(value, ",") {
				model = strings.TrimSpace(model)
				if model != "" && !strings.EqualFold(model, "unknown") {
					models[model] = struct{}{}
				}
			}
		}
	}
	return sortedSet(models)
}

func countAgentTaskCalls(spans []store.Span) (int, int) {
	llmCalls := 0
	toolCalls := 0
	for _, span := range spans {
		switch store.ClassifyGenAISpan(span) {
		case store.GenAISpanLLM:
			llmCalls++
		case store.GenAISpanTool:
			toolCalls++
		}
	}
	return llmCalls, toolCalls
}

func (a *tokenUsageAccumulator) addTrace(records []tokenUsageRecord) {
	observed, recognized, effective := a.addUnit(records)
	a.coverage.TraceCount++
	if observed {
		a.coverage.ObservedTraceCount++
	}
	if recognized {
		a.coverage.RecognizedTraceCount++
	}
	if effective {
		a.coverage.EffectiveTotalTraceCount++
	}
}

func (a *tokenUsageAccumulator) addTask(records []tokenUsageRecord) {
	observed, recognized, effective := a.addUnit(records)
	a.coverage.TaskCount++
	if observed {
		a.coverage.ObservedTaskCount++
	}
	if recognized {
		a.coverage.RecognizedTaskCount++
	}
	if effective {
		a.coverage.EffectiveTotalTaskCount++
	}
}

func (a *tokenUsageAccumulator) addUnit(records []tokenUsageRecord) (bool, bool, bool) {
	traceObserved := false
	traceRecognized := false
	traceEffective := len(records) > 0
	for _, record := range records {
		a.addRecord(record)
		traceObserved = traceObserved || record.observed
		traceRecognized = traceRecognized || record.recognized
		traceEffective = traceEffective && record.usage.EffectiveTotalTokens != nil
	}
	return traceObserved, traceRecognized, traceEffective
}

func (a *tokenUsageAccumulator) addRecord(record tokenUsageRecord) {
	a.coverage.RecordCount++
	if record.observed {
		a.coverage.ObservedRecordCount++
	}
	if record.recognized {
		a.coverage.RecognizedRecordCount++
	}
	a.addField(&a.sums.input, &a.overflows.input, &a.coverage.FieldCounts.InputTokens, record.usage.InputTokens)
	a.addField(&a.sums.cachedInput, &a.overflows.cachedInput, &a.coverage.FieldCounts.CachedInputTokens, record.usage.CachedInputTokens)
	a.addField(&a.sums.cacheCreationInput, &a.overflows.cacheCreationInput, &a.coverage.FieldCounts.CacheCreationInputTokens, record.usage.CacheCreationInputTokens)
	a.addField(&a.sums.output, &a.overflows.output, &a.coverage.FieldCounts.OutputTokens, record.usage.OutputTokens)
	a.addField(&a.sums.reasoningOutput, &a.overflows.reasoningOutput, &a.coverage.FieldCounts.ReasoningOutputTokens, record.usage.ReasoningOutputTokens)
	a.addField(&a.sums.providerTotal, &a.overflows.providerTotal, &a.coverage.FieldCounts.ProviderTotalTokens, record.usage.ProviderTotalTokens)
	a.addField(&a.sums.derivedTotal, &a.overflows.derivedTotal, &a.coverage.FieldCounts.DerivedTotalTokens, record.usage.DerivedTotalTokens)
	if record.usage.EffectiveTotalTokens != nil {
		a.addField(&a.sums.effectiveTotal, &a.overflows.effectiveTotal, &a.coverage.EffectiveTotalCount, record.usage.EffectiveTotalTokens)
	}
}

func (a *tokenUsageAccumulator) addField(sum *int64, overflow *bool, count *int, value *int64) {
	if value == nil {
		return
	}
	*count++
	if *overflow {
		return
	}
	total, ok := addTokenCounts(*sum, *value)
	if !ok {
		*overflow = true
		return
	}
	*sum = total
}

func addTokenCounts(left, right int64) (int64, bool) {
	if right > math.MaxInt64-left {
		return 0, false
	}
	return left + right, true
}

func (a tokenUsageAccumulator) values() tokenUsageValues {
	return tokenUsageValues{
		InputTokens:              measuredSum(a.sums.input, a.coverage.FieldCounts.InputTokens, a.overflows.input),
		CachedInputTokens:        measuredSum(a.sums.cachedInput, a.coverage.FieldCounts.CachedInputTokens, a.overflows.cachedInput),
		CacheCreationInputTokens: measuredSum(a.sums.cacheCreationInput, a.coverage.FieldCounts.CacheCreationInputTokens, a.overflows.cacheCreationInput),
		OutputTokens:             measuredSum(a.sums.output, a.coverage.FieldCounts.OutputTokens, a.overflows.output),
		ReasoningOutputTokens:    measuredSum(a.sums.reasoningOutput, a.coverage.FieldCounts.ReasoningOutputTokens, a.overflows.reasoningOutput),
		ProviderTotalTokens:      measuredSum(a.sums.providerTotal, a.coverage.FieldCounts.ProviderTotalTokens, a.overflows.providerTotal),
		DerivedTotalTokens:       measuredSum(a.sums.derivedTotal, a.coverage.FieldCounts.DerivedTotalTokens, a.overflows.derivedTotal),
		EffectiveTotalTokens:     measuredSum(a.sums.effectiveTotal, a.coverage.EffectiveTotalCount, a.overflows.effectiveTotal),
	}
}

func measuredSum(sum int64, count int, overflow bool) *int64 {
	if count == 0 || overflow {
		return nil
	}
	return &sum
}

func (a tokenUsageAccumulator) hasOverflow() bool {
	return a.overflows.input ||
		a.overflows.cachedInput ||
		a.overflows.cacheCreationInput ||
		a.overflows.output ||
		a.overflows.reasoningOutput ||
		a.overflows.providerTotal ||
		a.overflows.derivedTotal ||
		a.overflows.effectiveTotal
}

func (a tokenUsageAccumulator) status() string {
	if a.hasOverflow() {
		return "partial"
	}
	return tokenUsageStatus(a.coverage)
}

func tokenUsageStatus(coverage tokenUsageCoverage) string {
	unitCount := coverage.TaskCount + coverage.TraceCount
	observedCount := coverage.ObservedTaskCount + coverage.ObservedTraceCount
	recognizedCount := coverage.RecognizedTaskCount + coverage.RecognizedTraceCount
	effectiveCount := coverage.EffectiveTotalTaskCount + coverage.EffectiveTotalTraceCount
	if unitCount == 0 || observedCount == 0 {
		return "absent"
	}
	if recognizedCount == 0 {
		return "unrecognized"
	}
	if effectiveCount < unitCount {
		return "partial"
	}
	return "measured"
}

func providerTasksAccountingStatus(tasks []tokenUsageTask) string {
	if len(tasks) == 0 {
		return "unknown"
	}
	exact := 0
	uncorrelated := 0
	unknown := 0
	for _, task := range tasks {
		switch task.AccountingStatus {
		case "exact":
			exact++
		case "uncorrelated":
			uncorrelated++
		case "unknown":
			unknown++
		default:
			return "partial"
		}
	}
	if exact == len(tasks) {
		return "exact"
	}
	if uncorrelated == len(tasks) {
		return "uncorrelated"
	}
	if unknown == len(tasks) {
		return "unknown"
	}
	return "partial"
}

func providerTasksAggregateAccountingStatus(tasks []tokenUsageTask, aggregate tokenUsageAccumulator) string {
	if aggregate.hasOverflow() {
		return "partial"
	}
	return providerTasksAccountingStatus(tasks)
}

func spanAccountingStatus(status string) string {
	switch status {
	case "measured":
		return "estimated"
	case "partial":
		return "partial"
	default:
		return "unknown"
	}
}

func sortedSet(values map[string]struct{}) []string {
	result := make([]string, 0, len(values))
	for value := range values {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}
