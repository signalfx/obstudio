package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"

	"github.com/signalfx/obstudio/observer/internal/configstatus"
	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

// maxConfigBodyBytes bounds a POST /api/config body; a full v1 body is about
// 30 bytes.
const maxConfigBodyBytes = 4096

// UserConfig is the settings source and writer the config routes use.
type UserConfig interface {
	Get() userconfig.Snapshot
	Update(c userconfig.Changes) error
}

type managerUserConfig struct{ m *userconfig.Manager }

// NewUserConfig adapts the observer's config Manager for the config routes.
func NewUserConfig(m *userconfig.Manager) UserConfig { return managerUserConfig{m} }

func (u managerUserConfig) Get() userconfig.Snapshot { return u.m.Get() }

func (u managerUserConfig) Update(c userconfig.Changes) error { return userconfig.Update(u.m, c) }

func registerUserConfigRoutes(mux *http.ServeMux, uc UserConfig) {
	mux.HandleFunc("GET /api/config", func(w http.ResponseWriter, _ *http.Request) {
		writeConfigBytes(w, http.StatusOK, userconfig.EncodeSettings(uc.Get().Settings))
	})
	mux.HandleFunc("POST /api/config", localMutation(postUserConfig(uc)))
	mux.HandleFunc("GET /api/config/definitions", func(w http.ResponseWriter, _ *http.Request) {
		writeConfigBytes(w, http.StatusOK, userconfig.DefinitionsDocument())
	})
}

func registerConfigStatusRoute(mux *http.ServeMux, b *configstatus.Builder) {
	mux.HandleFunc("GET /api/config/status", func(w http.ResponseWriter, _ *http.Request) {
		writeSameOriginJSON(w, b.Build())
	})
}

// writeConfigBytes writes an already-encoded JSON body as is. The settings
// show whether the user opted out, so no CORS header is set.
func writeConfigBytes(w http.ResponseWriter, status int, body []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	if _, err := w.Write(body); err != nil {
		log.Printf("[api] config response: %v", err)
	}
}

func writeConfigError(w http.ResponseWriter, status int, message string) {
	body, _ := json.Marshal(map[string]string{"error": message})
	writeConfigBytes(w, status, body)
}

func postUserConfig(uc UserConfig) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(io.LimitReader(r.Body, maxConfigBodyBytes+1))
		if err != nil {
			writeConfigError(w, http.StatusBadRequest, "request body could not be read")
			return
		}
		if len(body) > maxConfigBodyBytes {
			writeConfigError(w, http.StatusBadRequest, fmt.Sprintf("request body is larger than %d bytes", maxConfigBodyBytes))
			return
		}
		changes, err := userconfig.DecodeChanges(body)
		if err != nil {
			writeConfigError(w, http.StatusBadRequest, err.Error())
			return
		}
		if err := uc.Update(changes); err != nil {
			switch {
			case errors.Is(err, userconfig.ErrSyntax), errors.Is(err, userconfig.ErrNotMapping):
				writeConfigError(w, http.StatusConflict, fmt.Sprintf("config.yaml could not be updated: %v. Fix the file, or delete it and try again.", err))
			case errors.Is(err, userconfig.ErrClosed):
				writeConfigError(w, http.StatusServiceUnavailable, "Splunk Observability Studio is shutting down.")
			case errors.Is(err, userconfig.ErrUnknownKey), errors.Is(err, userconfig.ErrInvalidValue):
				writeConfigError(w, http.StatusBadRequest, err.Error())
			default:
				writeConfigError(w, http.StatusInternalServerError, fmt.Sprintf("config.yaml could not be updated: %v", err))
			}
			return
		}
		writeConfigBytes(w, http.StatusOK, userconfig.EncodeSettings(uc.Get().Settings))
	}
}
