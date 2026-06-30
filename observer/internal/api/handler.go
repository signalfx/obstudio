// Package api implements the REST API handler for telemetry queries.
package api

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
)

type ServerInfo struct {
	APIVersion string                  `json:"apiVersion"`
	Kind       string                  `json:"kind"`
	Mode       string                  `json:"mode"`
	Owner      string                  `json:"owner"`
	StartedAt  time.Time               `json:"startedAt"`
	Version    string                  `json:"version"`
	Exporters  map[string]ExporterInfo `json:"exporters,omitempty"`
}

// ExporterInfo describes optional non-secret outbound exporter state.
type ExporterInfo struct {
	Enabled  bool   `json:"enabled"`
	Endpoint string `json:"endpoint,omitempty"`
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
	var splunkMetricsController *otlp.SplunkMetricsExportController
	var splunkTracesController *otlp.SplunkTracesExportController
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
		case *otlp.SplunkMetricsExportController:
			if value != nil {
				splunkMetricsController = value
			}
		case *otlp.SplunkTracesExportController:
			if value != nil {
				splunkTracesController = value
			}
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
	mux.HandleFunc("GET /api/query/stats/services", queryServiceStats(s))
	mux.HandleFunc("GET /api/query/validation/summary", queryValidationStatus(validationService))
	mux.HandleFunc("GET /api/query/validation/status", queryValidationStatus(validationService))
	mux.HandleFunc("GET /api/query/validation/latest", queryValidationLatest(validationService))
	mux.HandleFunc("POST /api/validation/run", runValidation(validationService))
	mux.HandleFunc("POST /api/validation/refresh", refreshValidation(validationService))
	mux.HandleFunc("POST /api/validation/analyze", analyzeValidation(validationService))
	mux.HandleFunc("GET /api/query/validation/findings", queryValidationFindings(validationService))
	mux.HandleFunc("DELETE /api/data", clearData(s, validationStore))
	if splunkMetricsController != nil || splunkTracesController != nil {
		revocationState := &splunkOAuthRevocationState{}
		mux.HandleFunc("GET /api/splunk/export", querySplunkExportStatus(splunkMetricsController, splunkTracesController))
		mux.HandleFunc("POST /api/splunk/export", configureSplunkExport(splunkMetricsController, splunkTracesController, revocationState))
		mux.HandleFunc("POST /api/splunk/export/enabled", setSplunkExportEnabled(splunkMetricsController, splunkTracesController, revocationState))
		mux.HandleFunc("POST /api/splunk/export/forget", forgetSplunkExport(splunkMetricsController, splunkTracesController, revocationState))
	}
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

func queryServiceStats(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, s.ServiceStatsAll())
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

type splunkExportConfigureRequest struct {
	AccessToken     string `json:"accessToken"`
	Enabled         bool   `json:"enabled"`
	Endpoint        string `json:"endpoint"`
	Issuer          string `json:"issuer"`
	MetricsEndpoint string `json:"metricsEndpoint"`
	Realm           string `json:"realm"`
	TimeoutSeconds  int    `json:"timeoutSeconds"`
	TracesEndpoint  string `json:"tracesEndpoint"`
}

type splunkOAuthRevocationConfig struct {
	AccessToken           string
	ConnectionFingerprint string
	Issuer                string
}

type splunkOAuthRevocationState struct {
	mu     sync.Mutex
	config splunkOAuthRevocationConfig
}

type splunkExportConfigureResponse struct {
	Metrics *splunkExportStatusResponse `json:"metrics,omitempty"`
	Traces  *splunkExportStatusResponse `json:"traces,omitempty"`
}

type splunkExportStatusResponse struct {
	AccessTokenConfigured bool                         `json:"accessTokenConfigured"`
	Configured            bool                         `json:"configured"`
	Enabled               bool                         `json:"enabled"`
	Endpoints             []string                     `json:"endpoints,omitempty"`
	FailedBatches         int64                        `json:"failedBatches,omitempty"`
	LastExport            *splunkExportAttemptResponse `json:"lastExport,omitempty"`
	MetricBatches         int64                        `json:"metricBatches,omitempty"`
	MetricPoints          int64                        `json:"metricPoints,omitempty"`
	Realm                 string                       `json:"realm,omitempty"`
	Timeout               string                       `json:"timeout,omitempty"`
	TraceBatches          int64                        `json:"traceBatches,omitempty"`
	TraceSpans            int64                        `json:"traceSpans,omitempty"`
}

type splunkExportAttemptResponse struct {
	Error   string    `json:"error,omitempty"`
	Success bool      `json:"success"`
	Time    time.Time `json:"time"`
}

type splunkExportEnabledRequest struct {
	Enabled bool `json:"enabled"`
}

type splunkExportForgetMarker struct {
	ConnectionFingerprint string    `json:"connectionFingerprint"`
	ForgottenAt           time.Time `json:"forgottenAt"`
}

const (
	splunkExportForgetMarkerDirName  = ".obstudio"
	splunkExportForgetMarkerFileName = "splunk-export-forgotten.json"
)

func querySplunkExportStatus(
	metricsController *otlp.SplunkMetricsExportController,
	tracesController *otlp.SplunkTracesExportController,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, splunkExportStatusSnapshot(metricsController, tracesController))
	}
}

func configureSplunkExport(
	metricsController *otlp.SplunkMetricsExportController,
	tracesController *otlp.SplunkTracesExportController,
	revocationState *splunkOAuthRevocationState,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !authorizeObserverControlRequest(r) {
			http.Error(w, "missing or invalid observer control token", http.StatusUnauthorized)
			return
		}

		var req splunkExportConfigureRequest
		if r.Body == nil {
			http.Error(w, "request body is required", http.StatusBadRequest)
			return
		}
		defer r.Body.Close()
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid JSON request body", http.StatusBadRequest)
			return
		}

		if req.Enabled && strings.TrimSpace(req.AccessToken) == "" {
			http.Error(w, "accessToken is required when export is enabled", http.StatusBadRequest)
			return
		}
		if req.TimeoutSeconds < 0 {
			http.Error(w, "timeoutSeconds must be non-negative", http.StatusBadRequest)
			return
		}
		revocationConfig, err := splunkOAuthRevocationConfigFromRequest(req)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		metricsEndpoint, tracesEndpoint, err := splunkExportEndpoints(req)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		revocationState.mu.Lock()
		defer revocationState.mu.Unlock()
		timeout := time.Duration(req.TimeoutSeconds) * time.Second
		metricsConfig := otlp.SplunkMetricsExporterConfig{
			Enabled:     req.Enabled,
			Realm:       strings.TrimSpace(req.Realm),
			Endpoint:    metricsEndpoint,
			AccessToken: strings.TrimSpace(req.AccessToken),
			Timeout:     timeout,
		}
		tracesConfig := otlp.SplunkTracesExporterConfig{
			Enabled:     req.Enabled,
			Realm:       strings.TrimSpace(req.Realm),
			Endpoint:    tracesEndpoint,
			AccessToken: strings.TrimSpace(req.AccessToken),
			Timeout:     timeout,
		}
		if err := applySplunkExportConfiguration(
			metricsController,
			metricsConfig,
			tracesController,
			tracesConfig,
		); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		revocationState.config = revocationConfig
		writeJSON(w, splunkExportStatusSnapshot(metricsController, tracesController))
	}
}

func setSplunkExportEnabled(
	metricsController *otlp.SplunkMetricsExportController,
	tracesController *otlp.SplunkTracesExportController,
	revocationState *splunkOAuthRevocationState,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !authorizeObserverControlRequest(r) && !authorizeObserverBrowserAction(r, "export") {
			http.Error(w, "missing or invalid observer control token", http.StatusUnauthorized)
			return
		}

		var req splunkExportEnabledRequest
		if r.Body == nil {
			http.Error(w, "request body is required", http.StatusBadRequest)
			return
		}
		defer r.Body.Close()
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid JSON request body", http.StatusBadRequest)
			return
		}
		revocationState.mu.Lock()
		defer revocationState.mu.Unlock()

		metricsConfig := otlp.SplunkMetricsExporterConfig{}
		if metricsController != nil {
			metricsConfig = metricsController.Config()
			if req.Enabled && strings.TrimSpace(metricsConfig.AccessToken) == "" {
				http.Error(w, "Splunk metrics access token is not configured", http.StatusBadRequest)
				return
			}
			metricsConfig.Enabled = req.Enabled
		}
		tracesConfig := otlp.SplunkTracesExporterConfig{}
		if tracesController != nil {
			tracesConfig = tracesController.Config()
			if req.Enabled && strings.TrimSpace(tracesConfig.AccessToken) == "" {
				http.Error(w, "Splunk traces access token is not configured", http.StatusBadRequest)
				return
			}
			tracesConfig.Enabled = req.Enabled
		}
		if err := applySplunkExportConfiguration(
			metricsController,
			metricsConfig,
			tracesController,
			tracesConfig,
		); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		writeJSON(w, splunkExportStatusSnapshot(metricsController, tracesController))
	}
}

func applySplunkExportConfiguration(
	metricsController *otlp.SplunkMetricsExportController,
	metricsConfig otlp.SplunkMetricsExporterConfig,
	tracesController *otlp.SplunkTracesExportController,
	tracesConfig otlp.SplunkTracesExporterConfig,
) error {
	oldMetricsConfig := otlp.SplunkMetricsExporterConfig{}
	if metricsController != nil {
		oldMetricsConfig = metricsController.Config()
		if err := metricsController.Configure(metricsConfig); err != nil {
			return fmt.Errorf("configure Splunk metrics export: %w", err)
		}
	}
	if tracesController == nil {
		return nil
	}
	if err := tracesController.Configure(tracesConfig); err != nil {
		if metricsController != nil {
			if rollbackErr := metricsController.Configure(oldMetricsConfig); rollbackErr != nil {
				return fmt.Errorf(
					"configure Splunk traces export: %v; restore metrics export: %w",
					err,
					rollbackErr,
				)
			}
		}
		return fmt.Errorf("configure Splunk traces export: %w", err)
	}
	return nil
}

func forgetSplunkExport(
	metricsController *otlp.SplunkMetricsExportController,
	tracesController *otlp.SplunkTracesExportController,
	revocationState *splunkOAuthRevocationState,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !authorizeObserverControlRequest(r) && !authorizeObserverBrowserAction(r, "forget") {
			http.Error(w, "missing or invalid observer control token", http.StatusUnauthorized)
			return
		}

		revocationState.mu.Lock()
		defer revocationState.mu.Unlock()
		revocationConfig := revocationState.config
		connectionFingerprint := revocationConfig.ConnectionFingerprint
		if revocationConfig.AccessToken != "" {
			if err := revokeSplunkOAuthToken(r.Context(), revocationConfig); err != nil {
				http.Error(w, "revoke Splunk access token: "+err.Error(), http.StatusBadGateway)
				return
			}
		}
		if metricsController != nil {
			if err := metricsController.Configure(otlp.SplunkMetricsExporterConfig{}); err != nil {
				http.Error(w, "clear Splunk metrics export: "+err.Error(), http.StatusBadRequest)
				return
			}
		}
		if tracesController != nil {
			if err := tracesController.Configure(otlp.SplunkTracesExporterConfig{}); err != nil {
				http.Error(w, "clear Splunk traces export: "+err.Error(), http.StatusBadRequest)
				return
			}
		}
		if err := writeSplunkExportForgetMarker(time.Now().UTC(), connectionFingerprint); err != nil {
			http.Error(w, "record Splunk export forget marker: "+err.Error(), http.StatusInternalServerError)
			return
		}
		revocationState.config = splunkOAuthRevocationConfig{}
		writeJSON(w, splunkExportStatusSnapshot(metricsController, tracesController))
	}
}

var trustedSplunkOAuthIssuerHost = regexp.MustCompile(`^app\.([a-z]{2,12}[0-9]+)\.(?:observability\.splunkcloud\.com|signalfx\.com)$`)
var trustedSplunkIngestHost = regexp.MustCompile(`^ingest\.([a-z]{2,12}[0-9]+)\.(?:observability\.splunkcloud\.com|signalfx\.com)$`)

var trustedInternalSplunkOAuthIssuerHosts = map[string]string{
	"mon.observability.splunkcloud.com": "mon0",
	"mon.signalfx.com":                  "mon0",
}

var trustedInternalSplunkIngestHosts = map[string]string{
	"mon-ingest.signalfx.com": "mon0",
}

func splunkOAuthRevocationConfigFromRequest(req splunkExportConfigureRequest) (splunkOAuthRevocationConfig, error) {
	config := splunkOAuthRevocationConfig{
		AccessToken: strings.TrimSpace(req.AccessToken),
		Issuer:      strings.TrimSpace(req.Issuer),
	}
	if config.AccessToken == "" {
		return config, nil
	}
	if config.Issuer == "" {
		return splunkOAuthRevocationConfig{}, errors.New("issuer is required with accessToken")
	}

	issuer, issuerRealm, err := normalizeSplunkOAuthIssuer(config.Issuer)
	if err != nil {
		return splunkOAuthRevocationConfig{}, err
	}
	if issuerRealm != "" && !strings.EqualFold(strings.TrimSpace(req.Realm), issuerRealm) {
		return splunkOAuthRevocationConfig{}, errors.New("OAuth issuer realm does not match export realm")
	}
	config.Issuer = issuer
	config.ConnectionFingerprint = splunkOAuthConnectionFingerprint(config.Issuer, config.AccessToken)
	return config, nil
}

func splunkOAuthConnectionFingerprint(issuer string, accessToken string) string {
	digest := sha256.Sum256([]byte(issuer + "\x00" + accessToken))
	return base64.RawURLEncoding.EncodeToString(digest[:])
}

func normalizeSplunkOAuthIssuer(rawIssuer string) (string, string, error) {
	parsed, err := url.Parse(strings.TrimSpace(rawIssuer))
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return "", "", errors.New("issuer is not a valid URL origin")
	}
	if parsed.User != nil || (parsed.Path != "" && parsed.Path != "/") || parsed.RawQuery != "" || parsed.Fragment != "" {
		return "", "", errors.New("issuer must be an origin without credentials, path, query, or fragment")
	}
	if parsed.Scheme == "http" {
		if !isLoopbackHostname(parsed.Hostname()) {
			return "", "", errors.New("HTTP issuer must use a loopback host")
		}
		return canonicalURLOrigin(parsed), "", nil
	}
	if parsed.Scheme != "https" {
		return "", "", errors.New("issuer must use https or loopback http")
	}
	hostname := strings.ToLower(parsed.Hostname())
	if realm := trustedInternalSplunkOAuthIssuerHosts[hostname]; realm != "" {
		return canonicalURLOrigin(parsed), realm, nil
	}
	match := trustedSplunkOAuthIssuerHost.FindStringSubmatch(hostname)
	if len(match) != 2 {
		return "", "", errors.New("issuer must use a registered Splunk Observability Cloud host")
	}
	return canonicalURLOrigin(parsed), match[1], nil
}

func canonicalURLOrigin(parsed *url.URL) string {
	scheme := strings.ToLower(parsed.Scheme)
	hostname := strings.ToLower(parsed.Hostname())
	port := parsed.Port()
	if (scheme == "http" && port == "80") || (scheme == "https" && port == "443") {
		port = ""
	}
	host := hostname
	if port != "" {
		host = net.JoinHostPort(hostname, port)
	} else if strings.Contains(hostname, ":") {
		host = "[" + hostname + "]"
	}
	return scheme + "://" + host
}

func revokeSplunkOAuthToken(ctx context.Context, config splunkOAuthRevocationConfig) error {
	form := url.Values{
		"token":           {config.AccessToken},
		"token_type_hint": {"access_token"},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, config.Issuer+"/v2/oauth/revoke", strings.NewReader(form.Encode()))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	client := &http.Client{
		Timeout: 10 * time.Second,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return errors.New("authorization server returned HTTP " + strconv.Itoa(resp.StatusCode))
	}
	return nil
}

func writeSplunkExportForgetMarker(now time.Time, connectionFingerprint string) error {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	markerDir := filepath.Join(homeDir, splunkExportForgetMarkerDirName)
	if err := os.MkdirAll(markerDir, 0o700); err != nil {
		return err
	}
	body, err := json.Marshal(splunkExportForgetMarker{
		ConnectionFingerprint: connectionFingerprint,
		ForgottenAt:           now.UTC(),
	})
	if err != nil {
		return err
	}
	body = append(body, '\n')
	return os.WriteFile(filepath.Join(markerDir, splunkExportForgetMarkerFileName), body, 0o600)
}

func splunkExportStatusSnapshot(
	metricsController *otlp.SplunkMetricsExportController,
	tracesController *otlp.SplunkTracesExportController,
) splunkExportConfigureResponse {
	response := splunkExportConfigureResponse{}
	if metricsController != nil {
		response.Metrics = splunkMetricsExportStatusResponse(metricsController.Status())
	}
	if tracesController != nil {
		response.Traces = splunkTracesExportStatusResponse(tracesController.Status())
	}
	return response
}

func authorizeObserverControlRequest(r *http.Request) bool {
	expected := strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN"))
	if expected == "" {
		return false
	}

	if subtleConstantTimeEquals(r.Header.Get("X-Obstudio-Control-Token"), expected) {
		return true
	}
	auth := strings.TrimSpace(r.Header.Get("Authorization"))
	const bearerPrefix = "Bearer "
	if strings.HasPrefix(auth, bearerPrefix) {
		return subtleConstantTimeEquals(strings.TrimSpace(strings.TrimPrefix(auth, bearerPrefix)), expected)
	}
	return false
}

func authorizeObserverBrowserAction(r *http.Request, action string) bool {
	if strings.TrimSpace(r.Header.Get("X-Obstudio-Browser-Action")) != action {
		return false
	}
	if !isLoopbackRequestHost(r.Host) || !isLoopbackRemoteAddr(r.RemoteAddr) {
		return false
	}
	if fetchSite := strings.TrimSpace(r.Header.Get("Sec-Fetch-Site")); fetchSite != "" {
		return fetchSite == "same-origin"
	}
	if origin := strings.TrimSpace(r.Header.Get("Origin")); origin != "" {
		return sameRequestHost(origin, r.Host)
	}
	if referer := strings.TrimSpace(r.Header.Get("Referer")); referer != "" {
		return sameRequestHost(referer, r.Host)
	}
	return false
}

func isLoopbackRequestHost(rawHost string) bool {
	parsed, err := url.Parse("//" + strings.TrimSpace(rawHost))
	if err != nil || parsed.User != nil || parsed.Host == "" {
		return false
	}
	return isLoopbackHostname(parsed.Hostname())
}

func isLoopbackRemoteAddr(rawAddr string) bool {
	host, _, err := net.SplitHostPort(strings.TrimSpace(rawAddr))
	if err != nil {
		host = strings.TrimSpace(rawAddr)
	}
	return host != "" && isLoopbackHostname(host)
}

func sameRequestHost(rawURL string, requestHost string) bool {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return false
	}
	return strings.EqualFold(parsed.Host, requestHost)
}

func subtleConstantTimeEquals(got string, want string) bool {
	if got == "" || want == "" || len(got) != len(want) {
		return false
	}
	var mismatch byte
	for i := range got {
		mismatch |= got[i] ^ want[i]
	}
	return mismatch == 0
}

func splunkExportEndpoints(req splunkExportConfigureRequest) (string, string, error) {
	metricsEndpoint := strings.TrimSpace(req.MetricsEndpoint)
	tracesEndpoint := strings.TrimSpace(req.TracesEndpoint)
	baseEndpoint := strings.TrimRight(strings.TrimSpace(req.Endpoint), "/")
	if baseEndpoint == "" {
		return validateSplunkExportEndpoints(metricsEndpoint, tracesEndpoint, req.Realm)
	}

	parsed, err := url.Parse(baseEndpoint)
	if err != nil {
		return "", "", errors.New("endpoint is not a valid URL")
	}
	if err := validateParsedSplunkExportEndpoint(parsed, req.Realm); err != nil {
		return "", "", err
	}

	switch {
	case parsed.Path == "" || parsed.Path == "/":
		if metricsEndpoint == "" {
			metricsEndpoint = baseEndpoint + "/v2/datapoint/otlp"
		}
		if tracesEndpoint == "" {
			tracesEndpoint = baseEndpoint + "/v2/trace/otlp"
		}
	case strings.HasSuffix(parsed.Path, "/v2/datapoint/otlp"):
		if metricsEndpoint == "" {
			metricsEndpoint = baseEndpoint
		}
	case strings.HasSuffix(parsed.Path, "/v2/trace/otlp"):
		if tracesEndpoint == "" {
			tracesEndpoint = baseEndpoint
		}
	default:
		return "", "", errors.New("endpoint must be an ingest base URL or OTLP endpoint")
	}
	return validateSplunkExportEndpoints(metricsEndpoint, tracesEndpoint, req.Realm)
}

func validateSplunkExportEndpoints(metricsEndpoint string, tracesEndpoint string, realm string) (string, string, error) {
	if err := validateSplunkExportEndpoint(metricsEndpoint, realm); err != nil {
		return "", "", fmt.Errorf("metricsEndpoint: %w", err)
	}
	if err := validateSplunkExportEndpoint(tracesEndpoint, realm); err != nil {
		return "", "", fmt.Errorf("tracesEndpoint: %w", err)
	}
	return metricsEndpoint, tracesEndpoint, nil
}

func validateSplunkExportEndpoint(rawEndpoint string, realm string) error {
	if rawEndpoint == "" {
		return nil
	}
	parsed, err := url.Parse(rawEndpoint)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return errors.New("endpoint is not a valid URL")
	}
	return validateParsedSplunkExportEndpoint(parsed, realm)
}

func validateParsedSplunkExportEndpoint(parsed *url.URL, realm string) error {
	if parsed.Scheme != "https" && parsed.Scheme != "http" {
		return errors.New("endpoint must use http or https")
	}
	if parsed.Scheme == "http" && !isLoopbackHostname(parsed.Hostname()) {
		return errors.New("non-loopback endpoint must use https")
	}
	if parsed.User != nil {
		return errors.New("endpoint must not contain credentials")
	}
	if parsed.RawQuery != "" || parsed.Fragment != "" {
		return errors.New("endpoint must not contain query parameters or fragments")
	}
	if parsed.Scheme == "https" {
		hostname := strings.ToLower(parsed.Hostname())
		if internalRealm := trustedInternalSplunkIngestHosts[hostname]; internalRealm != "" {
			if !strings.EqualFold(strings.TrimSpace(realm), internalRealm) {
				return errors.New("endpoint realm does not match export realm")
			}
			return nil
		}
		match := trustedSplunkIngestHost.FindStringSubmatch(hostname)
		if len(match) != 2 {
			return errors.New("endpoint must use a registered Splunk Observability Cloud ingest host")
		}
		if strings.TrimSpace(realm) == "" || !strings.EqualFold(strings.TrimSpace(realm), match[1]) {
			return errors.New("endpoint realm does not match export realm")
		}
	}
	return nil
}

func isLoopbackHostname(hostname string) bool {
	if strings.EqualFold(hostname, "localhost") {
		return true
	}
	ip := net.ParseIP(hostname)
	return ip != nil && ip.IsLoopback()
}

func splunkMetricsExportStatusResponse(status otlp.SplunkMetricsExportStatus) *splunkExportStatusResponse {
	return &splunkExportStatusResponse{
		AccessTokenConfigured: status.AccessTokenConfigured,
		Configured:            status.Configured,
		Enabled:               status.Enabled,
		Endpoints:             status.Endpoints,
		FailedBatches:         status.FailedBatches,
		LastExport:            splunkMetricsExportAttemptResponse(status.LastExport),
		MetricBatches:         status.MetricBatches,
		MetricPoints:          status.MetricPoints,
		Realm:                 status.Realm,
		Timeout:               status.Timeout,
	}
}

func splunkTracesExportStatusResponse(status otlp.SplunkTracesExportStatus) *splunkExportStatusResponse {
	return &splunkExportStatusResponse{
		AccessTokenConfigured: status.AccessTokenConfigured,
		Configured:            status.Configured,
		Enabled:               status.Enabled,
		Endpoints:             status.Endpoints,
		FailedBatches:         status.FailedBatches,
		LastExport:            splunkTracesExportAttemptResponse(status.LastExport),
		Realm:                 status.Realm,
		Timeout:               status.Timeout,
		TraceBatches:          status.TraceBatches,
		TraceSpans:            status.TraceSpans,
	}
}

func splunkMetricsExportAttemptResponse(attempt *otlp.SplunkMetricsExportAttempt) *splunkExportAttemptResponse {
	if attempt == nil {
		return nil
	}
	return &splunkExportAttemptResponse{
		Error:   attempt.Error,
		Success: attempt.Success,
		Time:    attempt.Time,
	}
}

func splunkTracesExportAttemptResponse(attempt *otlp.SplunkTracesExportAttempt) *splunkExportAttemptResponse {
	if attempt == nil {
		return nil
	}
	return &splunkExportAttemptResponse{
		Error:   attempt.Error,
		Success: attempt.Success,
		Time:    attempt.Time,
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
