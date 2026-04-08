// Package api implements the REST API handler for telemetry queries.
package api

import (
	"encoding/json"
	"log"
	"net/http"
	"strconv"

	"github.com/signalfx/obstudio/observer-go/internal/store"
)

// Register adds the REST API routes to the given mux.
// It registers handlers for querying traces, metrics, logs, and stats.
func Register(mux *http.ServeMux, s *store.Store) {
	mux.HandleFunc("OPTIONS /api/", corsPreflightHandler())
	mux.HandleFunc("GET /api/query/traces", queryTraces(s))
	mux.HandleFunc("GET /api/query/traces/{traceId}", queryTraceDetail(s))
	mux.HandleFunc("GET /api/query/metrics", queryMetrics(s))
	mux.HandleFunc("GET /api/query/logs", queryLogs(s))
	mux.HandleFunc("GET /api/query/stats", queryStats(s))
	mux.HandleFunc("DELETE /api/data", clearData(s))
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

func clearData(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.Clear()
		writeJSON(w, map[string]string{"status": "cleared"})
	}
}

func corsPreflightHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		w.WriteHeader(http.StatusNoContent)
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
