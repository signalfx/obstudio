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
	"time"
	"unicode"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

const (
	maxSplunkExportRequestBytes = 32 * 1024
	maxSplunkAccessTokenBytes   = 4096
	splunkConnectionTestTimeout = 10 * time.Second
	splunkBridgeTokenTTL        = 10 * time.Minute
	splunkBrowserLaunchTokenTTL = 10 * time.Minute
	splunkExportEnvFileSource   = "env-file"
	splunkMetricsOTLPTestPath   = "/v2/datapoint/otlp"
	splunkBrowserRequestHeader  = "X-Obstudio-Browser-Request"
	splunkBrowserTokenHeader    = "X-Obstudio-Browser-Token"
	splunkBrowserSigningKeyEnv  = "OBSTUDIO_CLOUD_BROWSER_SIGNING_KEY"
	splunkBrowserLaunchEnv      = "OBSTUDIO_CLOUD_BROWSER_LAUNCH_TOKEN"
	splunkBrowserTokenVersion   = byte(1)
	splunkBrowserTokenDataBytes = 25
	splunkBrowserTokenBytes     = splunkBrowserTokenDataBytes + sha256.Size
)

var splunkRealmPattern = regexp.MustCompile(`^[a-z]{2,12}[0-9]+$`)
var splunkBridgeTokenPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{24,128}$`)
var splunkBrowserLaunchTokenPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
var splunkBrowserTokenPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{76}$`)
var errSplunkAccessTokenRejected = errors.New("Splunk rejected the access token for this realm.")
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
	metrics           *otlp.SplunkMetricsExportController
	traces            *otlp.SplunkTracesExportController
	refresh           SplunkExportConfigurationRefresher
	verifyConnection  splunkConnectionVerifier
	controlToken      string
	browserSigningKey string
	browserLaunch     string
	browserLaunchEnd  time.Time
	browserLaunchUsed bool
	bridgeTokens      map[string]time.Time
	source            string
	mutationMu        sync.Mutex
	mu                sync.Mutex
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

type splunkExportBrowserSessionRequest struct {
	LaunchToken string `json:"launchToken"`
}

func newSplunkExportService(
	metrics *otlp.SplunkMetricsExportController,
	traces *otlp.SplunkTracesExportController,
	refresh SplunkExportConfigurationRefresher,
) *splunkExportService {
	browserLaunch := strings.TrimSpace(os.Getenv(splunkBrowserLaunchEnv))
	service := &splunkExportService{
		metrics: metrics,
		traces:  traces,
		refresh: refresh,
		verifyConnection: func(ctx context.Context, realm, accessToken string) error {
			return verifySplunkCloudConnection(ctx, splunkConnectionHTTPClient, realm, accessToken)
		},
		controlToken:      strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")),
		browserSigningKey: strings.TrimSpace(os.Getenv(splunkBrowserSigningKeyEnv)),
		browserLaunch:     browserLaunch,
		bridgeTokens:      map[string]time.Time{},
	}
	if browserLaunch != "" {
		service.browserLaunchEnd = time.Now().Add(splunkBrowserLaunchTokenTTL)
	}
	return service
}

func (s *splunkExportService) register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/splunk/export", s.status)
	mux.HandleFunc("POST /api/splunk/export", s.authorizeMutation(s.serializeMutation(s.configure)))
	mux.HandleFunc("POST /api/splunk/export/restore", s.authorizeControlToken(s.serializeMutation(s.restore)))
	mux.HandleFunc("POST /api/splunk/export/browser/session", s.issueBrowserSession)
	mux.HandleFunc("POST /api/splunk/export/bridge", s.authorizeControlToken(s.registerBridgeToken))
	mux.HandleFunc("POST /api/splunk/export/bridge/verify", s.verifyBridgeToken)
	mux.HandleFunc("POST /api/splunk/export/enabled", s.authorizeMutation(s.serializeMutation(s.setEnabled)))
	mux.HandleFunc("POST /api/splunk/export/forget", s.authorizeMutation(s.serializeMutation(s.forget)))
	if s.refresh != nil {
		mux.HandleFunc("POST /api/splunk/export/refresh", s.authorizeControlToken(s.serializeMutation(s.refreshConfiguration)))
	}
}

func (s *splunkExportService) status(w http.ResponseWriter, _ *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()

	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, s.snapshot())
}

func (s *splunkExportService) configure(w http.ResponseWriter, r *http.Request) {
	realm, accessToken, ok := decodeSplunkExportConfiguration(w, r)
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

	s.applyCloudConnection(w, realm, accessToken)
}

func (s *splunkExportService) restore(w http.ResponseWriter, r *http.Request) {
	realm, accessToken, ok := decodeSplunkExportConfiguration(w, r)
	if !ok {
		return
	}
	s.applyCloudConnection(w, realm, accessToken)
}

func decodeSplunkExportConfiguration(w http.ResponseWriter, r *http.Request) (string, string, bool) {
	var request configureSplunkExportRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return "", "", false
	}

	realm, err := validateSplunkRealm(request.Realm)
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return "", "", false
	}
	accessToken, err := validateSplunkAccessToken(request.AccessToken)
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return "", "", false
	}
	return realm, accessToken, true
}

func (s *splunkExportService) applyCloudConnection(w http.ResponseWriter, realm, accessToken string) {
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

func (s *splunkExportService) issueBrowserSession(w http.ResponseWriter, r *http.Request) {
	if s.controlToken == "" {
		writeSplunkExportError(w, http.StatusServiceUnavailable, "Observer control is not configured")
		return
	}
	if s.browserSigningKey == "" {
		writeSplunkExportError(w, http.StatusServiceUnavailable, "standalone browser cloud control is not configured")
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

	now := time.Now()
	providedSession := strings.TrimSpace(r.Header.Get(splunkBrowserTokenHeader))
	authorizedBySession := s.hasValidBrowserToken(providedSession)
	launchToken := strings.TrimSpace(request.LaunchToken)
	authorizedByLaunch := !authorizedBySession &&
		!s.browserLaunchUsed &&
		now.Before(s.browserLaunchEnd) &&
		equalSplunkBrowserLaunchToken(launchToken, s.browserLaunch)
	if !authorizedBySession && !authorizedByLaunch {
		writeSplunkExportError(w, http.StatusUnauthorized, "browser cloud control launch is not valid")
		return
	}
	if s.refresh != nil {
		if err := s.refreshConfigurationState(); err != nil {
			writeSplunkExportError(w, http.StatusBadRequest, err.Error())
			return
		}
	}

	token, err := s.newBrowserToken()
	if err != nil {
		writeSplunkExportError(w, http.StatusInternalServerError, "could not create browser cloud control session")
		return
	}
	if authorizedByLaunch {
		s.browserLaunchUsed = true
	}
	w.Header().Set("Cache-Control", "no-store")
	writeSameOriginJSON(w, map[string]string{"browserToken": token})
}

func equalSplunkBrowserLaunchToken(provided, expected string) bool {
	return splunkBrowserLaunchTokenPattern.MatchString(provided) &&
		len(provided) == len(expected) &&
		subtle.ConstantTimeCompare([]byte(provided), []byte(expected)) == 1
}

func (s *splunkExportService) newBrowserToken() (string, error) {
	key, err := base64.RawURLEncoding.DecodeString(s.browserSigningKey)
	if err != nil || len(key) != 32 {
		return "", errors.New("browser signing key is not valid")
	}
	payload := make([]byte, splunkBrowserTokenDataBytes)
	payload[0] = splunkBrowserTokenVersion
	if _, err := rand.Read(payload[1:]); err != nil {
		return "", err
	}
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write(payload)
	_, _ = mac.Write([]byte{0})
	_, _ = mac.Write([]byte(s.browserLaunch))
	token := append(payload, mac.Sum(nil)...)
	return base64.RawURLEncoding.EncodeToString(token), nil
}

func (s *splunkExportService) hasValidBrowserToken(token string) bool {
	if !splunkBrowserTokenPattern.MatchString(token) {
		return false
	}
	decoded, err := base64.RawURLEncoding.DecodeString(token)
	if err != nil || len(decoded) != splunkBrowserTokenBytes || decoded[0] != splunkBrowserTokenVersion {
		return false
	}
	key, err := base64.RawURLEncoding.DecodeString(s.browserSigningKey)
	if err != nil || len(key) != 32 {
		return false
	}
	payload := decoded[:splunkBrowserTokenDataBytes]
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write(payload)
	_, _ = mac.Write([]byte{0})
	_, _ = mac.Write([]byte(s.browserLaunch))
	if !hmac.Equal(decoded[splunkBrowserTokenDataBytes:], mac.Sum(nil)) {
		return false
	}
	return true
}

func (s *splunkExportService) pruneBridgeTokens(now time.Time) {
	for token, expiresAt := range s.bridgeTokens {
		if !expiresAt.After(now) {
			delete(s.bridgeTokens, token)
		}
	}
}

func (s *splunkExportService) refreshConfiguration(w http.ResponseWriter, _ *http.Request) {
	if err := s.refreshConfigurationState(); err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, err.Error())
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	writeJSON(w, s.snapshot())
}

func (s *splunkExportService) refreshConfigurationState() error {
	s.mu.Lock()
	defer s.mu.Unlock()

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

		browserToken := strings.TrimSpace(r.Header.Get(splunkBrowserTokenHeader))
		if browserToken == "" {
			message := "missing Observer control token"
			if hasBearerAuthorization(r) {
				message = "invalid Observer control token"
			}
			writeSplunkExportError(w, http.StatusUnauthorized, message)
			return
		}
		if !isSameOriginLoopbackBrowserRequest(r) {
			writeSplunkExportError(w, http.StatusUnauthorized, "browser cloud control session is not valid")
			return
		}
		if !s.hasValidBrowserToken(browserToken) {
			writeSplunkExportError(w, http.StatusUnauthorized, "browser cloud control session is not valid")
			return
		}
		renewedToken, err := s.newBrowserToken()
		if err != nil {
			writeSplunkExportError(w, http.StatusInternalServerError, "could not renew browser cloud control session")
			return
		}
		w.Header().Set(splunkBrowserTokenHeader, renewedToken)

		next(w, r)
	}
}

func (s *splunkExportService) serializeMutation(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !s.mutationMu.TryLock() {
			writeSplunkExportError(w, http.StatusConflict, "A cloud configuration change is already in progress.")
			return
		}
		defer s.mutationMu.Unlock()
		next(w, r)
	}
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
