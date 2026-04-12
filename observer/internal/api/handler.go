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
	mux.HandleFunc("GET /api/query/traces/{traceId}", queryTraceDetail(s))
	mux.HandleFunc("GET /api/query/metrics", queryMetrics(s))
	mux.HandleFunc("GET /api/query/logs", queryLogs(s))
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
		writeJSON(w, s.QueryTraces(queryInt(r, "limit", 100)))
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
		writeJSON(w, s.QueryMetrics(queryInt(r, "limit", 100)))
	}
}

func queryLogs(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, s.QueryLogs(queryInt(r, "limit", 100)))
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
