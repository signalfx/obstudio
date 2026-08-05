package api

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

const (
	maxSplunkExportRequestBytes = 8 * 1024
	maxSplunkAccessTokenLength  = 4096
	splunkBridgeTokenTTL        = 10 * time.Minute
	splunkExportEnvFileSource   = "env-file"
)

var splunkRealmPattern = regexp.MustCompile(`^[a-z]{2,12}[0-9]+$`)
var splunkBridgeTokenPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{24,128}$`)

// SplunkExportConfigurationRefresher reloads an optional local configuration
// source without changing process-wide environment variables. It reports whether
// that local source was applied.
type SplunkExportConfigurationRefresher func() (bool, error)

type splunkExportService struct {
	metrics      *otlp.SplunkMetricsExportController
	traces       *otlp.SplunkTracesExportController
	refresh      SplunkExportConfigurationRefresher
	controlToken string
	bridgeTokens map[string]time.Time
	source       string
	mu           sync.Mutex
}

type splunkExportSignalStatus struct {
	Configured      bool        `json:"configured"`
	Enabled         bool        `json:"enabled"`
	ExportedBatches uint64      `json:"exportedBatches"`
	ExportedItems   uint64      `json:"exportedItems"`
	FailedBatches   uint64      `json:"failedBatches"`
	LastExport      interface{} `json:"lastExport,omitempty"`
}

type splunkExportStatusResponse struct {
	Connected bool                     `json:"connected"`
	Enabled   bool                     `json:"enabled"`
	Realm     string                   `json:"realm,omitempty"`
	Metrics   splunkExportSignalStatus `json:"metrics"`
	Traces    splunkExportSignalStatus `json:"traces"`
}

type configureSplunkExportRequest struct {
	Realm       string `json:"realm"`
	AccessToken string `json:"accessToken"`
}

type setSplunkExportEnabledRequest struct {
	Enabled *bool `json:"enabled"`
}

type splunkExportBridgeTokenRequest struct {
	BridgeToken string `json:"bridgeToken"`
}

func newSplunkExportService(
	metrics *otlp.SplunkMetricsExportController,
	traces *otlp.SplunkTracesExportController,
	refresh SplunkExportConfigurationRefresher,
) *splunkExportService {
	return &splunkExportService{
		metrics:      metrics,
		traces:       traces,
		refresh:      refresh,
		controlToken: strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")),
		bridgeTokens: map[string]time.Time{},
	}
}

func (s *splunkExportService) register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/splunk/export", s.status)
	mux.HandleFunc("POST /api/splunk/export", s.authorize(s.configure))
	mux.HandleFunc("POST /api/splunk/export/bridge", s.authorize(s.registerBridgeToken))
	mux.HandleFunc("POST /api/splunk/export/bridge/verify", s.verifyBridgeToken)
	mux.HandleFunc("POST /api/splunk/export/enabled", s.authorize(s.setEnabled))
	mux.HandleFunc("POST /api/splunk/export/forget", s.authorize(s.forget))
	if s.refresh != nil {
		mux.HandleFunc("POST /api/splunk/export/refresh", s.authorize(s.refreshConfiguration))
	}
}

func (s *splunkExportService) status(w http.ResponseWriter, _ *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()

	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, s.snapshot())
}

func (s *splunkExportService) configure(w http.ResponseWriter, r *http.Request) {
	var request configureSplunkExportRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}

	realm, err := validateSplunkRealm(request.Realm)
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}
	accessToken, err := validateSplunkAccessToken(request.AccessToken)
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if err := s.apply(
		otlp.SplunkMetricsExporterConfig{Realm: realm, AccessToken: accessToken},
		otlp.SplunkTracesExporterConfig{Realm: realm, AccessToken: accessToken},
	); err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not configure Splunk Observability Cloud export")
		return
	}
	s.source = ""
	writeJSON(w, s.snapshot())
}

func (s *splunkExportService) setEnabled(w http.ResponseWriter, r *http.Request) {
	var request setSplunkExportEnabledRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}
	if request.Enabled == nil {
		writeSplunkExportError(w, http.StatusBadRequest, "enabled must be a boolean")
		return
	}
	enabled := *request.Enabled

	s.mu.Lock()
	defer s.mu.Unlock()

	metricsConfig := s.metrics.Config()
	tracesConfig := s.traces.Config()
	if enabled && !sameSplunkCloudRealm(
		metricsConfig.Realm,
		metricsConfig.AccessToken,
		metricsConfig.Endpoint != "",
		tracesConfig.Realm,
		tracesConfig.AccessToken,
		tracesConfig.Endpoint != "",
	) {
		writeSplunkExportError(w, http.StatusConflict, "connect a Splunk Observability Cloud destination before enabling export")
		return
	}
	metricsConfig.Enabled = enabled
	tracesConfig.Enabled = enabled
	if err := s.apply(metricsConfig, tracesConfig); err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not update Splunk Observability Cloud export")
		return
	}
	writeJSON(w, s.snapshot())
}

func (s *splunkExportService) forget(w http.ResponseWriter, _ *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.source == splunkExportEnvFileSource {
		writeSplunkExportError(w, http.StatusConflict, "remove SPLUNK_ACCESS_TOKEN from the env file before forgetting this connection")
		return
	}
	if err := s.apply(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not forget Splunk Observability Cloud destination")
		return
	}
	s.source = ""
	writeJSON(w, s.snapshot())
}

func (s *splunkExportService) registerBridgeToken(w http.ResponseWriter, r *http.Request) {
	var request splunkExportBridgeTokenRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}
	token := strings.TrimSpace(request.BridgeToken)
	if !splunkBridgeTokenPattern.MatchString(token) {
		writeSplunkExportError(w, http.StatusBadRequest, "bridge token is not valid")
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now()
	s.pruneBridgeTokens(now)
	s.bridgeTokens[token] = now.Add(splunkBridgeTokenTTL)
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, map[string]bool{"ok": true})
}

func (s *splunkExportService) verifyBridgeToken(w http.ResponseWriter, r *http.Request) {
	var request splunkExportBridgeTokenRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}
	token := strings.TrimSpace(request.BridgeToken)
	if !splunkBridgeTokenPattern.MatchString(token) {
		writeSplunkExportError(w, http.StatusUnauthorized, "bridge token is not registered")
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now()
	s.pruneBridgeTokens(now)
	if expiresAt, ok := s.bridgeTokens[token]; !ok || !expiresAt.After(now) {
		writeSplunkExportError(w, http.StatusUnauthorized, "bridge token is not registered")
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, map[string]bool{"ok": true})
}

func (s *splunkExportService) pruneBridgeTokens(now time.Time) {
	for token, expiresAt := range s.bridgeTokens {
		if !expiresAt.After(now) {
			delete(s.bridgeTokens, token)
		}
	}
}

func (s *splunkExportService) refreshConfiguration(w http.ResponseWriter, _ *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()

	applied, err := s.refresh()
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}
	if applied {
		s.source = splunkExportEnvFileSource
	} else {
		s.source = ""
	}
	writeJSON(w, s.snapshot())
}

func (s *splunkExportService) authorize(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.controlToken == "" {
			writeSplunkExportError(w, http.StatusServiceUnavailable, "Observer control is not configured")
			return
		}
		const bearerPrefix = "Bearer "
		authorization := r.Header.Get("Authorization")
		if !strings.HasPrefix(authorization, bearerPrefix) {
			writeSplunkExportError(w, http.StatusUnauthorized, "missing Observer control token")
			return
		}
		provided := strings.TrimSpace(strings.TrimPrefix(authorization, bearerPrefix))
		if len(provided) != len(s.controlToken) ||
			subtle.ConstantTimeCompare([]byte(provided), []byte(s.controlToken)) != 1 {
			writeSplunkExportError(w, http.StatusUnauthorized, "invalid Observer control token")
			return
		}
		next(w, r)
	}
}

func (s *splunkExportService) apply(
	metricsConfig otlp.SplunkMetricsExporterConfig,
	tracesConfig otlp.SplunkTracesExporterConfig,
) error {
	previousMetrics := s.metrics.Config()
	if err := s.metrics.Configure(metricsConfig); err != nil {
		return err
	}
	if err := s.traces.Configure(tracesConfig); err != nil {
		if rollbackErr := s.metrics.Configure(previousMetrics); rollbackErr != nil {
			return fmt.Errorf("configure traces: %w; rollback metrics: %v", err, rollbackErr)
		}
		return err
	}
	return nil
}

func (s *splunkExportService) snapshot() splunkExportStatusResponse {
	metrics := s.metrics.Status()
	traces := s.traces.Status()
	metricsConfig := s.metrics.Config()
	tracesConfig := s.traces.Config()
	realm := ""
	connected := sameSplunkCloudRealm(
		metrics.Realm,
		metricsConfig.AccessToken,
		metricsConfig.Endpoint != "",
		traces.Realm,
		tracesConfig.AccessToken,
		tracesConfig.Endpoint != "",
	)
	if connected {
		realm = metrics.Realm
	}

	return splunkExportStatusResponse{
		Connected: connected,
		Enabled:   connected && metrics.Enabled && traces.Enabled,
		Realm:     realm,
		Metrics: splunkExportSignalStatus{
			Configured:      splunkSignalConfigured(metricsConfig.Realm, metrics.AccessTokenConfigured, metricsConfig.Endpoint),
			Enabled:         metrics.Enabled,
			ExportedBatches: metrics.ExportedBatches,
			ExportedItems:   metrics.ExportedDataPoints,
			FailedBatches:   metrics.FailedBatches,
			LastExport:      metrics.LastExport,
		},
		Traces: splunkExportSignalStatus{
			Configured:      splunkSignalConfigured(tracesConfig.Realm, traces.AccessTokenConfigured, tracesConfig.Endpoint),
			Enabled:         traces.Enabled,
			ExportedBatches: traces.ExportedBatches,
			ExportedItems:   traces.ExportedSpans,
			FailedBatches:   traces.FailedBatches,
			LastExport:      traces.LastExport,
		},
	}
}

func splunkSignalConfigured(realm string, accessTokenConfigured bool, endpoint string) bool {
	return strings.TrimSpace(realm) != "" ||
		accessTokenConfigured ||
		strings.TrimSpace(endpoint) != ""
}

func sameSplunkCloudRealm(
	metricsRealm string,
	metricsAccessToken string,
	metricsEndpointOverridden bool,
	tracesRealm string,
	tracesAccessToken string,
	tracesEndpointOverridden bool,
) bool {
	metricsAccessToken = strings.TrimSpace(metricsAccessToken)
	tracesAccessToken = strings.TrimSpace(tracesAccessToken)
	return metricsRealm != "" &&
		tracesRealm != "" &&
		metricsRealm == tracesRealm &&
		metricsAccessToken != "" &&
		metricsAccessToken == tracesAccessToken &&
		!metricsEndpointOverridden &&
		!tracesEndpointOverridden
}

func validateSplunkRealm(value string) (string, error) {
	realm := strings.ToLower(strings.TrimSpace(value))
	if !splunkRealmPattern.MatchString(realm) {
		return "", errors.New("region is not valid")
	}
	return realm, nil
}

func validateSplunkAccessToken(value string) (string, error) {
	token := strings.TrimSpace(value)
	if len(token) < 16 || len(token) > maxSplunkAccessTokenLength {
		return "", errors.New("access token length is not valid")
	}
	for _, r := range token {
		if unicode.IsSpace(r) || unicode.IsControl(r) {
			return "", errors.New("access token contains whitespace or control characters")
		}
	}
	lower := strings.ToLower(token)
	if strings.Contains(token, "***") || strings.Contains(lower, "redacted") {
		return "", errors.New("paste the token secret, not a masked value")
	}
	return token, nil
}

func decodeStrictJSON(w http.ResponseWriter, r *http.Request, destination any) error {
	defer r.Body.Close()
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxSplunkExportRequestBytes))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return fmt.Errorf("invalid JSON request: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("request must contain one JSON object")
		}
		return fmt.Errorf("invalid JSON request: %w", err)
	}
	return nil
}

func writeSplunkExportError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": message})
}
