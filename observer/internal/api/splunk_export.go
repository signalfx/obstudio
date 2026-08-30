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
	"net"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

const (
	maxSplunkExportRequestBytes = 32 * 1024
	maxSplunkAccessTokenBytes   = 4096
	splunkConnectionTestTimeout = 10 * time.Second
	splunkExportEnvFileSource   = "env-file"
	splunkMetricsOTLPTestPath   = "/v2/datapoint/otlp"
	splunkBrowserRequestHeader  = "X-Obstudio-Browser-Request"
	splunkBrowserTokenHeader    = "X-Obstudio-Browser-Token"
	splunkRollbackTokenHeader   = "X-Obstudio-Cloud-Rollback-Token"
	splunkBrowserCookiePrefix   = "obstudio_cloud_browser_session_"
	splunkBrowserLaunchEnv      = "OBSTUDIO_CLOUD_BROWSER_LAUNCH_TOKEN"
)

var splunkRealmPattern = regexp.MustCompile(`^[a-z]{2,12}[0-9]+$`)
var splunkBrowserLaunchTokenPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
var splunkBrowserTokenPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
var splunkRollbackTokenPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
var splunkStateVersionPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
var errSplunkAccessTokenRejected = errors.New("Splunk rejected the access token for this realm.")
var errSplunkExportQuiesced = errors.New("Observer is shutting down; cloud configuration changes are unavailable.")
var splunkConnectionHTTPClient = &http.Client{
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
	metrics              *otlp.SplunkMetricsExportController
	traces               *otlp.SplunkTracesExportController
	refresh              SplunkExportConfigurationRefresher
	verifyConnection     splunkConnectionVerifier
	controlToken         string
	browserLaunch        string
	browserSessionIssued bool
	browserToken         string
	rollbackToken        string
	rollbackMetrics      otlp.SplunkMetricsExporterConfig
	rollbackChanged      bool
	rollbackTraces       otlp.SplunkTracesExporterConfig
	rollbackSource       string
	source               string
	configurationChanged bool
	mutationsQuiesced    atomic.Bool
	stateVersionKey      [32]byte
	browserMu            sync.Mutex
	mutationMu           sync.Mutex
	mu                   sync.Mutex
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
	Connected     bool                     `json:"connected"`
	Enabled       bool                     `json:"enabled"`
	Realm         string                   `json:"realm,omitempty"`
	RollbackToken string                   `json:"rollbackToken,omitempty"`
	Version       string                   `json:"version"`
	Metrics       splunkExportSignalStatus `json:"metrics"`
	Traces        splunkExportSignalStatus `json:"traces"`
}

type splunkExportConfigurationResponse struct {
	AccessToken string `json:"accessToken,omitempty"`
	Changed     bool   `json:"changed"`
	Connected   bool   `json:"connected"`
	Enabled     bool   `json:"enabled"`
	Realm       string `json:"realm,omitempty"`
	Source      string `json:"source,omitempty"`
	Version     string `json:"version"`
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

type splunkExportBrowserSessionRequest struct {
	LaunchToken string `json:"launchToken"`
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
		controlToken:  strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")),
		browserLaunch: strings.TrimSpace(os.Getenv(splunkBrowserLaunchEnv)),
	}
	if _, err := rand.Read(service.stateVersionKey[:]); err != nil {
		service.stateVersionKey = sha256.Sum256([]byte(fmt.Sprintf(
			"%s:%d:%d",
			service.controlToken,
			os.Getpid(),
			time.Now().UnixNano(),
		)))
	}
	return service
}

func (s *splunkExportService) register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/splunk/export", s.status)
	mux.HandleFunc("GET /api/splunk/export/configuration", s.authorizeControlToken(s.serializeRecoveryMutation(s.configuration)))
	mux.HandleFunc("POST /api/splunk/export/shutdown-snapshot", s.authorizeControlToken(s.serializeShutdownSnapshot(s.shutdownSnapshot)))
	mux.HandleFunc("POST /api/splunk/export", s.authorizeMutation(s.serializeMutation(s.configure)))
	mux.HandleFunc("POST /api/splunk/export/rollback", s.authorizeControlToken(s.serializeRecoveryMutation(s.rollback)))
	mux.HandleFunc("POST /api/splunk/export/browser/session", s.issueBrowserSession)
	mux.HandleFunc("POST /api/splunk/export/enabled", s.authorizeMutation(s.serializeMutation(s.setEnabled)))
	mux.HandleFunc("POST /api/splunk/export/forget", s.authorizeMutation(s.serializeMutation(s.forget)))
	if s.refresh != nil {
		mux.HandleFunc("POST /api/splunk/export/refresh", s.authorizeControlToken(s.serializeMutation(s.refreshConfiguration)))
	}
}

func (s *splunkExportService) status(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, s.snapshot())
}

func (s *splunkExportService) configuration(w http.ResponseWriter, _ *http.Request) {
	s.writeConfigurationSnapshot(w)
}

func (s *splunkExportService) shutdownSnapshot(w http.ResponseWriter, _ *http.Request) {
	s.writeConfigurationSnapshot(w)
}

func (s *splunkExportService) writeConfigurationSnapshot(w http.ResponseWriter) {
	s.mu.Lock()
	defer s.mu.Unlock()

	metrics := s.metrics.Config()
	traces := s.traces.Config()
	connected := sameSplunkCloudRealm(
		metrics.Realm,
		metrics.AccessToken,
		metrics.Endpoint != "",
		traces.Realm,
		traces.AccessToken,
		traces.Endpoint != "",
	)
	response := splunkExportConfigurationResponse{
		Changed:   s.configurationChanged,
		Connected: connected,
		Enabled:   connected && metrics.Enabled && traces.Enabled,
		Source:    s.source,
		Version:   s.stateVersionLocked(metrics, traces),
	}
	if connected {
		response.AccessToken = metrics.AccessToken
		response.Realm = metrics.Realm
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, response)
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
	if s.rejectQuiescedMutation(w) {
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
	if s.rejectQuiescedMutation(w) {
		return
	}

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
	writeJSON(w, status)
}

func (s *splunkExportService) rollback(w http.ResponseWriter, r *http.Request) {
	if s.rejectQuiescedMutation(w) {
		return
	}
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
	if s.rejectQuiescedMutation(w) {
		return
	}
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
	writeJSON(w, s.snapshotLocked())
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
	if s.rejectQuiescedMutation(w) {
		return
	}

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
	writeJSON(w, status)
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
	if s.rejectQuiescedMutation(w) {
		return
	}

	if s.source == splunkExportEnvFileSource {
		writeSplunkExportError(w, http.StatusConflict, "remove SPLUNK_ACCESS_TOKEN from the env file before forgetting this connection")
		return
	}
	rollbackToken, err := s.beginRollbackLocked(issueRollback, requestedRollbackToken)
	if err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not create cloud rollback capability")
		return
	}
	if err := s.apply(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not forget Splunk Observability Cloud destination")
		return
	}
	s.source = ""
	s.configurationChanged = true
	status := s.snapshotLocked()
	status.RollbackToken = rollbackToken
	writeJSON(w, status)
}

func (s *splunkExportService) issueBrowserSession(w http.ResponseWriter, r *http.Request) {
	if s.controlToken == "" {
		writeSplunkExportError(w, http.StatusServiceUnavailable, "Observer control is not configured")
		return
	}
	if !isSameOriginLoopbackBrowserRequest(r) {
		writeSplunkExportError(w, http.StatusForbidden, "browser cloud control requires the local Observer page")
		return
	}
	var request splunkExportBrowserSessionRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}
	s.mutationMu.Lock()
	defer s.mutationMu.Unlock()
	if s.rejectQuiescedMutation(w) {
		return
	}

	providedSession := s.validBrowserTokenFromRequest(r)
	authorizedBySession := providedSession != ""
	launchToken := strings.TrimSpace(request.LaunchToken)
	token := providedSession
	if !authorizedBySession {
		var authorizedByBrowser bool
		var err error
		token, authorizedByBrowser, err = s.browserSessionForLocalPage(launchToken)
		if err != nil {
			writeSplunkExportError(w, http.StatusInternalServerError, "could not create browser cloud control session")
			return
		}
		if !authorizedByBrowser {
			writeSplunkExportError(w, http.StatusUnauthorized, "browser cloud control launch is not valid")
			return
		}
	}
	warning := ""
	if s.refresh != nil && !s.hasPendingRollback() {
		if err := s.refreshConfigurationState(); err != nil {
			warning = err.Error()
		}
	}
	w.Header().Set("Cache-Control", "no-store")
	http.SetCookie(w, &http.Cookie{
		Name:     splunkBrowserTokenCookieName(r),
		Value:    token,
		Path:     "/api/splunk/export",
		HttpOnly: true,
		Secure:   r.TLS != nil,
		SameSite: http.SameSiteStrictMode,
	})
	response := map[string]string{"browserToken": token}
	if warning != "" {
		response["warning"] = warning
	}
	writeSameOriginJSON(w, response)
}

func splunkBrowserTokenCookieFromRequest(r *http.Request) string {
	cookie, err := r.Cookie(splunkBrowserTokenCookieName(r))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(cookie.Value)
}

func splunkBrowserTokenCookieName(r *http.Request) string {
	port := "80"
	if r.TLS != nil {
		port = "443"
	}
	if _, requestPort, err := net.SplitHostPort(r.Host); err == nil && requestPort != "" {
		port = requestPort
	}
	return splunkBrowserCookiePrefix + port
}

func (s *splunkExportService) browserSessionForLocalPage(
	launchToken string,
) (string, bool, error) {
	// The caller's loopback, Origin, request-marker, and fetch-metadata checks are
	// the browser security boundary. A launch capability is optional so a local
	// standalone page can be the first controller, but it must be valid whenever
	// one is supplied so stale or tampered secure launch URLs fail closed.
	if launchToken != "" && !equalSplunkBrowserLaunchToken(launchToken, s.browserLaunch) {
		return "", false, nil
	}

	s.browserMu.Lock()
	defer s.browserMu.Unlock()
	if s.browserSessionIssued {
		// The launch credential is process-scoped so the same secure URL can
		// attach another legitimate tab or loopback hostname to this session.
		if splunkBrowserTokenPattern.MatchString(s.browserToken) {
			return s.browserToken, true, nil
		}
		return "", false, nil
	}

	token, err := newSplunkOpaqueToken()
	if err != nil {
		return "", false, err
	}
	s.browserToken = token
	s.browserSessionIssued = true
	return token, true, nil
}

func equalSplunkBrowserLaunchToken(provided, expected string) bool {
	return splunkBrowserLaunchTokenPattern.MatchString(provided) &&
		len(provided) == len(expected) &&
		subtle.ConstantTimeCompare([]byte(provided), []byte(expected)) == 1
}

func newSplunkOpaqueToken() (string, error) {
	token := make([]byte, 32)
	if _, err := rand.Read(token); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(token), nil
}

func (s *splunkExportService) hasValidBrowserToken(token string) bool {
	if !splunkBrowserTokenPattern.MatchString(token) {
		return false
	}
	s.browserMu.Lock()
	defer s.browserMu.Unlock()
	return len(token) == len(s.browserToken) &&
		subtle.ConstantTimeCompare([]byte(token), []byte(s.browserToken)) == 1
}

func (s *splunkExportService) validBrowserTokenFromRequest(r *http.Request) string {
	headerToken := strings.TrimSpace(r.Header.Get(splunkBrowserTokenHeader))
	if s.hasValidBrowserToken(headerToken) {
		return headerToken
	}
	cookieToken := splunkBrowserTokenCookieFromRequest(r)
	if s.hasValidBrowserToken(cookieToken) {
		return cookieToken
	}
	return ""
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
	if !s.hasValidControlToken(r) {
		return false, "", true
	}
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

func (s *splunkExportService) hasPendingRollback() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.rollbackToken != ""
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
	writeJSON(w, s.snapshotLocked())
}

func (s *splunkExportService) refreshConfigurationState() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.mutationsQuiesced.Load() {
		return errSplunkExportQuiesced
	}
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

func (s *splunkExportService) authorizeControlToken(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.controlToken == "" {
			writeSplunkExportError(w, http.StatusServiceUnavailable, "Observer control is not configured")
			return
		}
		if !hasBearerAuthorization(r) {
			writeSplunkExportError(w, http.StatusUnauthorized, "missing Observer control token")
			return
		}
		if !s.hasValidControlToken(r) {
			writeSplunkExportError(w, http.StatusUnauthorized, "invalid Observer control token")
			return
		}
		next(w, r)
	}
}

func (s *splunkExportService) authorizeMutation(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.controlToken == "" {
			writeSplunkExportError(w, http.StatusServiceUnavailable, "Observer control is not configured")
			return
		}
		if s.hasValidControlToken(r) {
			next(w, r)
			return
		}

		browserToken := s.validBrowserTokenFromRequest(r)
		if browserToken == "" {
			message := "missing Observer control token"
			if hasBearerAuthorization(r) {
				message = "invalid Observer control token"
			}
			if strings.TrimSpace(r.Header.Get(splunkBrowserTokenHeader)) != "" ||
				splunkBrowserTokenCookieFromRequest(r) != "" {
				message = "browser cloud control session is not valid"
			}
			writeSplunkExportError(w, http.StatusUnauthorized, message)
			return
		}
		if !isSameOriginLoopbackBrowserRequest(r) {
			writeSplunkExportError(w, http.StatusUnauthorized, "browser cloud control session is not valid")
			return
		}
		next(w, r)
	}
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
		if s.rejectQuiescedMutation(w) {
			return
		}
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

func (s *splunkExportService) serializeShutdownSnapshot(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Seal first so a long-running Connect cannot finish verification and
		// apply while this shutdown request waits for the mutation lock.
		s.mu.Lock()
		s.mutationsQuiesced.Store(true)
		s.mu.Unlock()
		s.mutationMu.Lock()
		defer s.mutationMu.Unlock()
		next(w, r)
	}
}

func (s *splunkExportService) rejectQuiescedMutation(w http.ResponseWriter) bool {
	if !s.mutationsQuiesced.Load() {
		return false
	}
	writeSplunkExportError(w, http.StatusServiceUnavailable, "Observer is shutting down; cloud configuration changes are unavailable.")
	return true
}

func (s *splunkExportService) hasValidControlToken(r *http.Request) bool {
	const bearerPrefix = "Bearer "
	authorization := r.Header.Get("Authorization")
	if !strings.HasPrefix(authorization, bearerPrefix) {
		return false
	}
	provided := strings.TrimSpace(strings.TrimPrefix(authorization, bearerPrefix))
	return len(provided) == len(s.controlToken) &&
		subtle.ConstantTimeCompare([]byte(provided), []byte(s.controlToken)) == 1
}

func hasBearerAuthorization(r *http.Request) bool {
	return strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ")
}

// isSameOriginLoopbackBrowserRequest is the standalone browser CSRF boundary.
// Observer trusts same-user local processes; these checks prevent a remote web
// origin from driving cloud mutations through the loopback HTTP API.
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

func isLoopbackHostname(host string) bool {
	host = strings.Trim(strings.TrimSpace(host), "[]")
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
		Connected: connected,
		Enabled:   connected && metrics.Enabled && traces.Enabled,
		Realm:     realm,
		Version:   s.stateVersionLocked(metricsConfig, tracesConfig),
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
		return "", errors.New("region is not valid")
	}
	return realm, nil
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
