package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"

	"kvstore/internal/store"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/trace"
)

// Server provides HTTP handlers for key/value operations.
type Server struct {
	store *store.Store
	mux   *http.ServeMux
}

// New creates a new API server for the given store.
func New(s *store.Store) *Server {
	srv := &Server{
		store: s,
		mux:   http.NewServeMux(),
	}

	srv.mux.Handle("/set", instrumentRoute("/set", http.MethodPost, srv.handleSet))
	srv.mux.Handle("/get", instrumentRoute("/get", http.MethodPost, srv.handleGet))
	srv.mux.Handle("/delete", instrumentRoute("/delete", http.MethodPost, srv.handleDelete))
	srv.mux.Handle("/list", instrumentRoute("/list", http.MethodPost, srv.handleList))
	srv.mux.Handle("/health", instrumentRoute("/health", http.MethodGet, srv.handleHealth))

	return srv
}

// ServeHTTP routes requests to API handlers.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mux.ServeHTTP(w, r)
}

type setRequest struct {
	Key   string `json:"key"`
	Value string `json:"value"`
}

type keyRequest struct {
	Key string `json:"key"`
}

type listRequest struct {
	Prefix string `json:"prefix"`
}

type getResponse struct {
	Value string `json:"value"`
}

type listResponse struct {
	Keys []string `json:"keys"`
}

type messageResponse struct {
	Message string `json:"message"`
}

type errorResponse struct {
	Error string `json:"error"`
}

func (s *Server) handleSet(w http.ResponseWriter, r *http.Request) {
	if !allowMethod(w, r, http.MethodPost) {
		return
	}

	var req setRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}

	if err := s.store.Set(r.Context(), req.Key, req.Value); err != nil {
		writeStoreError(w, r, err)
		return
	}

	writeJSON(w, http.StatusOK, messageResponse{Message: "ok"})
}

func (s *Server) handleGet(w http.ResponseWriter, r *http.Request) {
	if !allowMethod(w, r, http.MethodPost) {
		return
	}

	var req keyRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}

	value, err := s.store.Get(r.Context(), req.Key)
	if err != nil {
		writeStoreError(w, r, err)
		return
	}

	writeJSON(w, http.StatusOK, getResponse{Value: value})
}

func (s *Server) handleDelete(w http.ResponseWriter, r *http.Request) {
	if !allowMethod(w, r, http.MethodPost) {
		return
	}

	var req keyRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}

	if err := s.store.Delete(r.Context(), req.Key); err != nil {
		writeStoreError(w, r, err)
		return
	}

	writeJSON(w, http.StatusOK, messageResponse{Message: "deleted"})
}

func (s *Server) handleList(w http.ResponseWriter, r *http.Request) {
	if !allowMethod(w, r, http.MethodPost) {
		return
	}

	var req listRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}

	keys, err := s.store.ListByPrefix(r.Context(), req.Prefix)
	if err != nil {
		writeStoreError(w, r, err)
		return
	}

	writeJSON(w, http.StatusOK, listResponse{Keys: keys})
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	if !allowMethod(w, r, http.MethodGet) {
		return
	}

	writeJSON(w, http.StatusOK, messageResponse{Message: "ok"})
}

func allowMethod(w http.ResponseWriter, r *http.Request, method string) bool {
	if r.Method != method {
		w.Header().Set("Allow", method)
		recordValidationFailure(r.Context(), "method", fmt.Errorf("method %s is required", method))
		writeError(w, http.StatusMethodNotAllowed, fmt.Errorf("method %s is required", method))
		return false
	}
	return true
}

func decodeJSON(r *http.Request, dst any) error {
	defer func() {
		_ = r.Body.Close()
	}()

	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		recordValidationFailure(r.Context(), "json", err)
		return fmt.Errorf("invalid JSON body: %w", err)
	}

	if err := dec.Decode(&struct{}{}); err != nil && !errors.Is(err, io.EOF) {
		recordValidationFailure(r.Context(), "json", err)
		return errors.New("request body must contain a single JSON object")
	}

	return nil
}

func writeStoreError(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, store.ErrNotFound):
		writeError(w, http.StatusNotFound, err)
	case errors.Is(err, store.ErrKeyTooLarge), errors.Is(err, store.ErrValueTooLarge):
		recordValidationFailure(r.Context(), "store", err)
		writeError(w, http.StatusBadRequest, err)
	default:
		span := trace.SpanFromContext(r.Context())
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		logFailure(r.Context(), "store", err)
		writeError(w, http.StatusInternalServerError, err)
	}
}

func writeError(w http.ResponseWriter, status int, err error) {
	writeJSON(w, status, errorResponse{Error: err.Error()})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		http.Error(w, http.StatusText(http.StatusInternalServerError), http.StatusInternalServerError)
	}
}

func instrumentRoute(route, method string, handler http.HandlerFunc) http.Handler {
	return otelhttp.NewHandler(
		http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if labeler, ok := otelhttp.LabelerFromContext(r.Context()); ok {
				labeler.Add(attribute.String("http.route", route))
			}
			handler(w, r)
		}),
		method+" "+route,
		otelhttp.WithSpanNameFormatter(func(_ string, _ *http.Request) string {
			return method + " " + route
		}),
	)
}

func recordValidationFailure(ctx context.Context, category string, err error) {
	meter := otel.GetMeterProvider().Meter("kvstore/internal/api")
	counter, counterErr := meter.Int64Counter(
		"kvstore.validation.failure.count",
		metric.WithDescription("Total API validation failures"),
		metric.WithUnit("{failures}"),
	)
	if counterErr == nil {
		counter.Add(ctx, 1, metric.WithAttributes(attribute.String("kvstore.validation.category", category)))
	}

	span := trace.SpanFromContext(ctx)
	span.RecordError(err)
	span.SetStatus(codes.Error, err.Error())
	span.SetAttributes(attribute.String("kvstore.validation.category", category))
	logFailure(ctx, category, err)
}

func logFailure(ctx context.Context, category string, err error) {
	spanCtx := trace.SpanContextFromContext(ctx)
	log.Printf("category=%s error=%q trace_id=%s span_id=%s", category, err.Error(), spanCtx.TraceID(), spanCtx.SpanID())
}
