package mcp

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

type claudeMetricSeries struct {
	tokenType           string
	dimensionKey        string
	logicalDimensionKey string
	points              []store.MetricDataPoint
}

type claudeMetricCoverage struct {
	start       time.Time
	latest      time.Time
	startKnown  bool
	latestKnown bool
}

type claudeMetricPointValue struct {
	bits      uint64
	flags     int
	monotonic bool
}

var requiredClaudeMetricTokenTypes = []string{"input", "cache_read", "cache_creation", "output"}

func buildProviderMetricTasks(
	metrics []store.MetricDataPoint,
	args map[string]any,
	unavailableThrough time.Time,
) []providerLogTaskBuild {
	if strArg(args, "spanName") != "" || strArg(args, "skillName") != "" {
		return nil
	}
	providerFilter := strings.ToLower(strings.TrimSpace(strArg(args, "provider")))
	if providerFilter != "" && providerFilter != "claude" {
		return nil
	}
	if strArg(args, "traceId") != "" {
		return nil
	}

	serviceName := strings.TrimSpace(strArg(args, "serviceName"))
	exactTaskID := strings.TrimSpace(strArg(args, "taskId"))
	exactConversationID := conversationIDArg(args)
	taskIDPrefix := strings.ToLower(strings.TrimSpace(strArg(args, "traceIdPrefix")))
	groups := make(map[string][]store.MetricDataPoint)
	groupOrder := make([]string, 0)

	for _, point := range metrics {
		if store.ClassifyProviderUsageMetric(point) != store.ProviderUsageMetricClaude {
			continue
		}
		if serviceName != "" && !strings.EqualFold(point.Resource.ServiceName, serviceName) {
			continue
		}
		sessionID := firstStringAttribute(point.Attributes, "session.id", "session_id")
		if exactTaskID != "" && !strings.EqualFold(sessionID, exactTaskID) {
			continue
		}
		if exactConversationID != "" && !strings.EqualFold(sessionID, exactConversationID) {
			continue
		}
		if taskIDPrefix != "" && !strings.HasPrefix(strings.ToLower(sessionID), taskIDPrefix) {
			continue
		}

		groupKey := strings.ToLower(sessionID)
		if groupKey == "" {
			groupKey = "missing:" + metricPointTime(point).UTC().Format(time.RFC3339Nano)
		}
		if _, exists := groups[groupKey]; !exists {
			groupOrder = append(groupOrder, groupKey)
		}
		groups[groupKey] = append(groups[groupKey], point)
	}

	built := make([]providerLogTaskBuild, 0, len(groups))
	for _, groupKey := range groupOrder {
		points := groups[groupKey]
		if len(points) == 0 {
			continue
		}
		built = append(built, buildClaudeMetricTask(points, unavailableThrough))
	}
	return sortProviderTaskBuilds(built)
}

func buildClaudeMetricTask(points []store.MetricDataPoint, unavailableThrough time.Time) providerLogTaskBuild {
	sort.SliceStable(points, func(i, j int) bool {
		left := metricPointTime(points[i])
		right := metricPointTime(points[j])
		if left.Equal(right) {
			return claudeMetricPointDedupeKey(points[i]) < claudeMetricPointDedupeKey(points[j])
		}
		return left.Before(right)
	})

	first := points[0]
	sessionID := firstStringAttribute(first.Attributes, "session.id", "session_id")
	taskID := sessionID
	taskKind := "session"
	correlationStatus := "provider_session"
	if taskID == "" {
		taskID = fmt.Sprintf("claude-metric:%d", metricPointTime(first).UnixNano())
		taskKind = "metric_batch"
		correlationStatus = "uncorrelated"
	}

	models := make(map[string]struct{})
	pointValues := make(map[string]claudeMetricPointValue, len(points))
	conflictingPoints := make(map[string]struct{})
	uniquePoints := make([]store.MetricDataPoint, 0, len(points))
	for _, point := range points {
		identity := claudeMetricPointIdentityKey(point)
		value := claudeMetricPointValue{
			bits:      math.Float64bits(point.Value),
			flags:     point.Flags,
			monotonic: point.IsMonotonic,
		}
		if previous, duplicate := pointValues[identity]; duplicate {
			if previous != value {
				conflictingPoints[identity] = struct{}{}
			}
			continue
		}
		pointValues[identity] = value
		uniquePoints = append(uniquePoints, point)
	}

	seriesByKey := make(map[string]*claudeMetricSeries)
	seriesOrder := make([]string, 0)
	dimensionObserved := make(map[string]map[string]bool)
	unrecognized := 0
	for _, point := range uniquePoints {
		if model := firstStringAttribute(point.Attributes, "model", "gen_ai.response.model", "gen_ai.request.model"); model != "" {
			models[model] = struct{}{}
		}
		tokenType, knownType := claudeMetricTokenType(firstStringAttribute(point.Attributes, "type"))
		if knownType {
			dimensionKey := claudeMetricDimensionKey(point)
			if dimensionObserved[dimensionKey] == nil {
				dimensionObserved[dimensionKey] = make(map[string]bool)
			}
			dimensionObserved[dimensionKey][tokenType] = true
		}
		if _, conflicting := conflictingPoints[claudeMetricPointIdentityKey(point)]; conflicting {
			unrecognized++
			continue
		}

		_, validValue := nonNegativeInt64(point.Value)
		temporality := strings.ToLower(strings.TrimSpace(point.Temporality))
		if !knownType || !strings.EqualFold(point.Type, "sum") || !point.IsMonotonic || (temporality != "delta" && temporality != "cumulative") || !validValue || point.Flags&1 != 0 {
			unrecognized++
			continue
		}

		seriesKey := claudeMetricSeriesKey(point, tokenType)
		series := seriesByKey[seriesKey]
		if series == nil {
			series = &claudeMetricSeries{
				tokenType:           tokenType,
				dimensionKey:        claudeMetricDimensionKey(point),
				logicalDimensionKey: claudeMetricLogicalDimensionKey(point),
			}
			seriesByKey[seriesKey] = series
			seriesOrder = append(seriesOrder, seriesKey)
		}
		series.points = append(series.points, point)
	}

	componentSums := make(map[string]int64)
	componentSeen := make(map[string]bool)
	dimensionSeen := make(map[string]map[string]bool)
	allSeriesCumulative := len(seriesOrder) > 0
	seriesHistoryTruncated := false
	coverageByComponent := make(map[string]*claudeMetricCoverage)
	for _, seriesKey := range seriesOrder {
		series := seriesByKey[seriesKey]
		coverageKey := series.logicalDimensionKey + "\x00" + series.tokenType
		coverage := coverageByComponent[coverageKey]
		if coverage == nil {
			coverage = &claudeMetricCoverage{startKnown: true, latestKnown: true}
			coverageByComponent[coverageKey] = coverage
		}
		if len(series.points) == 0 || !strings.EqualFold(strings.TrimSpace(series.points[0].Temporality), "cumulative") {
			allSeriesCumulative = false
		}
		if claudeMetricSeriesTruncated(series.points, unavailableThrough) {
			unrecognized++
			seriesHistoryTruncated = true
		}
		value, ok := aggregateClaudeMetricSeries(series.points)
		if !ok {
			unrecognized++
			coverage.startKnown = false
			coverage.latestKnown = false
			continue
		}
		seriesStart := latestClaudeMetricSeriesStart(series.points)
		if seriesStart.IsZero() {
			coverage.startKnown = false
		} else if coverage.start.IsZero() || seriesStart.Before(coverage.start) {
			coverage.start = seriesStart
		}
		seriesLatest := latestClaudeMetricSeriesTime(series.points)
		if seriesLatest.IsZero() {
			coverage.latestKnown = false
		} else if seriesLatest.After(coverage.latest) {
			coverage.latest = seriesLatest
		}
		current := componentSums[series.tokenType]
		if value > math.MaxInt64-current {
			unrecognized++
			continue
		}
		componentSums[series.tokenType] = current + value
		componentSeen[series.tokenType] = true
		if dimensionSeen[series.dimensionKey] == nil {
			dimensionSeen[series.dimensionKey] = make(map[string]bool)
		}
		dimensionSeen[series.dimensionKey][series.tokenType] = true
	}
	coverageStart := time.Time{}
	coverageStartKnown := len(coverageByComponent) > 0
	coverageLatest := time.Time{}
	coverageLatestKnown := len(coverageByComponent) > 0
	for _, coverage := range coverageByComponent {
		if !coverage.startKnown || coverage.start.IsZero() {
			coverageStartKnown = false
		} else if coverage.start.After(coverageStart) {
			coverageStart = coverage.start
		}
		if !coverage.latestKnown || coverage.latest.IsZero() {
			coverageLatestKnown = false
		} else if coverageLatest.IsZero() || coverage.latest.Before(coverageLatest) {
			coverageLatest = coverage.latest
		}
	}
	allDimensionsComplete := len(dimensionObserved) > 0
	for dimensionKey, observed := range dimensionObserved {
		seen := dimensionSeen[dimensionKey]
		for _, tokenType := range requiredClaudeMetricTokenTypes {
			if seen[tokenType] {
				continue
			}
			allDimensionsComplete = false
			if !observed[tokenType] {
				unrecognized++
			}
		}
	}

	uncachedInput := measuredMetricComponent(componentSums, componentSeen, "input")
	cachedInput := measuredMetricComponent(componentSums, componentSeen, "cache_read")
	cacheCreationInput := measuredMetricComponent(componentSums, componentSeen, "cache_creation")
	output := measuredMetricComponent(componentSums, componentSeen, "output")
	normalizedInput := addKnownTokens(uncachedInput, cachedInput, cacheCreationInput)
	usage := normalizedTokenUsage(normalizedInput, cachedInput, cacheCreationInput, output, nil, nil)

	records := make([]tokenUsageRecord, 0, 1+unrecognized)
	if len(componentSeen) > 0 {
		records = append(records, tokenUsageRecord{
			observed:   true,
			recognized: true,
			provider:   "claude",
			usage:      usage,
		})
	}
	for index := 0; index < unrecognized; index++ {
		records = append(records, tokenUsageRecord{observed: true, provider: "claude"})
	}
	if len(records) == 0 {
		records = append(records, tokenUsageRecord{observed: true, provider: "claude"})
	}

	var aggregate tokenUsageAccumulator
	aggregate.addTask(records)
	status := aggregate.status()
	accountingStatus := "unknown"
	if status == "partial" {
		accountingStatus = "partial"
	} else if status == "measured" {
		if sessionID == "" {
			accountingStatus = "uncorrelated"
		} else if !allSeriesCumulative || !allDimensionsComplete {
			accountingStatus = "partial"
		} else {
			accountingStatus = "exact"
		}
	}
	normalization := "input is derived from uncached input plus cache-read and cache-creation input; output includes provider thinking tokens; provider total and separate reasoning output are not emitted by this metric"
	if !allSeriesCumulative {
		normalization += "; delta points measure only the retained export window and cannot prove full-session accounting"
	}
	if seriesHistoryTruncated {
		normalization += "; the metric history availability boundary reached this session's series start, so earlier points or dimensions cannot be proven complete"
	}
	if !allDimensionsComplete {
		normalization += "; at least one metric dimension omitted a required token component"
	}

	startTime := first.StartTime
	if startTime.IsZero() {
		startTime = metricPointTime(first)
	}
	endTime := metricPointTime(points[len(points)-1])
	if !coverageStartKnown {
		coverageStart = time.Time{}
	}
	if !coverageLatestKnown {
		coverageLatest = time.Time{}
	}
	serviceName := first.Resource.ServiceName
	if serviceName == "" {
		serviceName = "claude-code"
	}
	return providerLogTaskBuild{
		task: tokenUsageTask{
			TaskID:              taskID,
			TaskKind:            taskKind,
			ConversationID:      sessionID,
			ServiceName:         serviceName,
			StartTime:           formatTokenUsageTime(startTime),
			EndTime:             formatTokenUsageTime(endTime),
			MeasurementSource:   "claude_token_metrics",
			Normalization:       normalization,
			Status:              status,
			AccountingStatus:    accountingStatus,
			CorrelationStatus:   correlationStatus,
			Provider:            "claude",
			SkillNames:          []string{},
			ModelNames:          sortedSet(models),
			RequestCount:        0,
			ProviderEventCount:  0,
			ProviderMetricCount: len(points),
			TraceSpanCount:      0,
			TraceComplete:       false,
			Usage:               aggregate.values(),
			Coverage:            aggregate.coverage,
		},
		records:                  records,
		latest:                   endTime,
		metricCoverageStart:      &coverageStart,
		metricCoverageLatest:     &coverageLatest,
		sessionHistoryIncomplete: seriesHistoryTruncated,
	}
}

func latestClaudeMetricSeriesStart(points []store.MetricDataPoint) time.Time {
	latest := time.Time{}
	for _, point := range points {
		if point.StartTime.IsZero() {
			return time.Time{}
		}
		if point.StartTime.After(latest) {
			latest = point.StartTime
		}
	}
	return latest
}

func latestClaudeMetricSeriesTime(points []store.MetricDataPoint) time.Time {
	latest := time.Time{}
	for _, point := range points {
		pointTime := metricPointTime(point)
		if pointTime.After(latest) {
			latest = pointTime
		}
	}
	return latest
}

func claudeMetricSeriesTruncated(points []store.MetricDataPoint, unavailableThrough time.Time) bool {
	if len(points) == 0 || unavailableThrough.IsZero() {
		return false
	}
	start := points[0].StartTime
	if start.IsZero() {
		return true
	}
	return !start.After(unavailableThrough)
}

func aggregateClaudeMetricSeries(points []store.MetricDataPoint) (int64, bool) {
	if len(points) == 0 {
		return 0, false
	}
	temporality := strings.ToLower(strings.TrimSpace(points[0].Temporality))
	ordered := points
	if temporality == "cumulative" {
		ordered = append([]store.MetricDataPoint(nil), points...)
		sort.SliceStable(ordered, func(i, j int) bool {
			return metricPointTime(ordered[i]).Before(metricPointTime(ordered[j]))
		})
	}
	var total int64
	var latest time.Time
	latestSet := false
	for _, point := range ordered {
		if strings.ToLower(strings.TrimSpace(point.Temporality)) != temporality {
			return 0, false
		}
		value, ok := nonNegativeInt64(point.Value)
		if !ok {
			return 0, false
		}
		switch temporality {
		case "delta":
			if value > math.MaxInt64-total {
				return 0, false
			}
			total += value
		case "cumulative":
			pointTime := metricPointTime(point)
			if latestSet && pointTime.Equal(latest) && value != total {
				return 0, false
			}
			if !latestSet || pointTime.After(latest) {
				if latestSet && value < total {
					return 0, false
				}
				total = value
				latest = pointTime
				latestSet = true
			}
		default:
			return 0, false
		}
	}
	return total, true
}

func claudeMetricTokenType(raw string) (string, bool) {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "input":
		return "input", true
	case "cacheread":
		return "cache_read", true
	case "cachecreation":
		return "cache_creation", true
	case "output":
		return "output", true
	default:
		return "", false
	}
}

func measuredMetricComponent(values map[string]int64, seen map[string]bool, key string) *int64 {
	if !seen[key] {
		return nil
	}
	value := values[key]
	return &value
}

func claudeMetricSeriesKey(point store.MetricDataPoint, tokenType string) string {
	return claudeMetricDimensionKey(point) + "\x00" + tokenType
}

func claudeMetricDimensionKey(point store.MetricDataPoint) string {
	return claudeMetricDimensionKeyWithStartTime(point, true)
}

func claudeMetricLogicalDimensionKey(point store.MetricDataPoint) string {
	return claudeMetricDimensionKeyWithStartTime(point, false)
}

func claudeMetricDimensionKeyWithStartTime(point store.MetricDataPoint, includeStartTime bool) string {
	attributes := make(map[string]any, len(point.Attributes))
	for key, value := range point.Attributes {
		if strings.EqualFold(key, "type") {
			continue
		}
		attributes[key] = value
	}
	encodedAttributes := claudeMetricAttributesKey(attributes)
	encodedResourceAttributes := claudeMetricAttributesKey(point.Resource.Attributes)
	parts := []string{
		strings.TrimSpace(point.Resource.ServiceName),
		strings.TrimSpace(point.Resource.SchemaURL),
		encodedResourceAttributes,
		strings.TrimSpace(point.Scope.Name),
		strings.TrimSpace(point.Scope.Version),
		strings.TrimSpace(point.Scope.SchemaURL),
	}
	if includeStartTime {
		parts = append(parts, point.StartTime.UTC().Format(time.RFC3339Nano))
	}
	parts = append(parts, encodedAttributes)
	return strings.Join(parts, "\x00")
}

func claudeMetricAttributesKey(attributes map[string]any) string {
	if len(attributes) == 0 {
		return "{}"
	}
	encoded, err := json.Marshal(attributes)
	if err != nil {
		// OTLP attributes are JSON-compatible; preserve a distinct fail-safe key
		// if a manually constructed point violates that contract.
		return fmt.Sprintf("unencodable:%p:%#v", attributes, attributes)
	}
	return string(encoded)
}

func claudeMetricPointDedupeKey(point store.MetricDataPoint) string {
	return fmt.Sprintf("%s\x00%016x\x00%d",
		claudeMetricPointIdentityKey(point),
		math.Float64bits(point.Value),
		point.Flags,
	)
}

func claudeMetricPointIdentityKey(point store.MetricDataPoint) string {
	tokenType := strings.ToLower(firstStringAttribute(point.Attributes, "type"))
	return fmt.Sprintf("%s\x00%s\x00%s\x00%d",
		claudeMetricSeriesKey(point, tokenType),
		strings.ToLower(strings.TrimSpace(point.Type)),
		strings.ToLower(strings.TrimSpace(point.Temporality)),
		metricPointTime(point).UnixNano(),
	)
}

func metricPointTime(point store.MetricDataPoint) time.Time {
	if !point.Timestamp.IsZero() {
		return point.Timestamp
	}
	return point.StartTime
}
