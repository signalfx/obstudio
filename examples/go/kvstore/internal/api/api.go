package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"

	"kvstore/internal/store"
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

	srv.mux.HandleFunc("/set", srv.handleSet)
	srv.mux.HandleFunc("/get", srv.handleGet)
	srv.mux.HandleFunc("/delete", srv.handleDelete)
	srv.mux.HandleFunc("/list", srv.handleList)
	srv.mux.HandleFunc("/health", srv.handleHealth)

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

	if err := s.store.Set(req.Key, req.Value); err != nil {
		writeStoreError(w, err)
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

	value, err := s.store.Get(req.Key)
	if err != nil {
		writeStoreError(w, err)
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

	if err := s.store.Delete(req.Key); err != nil {
		writeStoreError(w, err)
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

	keys, err := s.store.ListByPrefix(req.Prefix)
	if err != nil {
		writeStoreError(w, err)
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
		return fmt.Errorf("invalid JSON body: %w", err)
	}

	if err := dec.Decode(&struct{}{}); err != nil && !errors.Is(err, io.EOF) {
		return errors.New("request body must contain a single JSON object")
	}

	return nil
}

func writeStoreError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, store.ErrNotFound):
		writeError(w, http.StatusNotFound, err)
	case errors.Is(err, store.ErrKeyTooLarge), errors.Is(err, store.ErrValueTooLarge):
		writeError(w, http.StatusBadRequest, err)
	default:
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
