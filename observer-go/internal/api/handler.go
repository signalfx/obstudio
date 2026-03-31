package api

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/signalfx/obstudio/observer-go/internal/store"
)

func Register(mux *http.ServeMux, s *store.Store) {
	mux.HandleFunc("GET /api/query/traces", queryTraces(s))
	mux.HandleFunc("GET /api/query/traces/{traceId}", queryTraceDetail(s))
	mux.HandleFunc("GET /api/query/metrics", queryMetrics(s))
	mux.HandleFunc("GET /api/query/logs", queryLogs(s))
	mux.HandleFunc("GET /api/query/stats", queryStats(s))
}

func queryTraces(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		f := store.TraceFilter{
			ServiceName:      r.URL.Query().Get("serviceName"),
			SpanName:         r.URL.Query().Get("spanName"),
			Status:           r.URL.Query().Get("status"),
			TraceIDPrefix:    r.URL.Query().Get("traceIdPrefix"),
			Limit:            queryInt(r, "limit", 20),
			SpanPreviewCount: queryInt(r, "spanPreviewCount", 5),
		}
		writeJSON(w, s.QueryTraces(f))
	}
}

func queryTraceDetail(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		traceID := r.PathValue("traceId")
		detail := s.GetTrace(traceID, queryInt(r, "eventLimit", 12))
		if detail == nil {
			http.Error(w, "trace not found", http.StatusNotFound)
			return
		}
		writeJSON(w, detail)
	}
}

func queryMetrics(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		f := store.MetricFilter{
			MetricName:        r.URL.Query().Get("metricName"),
			ServiceName:       r.URL.Query().Get("serviceName"),
			ScopeName:         r.URL.Query().Get("scopeName"),
			Type:              r.URL.Query().Get("type"),
			ResourceAttribute: r.URL.Query().Get("resourceAttribute"),
			Limit:             queryInt(r, "limit", 20),
			DataPointLimit:    queryInt(r, "dataPointLimit", 3),
		}
		writeJSON(w, s.QueryMetrics(f))
	}
}

func queryLogs(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		f := store.LogFilter{
			ServiceName:  r.URL.Query().Get("serviceName"),
			SeverityText: r.URL.Query().Get("severityText"),
			Body:         r.URL.Query().Get("body"),
			TraceID:      r.URL.Query().Get("traceId"),
			Limit:        queryInt(r, "limit", 50),
		}
		writeJSON(w, s.QueryLogs(f))
	}
}

func queryStats(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, s.Stats())
	}
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(v)
}

func queryInt(r *http.Request, key string, def int) int {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}
