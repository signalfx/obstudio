package api

// Step 2 of the O11y-OAuth-for-MCP-Gateway integration: user authorization / token
// exchange. See docs/o11y-oauth-mcp-gateway-impact.md §9. This mirrors the shape of
// sis_cimd_login.go (state machine, fixed loopback callback listener, generation-based
// stale-result handling) but is intentionally a separate implementation, not a shared
// refactor: the client here is an opaque admin-registered clientId/clientSecret pair
// (confidential client, Basic auth at the token endpoint) rather than a CIMD metadata-doc
// URL, and realm/orgId/clientId/clientSecret are supplied per request rather than read
// from environment variables, since there is no single global client for this flow (every
// customer org registers its own). The resulting O11y access token is held only in this
// process's memory (globalO11yOAuthLoginState below); it is never written to disk, never
// returned to the browser, and is lost on restart.

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	o11yOAuthLoginTimeout = 5 * time.Minute
	// o11yOAuthScope and o11yOAuthIDPLabel come from the confirmed lab0 reference flow,
	// not a published spec -- idp_label is a non-standard authorize parameter the O11y
	// OAuth server requires. See docs/o11y-oauth-mcp-gateway-impact.md §9.
	o11yOAuthScope       = "openid email groups offline_access"
	o11yOAuthIDPLabel    = "o11y"
	o11yOAuthMaxOrgIDLen = 64
)

// resolveO11yOAuthIssuer and resolveO11yOAuthExchangeURL default to the host pattern
// confirmed against the lab0 realm, but that pattern is explicitly not guaranteed to hold
// for every realm or to stay stable over time -- the override env vars below let either
// URL be replaced wholesale (with {realm}/{orgId} substituted in) rather than assuming the
// derivation always applies.
func resolveO11yOAuthIssuer(realm, orgID string) string {
	if override := strings.TrimSpace(os.Getenv("OBSTUDIO_O11Y_OAUTH_ISSUER_URL")); override != "" {
		return expandO11yOAuthURLTemplate(override, realm, orgID)
	}
	return fmt.Sprintf("https://api.%s.signalfx.com/%s/sis/v1/rg/%s", realm, realm, orgID)
}

func resolveO11yOAuthExchangeURL(realm string) string {
	if override := strings.TrimSpace(os.Getenv("OBSTUDIO_O11Y_OAUTH_EXCHANGE_URL")); override != "" {
		return expandO11yOAuthURLTemplate(override, realm, "")
	}
	return fmt.Sprintf("https://internal-identity-api.%s.signalfx.com/v2/sis-integration/_/o11y-access-token", realm)
}

// resolveO11yOAuthScope returns the space-separated scopes to request. The lab0 server
// rejected "profile" for a freshly registered client (its discovery document lists only
// openid, email, groups, offline_access, fedtype), so the default is limited to scopes it
// advertises. OBSTUDIO_O11Y_OAUTH_SCOPE overrides it without a rebuild.
func resolveO11yOAuthScope() string {
	if override := strings.TrimSpace(os.Getenv("OBSTUDIO_O11Y_OAUTH_SCOPE")); override != "" {
		return override
	}
	return o11yOAuthScope
}

func expandO11yOAuthURLTemplate(template, realm, orgID string) string {
	expanded := strings.ReplaceAll(template, "{realm}", realm)
	return strings.ReplaceAll(expanded, "{orgId}", orgID)
}

func validateO11yOAuthOrgID(value string) (string, error) {
	orgID := strings.TrimSpace(value)
	if orgID == "" || len(orgID) > o11yOAuthMaxOrgIDLen {
		return "", errors.New("org ID is required")
	}
	for _, r := range orgID {
		if !(r == '_' || r == '-' ||
			(r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9')) {
			return "", errors.New("org ID contains invalid characters")
		}
	}
	return orgID, nil
}

type o11yOAuthLoginRequest struct {
	Realm        string `json:"realm"`
	OrgID        string `json:"orgId"`
	ClientID     string `json:"clientId"`
	ClientSecret string `json:"clientSecret"`
}

// o11yOAuthDiscoveryDocument intentionally validates less strictly than
// sisCIMDDiscoveryDocument: the host/path pattern for the real O11y OAuth server is not
// guaranteed to stay fixed, so this trusts the discovered authorization_endpoint and
// token_endpoint themselves (after basic scheme/shape checks) rather than requiring them
// to match a hardcoded path suffix.
type o11yOAuthDiscoveryDocument struct {
	Issuer                        string   `json:"issuer"`
	AuthorizationEndpoint         string   `json:"authorization_endpoint"`
	TokenEndpoint                 string   `json:"token_endpoint"`
	CodeChallengeMethodsSupported []string `json:"code_challenge_methods_supported"`
}

func resolveO11yOAuthDiscovery(client *http.Client, issuer string) (*o11yOAuthDiscoveryDocument, error) {
	discoveryURL := strings.TrimSuffix(issuer, "/") + "/.well-known/openid-configuration"
	response, err := sisCIMDGet(client, discoveryURL)
	if err != nil {
		return nil, fmt.Errorf("fetch O11y OAuth discovery document: %w", err)
	}
	var discovery o11yOAuthDiscoveryDocument
	if err := sisCIMDDecodeJSON(response, &discovery); err != nil {
		return nil, fmt.Errorf("O11y OAuth discovery document: %w", err)
	}
	if err := validateO11yOAuthDiscoveryDocument(discovery, issuer); err != nil {
		return nil, err
	}
	return &discovery, nil
}

func validateO11yOAuthDiscoveryDocument(discovery o11yOAuthDiscoveryDocument, issuer string) error {
	if discovery.Issuer != issuer {
		return errors.New("O11y OAuth discovery issuer did not match the configured issuer")
	}
	// validateSISCIMDOAuthEndpoint is generic (absolute URL, HTTPS or loopback HTTP, no
	// userinfo/fragment) despite its name -- reused as-is rather than duplicated.
	if err := validateSISCIMDOAuthEndpoint(discovery.AuthorizationEndpoint, "authorization_endpoint"); err != nil {
		return err
	}
	if err := validateSISCIMDOAuthEndpoint(discovery.TokenEndpoint, "token_endpoint"); err != nil {
		return err
	}
	if !sisCIMDContains(discovery.CodeChallengeMethodsSupported, "S256") {
		return errors.New(`O11y OAuth discovery does not support PKCE method "S256"`)
	}
	return nil
}

// buildO11yOAuthAuthorizationURL returns the PKCE authorization URL along with the state
// and verifier the caller must retain through the callback and token exchange.
func buildO11yOAuthAuthorizationURL(authorizationEndpoint, clientID string) (authorizationURL, state, verifier string, err error) {
	endpoint, err := url.Parse(authorizationEndpoint)
	if err != nil {
		return "", "", "", fmt.Errorf("O11y OAuth discovery authorization_endpoint is invalid: %w", err)
	}
	verifier, err = sisCIMDRandomBase64URL(64)
	if err != nil {
		return "", "", "", fmt.Errorf("generate PKCE verifier: %w", err)
	}
	state, err = sisCIMDRandomBase64URL(32)
	if err != nil {
		return "", "", "", fmt.Errorf("generate OAuth state: %w", err)
	}
	challenge := sisCIMDCodeChallengeS256(verifier)

	query := endpoint.Query()
	query.Set("response_type", "code")
	query.Set("client_id", clientID)
	query.Set("redirect_uri", o11yOAuthRegistrationCallbackURL)
	query.Set("scope", resolveO11yOAuthScope())
	query.Set("state", state)
	query.Set("code_challenge", challenge)
	query.Set("code_challenge_method", "S256")
	query.Set("idp_label", o11yOAuthIDPLabel)
	endpoint.RawQuery = query.Encode()
	return endpoint.String(), state, verifier, nil
}

// o11yOAuthLoginPhase is exposed to the browser; the token itself never is.
type o11yOAuthLoginPhase string

const (
	o11yOAuthLoginPhaseDisconnected o11yOAuthLoginPhase = "disconnected"
	o11yOAuthLoginPhasePending      o11yOAuthLoginPhase = "pending"
	o11yOAuthLoginPhaseConnected    o11yOAuthLoginPhase = "connected"
	o11yOAuthLoginPhaseError        o11yOAuthLoginPhase = "error"
)

// o11yOAuthSession holds the O11y access token obtained from the second exchange hop
// (never the SIS token from the first hop, which is discarded immediately after use --
// see exchangeO11yOAuthAuthorizationCode).
type o11yOAuthSession struct {
	accessToken string
	issuer      string
	clientID    string
	realm       string
	orgID       string
	connectedAt time.Time
	expiresAt   time.Time
}

// o11yOAuthLoginState is process-wide, in-memory-only session state -- same shape and
// same rationale as sisCIMDLoginState, but a distinct instance: these two sign-in
// strategies are mutually exclusive in practice (OBSTUDIO_REGISTRATION_AND_AUTH_PROTOCOL
// selects one), but kept as cleanly separable state and code, matching how CIMD and
// O11Y_OAUTH registration are already two independent implementations.
type o11yOAuthLoginState struct {
	mu         sync.Mutex
	phase      o11yOAuthLoginPhase
	session    *o11yOAuthSession
	errorMsg   string
	cancelFunc func()
	generation uint64
}

var globalO11yOAuthLoginState = &o11yOAuthLoginState{phase: o11yOAuthLoginPhaseDisconnected}

type o11yOAuthLoginStartResult struct {
	AuthorizationURL string `json:"authorizationUrl"`
}

type o11yOAuthSessionStatus struct {
	Phase       o11yOAuthLoginPhase `json:"phase"`
	Error       string              `json:"error,omitempty"`
	Issuer      string              `json:"issuer,omitempty"`
	Realm       string              `json:"realm,omitempty"`
	OrgID       string              `json:"orgId,omitempty"`
	ConnectedAt string              `json:"connectedAt,omitempty"`
	ExpiresAt   string              `json:"expiresAt,omitempty"`
}

func (s *o11yOAuthLoginState) status() o11yOAuthSessionStatus {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.phase == o11yOAuthLoginPhaseConnected && s.session != nil && !s.session.expiresAt.After(time.Now()) {
		s.phase = o11yOAuthLoginPhaseDisconnected
		s.session = nil
	}
	status := o11yOAuthSessionStatus{Phase: s.phase, Error: s.errorMsg}
	if s.session != nil {
		status.Issuer = s.session.issuer
		status.Realm = s.session.realm
		status.OrgID = s.session.orgID
		status.ConnectedAt = s.session.connectedAt.UTC().Format(time.RFC3339)
		status.ExpiresAt = s.session.expiresAt.UTC().Format(time.RFC3339)
	}
	return status
}

func (s *o11yOAuthLoginState) disconnect() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.generation++
	if s.cancelFunc != nil {
		s.cancelFunc()
	}
	s.phase = o11yOAuthLoginPhaseDisconnected
	s.session = nil
	s.errorMsg = ""
	s.cancelFunc = nil
}

func (s *o11yOAuthLoginState) beginPending(cancelFunc func()) (uint64, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.phase == o11yOAuthLoginPhasePending {
		return 0, false
	}
	s.generation++
	s.phase = o11yOAuthLoginPhasePending
	s.session = nil
	s.errorMsg = ""
	s.cancelFunc = cancelFunc
	return s.generation, true
}

func (s *o11yOAuthLoginState) succeed(generation uint64, session *o11yOAuthSession) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if generation != s.generation {
		return
	}
	s.phase = o11yOAuthLoginPhaseConnected
	s.session = session
	s.errorMsg = ""
	s.cancelFunc = nil
}

func (s *o11yOAuthLoginState) fail(generation uint64, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if generation != s.generation {
		return
	}
	s.phase = o11yOAuthLoginPhaseError
	s.session = nil
	s.errorMsg = err.Error()
	s.cancelFunc = nil
}

// o11yOAuthExchangeConfig bundles what the callback listener and token exchange need,
// since (unlike CIMD) these come from the per-request login payload, not environment
// variables -- there is no single global client for this flow.
type o11yOAuthExchangeConfig struct {
	realm         string
	orgID         string
	clientID      string
	clientSecret  string
	issuer        string
	tokenEndpoint string
	exchangeURL   string
}

// startO11yOAuthLoginHandler resolves discovery for the given realm/orgId, opens the
// fixed loopback callback listener (shared with CIMD's; the two flows are mutually
// exclusive via OBSTUDIO_REGISTRATION_AND_AUTH_PROTOCOL), and returns the authorization
// URL for the browser to open. The actual code exchange happens in the background; poll
// o11yOAuthSessionStatusHandler for the result.
func startO11yOAuthLoginHandler(w http.ResponseWriter, r *http.Request) {
	var request o11yOAuthLoginRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeO11yOAuthRegistrationError(w, http.StatusBadRequest, err.Error())
		return
	}
	realm, err := validateSplunkRealm(request.Realm)
	if err != nil {
		writeO11yOAuthRegistrationError(w, http.StatusBadRequest, "enter a valid Splunk Observability Cloud realm")
		return
	}
	orgID, err := validateO11yOAuthOrgID(request.OrgID)
	if err != nil {
		writeO11yOAuthRegistrationError(w, http.StatusBadRequest, "enter the O11y organization ID")
		return
	}
	clientID := strings.TrimSpace(request.ClientID)
	if clientID == "" {
		writeO11yOAuthRegistrationError(w, http.StatusBadRequest, "paste the client ID from your O11y OAuth registration")
		return
	}
	clientSecret := strings.TrimSpace(request.ClientSecret)
	if clientSecret == "" {
		writeO11yOAuthRegistrationError(w, http.StatusBadRequest, "paste the client secret from your O11y OAuth registration")
		return
	}

	client := &http.Client{Timeout: o11yOAuthRequestTimeout}
	issuer := resolveO11yOAuthIssuer(realm, orgID)
	discovery, err := resolveO11yOAuthDiscovery(client, issuer)
	if err != nil {
		writeO11yOAuthRegistrationError(w, http.StatusBadGateway, err.Error())
		return
	}

	authorizationURL, state, verifier, err := buildO11yOAuthAuthorizationURL(discovery.AuthorizationEndpoint, clientID)
	if err != nil {
		writeO11yOAuthRegistrationError(w, http.StatusBadGateway, err.Error())
		return
	}

	exchangeConfig := o11yOAuthExchangeConfig{
		realm:         realm,
		orgID:         orgID,
		clientID:      clientID,
		clientSecret:  clientSecret,
		issuer:        discovery.Issuer,
		tokenEndpoint: discovery.TokenEndpoint,
		exchangeURL:   resolveO11yOAuthExchangeURL(realm),
	}

	listener, err := startO11yOAuthCallbackListener(state, client, discovery.Issuer, verifier, exchangeConfig)
	if err != nil {
		writeO11yOAuthRegistrationError(w, http.StatusConflict, err.Error())
		return
	}
	generation, ok := globalO11yOAuthLoginState.beginPending(listener.cancel)
	if !ok {
		_ = listener.close()
		writeO11yOAuthRegistrationError(w, http.StatusConflict, "an O11y OAuth sign-in is already in progress")
		return
	}
	listener.run(generation)

	writeSameOriginJSON(w, o11yOAuthLoginStartResult{AuthorizationURL: authorizationURL})
}

func o11yOAuthSessionStatusHandler(w http.ResponseWriter, _ *http.Request) {
	writeSameOriginJSON(w, globalO11yOAuthLoginState.status())
}

func disconnectO11yOAuthSessionHandler(w http.ResponseWriter, _ *http.Request) {
	globalO11yOAuthLoginState.disconnect()
	writeSameOriginJSON(w, globalO11yOAuthLoginState.status())
}

type o11yOAuthCallbackListener struct {
	server *http.Server
	cancel func()
	close  func() error
	run    func(generation uint64)
}

// startO11yOAuthCallbackListener mirrors startSISCIMDCallbackListener's state/claim/
// timeout/drain logic exactly (see that function for the rationale behind each check) but
// targets globalO11yOAuthLoginState and exchangeO11yOAuthAuthorizationCode instead.
func startO11yOAuthCallbackListener(
	expectedState string,
	client *http.Client,
	expectedIssuer string,
	verifier string,
	exchangeConfig o11yOAuthExchangeConfig,
) (*o11yOAuthCallbackListener, error) {
	mux := http.NewServeMux()
	server := &http.Server{Handler: mux}

	type callbackResult struct {
		session *o11yOAuthSession
		err     error
	}
	resultCh := make(chan callbackResult, 1)
	var settled sync.Once
	var claimed atomic.Bool
	attemptCtx, cancelAttempt := context.WithCancel(context.Background())

	mux.HandleFunc("GET /callback", func(w http.ResponseWriter, r *http.Request) {
		writeSISCIMDCallbackHeaders(w)
		query := r.URL.Query()
		if query.Get("state") != expectedState {
			writeSISCIMDCallbackPage(w, http.StatusBadRequest, "Sign-in could not be verified", "Return to Splunk Observability Studio and try again.")
			return
		}
		if oauthError := query.Get("error"); oauthError != "" {
			writeSISCIMDCallbackPage(w, http.StatusBadRequest, "Sign-in was not completed", "Return to Splunk Observability Studio and try again.")
			safeError := "unknown_error"
			if isSISCIMDSafeErrorCode(oauthError) {
				safeError = oauthError
			}
			settled.Do(func() { resultCh <- callbackResult{err: fmt.Errorf("O11y OAuth authorization failed (%s)", safeError)} })
			return
		}
		if callbackIssuer := query.Get("iss"); callbackIssuer != "" && callbackIssuer != expectedIssuer {
			writeSISCIMDCallbackPage(w, http.StatusBadRequest, "Sign-in could not be verified", "Return to Splunk Observability Studio and try again.")
			settled.Do(func() { resultCh <- callbackResult{err: errors.New("O11y OAuth callback issuer did not match")} })
			return
		}
		code := query.Get("code")
		if code == "" {
			writeSISCIMDCallbackPage(w, http.StatusBadRequest, "Sign-in response was incomplete", "Return to Splunk Observability Studio and try again.")
			settled.Do(func() {
				resultCh <- callbackResult{err: errors.New("O11y OAuth callback did not include an authorization code")}
			})
			return
		}
		if !claimed.CompareAndSwap(false, true) {
			writeSISCIMDCallbackPage(w, http.StatusConflict, "Sign-in response already received", "You can close this page.")
			return
		}
		session, err := exchangeO11yOAuthAuthorizationCode(attemptCtx, client, code, verifier, exchangeConfig)
		if err != nil {
			writeSISCIMDCallbackPage(w, http.StatusBadGateway, "Sign-in could not be completed", "Return to Splunk Observability Studio and try again.")
			settled.Do(func() { resultCh <- callbackResult{err: err} })
			return
		}
		writeSISCIMDCallbackPage(w, http.StatusOK, "Sign-in complete", "You can return to Splunk Observability Studio.")
		settled.Do(func() { resultCh <- callbackResult{session: session} })
	})

	// Binds the exact same fixed loopback address CIMD's login listener uses: both are the
	// callback obstudio registered for its clients, and the two flows never run at once.
	address := fmt.Sprintf("%s:%d", sisCIMDCallbackHost, sisCIMDCallbackPort)
	listener, err := net.Listen("tcp", address)
	if err != nil {
		cancelAttempt()
		return nil, fmt.Errorf("could not start the O11y OAuth callback server: %w", err)
	}

	closeFunc := func() error { return listener.Close() }
	cancelFunc := func() {
		settled.Do(func() { resultCh <- callbackResult{err: errors.New("O11y OAuth sign-in was cancelled")} })
	}

	run := func(generation uint64) {
		go func() { _ = server.Serve(listener) }()
		go func() {
			defer cancelAttempt()
			timer := time.NewTimer(o11yOAuthLoginTimeout)
			defer timer.Stop()
			var result callbackResult
			select {
			case result = <-resultCh:
			case <-timer.C:
				result = callbackResult{err: errors.New("timed out waiting for O11y OAuth authorization")}
			}
			cancelAttempt()
			time.Sleep(sisCIMDCallbackDrainDelay)
			shutdownCtx, cancelShutdown := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancelShutdown()
			_ = server.Shutdown(shutdownCtx)

			if result.err != nil {
				globalO11yOAuthLoginState.fail(generation, result.err)
				return
			}
			globalO11yOAuthLoginState.succeed(generation, result.session)
		}()
	}

	return &o11yOAuthCallbackListener{server: server, cancel: cancelFunc, close: closeFunc, run: run}, nil
}

// exchangeO11yOAuthAuthorizationCode redeems the authorization code at the SIS token
// endpoint (PKCE verifier + HTTP Basic clientId:clientSecret, per the confirmed lab0
// curl -- both are sent together) and then immediately exchanges the resulting SIS access
// token for an O11y access token (exchangeO11ySISTokenForAccessToken). The SIS token is
// never retained past that second call: only the O11y access token is stored in the
// resulting session.
func exchangeO11yOAuthAuthorizationCode(
	ctx context.Context,
	client *http.Client,
	code string,
	verifier string,
	config o11yOAuthExchangeConfig,
) (*o11yOAuthSession, error) {
	form := url.Values{}
	form.Set("grant_type", "authorization_code")
	form.Set("code", code)
	form.Set("code_verifier", verifier)
	form.Set("redirect_uri", o11yOAuthRegistrationCallbackURL)
	form.Set("client_id", config.clientID)

	request, err := http.NewRequestWithContext(ctx, http.MethodPost, config.tokenEndpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, fmt.Errorf("build O11y OAuth token request: %w", err)
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	request.Header.Set("Accept", "application/json")
	request.SetBasicAuth(config.clientID, config.clientSecret)

	response, err := client.Do(request)
	if err != nil {
		return nil, fmt.Errorf("call O11y OAuth token endpoint: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		// Never reflect the response body into an error that could surface to the
		// browser via GET /api/splunk/o11y-oauth/session: it may carry token material or
		// sensitive error_description content. Mirrors exchangeSISCIMDAuthorizationCode.
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, o11yOAuthMaxResponseBodyBytes))
		return nil, fmt.Errorf("O11y OAuth token endpoint returned HTTP %d", response.StatusCode)
	}

	var token struct {
		AccessToken string `json:"access_token"`
		TokenType   string `json:"token_type"`
		ExpiresIn   int    `json:"expires_in"`
	}
	if err := sisCIMDDecodeJSON(response, &token); err != nil {
		return nil, fmt.Errorf("O11y OAuth token endpoint response: %w", err)
	}
	if token.AccessToken == "" || !strings.EqualFold(token.TokenType, "bearer") {
		return nil, errors.New("O11y OAuth token endpoint returned an invalid bearer token response")
	}
	if token.ExpiresIn <= 0 {
		return nil, errors.New("O11y OAuth token endpoint returned an invalid expires_in value")
	}

	o11yAccessToken, err := exchangeO11ySISTokenForAccessToken(ctx, client, token.AccessToken, config.exchangeURL)
	if err != nil {
		return nil, err
	}

	connectedAt := time.Now()
	return &o11yOAuthSession{
		// The O11y access token's own lifetime is not reported by the exchange response
		// (just {accessToken}); the SIS token's expires_in is used as a conservative
		// stand-in until the real O11y OAuth server exposes its own.
		accessToken: o11yAccessToken,
		issuer:      config.issuer,
		clientID:    config.clientID,
		realm:       config.realm,
		orgID:       config.orgID,
		connectedAt: connectedAt,
		expiresAt:   connectedAt.Add(time.Duration(token.ExpiresIn) * time.Second),
	}, nil
}

// exchangeO11ySISTokenForAccessToken is the second hop confirmed against lab0: the SIS
// access token (Bearer) is exchanged for an O11y access token (the value used as
// X-SF-TOKEN against the O11y MCP server). A 201 with a non-empty accessToken is the only
// success case; the SIS token passed in is never logged or persisted by this call or its
// caller.
func exchangeO11ySISTokenForAccessToken(ctx context.Context, client *http.Client, sisAccessToken, exchangeURL string) (string, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, exchangeURL, nil)
	if err != nil {
		return "", fmt.Errorf("build O11y access token exchange request: %w", err)
	}
	request.Header.Set("Accept", "application/json")
	request.Header.Set("Authorization", "Bearer "+sisAccessToken)

	response, err := client.Do(request)
	if err != nil {
		return "", fmt.Errorf("call O11y access token exchange endpoint: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusCreated {
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, o11yOAuthMaxResponseBodyBytes))
		return "", fmt.Errorf("O11y access token exchange endpoint returned HTTP %d", response.StatusCode)
	}

	var decoded struct {
		AccessToken string `json:"accessToken"`
	}
	if err := sisCIMDDecodeJSON(response, &decoded); err != nil {
		return "", fmt.Errorf("O11y access token exchange response: %w", err)
	}
	if decoded.AccessToken == "" {
		return "", errors.New("O11y access token exchange endpoint did not return an access token")
	}
	return decoded.AccessToken, nil
}

// registerO11yOAuthLoginRoutes wires the local-only login/session routes onto mux,
// alongside registerO11yOAuthRoutes's registration route. Same local-request gate as
// everywhere else in this file family.
func registerO11yOAuthLoginRoutes(mux *http.ServeMux) {
	gate := func(next http.HandlerFunc) http.HandlerFunc {
		return requireLocalObserverRequest(next, writeO11yOAuthRegistrationError)
	}
	mux.HandleFunc("POST /api/splunk/o11y-oauth/login", gate(startO11yOAuthLoginHandler))
	mux.HandleFunc("GET /api/splunk/o11y-oauth/session", gate(o11yOAuthSessionStatusHandler))
	mux.HandleFunc("POST /api/splunk/o11y-oauth/session/disconnect", gate(disconnectO11yOAuthSessionHandler))
}
