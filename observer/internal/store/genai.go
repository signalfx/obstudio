package store

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"
)

type GenAISpanKind string

const (
	GenAISpanWorkflow  GenAISpanKind = "workflow"
	GenAISpanAgent     GenAISpanKind = "agent"
	GenAISpanTool      GenAISpanKind = "tool"
	GenAISpanLLM       GenAISpanKind = "llm"
	GenAISpanRetrieval GenAISpanKind = "retrieval"
	GenAISpanLoop      GenAISpanKind = "loop"
	GenAISpanGeneric   GenAISpanKind = "genai"
)

type GenAITokenUsage struct {
	Input  float64 `json:"input"`
	Output float64 `json:"output"`
	Total  float64 `json:"total"`
}

type GenAITraceSummary struct {
	IsGenAI    bool            `json:"isGenAI"`
	Tokens     GenAITokenUsage `json:"tokens"`
	ToolCalls  int             `json:"toolCalls"`
	LLMCalls   int             `json:"llmCalls"`
	ModelNames []string        `json:"modelNames"`
	FlowNodes  []GenAIFlowNode `json:"flowNodes"`
	FlowEdges  []GenAIFlowEdge `json:"flowEdges"`
}

type GenAIFlowNode struct {
	NodeID                            string          `json:"nodeId"`
	TraceID                           string          `json:"traceId"`
	SpanID                            string          `json:"spanId"`
	Name                              string          `json:"name"`
	Kind                              GenAISpanKind   `json:"kind"`
	Operation                         string          `json:"operation,omitempty"`
	ModelNames                        []string        `json:"modelNames"`
	TokenUsage                        GenAITokenUsage `json:"tokenUsage"`
	Depth                             int             `json:"depth"`
	DurationMs                        float64         `json:"durationMs"`
	AvgDurationMs                     float64         `json:"avgDurationMs,omitempty"`
	MaxDurationMs                     float64         `json:"maxDurationMs,omitempty"`
	StatusCode                        string          `json:"statusCode"`
	Grouped                           bool            `json:"grouped"`
	CallCount                         int             `json:"callCount,omitempty"`
	GroupedSpanIDs                    []string        `json:"groupedSpanIds"`
	ParentFlowSpanID                  string          `json:"parentFlowSpanId,omitempty"`
	DescendantSpanIDs                 []string        `json:"descendantSpanIds"`
	DescendantTokenUsage              GenAITokenUsage `json:"descendantTokenUsage"`
	DescendantLLMCalls                int             `json:"descendantLlmCalls"`
	DescendantLLMSpanIDs              []string        `json:"descendantLlmSpanIds"`
	DescendantToolCalls               int             `json:"descendantToolCalls"`
	DescendantToolSpanIDs             []string        `json:"descendantToolSpanIds"`
	DescendantSecurityRiskCount       int             `json:"descendantSecurityRiskCount"`
	DescendantSecurityRiskSpanIDs     []string        `json:"descendantSecurityRiskSpanIds"`
	DescendantPrivacyRiskCount        int             `json:"descendantPrivacyRiskCount"`
	DescendantPrivacyRiskSpanIDs      []string        `json:"descendantPrivacyRiskSpanIds"`
	DescendantRiskCount               int             `json:"descendantRiskCount"`
	DescendantEvaluationCount         int             `json:"descendantEvaluationCount"`
	DescendantEvaluationFailedCount   int             `json:"descendantEvaluationFailedCount"`
	DescendantEvaluationFailedSpanIDs []string        `json:"descendantEvaluationFailedSpanIds"`

	parentSpanID string
	linkSpanIDs  []string
}

type GenAIFlowEdge struct {
	Source string `json:"source"`
	Target string `json:"target"`
}

const genAIPrefix = "gen_ai."
const genAIFlowGroupThreshold = 8
const genAIFlowCycleMinIterations = 2
const genAIFlowCycleMaxPatternLength = 4

var (
	genAIOperationKeys = []string{
		"gen_ai.operation.name",
		"gen_ai.operation",
		"llm.operation",
		"openinference.span.kind",
	}
	genAIResponseModelKeys = []string{
		"gen_ai.response.model",
		"openai.response.model",
	}
	genAIRequestModelKeys = []string{
		"gen_ai.request.model",
		"llm.request.model",
		"openai.request.model",
	}
	genAIOtherModelKeys = []string{
		"llm.model_name",
		"ai.model.id",
		"model",
	}
	genAIPlaceholderModelNames = map[string]struct{}{
		"unknown":       {},
		"unknown_model": {},
		"n/a":           {},
		"none":          {},
		"null":          {},
		"<nil>":         {},
	}
	genAIInputTokenKeys = []string{
		"gen_ai.usage.input_tokens",
		"gen_ai.usage.prompt_tokens",
		"llm.token_count.prompt",
		"openai.usage.prompt_tokens",
		"ai.usage.input_tokens",
		"prompt_tokens",
	}
	genAIOutputTokenKeys = []string{
		"gen_ai.usage.output_tokens",
		"gen_ai.usage.completion_tokens",
		"llm.token_count.completion",
		"openai.usage.completion_tokens",
		"ai.usage.output_tokens",
		"completion_tokens",
	}
	genAITotalTokenKeys = []string{
		"gen_ai.usage.total_tokens",
		"llm.token_count.total",
		"openai.usage.total_tokens",
		"ai.usage.total_tokens",
		"total_tokens",
	}
	genAIToolNameKeys = []string{
		"gen_ai.tool.name",
		"tool.name",
		"ai.tool.name",
		"openinference.tool.name",
	}
	genAIAgentNameKeys = []string{
		"gen_ai.agent.name",
		"agent.name",
		"ai.agent.name",
	}
	genAIRetrievalNameKeys = []string{
		"gen_ai.retrieval.source",
		"gen_ai.retrieval.source.name",
		"gen_ai.data_source.name",
		"retrieval.source",
		"retrieval.source.name",
		"data_source.name",
	}
)

func buildGenAITraceSummary(spans []Span) *GenAITraceSummary {
	nodes := buildGenAIFlowNodes(spans, maxGenAIFlowNodeSpanListSize())
	genAISpans := make([]Span, 0)
	for _, span := range spans {
		if isGenAISpan(span) {
			genAISpans = append(genAISpans, span)
		}
	}
	if len(genAISpans) == 0 {
		return nil
	}

	var tokens GenAITokenUsage
	toolCalls := 0
	llmCalls := 0
	for _, span := range genAISpans {
		tokens = addTokenUsage(tokens, getGenAITokenUsage(span))
		if isGenAIEvaluationOnlySpan(span) {
			continue
		}
		switch classifyGenAISpan(span) {
		case GenAISpanTool:
			toolCalls++
		case GenAISpanLLM:
			llmCalls++
		}
	}
	return &GenAITraceSummary{
		IsGenAI:    true,
		Tokens:     tokens,
		ToolCalls:  toolCalls,
		LLMCalls:   llmCalls,
		ModelNames: getGenAITraceModelNames(genAISpans),
		FlowNodes:  nodes,
		FlowEdges:  buildGenAIFlowEdges(nodes),
	}
}

func buildGenAIFlowNodes(spans []Span, descendantCap int) []GenAIFlowNode {
	if len(spans) == 0 {
		return nil
	}

	byID := make(map[string]Span, len(spans))
	childrenByParent := make(map[string][]Span)
	for _, span := range spans {
		byID[span.SpanID] = span
	}
	for _, span := range spans {
		if span.ParentSpanID != "" {
			if _, ok := byID[span.ParentSpanID]; ok {
				childrenByParent[span.ParentSpanID] = append(childrenByParent[span.ParentSpanID], span)
			}
		}
	}
	for parentID := range childrenByParent {
		sort.SliceStable(childrenByParent[parentID], func(i, j int) bool {
			return childrenByParent[parentID][i].StartTime.Before(childrenByParent[parentID][j].StartTime)
		})
	}

	roots := make([]Span, 0)
	for _, span := range spans {
		if span.ParentSpanID == "" {
			roots = append(roots, span)
			continue
		}
		if _, ok := byID[span.ParentSpanID]; !ok {
			roots = append(roots, span)
		}
	}
	sort.SliceStable(roots, func(i, j int) bool {
		return roots[i].StartTime.Before(roots[j].StartTime)
	})

	nodes := make([]GenAIFlowNode, 0)
	nodeIndexBySpanID := make(map[string]int)

	addDescendant := func(parentFlowSpanID string, span Span) {
		index, ok := nodeIndexBySpanID[parentFlowSpanID]
		if !ok {
			return
		}
		node := &nodes[index]
		node.DescendantSpanIDs = appendSpanIDWithCap(node.DescendantSpanIDs, span.SpanID, descendantCap)
		addGenAIFlowNodeDescendantSignals(node, span, descendantCap)
	}

	addDescendantToAncestors := func(ancestorFlowSpanIDs []string, span Span) {
		for _, parentFlowSpanID := range ancestorFlowSpanIDs {
			addDescendant(parentFlowSpanID, span)
		}
	}

	appendAncestor := func(ancestorFlowSpanIDs []string, spanID string) []string {
		next := make([]string, 0, len(ancestorFlowSpanIDs)+1)
		next = append(next, ancestorFlowSpanIDs...)
		next = append(next, spanID)
		return next
	}

	var visit func(Span, []string, int)
	visit = func(span Span, ancestorFlowSpanIDs []string, flowDepth int) {
		if len(ancestorFlowSpanIDs) > 0 {
			addDescendantToAncestors(ancestorFlowSpanIDs, span)
		}

		nextAncestorFlowSpanIDs := ancestorFlowSpanIDs
		nextFlowDepth := flowDepth
		if isGenAIFlowNodeSpan(span) {
			parentFlowSpanID := ""
			if len(ancestorFlowSpanIDs) > 0 {
				parentFlowSpanID = ancestorFlowSpanIDs[len(ancestorFlowSpanIDs)-1]
			}
			node := newGenAIFlowNode(span, flowDepth)
			node.ParentFlowSpanID = parentFlowSpanID
			addGenAIFlowNodeOwnSignals(&node, span)
			nodes = append(nodes, node)
			nodeIndexBySpanID[span.SpanID] = len(nodes) - 1
			nextAncestorFlowSpanIDs = appendAncestor(ancestorFlowSpanIDs, span.SpanID)
			nextFlowDepth = flowDepth + 1
		}
		for _, child := range childrenByParent[span.SpanID] {
			visit(child, nextAncestorFlowSpanIDs, nextFlowDepth)
		}
	}

	for _, root := range roots {
		visit(root, nil, 0)
	}
	if len(nodes) == 0 {
		return nil
	}

	return groupGenAIFlowNodes(nodes)
}

func newGenAIFlowNode(span Span, depth int) GenAIFlowNode {
	kind := classifyGenAISpan(span)
	operation := getGenAIOperation(span)
	return GenAIFlowNode{
		NodeID:                            span.SpanID,
		TraceID:                           span.TraceID,
		SpanID:                            span.SpanID,
		Name:                              getGenAIFlowNodeName(span, kind, operation),
		Kind:                              kind,
		Operation:                         operation,
		ModelNames:                        getGenAIModelNames(span),
		TokenUsage:                        getGenAITokenUsage(span),
		Depth:                             depth,
		DurationMs:                        span.DurationMs,
		StatusCode:                        span.Status.Code,
		GroupedSpanIDs:                    []string{},
		DescendantSpanIDs:                 []string{},
		DescendantLLMSpanIDs:              []string{},
		DescendantToolSpanIDs:             []string{},
		DescendantSecurityRiskSpanIDs:     []string{},
		DescendantPrivacyRiskSpanIDs:      []string{},
		DescendantEvaluationFailedSpanIDs: []string{},
		parentSpanID:                      span.ParentSpanID,
		linkSpanIDs:                       getGenAILinkSpanIDs(span),
	}
}

func groupGenAIFlowNodes(nodes []GenAIFlowNode) []GenAIFlowNode {
	if len(nodes) == 0 {
		return nodes
	}
	hasChildFlowNode := genAIFlowChildNodeMap(nodes)
	nodes = groupRepeatedGenAIFlowCycles(nodes, hasChildFlowNode)
	return groupRepeatedGenAIFlowNodes(nodes, genAIFlowChildNodeMap(nodes))
}

func genAIFlowChildNodeMap(nodes []GenAIFlowNode) map[string]bool {
	hasChildFlowNode := make(map[string]bool)
	for _, node := range nodes {
		if node.ParentFlowSpanID != "" {
			hasChildFlowNode[node.ParentFlowSpanID] = true
		}
	}
	return hasChildFlowNode
}

func groupRepeatedGenAIFlowCycles(nodes []GenAIFlowNode, hasChildFlowNode map[string]bool) []GenAIFlowNode {
	if len(nodes) < genAIFlowCycleMinIterations*2 {
		return nodes
	}

	grouped := make([]GenAIFlowNode, 0, len(nodes))
	for index := 0; index < len(nodes); {
		match := bestGenAIFlowCycleMatch(nodes, index, hasChildFlowNode)
		if match.totalNodes == 0 {
			grouped = append(grouped, nodes[index])
			index++
			continue
		}

		indexes := make([]int, 0, match.totalNodes)
		for offset := 0; offset < match.totalNodes; offset++ {
			indexes = append(indexes, index+offset)
		}
		grouped = append(grouped, newGroupedGenAIFlowCycleNode(nodes, indexes, match.patternLength, match.iterations))
		index += match.totalNodes
	}
	return grouped
}

type genAIFlowCycleMatch struct {
	patternLength int
	iterations    int
	totalNodes    int
}

func bestGenAIFlowCycleMatch(nodes []GenAIFlowNode, start int, hasChildFlowNode map[string]bool) genAIFlowCycleMatch {
	best := genAIFlowCycleMatch{}
	maxPatternLength := genAIFlowCycleMaxPatternLength
	if remaining := len(nodes) - start; remaining < maxPatternLength {
		maxPatternLength = remaining
	}

	for patternLength := 2; patternLength <= maxPatternLength; patternLength++ {
		if !isGenAIFlowCyclePattern(nodes, start, patternLength, hasChildFlowNode) {
			continue
		}

		iterations := 1
		for matchesGenAIFlowCyclePattern(nodes, start, patternLength, iterations+1, hasChildFlowNode) {
			iterations++
		}
		if iterations < genAIFlowCycleMinIterations {
			continue
		}
		totalNodes := iterations * patternLength
		if totalNodes > best.totalNodes || (totalNodes == best.totalNodes && patternLength < best.patternLength) {
			best = genAIFlowCycleMatch{
				patternLength: patternLength,
				iterations:    iterations,
				totalNodes:    totalNodes,
			}
		}
	}
	return best
}

func isGenAIFlowCyclePattern(nodes []GenAIFlowNode, start, patternLength int, hasChildFlowNode map[string]bool) bool {
	if start+patternLength > len(nodes) {
		return false
	}
	parentFlowSpanID := nodes[start].ParentFlowSpanID
	hasLLM := false
	hasTool := false
	for index := start; index < start+patternLength; index++ {
		node := nodes[index]
		if !isLoopGroupableGenAIFlowNode(node, hasChildFlowNode) {
			return false
		}
		if node.ParentFlowSpanID != parentFlowSpanID {
			return false
		}
		switch node.Kind {
		case GenAISpanLLM:
			hasLLM = true
		case GenAISpanTool:
			hasTool = true
		}
	}
	return hasLLM && hasTool
}

func matchesGenAIFlowCyclePattern(nodes []GenAIFlowNode, start, patternLength, iterations int, hasChildFlowNode map[string]bool) bool {
	nextStart := start + (iterations-1)*patternLength
	if nextStart+patternLength > len(nodes) {
		return false
	}

	parentFlowSpanID := nodes[start].ParentFlowSpanID
	for offset := 0; offset < patternLength; offset++ {
		patternNode := nodes[start+offset]
		nextNode := nodes[nextStart+offset]
		if !isLoopGroupableGenAIFlowNode(nextNode, hasChildFlowNode) {
			return false
		}
		if nextNode.ParentFlowSpanID != parentFlowSpanID {
			return false
		}
		if genAIFlowCycleNodeSignature(nextNode) != genAIFlowCycleNodeSignature(patternNode) {
			return false
		}
	}
	return true
}

func isLoopGroupableGenAIFlowNode(node GenAIFlowNode, hasChildFlowNode map[string]bool) bool {
	switch node.Kind {
	case GenAISpanLLM, GenAISpanTool:
	default:
		return false
	}
	return !hasChildFlowNode[node.SpanID]
}

func genAIFlowCycleNodeSignature(node GenAIFlowNode) string {
	return strings.Join([]string{
		string(node.Kind),
		node.Operation,
		node.Name,
		strings.Join(node.ModelNames, ","),
	}, "\x00")
}

func groupRepeatedGenAIFlowNodes(nodes []GenAIFlowNode, hasChildFlowNode map[string]bool) []GenAIFlowNode {
	if len(nodes) <= genAIFlowGroupThreshold {
		return nodes
	}

	groups := make(map[string][]int)
	for index, node := range nodes {
		if !isGroupableGenAIFlowNode(node, hasChildFlowNode) {
			continue
		}
		key := genAIFlowGroupKey(node)
		groups[key] = append(groups[key], index)
	}

	groupedByFirstIndex := make(map[int]GenAIFlowNode)
	removed := make(map[int]bool)
	for _, indexes := range groups {
		if len(indexes) <= genAIFlowGroupThreshold {
			continue
		}
		grouped := newGroupedGenAIFlowNode(nodes, indexes)
		groupedByFirstIndex[indexes[0]] = grouped
		for _, index := range indexes[1:] {
			removed[index] = true
		}
	}
	if len(groupedByFirstIndex) == 0 {
		return nodes
	}

	result := make([]GenAIFlowNode, 0, len(nodes)-len(removed))
	for index, node := range nodes {
		if grouped, ok := groupedByFirstIndex[index]; ok {
			result = append(result, grouped)
			continue
		}
		if removed[index] {
			continue
		}
		result = append(result, node)
	}
	return result
}

func isGroupableGenAIFlowNode(node GenAIFlowNode, hasChildFlowNode map[string]bool) bool {
	switch node.Kind {
	case GenAISpanLLM, GenAISpanTool:
	default:
		return false
	}
	if hasChildFlowNode[node.SpanID] {
		return false
	}
	return true
}

func genAIFlowGroupKey(node GenAIFlowNode) string {
	return strings.Join([]string{
		node.ParentFlowSpanID,
		string(node.Kind),
		node.Operation,
		node.Name,
		strings.Join(node.ModelNames, ","),
	}, "\x00")
}

func newGroupedGenAIFlowNode(nodes []GenAIFlowNode, indexes []int) GenAIFlowNode {
	first := nodes[indexes[0]]
	groupedSpanIDs := make([]string, 0, len(indexes))
	var tokenUsage GenAITokenUsage
	var durationTotal float64
	var durationMax float64
	statusCode := "OK"
	securityRiskSpanIDs := make([]string, 0)
	privacyRiskSpanIDs := make([]string, 0)
	evaluationFailedSpanIDs := make([]string, 0)
	linkSpanIDs := make([]string, 0)
	internalSpanIDs := make(map[string]struct{})
	riskCount := 0
	evaluationCount := 0
	evaluationFailedCount := 0

	for _, index := range indexes {
		internalSpanIDs[nodes[index].SpanID] = struct{}{}
	}

	for _, index := range indexes {
		node := nodes[index]
		groupedSpanIDs = append(groupedSpanIDs, node.SpanID)
		tokenUsage = addTokenUsage(tokenUsage, node.TokenUsage)
		durationTotal += node.DurationMs
		if node.DurationMs > durationMax {
			durationMax = node.DurationMs
		}
		if node.StatusCode == "ERROR" {
			statusCode = "ERROR"
		}
		securityRiskSpanIDs = append(securityRiskSpanIDs, node.DescendantSecurityRiskSpanIDs...)
		privacyRiskSpanIDs = append(privacyRiskSpanIDs, node.DescendantPrivacyRiskSpanIDs...)
		evaluationCount += node.DescendantEvaluationCount
		evaluationFailedCount += node.DescendantEvaluationFailedCount
		evaluationFailedSpanIDs = append(evaluationFailedSpanIDs, node.DescendantEvaluationFailedSpanIDs...)
		for _, linkSpanID := range node.linkSpanIDs {
			if _, ok := internalSpanIDs[linkSpanID]; !ok {
				linkSpanIDs = append(linkSpanIDs, linkSpanID)
			}
		}
		riskCount += node.DescendantRiskCount
	}

	callCount := len(indexes)
	groupID := genAIFlowGroupID(first.ParentFlowSpanID, string(first.Kind), first.Operation, first.Name, strings.Join(first.ModelNames, ","))
	groupedName := fmt.Sprintf("%s x%d", first.Name, callCount)
	avgDuration := 0.0
	if callCount > 0 {
		avgDuration = durationTotal / float64(callCount)
	}

	grouped := GenAIFlowNode{
		NodeID:                            groupID,
		TraceID:                           first.TraceID,
		SpanID:                            groupID,
		Name:                              groupedName,
		Kind:                              first.Kind,
		Operation:                         first.Operation,
		ModelNames:                        first.ModelNames,
		TokenUsage:                        tokenUsage,
		Depth:                             first.Depth,
		DurationMs:                        durationMax,
		AvgDurationMs:                     avgDuration,
		MaxDurationMs:                     durationMax,
		StatusCode:                        statusCode,
		Grouped:                           true,
		CallCount:                         callCount,
		GroupedSpanIDs:                    cloneStrings(groupedSpanIDs),
		ParentFlowSpanID:                  first.ParentFlowSpanID,
		DescendantSpanIDs:                 cloneStrings(groupedSpanIDs),
		DescendantTokenUsage:              tokenUsage,
		DescendantSecurityRiskCount:       len(securityRiskSpanIDs),
		DescendantSecurityRiskSpanIDs:     securityRiskSpanIDs,
		DescendantPrivacyRiskCount:        len(privacyRiskSpanIDs),
		DescendantPrivacyRiskSpanIDs:      privacyRiskSpanIDs,
		DescendantRiskCount:               riskCount,
		DescendantEvaluationCount:         evaluationCount,
		DescendantEvaluationFailedCount:   evaluationFailedCount,
		DescendantEvaluationFailedSpanIDs: uniqueStrings(evaluationFailedSpanIDs),
		linkSpanIDs:                       uniqueStrings(linkSpanIDs),
	}
	switch first.Kind {
	case GenAISpanLLM:
		grouped.DescendantLLMCalls = callCount
		grouped.DescendantLLMSpanIDs = cloneStrings(groupedSpanIDs)
		grouped.DescendantToolSpanIDs = []string{}
	case GenAISpanTool:
		grouped.DescendantToolCalls = callCount
		grouped.DescendantToolSpanIDs = cloneStrings(groupedSpanIDs)
		grouped.DescendantLLMSpanIDs = []string{}
	default:
		grouped.DescendantLLMSpanIDs = []string{}
		grouped.DescendantToolSpanIDs = []string{}
	}
	return grouped
}

func newGroupedGenAIFlowCycleNode(nodes []GenAIFlowNode, indexes []int, patternLength int, iterations int) GenAIFlowNode {
	first := nodes[indexes[0]]
	patternNodes := make([]GenAIFlowNode, 0, patternLength)
	for _, index := range indexes[:patternLength] {
		patternNodes = append(patternNodes, nodes[index])
	}

	groupedSpanIDs := make([]string, 0, len(indexes))
	llmSpanIDs := make([]string, 0)
	toolSpanIDs := make([]string, 0)
	securityRiskSpanIDs := make([]string, 0)
	privacyRiskSpanIDs := make([]string, 0)
	evaluationFailedSpanIDs := make([]string, 0)
	internalSpanIDs := make(map[string]struct{})
	var tokenUsage GenAITokenUsage
	var durationTotal float64
	var durationMax float64
	statusCode := "OK"
	riskCount := 0
	evaluationCount := 0
	evaluationFailedCount := 0
	llmCalls := 0
	toolCalls := 0

	for _, index := range indexes {
		node := nodes[index]
		internalSpanIDs[node.SpanID] = struct{}{}
	}

	for _, index := range indexes {
		node := nodes[index]
		groupedSpanIDs = append(groupedSpanIDs, node.SpanID)
		groupedSpanIDs = append(groupedSpanIDs, node.DescendantSpanIDs...)
		tokenUsage = addTokenUsage(tokenUsage, node.TokenUsage)
		durationTotal += node.DurationMs
		if node.DurationMs > durationMax {
			durationMax = node.DurationMs
		}
		if node.StatusCode == "ERROR" {
			statusCode = "ERROR"
		}

		switch node.Kind {
		case GenAISpanLLM:
			llmCalls++
			llmSpanIDs = append(llmSpanIDs, node.SpanID)
		case GenAISpanTool:
			toolCalls++
			toolSpanIDs = append(toolSpanIDs, node.SpanID)
		}
		llmCalls += node.DescendantLLMCalls
		llmSpanIDs = append(llmSpanIDs, node.DescendantLLMSpanIDs...)
		toolCalls += node.DescendantToolCalls
		toolSpanIDs = append(toolSpanIDs, node.DescendantToolSpanIDs...)

		securityRiskSpanIDs = append(securityRiskSpanIDs, node.DescendantSecurityRiskSpanIDs...)
		privacyRiskSpanIDs = append(privacyRiskSpanIDs, node.DescendantPrivacyRiskSpanIDs...)
		riskCount += node.DescendantRiskCount
		evaluationCount += node.DescendantEvaluationCount
		evaluationFailedCount += node.DescendantEvaluationFailedCount
		evaluationFailedSpanIDs = append(evaluationFailedSpanIDs, node.DescendantEvaluationFailedSpanIDs...)
	}

	linkSpanIDs := make([]string, 0)
	for _, index := range indexes {
		for _, linkSpanID := range nodes[index].linkSpanIDs {
			if _, ok := internalSpanIDs[linkSpanID]; !ok {
				linkSpanIDs = append(linkSpanIDs, linkSpanID)
			}
		}
	}

	groupID := genAIFlowGroupID(first.ParentFlowSpanID, "loop", genAIFlowCyclePatternName(patternNodes))
	avgDuration := 0.0
	if len(indexes) > 0 {
		avgDuration = durationTotal / float64(len(indexes))
	}

	return GenAIFlowNode{
		NodeID:                            groupID,
		TraceID:                           first.TraceID,
		SpanID:                            groupID,
		Name:                              fmt.Sprintf("%s loop x%d", genAIFlowCyclePatternName(patternNodes), iterations),
		Kind:                              GenAISpanLoop,
		Operation:                         "loop",
		ModelNames:                        uniqueStrings(flattenGenAIFlowNodeModelNames(patternNodes)),
		TokenUsage:                        tokenUsage,
		Depth:                             first.Depth,
		DurationMs:                        durationTotal,
		AvgDurationMs:                     avgDuration,
		MaxDurationMs:                     durationMax,
		StatusCode:                        statusCode,
		Grouped:                           true,
		CallCount:                         iterations,
		GroupedSpanIDs:                    uniqueStrings(groupedSpanIDs),
		ParentFlowSpanID:                  first.ParentFlowSpanID,
		DescendantSpanIDs:                 uniqueStrings(groupedSpanIDs),
		DescendantTokenUsage:              tokenUsage,
		DescendantLLMCalls:                llmCalls,
		DescendantLLMSpanIDs:              uniqueStrings(llmSpanIDs),
		DescendantToolCalls:               toolCalls,
		DescendantToolSpanIDs:             uniqueStrings(toolSpanIDs),
		DescendantSecurityRiskCount:       len(uniqueStrings(securityRiskSpanIDs)),
		DescendantSecurityRiskSpanIDs:     uniqueStrings(securityRiskSpanIDs),
		DescendantPrivacyRiskCount:        len(uniqueStrings(privacyRiskSpanIDs)),
		DescendantPrivacyRiskSpanIDs:      uniqueStrings(privacyRiskSpanIDs),
		DescendantRiskCount:               riskCount,
		DescendantEvaluationCount:         evaluationCount,
		DescendantEvaluationFailedCount:   evaluationFailedCount,
		DescendantEvaluationFailedSpanIDs: uniqueStrings(evaluationFailedSpanIDs),
		linkSpanIDs:                       uniqueStrings(linkSpanIDs),
	}
}

func genAIFlowCyclePatternName(nodes []GenAIFlowNode) string {
	parts := make([]string, 0, len(nodes))
	for _, node := range nodes {
		parts = append(parts, node.Name)
	}
	return strings.Join(parts, " + ")
}

func genAIFlowGroupID(parts ...string) string {
	safeParts := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		part = strings.ReplaceAll(part, "\x00", "_")
		part = strings.ReplaceAll(part, ":", "_")
		part = strings.ReplaceAll(part, " ", "_")
		if part == "" {
			part = "_"
		}
		safeParts = append(safeParts, part)
	}
	return "group:" + strings.Join(safeParts, ":")
}

func flattenGenAIFlowNodeModelNames(nodes []GenAIFlowNode) []string {
	modelNames := make([]string, 0)
	for _, node := range nodes {
		modelNames = append(modelNames, node.ModelNames...)
	}
	return modelNames
}

func buildGenAIFlowEdges(nodes []GenAIFlowNode) []GenAIFlowEdge {
	selectedIDs := make(map[string]struct{}, len(nodes))
	groupAliasBySpanID := make(map[string]string)
	for _, node := range nodes {
		selectedIDs[node.SpanID] = struct{}{}
		for _, groupedSpanID := range node.GroupedSpanIDs {
			groupAliasBySpanID[groupedSpanID] = node.SpanID
		}
	}

	resolveSelectedFlowSpanID := func(spanID string) (string, bool) {
		if _, ok := selectedIDs[spanID]; ok {
			return spanID, true
		}
		if groupID, ok := groupAliasBySpanID[spanID]; ok {
			return groupID, true
		}
		return "", false
	}

	edges := make([]GenAIFlowEdge, 0, len(nodes))
	seen := make(map[GenAIFlowEdge]struct{})
	for _, node := range nodes {
		var predecessors []string
		for _, link := range node.linkSpanIDs {
			if predecessor, ok := resolveSelectedFlowSpanID(link); ok && predecessor != node.SpanID {
				predecessors = append(predecessors, predecessor)
			}
		}
		if len(predecessors) == 0 && node.ParentFlowSpanID != "" {
			if predecessor, ok := resolveSelectedFlowSpanID(node.ParentFlowSpanID); ok && predecessor != node.SpanID {
				predecessors = append(predecessors, predecessor)
			}
		}
		for _, predecessor := range uniqueStrings(predecessors) {
			if predecessor == node.SpanID {
				continue
			}
			edge := GenAIFlowEdge{Source: predecessor, Target: node.SpanID}
			if _, ok := seen[edge]; ok {
				continue
			}
			seen[edge] = struct{}{}
			edges = append(edges, edge)
		}
	}
	return edges
}

func isGenAISpan(span Span) bool {
	return hasAttributePrefix(span.Attributes, genAIPrefix) || hasAttributePrefix(span.Resource.Attributes, genAIPrefix) || hasGenAIEvaluationSignal(span)
}

func isGenAIFlowNodeSpan(span Span) bool {
	if isInferredGenAISpan(span) {
		return false
	}
	if isGenAIEvaluationOnlySpan(span) {
		return false
	}
	switch classifyGenAISpan(span) {
	case GenAISpanWorkflow, GenAISpanAgent, GenAISpanTool, GenAISpanLLM, GenAISpanRetrieval:
		return true
	default:
		return false
	}
}

func isInferredGenAISpan(span Span) bool {
	for _, attrs := range []map[string]any{span.Resource.Attributes, span.Attributes} {
		if inferredType := strings.TrimSpace(fmt.Sprint(attrs["_sf_inferredServiceType"])); inferredType != "" && inferredType != "<nil>" {
			switch inferredType {
			case "database", "_sf_pubsub", "_sf_service", "_sf_llm":
				return true
			}
		}
	}
	if value, ok := span.Resource.Attributes["sf.inferred"]; ok && toBool(value) {
		return true
	}
	if value, ok := span.Attributes["sf.inferred"]; ok && toBool(value) {
		return true
	}
	if value, ok := span.Resource.Attributes["splunk.inferred"]; ok && toBool(value) {
		return true
	}
	if value, ok := span.Attributes["splunk.inferred"]; ok && toBool(value) {
		return true
	}
	return false
}

func classifyGenAISpan(span Span) GenAISpanKind {
	operation := strings.ToLower(getGenAIOperation(span))
	toolName := getFirstAttributeString(span.Attributes, genAIToolNameKeys)
	agentName := getFirstAttributeString(span.Attributes, genAIAgentNameKeys)
	modelNames := getGenAIModelNames(span)
	tokens := getGenAITokenUsage(span)
	spanName := strings.ToLower(span.Name)
	isToolOperation := strings.Contains(operation, "tool") || operation == "function" || strings.Contains(spanName, " tool")
	isWorkflowOperation := strings.Contains(operation, "workflow")
	isRetrievalOperation := operation == "retrieval" || operation == "retriever" || strings.Contains(operation, "retrieval") || strings.Contains(operation, "retriever")
	isLLMOperation := operation == "llm" || strings.Contains(operation, "chat") || strings.Contains(operation, "completion") || strings.Contains(operation, "embedding") || strings.Contains(operation, "generate")
	isAgentOperation := strings.Contains(operation, "agent")

	switch {
	case toolName != "" || isToolOperation:
		return GenAISpanTool
	case isWorkflowOperation:
		return GenAISpanWorkflow
	case isRetrievalOperation:
		return GenAISpanRetrieval
	case isLLMOperation:
		return GenAISpanLLM
	case isAgentOperation || (agentName != "" && !isGenAIStepSpan(span)):
		return GenAISpanAgent
	case isGenAIStepSpan(span):
		return GenAISpanGeneric
	case len(modelNames) > 0 || tokens.Total > 0:
		return GenAISpanLLM
	default:
		return GenAISpanGeneric
	}
}

func isGenAIStepSpan(span Span) bool {
	return firstNonBlankString(span.Attributes["gen_ai.step.name"], span.Attributes["gen_ai.step.type"]) != ""
}

func getGenAIOperation(span Span) string {
	return getFirstAttributeString(span.Attributes, genAIOperationKeys)
}

func getGenAIModelNames(span Span) []string {
	var models []string
	for _, keys := range [][]string{genAIResponseModelKeys, genAIRequestModelKeys, genAIOtherModelKeys} {
		models = append(models, getGenAIModelNamesForKeys(span, keys)...)
	}
	return uniqueStrings(models)
}

func getGenAITraceModelNames(spans []Span) []string {
	models := make([]string, 0)
	for _, keys := range [][]string{genAIResponseModelKeys, genAIRequestModelKeys, genAIOtherModelKeys} {
		for _, span := range spans {
			models = append(models, getGenAIModelNamesForKeys(span, keys)...)
		}
	}
	return uniqueStrings(models)
}

func getGenAIModelNamesForKeys(span Span, keys []string) []string {
	models := make([]string, 0)
	for _, key := range keys {
		for _, model := range splitAttributeValues(span.Attributes[key]) {
			if isKnownGenAIModelName(model) {
				models = append(models, model)
			}
		}
	}
	return models
}

func isKnownGenAIModelName(model string) bool {
	normalized := strings.ToLower(strings.TrimSpace(model))
	if normalized == "" {
		return false
	}
	_, unknown := genAIPlaceholderModelNames[normalized]
	return !unknown
}

func getGenAITokenUsage(span Span) GenAITokenUsage {
	input := firstNumericAttribute(span.Attributes, genAIInputTokenKeys)
	output := firstNumericAttribute(span.Attributes, genAIOutputTokenKeys)
	total, hasTotal := firstNumericAttributeValue(span.Attributes, genAITotalTokenKeys)
	if !hasTotal {
		total = input + output
	}
	return GenAITokenUsage{Input: input, Output: output, Total: total}
}

func getGenAIFlowNodeName(span Span, kind GenAISpanKind, operation string) string {
	switch kind {
	case GenAISpanWorkflow:
		if name := firstNonBlankString(span.Attributes["gen_ai.workflow.name"], span.Attributes["workflow.name"], operation); name != "" {
			return name
		}
	case GenAISpanAgent:
		if name := firstNonBlankString(span.Attributes["gen_ai.agent.name"], span.Attributes["agent.name"], operation); name != "" {
			return name
		}
	case GenAISpanTool:
		if name := firstNonBlankString(span.Attributes["gen_ai.tool.name"], span.Attributes["tool.name"], operation); name != "" {
			return name
		}
	case GenAISpanRetrieval:
		if source := getFirstAttributeString(span.Attributes, genAIRetrievalNameKeys); source != "" && operation != "" {
			return operation + " " + source
		}
		if source := getFirstAttributeString(span.Attributes, genAIRetrievalNameKeys); source != "" {
			return source
		}
	case GenAISpanLLM:
		modelNames := getGenAIModelNames(span)
		if operation != "" && len(modelNames) > 0 {
			return operation + " " + modelNames[0]
		}
		if operation != "" {
			return operation
		}
	}
	if operation != "" {
		return operation
	}
	return span.Name
}

func addGenAIFlowNodeOwnSignals(node *GenAIFlowNode, span Span) {
	addGenAIFlowNodeRiskSignals(node, span, 0)
	addGenAIFlowNodeEvaluationSignals(node, span, 0)
}

func addGenAIFlowNodeDescendantSignals(node *GenAIFlowNode, span Span, spanListCap int) {
	if isGenAISpan(span) {
		node.DescendantTokenUsage = addTokenUsage(node.DescendantTokenUsage, getGenAITokenUsage(span))
		if !isGenAIEvaluationOnlySpan(span) {
			switch classifyGenAISpan(span) {
			case GenAISpanLLM:
				node.DescendantLLMCalls++
				node.DescendantLLMSpanIDs = appendSpanIDWithCap(node.DescendantLLMSpanIDs, span.SpanID, spanListCap)
			case GenAISpanTool:
				node.DescendantToolCalls++
				node.DescendantToolSpanIDs = appendSpanIDWithCap(node.DescendantToolSpanIDs, span.SpanID, spanListCap)
			}
		}
	}
	addGenAIFlowNodeRiskSignals(node, span, spanListCap)
	addGenAIFlowNodeEvaluationSignals(node, span, spanListCap)
}

func addGenAIFlowNodeRiskSignals(node *GenAIFlowNode, span Span, spanListCap int) {
	hasSecurityRisk := hasGenAISecurityRiskAttributes(span)
	hasPrivacyRisk := hasGenAIPrivacyRiskAttributes(span)
	if hasSecurityRisk || hasPrivacyRisk {
		node.DescendantRiskCount++
	}
	if hasSecurityRisk {
		node.DescendantSecurityRiskCount++
		node.DescendantSecurityRiskSpanIDs = appendSpanIDWithCap(node.DescendantSecurityRiskSpanIDs, span.SpanID, spanListCap)
	}
	if hasPrivacyRisk {
		node.DescendantPrivacyRiskCount++
		node.DescendantPrivacyRiskSpanIDs = appendSpanIDWithCap(node.DescendantPrivacyRiskSpanIDs, span.SpanID, spanListCap)
	}
}

func appendSpanIDWithCap(spanIDs []string, spanID string, cap int) []string {
	if cap > 0 && len(spanIDs) >= cap {
		return spanIDs
	}
	return append(spanIDs, spanID)
}

func hasGenAISecurityRiskAttributes(span Span) bool {
	return hasAttributePrefix(span.Attributes, "gen_ai.security.")
}

func hasGenAIPrivacyRiskAttributes(span Span) bool {
	return hasAttributePrefix(span.Attributes, "gen_ai.privacy.")
}

func addGenAIFlowNodeEvaluationSignals(node *GenAIFlowNode, span Span, spanListCap int) {
	evaluationCount, failedCount := getGenAIEvaluationCounts(span)
	if evaluationCount == 0 {
		return
	}
	node.DescendantEvaluationCount += evaluationCount
	node.DescendantEvaluationFailedCount += failedCount
	if failedCount > 0 {
		node.DescendantEvaluationFailedSpanIDs = appendSpanIDWithCap(node.DescendantEvaluationFailedSpanIDs, span.SpanID, spanListCap)
	}
}

func getGenAIEvaluationCounts(span Span) (int, int) {
	evaluationCount := 0
	failedCount := 0
	for _, event := range span.Events {
		if !isGenAIEvaluationEvent(event) {
			continue
		}
		evaluationCount++
		if genAIEvaluationAttributesFailed(event.Attributes) {
			failedCount++
		}
	}
	if evaluationCount > 0 {
		return evaluationCount, failedCount
	}
	if !hasGenAIEvaluationAttributes(span.Attributes) {
		return 0, 0
	}
	evaluationCount = 1
	if genAIEvaluationAttributesFailed(span.Attributes) {
		failedCount = 1
	}
	return evaluationCount, failedCount
}

func isGenAIEvaluationOnlySpan(span Span) bool {
	if !hasGenAIEvaluationSignal(span) {
		return false
	}
	if strings.TrimSpace(getGenAIOperation(span)) != "" {
		return false
	}
	if getFirstAttributeString(span.Attributes, genAIToolNameKeys) != "" {
		return false
	}
	if getFirstAttributeString(span.Attributes, genAIAgentNameKeys) != "" {
		return false
	}
	if getFirstAttributeString(span.Attributes, genAIRetrievalNameKeys) != "" {
		return false
	}
	return true
}

func hasGenAIEvaluationSignal(span Span) bool {
	if hasGenAIEvaluationAttributes(span.Attributes) {
		return true
	}
	for _, event := range span.Events {
		if isGenAIEvaluationEvent(event) {
			return true
		}
	}
	return false
}

func isGenAIEvaluationEvent(event SpanEvent) bool {
	return event.Name == "gen_ai.evaluation.result" || hasGenAIEvaluationAttributes(event.Attributes)
}

func hasGenAIEvaluationAttributes(attrs map[string]any) bool {
	if hasAttributePrefix(attrs, "gen_ai.evaluation.") {
		return true
	}
	if _, ok := attrs["gen_ai.evaluations"]; ok {
		return true
	}
	if _, ok := attrs["assistant.evaluation.outcome"]; ok {
		return true
	}
	return false
}

func genAIEvaluationAttributesFailed(attrs map[string]any) bool {
	if raw, ok := attrs["gen_ai.evaluation.passed"]; ok {
		switch typed := raw.(type) {
		case bool:
			return !typed
		case string:
			parsed, err := strconv.ParseBool(strings.TrimSpace(typed))
			if err == nil {
				return !parsed
			}
		}
	}

	outcome := strings.ToLower(firstNonBlankString(attrs["assistant.evaluation.outcome"]))
	switch outcome {
	case "failed", "fail", "error", "no_data":
		return true
	}

	scoreLabel := strings.ToLower(firstNonBlankString(attrs["gen_ai.evaluation.score.label"]))
	switch scoreLabel {
	case "failed", "fail", "error":
		return true
	}

	errorType := strings.ToLower(firstNonBlankString(attrs["error.type"]))
	return errorType != "" && errorType != "unknown" && errorType != "none"
}

func getGenAILinkSpanIDs(span Span) []string {
	if len(span.Links) == 0 {
		return nil
	}
	ids := make([]string, 0, len(span.Links))
	for _, link := range span.Links {
		if link.SpanID != "" {
			ids = append(ids, link.SpanID)
		}
	}
	return uniqueStrings(ids)
}

func addTokenUsage(a, b GenAITokenUsage) GenAITokenUsage {
	return GenAITokenUsage{
		Input:  a.Input + b.Input,
		Output: a.Output + b.Output,
		Total:  a.Total + b.Total,
	}
}

func hasAttributePrefix(attrs map[string]any, prefix string) bool {
	for key := range attrs {
		if strings.HasPrefix(key, prefix) {
			return true
		}
	}
	return false
}

func getFirstAttributeString(attrs map[string]any, keys []string) string {
	for _, key := range keys {
		values := splitAttributeValues(attrs[key])
		if len(values) > 0 {
			return values[0]
		}
	}
	return ""
}

func firstNonBlankString(values ...any) string {
	for _, value := range values {
		for _, part := range splitAttributeValues(value) {
			if strings.TrimSpace(part) != "" {
				return strings.TrimSpace(part)
			}
		}
	}
	return ""
}

func splitAttributeValues(value any) []string {
	switch typed := value.(type) {
	case nil:
		return nil
	case string:
		parts := strings.Split(typed, ",")
		values := make([]string, 0, len(parts))
		for _, part := range parts {
			if trimmed := strings.TrimSpace(part); trimmed != "" {
				values = append(values, trimmed)
			}
		}
		return values
	case []string:
		values := make([]string, 0, len(typed))
		for _, part := range typed {
			if trimmed := strings.TrimSpace(part); trimmed != "" {
				values = append(values, trimmed)
			}
		}
		return values
	case []any:
		var values []string
		for _, item := range typed {
			values = append(values, splitAttributeValues(item)...)
		}
		return values
	case json.Number:
		return []string{string(typed)}
	case float64, float32, int, int64, int32, uint64, uint32, bool:
		return []string{strings.TrimSpace(fmt.Sprint(value))}
	default:
		return nil
	}
}

func firstNumericAttribute(attrs map[string]any, keys []string) float64 {
	value, _ := firstNumericAttributeValue(attrs, keys)
	return value
}

func firstNumericAttributeValue(attrs map[string]any, keys []string) (float64, bool) {
	for _, key := range keys {
		raw, ok := attrs[key]
		if !ok {
			continue
		}
		value, ok := numericAttributeValue(raw)
		if ok && value >= 0 {
			return value, true
		}
	}
	return 0, false
}

func toFloat64(value any) float64 {
	numericValue, ok := numericAttributeValue(value)
	if !ok {
		return 0
	}
	return numericValue
}

func numericAttributeValue(value any) (float64, bool) {
	switch typed := value.(type) {
	case nil:
		return 0, false
	case float64:
		return typed, true
	case float32:
		return float64(typed), true
	case int:
		return float64(typed), true
	case int64:
		return float64(typed), true
	case int32:
		return float64(typed), true
	case uint64:
		return float64(typed), true
	case uint32:
		return float64(typed), true
	case string:
		parsed, err := strconv.ParseFloat(strings.TrimSpace(typed), 64)
		if err != nil {
			return 0, false
		}
		return parsed, true
	case json.Number:
		parsed, err := strconv.ParseFloat(string(typed), 64)
		if err != nil {
			return 0, false
		}
		return parsed, true
	default:
		return 0, false
	}
}

func toBool(value any) bool {
	switch typed := value.(type) {
	case bool:
		return typed
	case string:
		parsed, err := strconv.ParseBool(strings.TrimSpace(typed))
		return err == nil && parsed
	default:
		return false
	}
}

func uniqueStrings(values []string) []string {
	seen := make(map[string]struct{}, len(values))
	result := make([]string, 0, len(values))
	for _, value := range values {
		if value == "" {
			continue
		}
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		result = append(result, value)
	}
	return result
}

func cloneStrings(values []string) []string {
	if len(values) == 0 {
		return []string{}
	}
	return append([]string(nil), values...)
}

func maxGenAIFlowNodeSpanListSize() int {
	raw := os.Getenv("MAX_FLOW_NODE_SPAN_LIST_SIZE")
	if raw == "" {
		return 1000
	}
	parsed, err := strconv.Atoi(raw)
	if err != nil || parsed < 0 {
		return 1000
	}
	return parsed
}
