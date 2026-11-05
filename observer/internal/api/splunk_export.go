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
	"runtime"
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
// source after another local client saves a connection.
type SplunkExportConfigurationRefresher func() error

// registrationAndAuthProtocol selects which MCP client registration/auth
// strategy the Cloud tab exposes. Exactly one of these -- or none -- is
// active at a time; see docs/o11y-oauth-mcp-gateway-impact.md §5.
type registrationAndAuthProtocol string

const (
	registrationAndAuthProtocolNone      registrationAndAuthProtocol = "NONE"
	registrationAndAuthProtocolCIMD      registrationAndAuthProtocol = "CIMD"
	registrationAndAuthProtocolO11yOAuth registrationAndAuthProtocol = "O11Y_OAUTH"
)

// parseRegistrationAndAuthProtocol defaults an empty or unrecognized value to
// "NONE" rather than erroring -- this flag only ever reveals a PoC control,
// so a typo'd env var should disable it, not crash startup.
func parseRegistrationAndAuthProtocol(raw string) registrationAndAuthProtocol {
	switch registrationAndAuthProtocol(strings.ToUpper(strings.TrimSpace(raw))) {
	case registrationAndAuthProtocolCIMD:
		return registrationAndAuthProtocolCIMD
	case registrationAndAuthProtocolO11yOAuth:
		return registrationAndAuthProtocolO11yOAuth
	default:
		return registrationAndAuthProtocolNone
	}
}

type splunkExportService struct {
	sessionOnly                   bool
	metrics                       *otlp.SplunkMetricsExportController
	traces                        *otlp.SplunkTracesExportController
	logs                          SplunkLogsSettings
	saveConnection                SplunkCloudSettingsSaver
	savePreferences               SplunkCloudPreferencesSaver
	storageManaged                SplunkCloudStorageManaged
	cleanupPending                SplunkCloudCleanupPending
	refresh                       SplunkExportConfigurationRefresher
	verifyConnection              splunkConnectionVerifier
	resolveRealmClient            *http.Client
	agentObservabilityProxyClient *http.Client
	rollbackSessionOnly           bool
	rollbackToken                 string
	rollbackMetrics               otlp.SplunkMetricsExporterConfig
	rollbackChanged               bool
	rollbackTraces                otlp.SplunkTracesExporterConfig
	registrationAndAuthProtocol   registrationAndAuthProtocol
	configurationChanged          bool
	stateVersionKey               [32]byte
	mutationMu                    sync.Mutex
	agentResourceMu               sync.Mutex
	mu                            sync.Mutex
}

// ErrConnectionCleanupPending means saved settings must be applied before reporting cleanup failure.
var ErrConnectionCleanupPending = errors.New("connection settings were saved; credential cleanup is pending, unlock the system credential store and retry")

var ErrConnectionSettingsChanged = errors.New("Connection settings changed in another session. Refresh or restart Studio, then retry.")

var ErrCredentialStorageUnavailable = errors.New("Secure storage is unavailable. Use this token in memory until Studio stops, or restore secure storage and retry.")

var errSplunkCloudSecureSave = errors.New("could not save the connection; check that secure credential storage is unlocked and the settings file is writable")

type SplunkCloudStorageManaged func() bool
type SplunkCloudCleanupPending func() bool

type SplunkCloudSettingsSaver func(otlp.SplunkMetricsExporterConfig, otlp.SplunkTracesExporterConfig) error
type SplunkCloudPreferencesSaver SplunkCloudSettingsSaver

type splunkExportSignalStatus struct {
	Configured      bool        `json:"configured"`
	Enabled         bool        `json:"enabled"`
	ExportedBatches uint64      `json:"exportedBatches"`
	ExportedItems   uint64      `json:"exportedItems"`
	FailedBatches   uint64      `json:"failedBatches"`
	LastExport      interface{} `json:"lastExport,omitempty"`
}

type splunkExportStatusResponse struct {
	SessionOnly                 bool                      `json:"sessionOnly,omitempty"`
	CleanupPending              bool                      `json:"cleanupPending,omitempty"`
	StorageManaged              bool                      `json:"storageManaged"`
	Connected                   bool                      `json:"connected"`
	Enabled                     bool                      `json:"enabled"`
	Realm                       string                    `json:"realm,omitempty"`
	RollbackToken               string                    `json:"rollbackToken,omitempty"`
	Version                     string                    `json:"version"`
	CloudVersion                string                    `json:"cloudVersion"`
	Metrics                     splunkExportSignalStatus  `json:"metrics"`
	Traces                      splunkExportSignalStatus  `json:"traces"`
	Logs                        *splunkExportSignalStatus `json:"logs,omitempty"`
	RegistrationAndAuthProtocol string                    `json:"registrationAndAuthProtocol"`
}

type configureSplunkExportRequest struct {
	SessionOnly     bool   `json:"sessionOnly,omitempty"`
	Enabled         *bool  `json:"enabled,omitempty"`
	Realm           string `json:"realm"`
	AccessToken     string `json:"accessToken"`
	ExpectedVersion string `json:"expectedVersion,omitempty"`
	ReuseSavedToken bool   `json:"reuseSavedToken,omitempty"`
	PreserveEnabled bool   `json:"preserveEnabled,omitempty"`
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
		resolveRealmClient:            splunkRealmHTTPClient,
		agentObservabilityProxyClient: newAgentObservabilityProxyHTTPClient(),
		// Single source of truth for both launch paths (standalone `go run
		// ./cmd/obstudio` + browser dev, and the VS Code extension): the extension
		// reads this same env var directly rather than keeping an independent VS
		registrationAndAuthProtocol: parseRegistrationAndAuthProtocol(os.Getenv("OBSTUDIO_REGISTRATION_AND_AUTH_PROTOCOL")),
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

func (s *splunkExportService) register(mux *http.ServeMux) {
	s.registerAgentObservabilitySDKAuth(mux)
	s.registerAgentObservabilityProxy(mux)
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
	writeSameOriginJSON(w, s.snapshot())
}

func (s *splunkExportService) configure(w http.ResponseWriter, r *http.Request) {
	request, ok := s.decodeSplunkExportConfiguration(w, r)
	if !ok {
		return
	}
	if !s.acceptExpectedVersion(w, request.ExpectedVersion) {
		return
	}
	issueRollback, requestedRollbackToken, ok := s.rollbackRequest(w, r)
	if !ok {
		return
	}

	verificationContext, cancelVerification := context.WithTimeout(r.Context(), splunkConnectionTestTimeout)
	err := s.verifyConnection(verificationContext, request.Realm, request.AccessToken)
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
	s.applyCloudConnection(w, request.Realm, request.AccessToken, issueRollback, requestedRollbackToken, request.PreserveEnabled, request.Enabled, request.SessionOnly)
}

func (s *splunkExportService) decodeSplunkExportConfiguration(w http.ResponseWriter, r *http.Request) (configureSplunkExportRequest, bool) {
	var request configureSplunkExportRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return request, false
	}

	realm, err := validateSplunkRealm(request.Realm)
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return request, false
	}
	if request.PreserveEnabled && request.ExpectedVersion == "" {
		writeSplunkExportError(w, http.StatusBadRequest, "Editing a connection requires its current version.")
		return request, false
	}
	if request.ReuseSavedToken {
		if request.AccessToken != "" || request.ExpectedVersion == "" {
			writeSplunkExportError(w, http.StatusBadRequest, "Saved-token reuse requires an empty token and the current connection version.")
			return request, false
		}
		s.mu.Lock()
		metrics, traces := s.metrics.Config(), s.traces.Config()
		s.mu.Unlock()
		if realm != metrics.Realm || realm != traces.Realm || metrics.Endpoint != "" || traces.Endpoint != "" || metrics.AccessToken == "" || metrics.AccessToken != traces.AccessToken {
			writeSplunkExportError(w, http.StatusBadRequest, "A new realm needs a token issued for it.")
			return request, false
		}
		request.AccessToken = metrics.AccessToken
	}
	accessToken, err := validateSplunkAccessToken(request.AccessToken)
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return request, false
	}
	request.Realm, request.AccessToken = realm, accessToken
	return request, true
}

func (s *splunkExportService) applyCloudConnection(
	w http.ResponseWriter,
	realm string,
	accessToken string,
	issueRollback bool,
	requestedRollbackToken string,
	preserveEnabled bool,
	initialEnabled *bool,
	sessionOnly bool,
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

	metricsEnabled, tracesEnabled := preserveEnabled && previousMetrics.Enabled, preserveEnabled && previousTraces.Enabled
	if initialEnabled != nil && !preserveEnabled {
		metricsEnabled, tracesEnabled = *initialEnabled, *initialEnabled
	}
	save := s.saveConnection
	if sessionOnly {
		save = nil
	}
	if err := s.applyConnection(
		otlp.SplunkMetricsExporterConfig{Realm: realm, AccessToken: accessToken, Enabled: metricsEnabled},
		otlp.SplunkTracesExporterConfig{Realm: realm, AccessToken: accessToken, Enabled: tracesEnabled},
		preserveEnabled, save,
	); err != nil {
		if errors.Is(err, ErrConnectionCleanupPending) {
			s.sessionOnly = sessionOnly
		}
		if rollbackToken != "" && !errors.Is(err, ErrConnectionCleanupPending) {
			if rollbackErr := s.apply(previousMetrics, previousTraces); rollbackErr == nil {
				s.clearRollbackLocked()
			}
		}
		writeSplunkCloudMutationError(w, err, "could not configure Splunk Observability Cloud export")
		return
	}
	s.sessionOnly = sessionOnly
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
	previousChanged := s.rollbackChanged
	var rollbackErr error
	if s.sessionOnly || s.rollbackSessionOnly {
		rollbackErr = s.applyConnection(s.rollbackMetrics, s.rollbackTraces, false, nil)
	} else {
		rollbackErr = s.apply(s.rollbackMetrics, s.rollbackTraces)
	}
	if err := rollbackErr; err != nil {
		if errors.Is(err, ErrConnectionCleanupPending) {
			s.configurationChanged = previousChanged
		}
		writeSplunkCloudMutationError(w, err, "could not roll back Splunk Observability Cloud export")
		return
	}
	s.sessionOnly = s.rollbackSessionOnly
	s.configurationChanged = previousChanged
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
	if !enabled && s.saveConnection != nil && (metricsConfig.AccessToken == "" || tracesConfig.AccessToken == "") {
		writeSplunkExportError(w, http.StatusConflict, "Reconnect the saved connection before changing export state.")
		return
	}
	cloudConnected := sameSplunkCloudRealm(
		metricsConfig.Realm,
		metricsConfig.AccessToken,
		metricsConfig.Endpoint != "",
		tracesConfig.Realm,
		tracesConfig.AccessToken,
		tracesConfig.Endpoint != "",
	)
	if enabled && !cloudConnected {
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
	savePreference := s.saveConnection
	if s.savePreferences != nil {
		savePreference = SplunkCloudSettingsSaver(s.savePreferences)
	}
	if s.sessionOnly {
		savePreference = nil
	}
	if err := s.applyConnection(metricsConfig, tracesConfig, true, savePreference); err != nil {
		writeSplunkCloudMutationError(w, err, "could not update Splunk Observability Cloud export")
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
	rollbackToken, err := s.beginRollbackLocked(issueRollback, requestedRollbackToken)
	if err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not create cloud rollback capability")
		return
	}
	if err := s.apply(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
		writeSplunkCloudMutationError(w, err, "could not remove Splunk Observability Cloud connection")
		return
	}
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
	s.rollbackSessionOnly = s.sessionOnly
	s.rollbackChanged = s.configurationChanged
	s.rollbackMetrics = s.metrics.Config()
	s.rollbackTraces = s.traces.Config()
	return token, nil
}

func (s *splunkExportService) clearRollbackLocked() {
	s.rollbackSessionOnly = false
	s.rollbackToken = ""
	s.rollbackChanged = false
	s.rollbackMetrics = otlp.SplunkMetricsExporterConfig{}
	s.rollbackTraces = otlp.SplunkTracesExporterConfig{}
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

	if s.sessionOnly {
		return nil
	}
	return s.refresh()
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
	save := s.saveConnection
	if s.sessionOnly {
		save = nil
	}
	return s.applyConnection(metricsConfig, tracesConfig, false, save)
}

func (s *splunkExportService) applyConnection(metricsConfig otlp.SplunkMetricsExporterConfig, tracesConfig otlp.SplunkTracesExporterConfig, keepActivity bool, save SplunkCloudSettingsSaver) error {
	configureMetrics, configureTraces := s.metrics.Configure, s.traces.Configure
	if keepActivity {
		configureMetrics, configureTraces = s.metrics.ConfigureKeepingActivity, s.traces.ConfigureKeepingActivity
	}
	previousMetrics := s.metrics.Config()
	previousTraces := s.traces.Config()
	var cleanupErr error
	if save != nil {
		if err := save(metricsConfig, tracesConfig); errors.Is(err, ErrConnectionCleanupPending) {
			cleanupErr = ErrConnectionCleanupPending
		} else if err != nil {
			if errors.Is(err, ErrConnectionSettingsChanged) || errors.Is(err, ErrCredentialStorageUnavailable) {
				return err
			}
			return errSplunkCloudSecureSave
		}
	}
	restoreSaved := func(err error) error {
		if save != nil {
			if saveErr := save(previousMetrics, previousTraces); saveErr != nil {
				return errors.New("could not apply connection or restore saved settings")
			}
		}
		return err
	}
	if err := configureMetrics(metricsConfig); err != nil {
		return restoreSaved(err)
	}
	if err := configureTraces(tracesConfig); err != nil {
		if rollbackErr := configureMetrics(previousMetrics); rollbackErr != nil {
			return restoreSaved(fmt.Errorf("configure traces: %w; rollback metrics: %v", err, rollbackErr))
		}
		return restoreSaved(err)
	}
	if save != nil {
		s.configurationChanged = true
	}
	if cleanupErr != nil {
		s.clearRollbackLocked()
	}
	return cleanupErr
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

	status := splunkExportStatusResponse{
		SessionOnly:                 s.sessionOnly,
		StorageManaged:              s.storageManaged != nil && s.storageManaged(),
		CleanupPending:              s.cleanupPending != nil && s.cleanupPending(),
		Connected:                   connected,
		Enabled:                     connected && metrics.Enabled && traces.Enabled,
		Realm:                       realm,
		Version:                     s.stateVersionLocked(metricsConfig, tracesConfig),
		CloudVersion:                s.configurationVersionLocked(metricsConfig, tracesConfig, nil),
		RegistrationAndAuthProtocol: string(s.registrationAndAuthProtocol),
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
	if s.logs.Controller != nil {
		logs := s.logs.Controller.Status()
		status.Logs = &splunkExportSignalStatus{
			Configured: logs.Configured, Enabled: logs.Enabled,
			ExportedBatches: logs.ExportedBatches, ExportedItems: logs.ExportedRecords,
			FailedBatches: logs.FailedBatches,
		}
		if logs.LastExportError != "" || logs.LastExportSuccess != "" {
			status.Logs.LastExport = map[string]any{"success": logs.LastExportError == "", "error": logs.LastExportError, "time": logs.LastExportSuccess}
		}
	}
	return status
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
	cloud := s.configurationVersionLocked(s.metrics.Config(), s.traces.Config(), nil)
	s.mu.Unlock()
	if subtle.ConstantTimeCompare([]byte(expected), []byte(current)) != 1 && subtle.ConstantTimeCompare([]byte(expected), []byte(cloud)) != 1 {
		writeSplunkExportError(
			w,
			http.StatusConflict,
			"Cloud configuration changed in another session. Refresh and try again.",
		)
		return false
	}
	return true
}

func (s *splunkExportService) stateVersionLocked(
	metrics otlp.SplunkMetricsExporterConfig,
	traces otlp.SplunkTracesExporterConfig,
) string {
	var logs *otlp.SplunkHECLogsExporterConfig
	if s.logs.Controller != nil {
		config := s.logs.Controller.Config()
		logs = &config
	}
	return s.configurationVersionLocked(metrics, traces, logs)
}

func (s *splunkExportService) configurationVersionLocked(
	metrics otlp.SplunkMetricsExporterConfig,
	traces otlp.SplunkTracesExporterConfig,
	logs *otlp.SplunkHECLogsExporterConfig,
) string {
	state, err := json.Marshal(struct {
		SessionOnly bool                              `json:"sessionOnly,omitempty"`
		Metrics     otlp.SplunkMetricsExporterConfig  `json:"metrics"`
		Traces      otlp.SplunkTracesExporterConfig   `json:"traces"`
		Logs        *otlp.SplunkHECLogsExporterConfig `json:"logs,omitempty"`
	}{
		SessionOnly: s.sessionOnly,
		Metrics:     metrics,
		Traces:      traces,
		Logs:        logs,
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

func writeSplunkCloudMutationError(w http.ResponseWriter, err error, fallback string) {
	if errors.Is(err, ErrCredentialStorageUnavailable) {
		writeCredentialStorageUnavailable(w)
		return
	}
	if errors.Is(err, ErrConnectionSettingsChanged) {
		writeSplunkExportError(w, http.StatusConflict, ErrConnectionSettingsChanged.Error())
	} else if errors.Is(err, ErrConnectionCleanupPending) {
		writeSplunkExportError(w, http.StatusInternalServerError, ErrConnectionCleanupPending.Error())
	} else if errors.Is(err, errSplunkCloudSecureSave) {
		writeSplunkExportError(w, http.StatusInternalServerError, errSplunkCloudSecureSave.Error())
	} else {
		writeSplunkExportError(w, http.StatusInternalServerError, fallback)
	}
}

func writeSplunkExportError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": message})
}

func writeCredentialStorageUnavailable(w http.ResponseWriter) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusServiceUnavailable)
	_ = json.NewEncoder(w).Encode(map[string]any{"error": ErrCredentialStorageUnavailable.Error(), "code": "credential_storage_unavailable", "retrySafe": true, "platform": runtime.GOOS})
}
