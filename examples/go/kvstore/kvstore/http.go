package kvstore

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// API exposes Store operations over HTTP.
type API struct {
	store *Store
}

// NewAPI creates an API for the provided store.
func NewAPI(store *Store) *API {
	return &API{store: store}
}

// Handler returns an HTTP handler exposing key/value and search endpoints.
func (a *API) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.Handle("/kv/", telemetryHTTPHandler(http.HandlerFunc(a.handleKV), "/kv/{key}"))
	mux.Handle("/search", telemetryHTTPHandler(http.HandlerFunc(a.handleSearch), "/search"))
	return mux
}

func (a *API) handleKV(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	key := strings.TrimPrefix(r.URL.Path, "/kv/")
	if key == "" || strings.ContainsRune(key, '/') {
		http.Error(w, "invalid key", http.StatusBadRequest)
		return
	}

	switch r.Method {
	case http.MethodGet:
		value, err := a.store.GetContext(ctx, key)
		if err != nil {
			a.writeStoreError(w, err)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(value)
	case http.MethodPut:
		body := http.MaxBytesReader(w, r.Body, MaxValueSize+1)
		defer body.Close()
		value, err := io.ReadAll(body)
		if err != nil {
			http.Error(w, "failed to read body", http.StatusBadRequest)
			return
		}
		if err := a.store.SetContext(ctx, key, value); err != nil {
			a.writeStoreError(w, err)
			return
		}
		w.WriteHeader(http.StatusAccepted)
	case http.MethodDelete:
		err := a.store.DeleteContext(ctx, key)
		if err != nil {
			a.writeStoreError(w, err)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	default:
		w.Header().Set("Allow", "GET, PUT, DELETE")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (a *API) handleSearch(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", "GET")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	word := r.URL.Query().Get("word")
	if word == "" {
		http.Error(w, "word query parameter is required", http.StatusBadRequest)
		return
	}
	resp := struct {
		Keys []string `json:"keys"`
	}{
		Keys: a.store.SearchContext(r.Context(), word),
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

func (a *API) writeStoreError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrInvalidKey):
		http.Error(w, fmt.Sprintf("key must match %q and be at most %d bytes", `^[A-Za-z0-9_-]+$`, MaxKeySize), http.StatusBadRequest)
	case errors.Is(err, ErrValueTooLarge):
		http.Error(w, fmt.Sprintf("value must be at most %d bytes", MaxValueSize), http.StatusRequestEntityTooLarge)
	case errors.Is(err, ErrNotFound):
		http.Error(w, "not found", http.StatusNotFound)
	default:
		http.Error(w, "internal server error", http.StatusInternalServerError)
	}
}
