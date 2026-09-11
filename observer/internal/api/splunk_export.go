package api

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

const (
	maxSplunkExportRequestBytes  = 32 * 1024
	maxSplunkAccessTokenBytes    = 4096
	maxSplunkDestinationBytes    = 2048
	maxSplunkRealmPageBytes      = 512 * 1024
	splunkConnectionTestTimeout  = 10 * time.Second
	splunkRealmResolutionTimeout = 8 * time.Second
	splunkExportEnvFileSource    = "env-file"
	splunkMetricsOTLPTestPath    = "/v2/datapoint/otlp"
	splunkBrowserRequestHeader   = "X-Obstudio-Browser-Request"
	splunkRollbackTokenHeader    = "X-Obstudio-Cloud-Rollback-Token"
)

var splunkRealmPattern = regexp.MustCompile(`^[a-z]{2,12}[0-9]+$`)
var splunkSignalviewConfigPattern = regexp.MustCompile(`window\.signalviewConfig\s*=\s*`)
var splunkRollbackTokenPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
var splunkStateVersionPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
var errSplunkAccessTokenRejected = errors.New("Splunk rejected the access token for this realm.")
var errSplunkExportQuiesced = errors.New("Splunk Observability Studio is shutting down; cloud configuration changes are unavailable.")
var splunkConnectionHTTPClient = &http.Client{
	CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	},
}
var splunkRealmHTTPClient = &http.Client{
	CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	},
}

type splunkConnectionVerifier func(context.Context, string, string) error

// SplunkExportConfigurationRefresher reloads an optional local configuration
// source without changing process-wide environment variables. It reports whether
// the effective cloud configuration remains managed by that local source.
type SplunkExportConfigurationRefresher func() (bool, error)

type splunkExportService struct {
	metrics                 *otlp.SplunkMetricsExportController
	traces                  *otlp.SplunkTracesExportController
	refresh                 SplunkExportConfigurationRefresher
	verifyConnection        splunkConnectionVerifier
	resolveRealmClient      *http.Client
	rollbackToken           string
	rollbackMetrics         otlp.SplunkMetricsExporterConfig
	rollbackChanged         bool
	rollbackTraces          otlp.SplunkTracesExporterConfig
	rollbackSource          string
	source                  string
	cimdRegistrationEnabled bool
	configurationChanged    bool
	stateVersionKey         [32]byte
	mutationMu              sync.Mutex
	mu                      sync.Mutex
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
	Connected               bool                     `json:"connected"`
	Enabled                 bool                     `json:"enabled"`
	Realm                   string                   `json:"realm,omitempty"`
	RollbackToken           string                   `json:"rollbackToken,omitempty"`
	Version                 string                   `json:"version"`
	Metrics                 splunkExportSignalStatus `json:"metrics"`
	Traces                  splunkExportSignalStatus `json:"traces"`
	CIMDRegistrationEnabled bool                     `json:"cimdRegistrationEnabled"`
}

type configureSplunkExportRequest struct {
	Realm           string `json:"realm"`
	AccessToken     string `json:"accessToken"`
	ExpectedVersion string `json:"expectedVersion,omitempty"`
}

type setSplunkExportEnabledRequest struct {
	Enabled         *bool  `json:"enabled"`
	ExpectedVersion string `json:"expectedVersion,omitempty"`
}

type forgetSplunkExportRequest struct {
	ExpectedVersion string `json:"expectedVersion,omitempty"`
}

type rollbackSplunkExportRequest struct {
	RollbackToken string `json:"rollbackToken"`
}

type splunkExportRealmRequest struct {
	Destination string `json:"destination"`
}

type splunkSignalviewConfig struct {
	AppDomain string `json:"appDomain"`
	Realm     string `json:"realm"`
}

func newSplunkExportService(
	metrics *otlp.SplunkMetricsExportController,
	traces *otlp.SplunkTracesExportController,
	refresh SplunkExportConfigurationRefresher,
) *splunkExportService {
	service := &splunkExportService{
		metrics: metrics,
		traces:  traces,
		refresh: refresh,
		verifyConnection: func(ctx context.Context, realm, accessToken string) error {
			return verifySplunkCloudConnection(ctx, splunkConnectionHTTPClient, realm, accessToken)
		},
		resolveRealmClient: splunkRealmHTTPClient,
		// TODO(CIMD PoC): standalone-binary source of truth for the CIMD registration
		// feature flag, independent of the VS Code "sisCimdRegistrationEnabled" setting
		// used when Splunk Observability Studio runs inside the extension. The IDE setting is the source of
		// truth whenever it is present; this env var only matters for direct-browser dev
		// (`go run ./cmd/obstudio` + `make dev`), where no VS Code settings exist.
		cimdRegistrationEnabled: envFlagEnabled("OBSTUDIO_SIS_CIMD_REGISTRATION_ENABLED"),
	}
	if _, err := rand.Read(service.stateVersionKey[:]); err != nil {
		service.stateVersionKey = sha256.Sum256([]byte(fmt.Sprintf(
			"%d:%d",
			os.Getpid(),
			time.Now().UnixNano(),
		)))
	}
	return service
}

func envFlagEnabled(name string) bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv(name)))
	return value == "1" || value == "true"
}

func (s *splunkExportService) register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/splunk/export", s.status)
	mux.HandleFunc("POST /api/splunk/export", s.authorizeMutation(s.serializeMutation(s.configure)))
	mux.HandleFunc("POST /api/splunk/export/realm", s.authorizeMutation(s.resolveRealm))
	mux.HandleFunc("POST /api/splunk/export/rollback", s.authorizeMutation(s.serializeRecoveryMutation(s.rollback)))
	mux.HandleFunc("POST /api/splunk/export/enabled", s.authorizeMutation(s.serializeMutation(s.setEnabled)))
	mux.HandleFunc("POST /api/splunk/export/forget", s.authorizeMutation(s.serializeMutation(s.forget)))
	if s.refresh != nil {
		mux.HandleFunc("POST /api/splunk/export/refresh", s.authorizeMutation(s.serializeMutation(s.refreshConfiguration)))
	}
}

func (s *splunkExportService) resolveRealm(w http.ResponseWriter, r *http.Request) {
	var request splunkExportRealmRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), splunkRealmResolutionTimeout)
	defer cancel()
	realm, err := resolveSplunkRealm(ctx, s.resolveRealmClient, request.Destination)
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) {
			writeSplunkExportError(w, http.StatusGatewayTimeout, "Splunk Observability Cloud realm lookup timed out.")
			return
		}
		var validationError *splunkRealmDestinationError
		if errors.As(err, &validationError) {
			writeSplunkExportError(w, http.StatusBadRequest, validationError.Error())
			return
		}
		writeSplunkExportError(w, http.StatusBadGateway, err.Error())
		return
	}

	w.Header().Set("Cache-Control", "no-store")
	writeSameOriginJSON(w, map[string]string{"realm": realm})
}

func (s *splunkExportService) status(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, s.snapshot())
}

func (s *splunkExportService) configure(w http.ResponseWriter, r *http.Request) {
	realm, accessToken, expectedVersion, ok := decodeSplunkExportConfiguration(w, r)
	if !ok {
		return
	}
	if !s.acceptExpectedVersion(w, expectedVersion) {
		return
	}
	issueRollback, requestedRollbackToken, ok := s.rollbackRequest(w, r)
	if !ok {
		return
	}

	verificationContext, cancelVerification := context.WithTimeout(r.Context(), splunkConnectionTestTimeout)
	err := s.verifyConnection(verificationContext, realm, accessToken)
	cancelVerification()
	if err != nil {
		if errors.Is(err, errSplunkAccessTokenRejected) {
			writeSplunkExportError(w, http.StatusUnauthorized, errSplunkAccessTokenRejected.Error())
			return
		}
		if errors.Is(err, context.DeadlineExceeded) {
			writeSplunkExportError(w, http.StatusGatewayTimeout, "Splunk Observability Cloud connection test timed out.")
			return
		}
		writeSplunkExportError(w, http.StatusBadGateway, err.Error())
		return
	}
	s.applyCloudConnection(w, realm, accessToken, issueRollback, requestedRollbackToken)
}

func decodeSplunkExportConfiguration(w http.ResponseWriter, r *http.Request) (string, string, string, bool) {
	var request configureSplunkExportRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return "", "", "", false
	}

	realm, err := validateSplunkRealm(request.Realm)
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return "", "", "", false
	}
	accessToken, err := validateSplunkAccessToken(request.AccessToken)
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return "", "", "", false
	}
	return realm, accessToken, request.ExpectedVersion, true
}

func (s *splunkExportService) applyCloudConnection(
	w http.ResponseWriter,
	realm string,
	accessToken string,
	issueRollback bool,
	requestedRollbackToken string,
) {
	s.mu.Lock()
	defer s.mu.Unlock()
	previousMetrics := s.metrics.Config()
	previousTraces := s.traces.Config()
	rollbackToken, err := s.beginRollbackLocked(issueRollback, requestedRollbackToken)
	if err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not create cloud rollback capability")
		return
	}

	if err := s.apply(
		otlp.SplunkMetricsExporterConfig{Realm: realm, AccessToken: accessToken},
		otlp.SplunkTracesExporterConfig{Realm: realm, AccessToken: accessToken},
	); err != nil {
		if rollbackToken != "" {
			if rollbackErr := s.apply(previousMetrics, previousTraces); rollbackErr == nil {
				s.clearRollbackLocked()
			}
		}
		writeSplunkExportError(w, http.StatusInternalServerError, "could not configure Splunk Observability Cloud export")
		return
	}
	s.source = ""
	s.configurationChanged = true
	status := s.snapshotLocked()
	status.RollbackToken = rollbackToken
	writeSameOriginJSON(w, status)
}

func (s *splunkExportService) rollback(w http.ResponseWriter, r *http.Request) {
	var request rollbackSplunkExportRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}
	provided := strings.TrimSpace(request.RollbackToken)
	if !splunkRollbackTokenPattern.MatchString(provided) {
		writeSplunkExportError(w, http.StatusBadRequest, "rollbackToken is invalid")
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	if !equalSplunkRollbackToken(provided, s.rollbackToken) {
		writeSplunkExportError(w, http.StatusConflict, "cloud rollback capability is not valid")
		return
	}
	if err := s.apply(s.rollbackMetrics, s.rollbackTraces); err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not roll back Splunk Observability Cloud export")
		return
	}
	s.source = s.rollbackSource
	s.configurationChanged = s.rollbackChanged
	s.clearRollbackLocked()
	writeSameOriginJSON(w, s.snapshotLocked())
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
	if !s.acceptExpectedVersion(w, request.ExpectedVersion) {
		return
	}
	issueRollback, requestedRollbackToken, ok := s.rollbackRequest(w, r)
	if !ok {
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
	rollbackToken, err := s.beginRollbackLocked(issueRollback, requestedRollbackToken)
	if err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not create cloud rollback capability")
		return
	}
	metricsConfig.Enabled = enabled
	tracesConfig.Enabled = enabled
	if err := s.apply(metricsConfig, tracesConfig); err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not update Splunk Observability Cloud export")
		return
	}
	s.configurationChanged = true
	status := s.snapshotLocked()
	status.RollbackToken = rollbackToken
	writeSameOriginJSON(w, status)
}

func (s *splunkExportService) forget(w http.ResponseWriter, r *http.Request) {
	var request forgetSplunkExportRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}
	if !s.acceptExpectedVersion(w, request.ExpectedVersion) {
		return
	}
	issueRollback, requestedRollbackToken, ok := s.rollbackRequest(w, r)
	if !ok {
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	if s.source == splunkExportEnvFileSource {
		writeSplunkExportError(w, http.StatusConflict, "remove SPLUNK_ACCESS_TOKEN from the env file before removing this connection")
		return
	}
	rollbackToken, err := s.beginRollbackLocked(issueRollback, requestedRollbackToken)
	if err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not create cloud rollback capability")
		return
	}
	if err := s.apply(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not remove Splunk Observability Cloud connection")
		return
	}
	s.source = ""
	s.configurationChanged = true
	status := s.snapshotLocked()
	status.RollbackToken = rollbackToken
	writeSameOriginJSON(w, status)
}

func equalSplunkRollbackToken(provided, expected string) bool {
	return splunkRollbackTokenPattern.MatchString(provided) &&
		len(provided) == len(expected) &&
		subtle.ConstantTimeCompare([]byte(provided), []byte(expected)) == 1
}

func (s *splunkExportService) rollbackRequest(
	w http.ResponseWriter,
	r *http.Request,
) (bool, string, bool) {
	requested := strings.TrimSpace(r.Header.Get(splunkRollbackTokenHeader))
	if requested == "" {
		return false, "", true
	}
	if !splunkRollbackTokenPattern.MatchString(requested) {
		writeSplunkExportError(w, http.StatusBadRequest, "cloud rollback token is invalid")
		return false, "", false
	}
	return true, requested, true
}

func (s *splunkExportService) beginRollbackLocked(
	issue bool,
	requested string,
) (string, error) {
	s.clearRollbackLocked()
	if !issue {
		return "", nil
	}
	if !splunkRollbackTokenPattern.MatchString(requested) {
		return "", errors.New("invalid requested cloud rollback capability")
	}
	token := requested
	s.rollbackToken = token
	s.rollbackChanged = s.configurationChanged
	s.rollbackMetrics = s.metrics.Config()
	s.rollbackTraces = s.traces.Config()
	s.rollbackSource = s.source
	return token, nil
}

func (s *splunkExportService) clearRollbackLocked() {
	s.rollbackToken = ""
	s.rollbackChanged = false
	s.rollbackMetrics = otlp.SplunkMetricsExporterConfig{}
	s.rollbackTraces = otlp.SplunkTracesExporterConfig{}
	s.rollbackSource = ""
}

func (s *splunkExportService) refreshConfiguration(w http.ResponseWriter, _ *http.Request) {
	if err := s.refreshConfigurationState(); err != nil {
		if errors.Is(err, errSplunkExportQuiesced) {
			writeSplunkExportError(w, http.StatusServiceUnavailable, err.Error())
			return
		}
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	writeSameOriginJSON(w, s.snapshotLocked())
}

func (s *splunkExportService) refreshConfigurationState() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.clearRollbackLocked()

	managed, err := s.refresh()
	if err != nil {
		return err
	}
	if managed {
		s.source = splunkExportEnvFileSource
	} else {
		s.source = ""
	}
	return nil
}

func requireLocalObserverRequest(
	next http.HandlerFunc,
	writeError func(w http.ResponseWriter, status int, message string),
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !isLocalObserverRequest(r) {
			writeError(w, http.StatusForbidden, "request must come from the local Splunk Observability Studio origin")
			return
		}
		next(w, r)
	}
}

func (s *splunkExportService) authorizeMutation(next http.HandlerFunc) http.HandlerFunc {
	return requireLocalObserverRequest(next, writeSplunkExportError)
}

func (s *splunkExportService) serializeMutation(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !s.mutationMu.TryLock() {
			// Let the active mutation finish before the caller reconciles status.
			s.mutationMu.Lock()
			s.mutationMu.Unlock()
			writeSplunkExportError(w, http.StatusConflict, "A cloud configuration change is already in progress.")
			return
		}
		defer s.mutationMu.Unlock()
		next(w, r)
	}
}

func (s *splunkExportService) serializeRecoveryMutation(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.mutationMu.Lock()
		defer s.mutationMu.Unlock()
		next(w, r)
	}
}

// isSameOriginLoopbackBrowserRequest is the standalone browser CSRF boundary.
// Splunk Observability Studio trusts local-machine processes that can reach loopback; these checks
// prevent a remote web origin from driving cloud mutations through the HTTP API.
func isSameOriginLoopbackBrowserRequest(r *http.Request) bool {
	if r.Header.Get(splunkBrowserRequestHeader) != "1" {
		return false
	}
	if fetchSite := r.Header.Get("Sec-Fetch-Site"); fetchSite != "" && fetchSite != "same-origin" {
		return false
	}
	remoteHost, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil || !isLoopbackHostname(remoteHost) {
		return false
	}
	origin, err := url.Parse(r.Header.Get("Origin"))
	if err != nil || origin.User != nil || origin.Path != "" || origin.RawQuery != "" || origin.Fragment != "" {
		return false
	}
	expectedScheme := "http"
	if r.TLS != nil {
		expectedScheme = "https"
	}
	return origin.Scheme == expectedScheme &&
		strings.EqualFold(origin.Host, r.Host) &&
		isLoopbackHostname(origin.Hostname())
}

func isLocalObserverRequest(r *http.Request) bool {
	remoteHost, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil || !isLoopbackHostname(remoteHost) {
		return false
	}
	if strings.TrimSpace(r.Header.Get("Origin")) != "" {
		return isSameOriginLoopbackBrowserRequest(r)
	}
	if fetchSite := strings.TrimSpace(r.Header.Get("Sec-Fetch-Site")); fetchSite != "" {
		return fetchSite == "same-origin" && r.Header.Get(splunkBrowserRequestHeader) == "1"
	}
	return true
}

func isLoopbackHostname(host string) bool {
	host = strings.TrimSuffix(strings.Trim(strings.TrimSpace(host), "[]"), ".")
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
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
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.snapshotLocked()
}

// snapshotLocked returns a status whose configuration and source belong to
// the same mutation epoch. The caller must hold s.mu.
func (s *splunkExportService) snapshotLocked() splunkExportStatusResponse {
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
		Connected:               connected,
		Enabled:                 connected && metrics.Enabled && traces.Enabled,
		Realm:                   realm,
		Version:                 s.stateVersionLocked(metricsConfig, tracesConfig),
		CIMDRegistrationEnabled: s.cimdRegistrationEnabled,
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

func (s *splunkExportService) acceptExpectedVersion(w http.ResponseWriter, expected string) bool {
	if expected == "" {
		return true
	}
	if !splunkStateVersionPattern.MatchString(expected) {
		writeSplunkExportError(w, http.StatusBadRequest, "expectedVersion is invalid")
		return false
	}

	s.mu.Lock()
	current := s.stateVersionLocked(s.metrics.Config(), s.traces.Config())
	s.mu.Unlock()
	if subtle.ConstantTimeCompare([]byte(expected), []byte(current)) != 1 {
		writeSplunkExportError(
			w,
			http.StatusConflict,
			"Cloud configuration changed in another session. Refresh and try again.",
		)
		return false
	}
	return true
}

// stateVersionLocked includes s.source, so the caller must hold s.mu.
func (s *splunkExportService) stateVersionLocked(
	metrics otlp.SplunkMetricsExporterConfig,
	traces otlp.SplunkTracesExporterConfig,
) string {
	state, err := json.Marshal(struct {
		Metrics otlp.SplunkMetricsExporterConfig `json:"metrics"`
		Source  string                           `json:"source"`
		Traces  otlp.SplunkTracesExporterConfig  `json:"traces"`
	}{
		Metrics: metrics,
		Source:  s.source,
		Traces:  traces,
	})
	if err != nil {
		panic("serialize cloud configuration state: " + err.Error())
	}
	digest := hmac.New(sha256.New, s.stateVersionKey[:])
	_, _ = digest.Write(state)
	return base64.RawURLEncoding.EncodeToString(digest.Sum(nil))
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
		return "", errors.New("realm is not valid")
	}
	return realm, nil
}

type splunkRealmDestinationError struct {
	message string
}

func (e *splunkRealmDestinationError) Error() string {
	return e.message
}

func invalidSplunkRealmDestination(message string) error {
	return &splunkRealmDestinationError{message: message}
}

func resolveSplunkRealm(ctx context.Context, client *http.Client, value string) (string, error) {
	destination := strings.TrimSpace(value)
	if destination == "" {
		return "", invalidSplunkRealmDestination("Observability Cloud URL or realm is required")
	}
	if len(destination) > maxSplunkDestinationBytes {
		return "", invalidSplunkRealmDestination("Observability Cloud URL or realm is too long")
	}
	if strings.EqualFold(destination, "realm") {
		return "", invalidSplunkRealmDestination("replace the placeholder with your Observability Cloud realm")
	}
	if realm, err := validateSplunkRealm(destination); err == nil {
		return realm, nil
	}

	parsed, err := url.Parse(destination)
	if err != nil || parsed.Opaque != "" || !strings.EqualFold(parsed.Scheme, "https") || parsed.Host == "" {
		return "", invalidSplunkRealmDestination("destination must be a realm or HTTPS Splunk Observability Cloud URL")
	}
	if parsed.User != nil {
		return "", invalidSplunkRealmDestination("destination URL must not contain user information")
	}
	host := strings.ToLower(parsed.Hostname())
	if parsed.Port() != "" || !strings.EqualFold(parsed.Host, host) {
		return "", invalidSplunkRealmDestination("destination URL must not contain a port")
	}
	if net.ParseIP(host) != nil {
		return "", invalidSplunkRealmDestination("destination URL must use a Splunk hostname")
	}
	if !validDNSHostname(host) || !isSplunkObservabilityHostname(host) {
		return "", invalidSplunkRealmDestination("destination is not a Splunk Observability Cloud hostname")
	}
	if realm, standard, err := realmFromStandardSplunkHostname(host); standard {
		if err != nil {
			return "", invalidSplunkRealmDestination("destination URL does not contain a valid Observability Cloud realm")
		}
		return realm, nil
	}
	prefix, _, ok := splunkHostnamePrefix(host)
	if !ok || strings.Contains(prefix, ".") {
		return "", invalidSplunkRealmDestination("destination URL is not a supported Observability Cloud endpoint")
	}
	if strings.EqualFold(prefix, "realm") {
		return "", invalidSplunkRealmDestination("replace the placeholder with your Observability Cloud realm")
	}
	if isRealmLessSplunkService(prefix) {
		return "", invalidSplunkRealmDestination("destination URL does not identify an organization realm")
	}

	return fetchSplunkRealm(ctx, client, host)
}

func validDNSHostname(host string) bool {
	if host == "" || len(host) > 253 || strings.HasPrefix(host, ".") || strings.HasSuffix(host, ".") {
		return false
	}
	for _, label := range strings.Split(host, ".") {
		if label == "" || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return false
		}
		for _, character := range label {
			if (character < 'a' || character > 'z') &&
				(character < '0' || character > '9') && character != '-' {
				return false
			}
		}
	}
	return true
}

func isSplunkObservabilityHostname(host string) bool {
	return strings.HasSuffix(host, ".signalfx.com") ||
		strings.HasSuffix(host, ".observability.splunkcloud.com")
}

func realmFromStandardSplunkHostname(host string) (string, bool, error) {
	prefix, domain, ok := splunkHostnamePrefix(host)
	if !ok {
		return "", false, nil
	}
	parts := strings.Split(prefix, ".")
	if len(parts) == 1 {
		return "", false, nil
	}
	if len(parts) != 2 || !isSplunkRealmService(parts[0], domain) {
		return "", true, errors.New("unsupported Splunk Observability Cloud endpoint")
	}
	realm, err := validateSplunkRealm(parts[1])
	return realm, true, err
}

type splunkHostnameDomain uint8

const (
	splunkSignalFxDomain splunkHostnameDomain = iota + 1
	splunkObservabilityDomain
)

func splunkHostnamePrefix(host string) (string, splunkHostnameDomain, bool) {
	switch {
	case strings.HasSuffix(host, ".observability.splunkcloud.com"):
		return strings.TrimSuffix(host, ".observability.splunkcloud.com"), splunkObservabilityDomain, true
	case strings.HasSuffix(host, ".signalfx.com"):
		return strings.TrimSuffix(host, ".signalfx.com"), splunkSignalFxDomain, true
	default:
		return "", 0, false
	}
}

func isSplunkRealmService(value string, domain splunkHostnameDomain) bool {
	switch value {
	case "app", "api", "ingest", "rum-ingest", "stream", "backfill", "runner":
		return true
	case "private-api", "private-ingest", "private-stream":
		return domain == splunkSignalFxDomain
	case "customer-api":
		return domain == splunkObservabilityDomain
	default:
		return false
	}
}

func isRealmLessSplunkService(value string) bool {
	if value == "login" || value == "cdn" {
		return true
	}
	return isSplunkRealmService(value, splunkSignalFxDomain) ||
		isSplunkRealmService(value, splunkObservabilityDomain)
}

func fetchSplunkRealm(ctx context.Context, client *http.Client, host string) (string, error) {
	if client == nil {
		client = splunkRealmHTTPClient
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://"+host+"/", http.NoBody)
	if err != nil {
		return "", errors.New("could not prepare the Splunk Observability Cloud realm lookup")
	}

	lookupClient := *client
	lookupClient.Jar = nil
	lookupClient.CheckRedirect = func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}
	response, err := lookupClient.Do(request)
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return "", context.DeadlineExceeded
		}
		return "", errors.New("could not reach the Splunk Observability Cloud URL")
	}
	defer response.Body.Close()
	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 4*1024))
		return "", fmt.Errorf("Splunk Observability Cloud URL returned HTTP %d", response.StatusCode)
	}
	mediaType, _, err := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if err != nil || !strings.EqualFold(mediaType, "text/html") {
		return "", errors.New("Splunk Observability Cloud URL did not return an HTML page")
	}
	page, err := io.ReadAll(io.LimitReader(response.Body, maxSplunkRealmPageBytes+1))
	if err != nil {
		return "", errors.New("could not read the Splunk Observability Cloud page")
	}
	if len(page) > maxSplunkRealmPageBytes {
		return "", errors.New("Splunk Observability Cloud page is too large")
	}

	config, err := parseSplunkSignalviewConfig(page)
	if err != nil {
		return "", err
	}
	realm, err := validateSplunkRealm(config.Realm)
	if err != nil {
		return "", errors.New("Splunk Observability Cloud page did not contain a valid realm")
	}
	if !splunkAppDomainMatchesRealm(config.AppDomain, realm) {
		return "", errors.New("Splunk Observability Cloud page realm did not match its application domain")
	}
	return realm, nil
}

func parseSplunkSignalviewConfig(page []byte) (splunkSignalviewConfig, error) {
	match := splunkSignalviewConfigPattern.FindIndex(page)
	if match == nil {
		return splunkSignalviewConfig{}, errors.New("Splunk Observability Cloud page did not contain signalview configuration")
	}
	var config splunkSignalviewConfig
	decoder := json.NewDecoder(strings.NewReader(string(page[match[1]:])))
	if err := decoder.Decode(&config); err != nil {
		return splunkSignalviewConfig{}, errors.New("Splunk Observability Cloud page contained invalid signalview configuration")
	}
	return config, nil
}

func splunkAppDomainMatchesRealm(value, realm string) bool {
	host := strings.ToLower(strings.TrimSpace(value))
	if !validDNSHostname(host) {
		return false
	}
	domainRealm, standard, err := realmFromStandardSplunkHostname(host)
	if err != nil || !standard || !strings.HasPrefix(host, "app.") {
		return false
	}
	return domainRealm == realm
}

func validateSplunkAccessToken(value string) (string, error) {
	token := strings.TrimSpace(value)
	if len(token) == 0 || len(token) > maxSplunkAccessTokenBytes {
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

func verifySplunkCloudConnection(
	ctx context.Context,
	client *http.Client,
	realm string,
	accessToken string,
) error {
	endpoint := fmt.Sprintf(
		"https://ingest.%s.observability.splunkcloud.com%s",
		realm,
		splunkMetricsOTLPTestPath,
	)
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, http.NoBody)
	if err != nil {
		return errors.New("could not prepare the Splunk Observability Cloud connection test")
	}
	// An empty proto3 body is a valid ExportMetricsServiceRequest. It proves the
	// realm and ingest token without creating a metric or trace.
	request.Header.Set("Content-Type", "application/x-protobuf")
	request.Header.Set("X-SF-Token", accessToken)

	response, err := client.Do(request)
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return context.DeadlineExceeded
		}
		return errors.New("could not reach Splunk Observability Cloud for this realm")
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 4*1024))

	if response.StatusCode >= http.StatusOK && response.StatusCode < http.StatusMultipleChoices {
		return nil
	}
	if response.StatusCode == http.StatusUnauthorized || response.StatusCode == http.StatusForbidden {
		return errSplunkAccessTokenRejected
	}
	return fmt.Errorf("Splunk Observability Cloud connection test failed with HTTP %d", response.StatusCode)
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
