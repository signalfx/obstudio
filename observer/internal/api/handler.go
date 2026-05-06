// Package api implements the REST API handler for telemetry queries.
package api

import (
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
)

type ServerInfo struct {
	APIVersion string    `json:"apiVersion"`
	Kind       string    `json:"kind"`
	Mode       string    `json:"mode"`
	Owner      string    `json:"owner"`
	StartedAt  time.Time `json:"startedAt"`
	Version    string    `json:"version"`
}

type healthResponse struct {
	ServerInfo
	Endpoints map[string]string `json:"endpoints"`
}

// Register adds the REST API routes to the given mux.
// It registers handlers for querying traces, metrics, logs, and stats.
func Register(mux *http.ServeMux, s *store.Store, params ...any) {
	validationStore := validator.NewStore()
	var runner validator.Runner
	info := ServerInfo{
		Kind:       "obstudio",
		APIVersion: "v1",
		Version:    "dev",
		Owner:      "unknown",
		Mode:       "standalone",
		StartedAt:  time.Now().UTC(),
	}
	for _, param := range params {
		switch value := param.(type) {
		case *validator.Store:
			if value != nil {
				validationStore = value
			}
		case validator.Runner:
			if value != nil {
				runner = value
			}
		case ServerInfo:
			info = value
		}
	}
	validationService := validator.NewService(validationStore, runner)
	mux.HandleFunc("OPTIONS /api/", corsPreflightHandler())
	mux.HandleFunc("GET /api/health", queryHealth(s, info))
	mux.HandleFunc("GET /api/query/traces", queryTraces(s))
	mux.HandleFunc("GET /api/query/traces/filter-values", queryTraceFilterValues(s))
	mux.HandleFunc("GET /api/query/traces/{traceId}", queryTraceDetail(s))
	mux.HandleFunc("GET /api/query/metrics", queryMetrics(s))
	mux.HandleFunc("GET /api/query/metrics/filter-values", queryMetricFilterValues(s))
	mux.HandleFunc("GET /api/query/logs", queryLogs(s))
	mux.HandleFunc("GET /api/query/logs/filter-values", queryLogFilterValues(s))
	mux.HandleFunc("GET /api/query/stats", queryStats(s))
	mux.HandleFunc("GET /api/query/validation/summary", queryValidationStatus(validationService))
	mux.HandleFunc("GET /api/query/validation/status", queryValidationStatus(validationService))
	mux.HandleFunc("GET /api/query/validation/latest", queryValidationLatest(validationService))
	mux.HandleFunc("POST /api/validation/run", runValidation(validationService))
	mux.HandleFunc("POST /api/validation/refresh", refreshValidation(validationService))
	mux.HandleFunc("POST /api/validation/analyze", analyzeValidation(validationService))
	mux.HandleFunc("GET /api/query/validation/findings", queryValidationFindings(validationService))
	mux.HandleFunc("DELETE /api/data", clearData(s, validationStore))
}

func queryTraces(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, s.QueryTraceSummariesFiltered(traceSummaryFilterFromRequest(r)))
	}
}

func queryTraceDetail(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		traceID := r.PathValue("traceId")
		detail := s.Trace(traceID, queryInt(r, "eventLimit", 12))
		if detail == nil {
			http.Error(w, "trace not found", http.StatusNotFound)
			return
		}
		writeJSON(w, detail)
	}
}

func queryMetrics(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, s.QueryMetricGroupsFiltered(metricGroupFilterFromRequest(r)))
	}
}

func queryTraceFilterValues(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		field, prefix, limit := filterValueRequest(r)
		writeJSON(w, s.QueryTraceSummaryFieldValues(field, prefix, traceSummaryFilterFromRequest(r), limit))
	}
}

func queryMetricFilterValues(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		field, prefix, limit := filterValueRequest(r)
		writeJSON(w, s.QueryMetricGroupFieldValues(field, prefix, metricGroupFilterFromRequest(r), limit))
	}
}

func queryLogFilterValues(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		field, prefix, limit := filterValueRequest(r)
		writeJSON(w, s.QueryLogRecordFieldValues(field, prefix, logRecordFilterFromRequest(r), limit))
	}
}

func queryLogs(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, s.QueryLogRecordsFiltered(logRecordFilterFromRequest(r)))
	}
}

func queryStats(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, s.Stats())
	}
}

func queryValidationStatus(service *validator.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, service.Summary())
	}
}

func queryHealth(s *store.Store, info ServerInfo) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var endpoints store.Endpoints
		if s != nil {
			endpoints = s.Endpoints()
		}

		mcpEndpoint := ""
		if endpoints.REST != "" {
			mcpEndpoint = endpoints.REST + "/mcp"
		}

		writeJSON(w, healthResponse{
			ServerInfo: info,
			Endpoints: map[string]string{
				"mcp":      mcpEndpoint,
				"otlpGrpc": endpoints.OTLPgRPC,
				"otlpHttp": endpoints.OTLPHTTP,
				"rest":     endpoints.REST,
			},
		})
	}
}

func queryValidationFindings(service *validator.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		findings, err := service.Findings(validationQueryFromRequest(r), r.URL.Query().Get("runId"))
		if err != nil {
			statusCode, payload := validationHTTPErrorPayload(err, http.MethodPost, "/api/validation/analyze")
			w.WriteHeader(statusCode)
			writeJSON(w, payload)
			return
		}
		writeJSON(w, findings)
	}
}

func queryValidationLatest(service *validator.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		snapshot, err := service.Latest(validationQueryFromRequest(r))
		if err != nil {
			statusCode, payload := validationHTTPErrorPayload(err, http.MethodPost, "/api/validation/analyze")
			w.WriteHeader(statusCode)
			writeJSON(w, payload)
			return
		}
		writeJSON(w, snapshot)
	}
}

func analyzeValidation(service *validator.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		args := decodeJSONBodyMap(r)
		query := validationQueryFromMap(args)
		timeout := durationArgSeconds(args, "timeoutSeconds", 90*time.Second, 5*time.Second, 5*time.Minute)
		freshness := freshnessArg(args, "freshness", validator.FreshnessAuto)

		analysis, err := service.Analyze(r.Context(), query, freshness, timeout)
		if err != nil {
			nextMethod := http.MethodPost
			nextPath := "/api/validation/analyze"
			if freshness == validator.FreshnessLatestOK {
				nextPath = "/api/validation/refresh"
			}
			statusCode, payload := validationHTTPErrorPayload(err, nextMethod, nextPath)
			w.WriteHeader(statusCode)
			writeJSON(w, payload)
			return
		}
		writeJSON(w, analysis)
	}
}

func refreshValidation(service *validator.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		args := decodeJSONBodyMap(r)
		query := validationQueryFromMap(args)
		timeout := durationArgSeconds(args, "timeoutSeconds", 90*time.Second, 5*time.Second, 5*time.Minute)
		analysis, err := service.Refresh(r.Context(), query, timeout)
		if err != nil {
			statusCode, payload := validationHTTPErrorPayload(err, http.MethodGet, "/api/query/validation/status")
			w.WriteHeader(statusCode)
			writeJSON(w, payload)
			return
		}
		writeJSON(w, analysis)
	}
}

func runValidation(service *validator.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		summary, err := service.Run(r.Context())
		if err != nil {
			statusCode, payload := validationHTTPErrorPayload(err, http.MethodGet, "/api/query/validation/status")
			w.WriteHeader(statusCode)
			writeJSON(w, payload)
			return
		}
		writeJSON(w, summary)
	}
}

func clearData(s *store.Store, v *validator.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.Clear()
		v.Clear()
		writeJSON(w, map[string]string{"status": "cleared"})
	}
}

func corsPreflightHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		w.WriteHeader(http.StatusNoContent)
	}
}

func validationQueryFromRequest(r *http.Request) validator.Query {
	return validator.Query{
		ServiceName: r.URL.Query().Get("serviceName"),
		SignalType:  r.URL.Query().Get("signalType"),
		Severity:    r.URL.Query().Get("severity"),
		RuleID:      r.URL.Query().Get("ruleId"),
		TraceID:     r.URL.Query().Get("traceId"),
		SpanID:      r.URL.Query().Get("spanId"),
		MetricName:  r.URL.Query().Get("metricName"),
		LogBody:     r.URL.Query().Get("logBody"),
		Limit:       queryInt(r, "limit", 0),
	}
}

func traceSummaryFilterFromRequest(r *http.Request) store.TraceSummaryFilter {
	q := r.URL.Query()
	filter := store.TraceSummaryFilter{
		Query:               q.Get("query"),
		TraceID:             queryEqString(q, "traceId", "traceId"),
		ExcludeTraceID:      queryNeqString(q, "traceId"),
		RootSpanName:        queryEqString(q, "rootSpanName", "rootSpanName"),
		ExcludeRootSpanName: queryNeqString(q, "rootSpanName"),
		ServiceName:         queryEqString(q, "serviceName", "serviceName"),
		ExcludeServiceName:  queryNeqString(q, "serviceName"),
		Status:              queryEqString(q, "status", "status"),
		ExcludeStatus:       queryNeqString(q, "status"),
		Limit:               queryInt(r, "limit", 100),
		SpanPreviewCap:      8,
	}
	if n, ok := queryOptionalIntValues(q.Get("filter[spanCount][eq]"), q.Get("filter[spanCount]"), q.Get("spanCount")); ok {
		filter.SpanCount = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[spanCount][gt]")); ok {
		filter.SpanCountGT = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[spanCount][lt]")); ok {
		filter.SpanCountLT = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[spanCount][gte]"), q.Get("minSpanCount")); ok {
		filter.MinSpanCount = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[spanCount][lte]"), q.Get("maxSpanCount")); ok {
		filter.MaxSpanCount = &n
	}
	if n, ok := queryOptionalFloatValues(q.Get("filter[durationMs][eq]"), q.Get("filter[durationMs]"), q.Get("durationMs")); ok {
		filter.DurationMs = &n
	}
	if n, ok := queryOptionalFloatValues(q.Get("range[durationMs][gt]")); ok {
		filter.DurationMsGT = &n
	}
	if n, ok := queryOptionalFloatValues(q.Get("range[durationMs][lt]")); ok {
		filter.DurationMsLT = &n
	}
	if n, ok := queryOptionalFloatValues(q.Get("range[durationMs][gte]"), q.Get("minDurationMs")); ok {
		filter.MinDurationMs = &n
	}
	if n, ok := queryOptionalFloatValues(q.Get("range[durationMs][lte]"), q.Get("maxDurationMs")); ok {
		filter.MaxDurationMs = &n
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[from]")); ok {
		filter.TimeFrom = &ts
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[to]")); ok {
		filter.TimeTo = &ts
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[after]")); ok {
		filter.TimeAfter = &ts
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[before]")); ok {
		filter.TimeBefore = &ts
	}
	return filter
}

func metricGroupFilterFromRequest(r *http.Request) store.MetricGroupFilter {
	q := r.URL.Query()
	filter := store.MetricGroupFilter{
		Query:             q.Get("query"),
		MetricName:        queryEqString(q, "metricName", "metricName"),
		ExcludeMetricName: queryNeqString(q, "metricName"),
		DescriptionContains: firstNonEmpty(
			q.Get("filter[descriptionContains][eq]"),
			q.Get("filter[descriptionContains]"),
			q.Get("description"),
		),
		ExcludeDescriptionContains: q.Get("filter[descriptionContains][neq]"),
		Unit:                       queryEqString(q, "unit", "unit"),
		ExcludeUnit:                queryNeqString(q, "unit"),
		Type:                       queryEqString(q, "type", "type"),
		ExcludeType:                queryNeqString(q, "type"),
		ServiceName:                queryEqString(q, "serviceName", "serviceName"),
		ExcludeServiceName:         queryNeqString(q, "serviceName"),
		ScopeName:                  queryEqString(q, "scopeName", "scopeName"),
		ExcludeScopeName:           queryNeqString(q, "scopeName"),
		Limit:                      queryInt(r, "limit", 100),
	}
	if n, ok := queryOptionalIntValues(q.Get("filter[dataPointCount][eq]"), q.Get("filter[dataPointCount]"), q.Get("dataPointCount")); ok {
		filter.DataPointCount = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[dataPointCount][gt]")); ok {
		filter.DataPointCountGT = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[dataPointCount][lt]")); ok {
		filter.DataPointCountLT = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[dataPointCount][gte]"), q.Get("minDataPointCount")); ok {
		filter.MinDataPointCount = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[dataPointCount][lte]"), q.Get("maxDataPointCount")); ok {
		filter.MaxDataPointCount = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("filter[seriesCount][eq]"), q.Get("filter[seriesCount]"), q.Get("seriesCount")); ok {
		filter.SeriesCount = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[seriesCount][gt]")); ok {
		filter.SeriesCountGT = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[seriesCount][lt]")); ok {
		filter.SeriesCountLT = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[seriesCount][gte]"), q.Get("minSeriesCount")); ok {
		filter.MinSeriesCount = &n
	}
	if n, ok := queryOptionalIntValues(q.Get("range[seriesCount][lte]"), q.Get("maxSeriesCount")); ok {
		filter.MaxSeriesCount = &n
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[from]")); ok {
		filter.TimeFrom = &ts
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[to]")); ok {
		filter.TimeTo = &ts
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[after]")); ok {
		filter.TimeAfter = &ts
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[before]")); ok {
		filter.TimeBefore = &ts
	}
	return filter
}

func logRecordFilterFromRequest(r *http.Request) store.LogRecordFilter {
	q := r.URL.Query()
	filter := store.LogRecordFilter{
		ServiceName:            queryEqString(q, "serviceName", "serviceName"),
		ExcludeServiceName:     queryNeqString(q, "serviceName"),
		SeverityDisplay:        queryEqString(q, "severityDisplay", "severityDisplay"),
		ExcludeSeverityDisplay: queryNeqString(q, "severityDisplay"),
		SeverityText:           queryEqString(q, "severityText", "severityText"),
		ExcludeSeverityText:    queryNeqString(q, "severityText"),
		BodyContains:           firstNonEmpty(q.Get("filter[bodyContains][eq]"), q.Get("filter[bodyContains]"), q.Get("body")),
		ExcludeBodyContains:    q.Get("filter[bodyContains][neq]"),
		TraceID:                queryEqString(q, "traceId", "traceId"),
		ExcludeTraceID:         queryNeqString(q, "traceId"),
		SpanID:                 queryEqString(q, "spanId", "spanId"),
		ExcludeSpanID:          queryNeqString(q, "spanId"),
		ScopeName:              queryEqString(q, "scopeName", "scopeName"),
		ExcludeScopeName:       queryNeqString(q, "scopeName"),
		Query:                  q.Get("query"),
		Limit:                  queryInt(r, "limit", 100),
	}
	if n, ok := queryOptionalIntValues(q.Get("filter[severityNumber][eq]"), q.Get("filter[severityNumber]")); ok {
		severity := int32(n)
		filter.SeverityNumber = &severity
	}
	if n, ok := queryOptionalIntValues(q.Get("filter[severityNumber][neq]")); ok {
		severity := int32(n)
		filter.ExcludeSeverityNumber = &severity
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[from]")); ok {
		filter.TimeFrom = &ts
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[to]")); ok {
		filter.TimeTo = &ts
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[after]")); ok {
		filter.TimeAfter = &ts
	}
	if ts, ok := queryOptionalTimeValues(q.Get("time[before]")); ok {
		filter.TimeBefore = &ts
	}
	return filter
}

func validationQueryFromMap(args map[string]any) validator.Query {
	return validator.Query{
		ServiceName: stringArg(args, "serviceName"),
		SignalType:  stringArg(args, "signalType"),
		Severity:    stringArg(args, "severity"),
		RuleID:      stringArg(args, "ruleId"),
		TraceID:     stringArg(args, "traceId"),
		SpanID:      stringArg(args, "spanId"),
		MetricName:  stringArg(args, "metricName"),
		LogBody:     stringArg(args, "logBody"),
		Limit:       intArg(args, "limit", 50),
	}
}

func validationHTTPErrorPayload(err error, nextMethod, nextPath string) (int, map[string]any) {
	var serviceErr *validator.ServiceError
	if !errors.As(err, &serviceErr) {
		return http.StatusConflict, map[string]any{
			"error":      err.Error(),
			"nextAction": map[string]string{"method": nextMethod, "path": nextPath},
		}
	}

	payload := map[string]any{
		"error":      serviceErr.Error(),
		"summary":    serviceErr.Summary,
		"nextAction": map[string]string{"method": nextMethod, "path": nextPath},
	}
	if serviceErr.RequestedRunID != "" {
		payload["requestedRunId"] = serviceErr.RequestedRunID
	}
	if serviceErr.AvailableResultID != "" {
		payload["availableResultId"] = serviceErr.AvailableResultID
	}

	switch serviceErr.Kind {
	case validator.ErrRunnerUnavailable:
		return http.StatusServiceUnavailable, payload
	case validator.ErrRunStillRunning:
		payload["nextAction"] = map[string]string{"method": http.MethodGet, "path": "/api/query/validation/status"}
		return http.StatusConflict, payload
	case validator.ErrRunTimeout, validator.ErrRunFailed, validator.ErrNoAnalysis, validator.ErrNoRetainedResult, validator.ErrRunNotRetained:
		return http.StatusConflict, payload
	default:
		return http.StatusConflict, payload
	}
}

func decodeJSONBodyMap(r *http.Request) map[string]any {
	if r.Body == nil {
		return map[string]any{}
	}
	defer r.Body.Close()
	var payload map[string]any
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		return map[string]any{}
	}
	return payload
}

func stringArg(m map[string]any, key string) string {
	v, _ := m[key].(string)
	return v
}

func intArg(m map[string]any, key string, def int) int {
	switch v := m[key].(type) {
	case float64:
		n := int(v)
		if n < 0 {
			return def
		}
		if n > maxLimit {
			return maxLimit
		}
		return n
	case int:
		if v < 0 {
			return def
		}
		if v > maxLimit {
			return maxLimit
		}
		return v
	default:
		return def
	}
}

func durationArgSeconds(m map[string]any, key string, def, min, max time.Duration) time.Duration {
	seconds := intArg(m, key, int(def/time.Second))
	duration := time.Duration(seconds) * time.Second
	if duration < min {
		return min
	}
	if duration > max {
		return max
	}
	return duration
}

func freshnessArg(m map[string]any, key string, def validator.FreshnessMode) validator.FreshnessMode {
	switch value := stringArg(m, key); value {
	case string(validator.FreshnessAuto):
		return validator.FreshnessAuto
	case string(validator.FreshnessFreshRequired):
		return validator.FreshnessFreshRequired
	case string(validator.FreshnessLatestOK):
		return validator.FreshnessLatestOK
	default:
		return def
	}
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Cache-Control", "no-store")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("[api] writeJSON: %v", err)
	}
}

const maxLimit = 10_000

func queryInt(r *http.Request, key string, def int) int {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < 0 {
		return def
	}
	if n > maxLimit {
		return maxLimit
	}
	return n
}

func queryOptionalInt(r *http.Request, key string) (int, bool) {
	v := r.URL.Query().Get(key)
	if v == "" {
		return 0, false
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < 0 {
		return 0, false
	}
	if n > maxLimit {
		return maxLimit, true
	}
	return n, true
}

func queryOptionalFloat(r *http.Request, key string) (float64, bool) {
	v := r.URL.Query().Get(key)
	if v == "" {
		return 0, false
	}
	n, err := strconv.ParseFloat(v, 64)
	if err != nil || n < 0 {
		return 0, false
	}
	return n, true
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func queryOptionalIntValues(values ...string) (int, bool) {
	for _, value := range values {
		if value == "" {
			continue
		}
		n, err := strconv.Atoi(value)
		if err != nil || n < 0 {
			return 0, false
		}
		if n > maxLimit {
			return maxLimit, true
		}
		return n, true
	}
	return 0, false
}

func queryOptionalFloatValues(values ...string) (float64, bool) {
	for _, value := range values {
		if value == "" {
			continue
		}
		n, err := strconv.ParseFloat(value, 64)
		if err != nil || n < 0 {
			return 0, false
		}
		return n, true
	}
	return 0, false
}

func queryOptionalTimeValues(values ...string) (time.Time, bool) {
	for _, value := range values {
		if value == "" {
			continue
		}
		ts, err := time.Parse(time.RFC3339Nano, value)
		if err != nil {
			return time.Time{}, false
		}
		return ts, true
	}
	return time.Time{}, false
}

func queryEqString(q map[string][]string, key string, legacyKeys ...string) string {
	values := []string{
		firstQueryValue(q, "filter["+key+"][eq]"),
		firstQueryValue(q, "filter["+key+"]"),
	}
	for _, legacyKey := range legacyKeys {
		values = append(values, firstQueryValue(q, legacyKey))
	}
	return firstNonEmpty(values...)
}

func queryNeqString(q map[string][]string, key string) string {
	return firstQueryValue(q, "filter["+key+"][neq]")
}

func filterValueRequest(r *http.Request) (field, prefix string, limit int) {
	q := r.URL.Query()
	return q.Get("field"), q.Get("prefix"), queryInt(r, "limit", 20)
}

func firstQueryValue(q map[string][]string, key string) string {
	if values, ok := q[key]; ok && len(values) > 0 {
		return values[0]
	}
	return ""
}
