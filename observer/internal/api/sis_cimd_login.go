package api

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

// TODO(CIMD PoC): This mirrors extension/src/sis-cimd-oauth.ts's authorizeWithSISCIMD
// for Observer's own standalone web UI (no VS Code bridge). Unlike registration, login
// mints a real OAuth session, so every route here is gated by OBSTUDIO_CONTROL_TOKEN --
// see requireObserverControlToken in splunk_export.go. The resulting token is held only
// in this process's memory (sisCIMDLoginState below); it is never written to disk, never
// returned to the browser, and is lost on restart. If these two implementations drift,
// prefer the TypeScript one as the more heavily tested source of truth.

const (
	sisCIMDLoginTimeout = 5 * time.Minute
	sisCIMDCallbackPort = 33418
	sisCIMDCallbackHost = "127.0.0.1"
	// sisCIMDCallbackDrainDelay gives a request that is genuinely concurrent with the one
	// that just settled the flow (e.g. a reload of the SIS redirect landing page arriving
	// just after the original) a chance to be accepted and receive a real 409 response,
	// rather than a connection reset because the listener already closed underneath it.
	sisCIMDCallbackDrainDelay = 250 * time.Millisecond
)

// sisCIMDLoginPhase is exposed to the browser; the token itself never is.
type sisCIMDLoginPhase string

const (
	sisCIMDLoginPhaseDisconnected sisCIMDLoginPhase = "disconnected"
	sisCIMDLoginPhasePending      sisCIMDLoginPhase = "pending"
	sisCIMDLoginPhaseConnected    sisCIMDLoginPhase = "connected"
	sisCIMDLoginPhaseError        sisCIMDLoginPhase = "error"
)

type sisCIMDSession struct {
	accessToken string
	scope       string
	issuer      string
	clientID    string
	connectedAt time.Time
	expiresAt   time.Time
}

// sisCIMDLoginState is process-wide, in-memory-only OAuth session state for Observer's
// standalone web UI. There is one login at a time, matching the fixed loopback callback
// port -- a second concurrent login attempt would race for the same port anyway.
type sisCIMDLoginState struct {
	mu         sync.Mutex
	phase      sisCIMDLoginPhase
	session    *sisCIMDSession
	errorMsg   string
	cancelFunc func()
	// generation increments on every beginPending/disconnect, so a cancelled or
	// superseded attempt's eventual, asynchronous fail/succeed call -- which can arrive
	// after a newer login has already started -- can recognize it is stale and no-op
	// instead of clobbering the newer attempt's state.
	generation uint64
}

var globalSISCIMDLoginState = &sisCIMDLoginState{phase: sisCIMDLoginPhaseDisconnected}

type sisCIMDLoginStartResult struct {
	AuthorizationURL string `json:"authorizationUrl"`
}

type sisCIMDSessionStatus struct {
	Phase       sisCIMDLoginPhase `json:"phase"`
	Error       string            `json:"error,omitempty"`
	Issuer      string            `json:"issuer,omitempty"`
	Scope       string            `json:"scope,omitempty"`
	ConnectedAt string            `json:"connectedAt,omitempty"`
	ExpiresAt   string            `json:"expiresAt,omitempty"`
}

func (s *sisCIMDLoginState) status() sisCIMDSessionStatus {
	s.mu.Lock()
	defer s.mu.Unlock()
	// Mirrors sisCIMDOAuthSessionMatchesConfiguration's expiresAt check in
	// sis-cimd-oauth.ts: an expired access token must not keep reporting "connected"
	// indefinitely, even though nothing proactively expires this in-memory session.
	if s.phase == sisCIMDLoginPhaseConnected && s.session != nil && !s.session.expiresAt.After(time.Now()) {
		s.phase = sisCIMDLoginPhaseDisconnected
		s.session = nil
	}
	status := sisCIMDSessionStatus{Phase: s.phase, Error: s.errorMsg}
	if s.session != nil {
		status.Issuer = s.session.issuer
		status.Scope = s.session.scope
		status.ConnectedAt = s.session.connectedAt.UTC().Format(time.RFC3339)
		status.ExpiresAt = s.session.expiresAt.UTC().Format(time.RFC3339)
	}
	return status
}

func (s *sisCIMDLoginState) disconnect() {
	s.mu.Lock()
	defer s.mu.Unlock()
	// Bump first: disconnecting a pending attempt invalidates it, so its cancelFunc's
	// eventual fail() call below (asynchronous, via the callback listener's goroutine)
	// finds a stale generation and no-ops rather than flipping phase back to "error".
	s.generation++
	if s.cancelFunc != nil {
		s.cancelFunc()
	}
	s.phase = sisCIMDLoginPhaseDisconnected
	s.session = nil
	s.errorMsg = ""
	s.cancelFunc = nil
}

// beginPending returns false if a login is already pending, so the caller can report a
// conflict rather than starting a second listener on the same fixed port. The returned
// generation must be threaded through to the matching succeed/fail call so a superseded
// attempt's async completion can recognize itself as stale.
func (s *sisCIMDLoginState) beginPending(cancelFunc func()) (uint64, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.phase == sisCIMDLoginPhasePending {
		return 0, false
	}
	s.generation++
	s.phase = sisCIMDLoginPhasePending
	s.session = nil
	s.errorMsg = ""
	s.cancelFunc = cancelFunc
	return s.generation, true
}

func (s *sisCIMDLoginState) succeed(generation uint64, session *sisCIMDSession) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if generation != s.generation {
		return
	}
	s.phase = sisCIMDLoginPhaseConnected
	s.session = session
	s.errorMsg = ""
	s.cancelFunc = nil
}

func (s *sisCIMDLoginState) fail(generation uint64, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if generation != s.generation {
		return
	}
	s.phase = sisCIMDLoginPhaseError
	s.session = nil
	s.errorMsg = err.Error()
	s.cancelFunc = nil
}

// startSISCIMDLoginHandler resolves the CIMD client/discovery, opens the fixed loopback
// callback listener, and returns the authorization URL for the browser to open in a new
// tab (window.open from a click handler, since Observer cannot open the user's browser
// itself the way the VS Code extension can via vscode.env.openExternal). The actual code
// exchange happens in the background; poll sisCIMDSessionStatusHandler for the result.
func startSISCIMDLoginHandler(w http.ResponseWriter, _ *http.Request) {
	config := loadSISCIMDRegistrationConfig()
	client, discovery, err := resolveSISCIMDClientAndDiscovery(config)
	if err != nil {
		writeSISCIMDRegistrationError(w, http.StatusBadGateway, err.Error())
		return
	}
	authorizationURL, state, verifier, err := buildSISCIMDAuthorizationURL(discovery.AuthorizationEndpoint, config)
	if err != nil {
		writeSISCIMDRegistrationError(w, http.StatusBadGateway, err.Error())
		return
	}

	listener, err := startSISCIMDCallbackListener(state, discovery.TokenEndpoint, config, client, discovery.Issuer, verifier)
	if err != nil {
		writeSISCIMDRegistrationError(w, http.StatusConflict, err.Error())
		return
	}
	generation, ok := globalSISCIMDLoginState.beginPending(listener.cancel)
	if !ok {
		_ = listener.close()
		writeSISCIMDRegistrationError(w, http.StatusConflict, "a SIS sign-in is already in progress")
		return
	}
	listener.run(generation)

	writeJSON(w, sisCIMDLoginStartResult{AuthorizationURL: authorizationURL})
}

func sisCIMDSessionStatusHandler(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, globalSISCIMDLoginState.status())
}

func disconnectSISCIMDSessionHandler(w http.ResponseWriter, _ *http.Request) {
	globalSISCIMDLoginState.disconnect()
	writeJSON(w, globalSISCIMDLoginState.status())
}

type sisCIMDCallbackListener struct {
	server *http.Server
	cancel func()
	close  func() error
	run    func(generation uint64)
}

// startSISCIMDCallbackListener binds the fixed loopback callback port immediately (so
// callers learn about a port conflict before returning the authorization URL to the
// browser) and returns a listener whose run() awaits the callback in the background.
// The code-for-token exchange happens synchronously inside the /callback handler itself,
// before it responds to the browser, so a successful "Sign-in complete" page is never
// shown ahead of a still-pending or failed exchange.
func startSISCIMDCallbackListener(
	expectedState string,
	tokenEndpoint string,
	config sisCIMDRegistrationConfig,
	client *http.Client,
	expectedIssuer string,
	verifier string,
) (*sisCIMDCallbackListener, error) {
	mux := http.NewServeMux()
	server := &http.Server{Handler: mux}

	type callbackResult struct {
		session *sisCIMDSession
		err     error
	}
	resultCh := make(chan callbackResult, 1)
	var settled sync.Once
	var claimed atomic.Bool
	// attemptCtx bounds the token exchange to this login attempt: if disconnect or the
	// overall timeout fires while the claimed callback is still exchanging, the exchange
	// must be cancelled, not left to run in the background -- otherwise SIS could still
	// mint a token after Observer has already reported the attempt cancelled or timed out.
	attemptCtx, cancelAttempt := context.WithCancel(context.Background())

	mux.HandleFunc("GET /callback", func(w http.ResponseWriter, r *http.Request) {
		writeSISCIMDCallbackHeaders(w)
		query := r.URL.Query()
		if query.Get("state") != expectedState {
			// Reject only this request, without settling the flow: this port is fixed
			// and well-known, so any unrelated local request or a drive-by page can hit
			// it without ever knowing expectedState. Settling here would let a single
			// such request reliably deny sign-in before the real SIS redirect arrives.
			writeSISCIMDCallbackPage(w, http.StatusBadRequest, "Sign-in could not be verified", "Return to Observer and try again.")
			return
		}
		if oauthError := query.Get("error"); oauthError != "" {
			writeSISCIMDCallbackPage(w, http.StatusBadRequest, "Sign-in was not completed", "Return to Observer and try again.")
			safeError := "unknown_error"
			if isSISCIMDSafeErrorCode(oauthError) {
				safeError = oauthError
			}
			settled.Do(func() { resultCh <- callbackResult{err: fmt.Errorf("SIS authorization failed (%s)", safeError)} })
			return
		}
		if callbackIssuer := query.Get("iss"); callbackIssuer != "" && callbackIssuer != expectedIssuer {
			writeSISCIMDCallbackPage(w, http.StatusBadRequest, "Sign-in could not be verified", "Return to Observer and try again.")
			settled.Do(func() { resultCh <- callbackResult{err: errors.New("SIS OAuth callback issuer did not match")} })
			return
		}
		code := query.Get("code")
		if code == "" {
			writeSISCIMDCallbackPage(w, http.StatusBadRequest, "Sign-in response was incomplete", "Return to Observer and try again.")
			settled.Do(func() {
				resultCh <- callbackResult{err: errors.New("SIS OAuth callback did not include an authorization code")}
			})
			return
		}
		// Claim before exchanging, atomically: a reload of the SIS redirect landing page
		// (or any other duplicate) while the first request's exchange is still in flight
		// would otherwise race it, and a fast duplicate-code failure from SIS could settle
		// the whole attempt as an error even while the original request goes on to
		// succeed. Only the request that wins the claim may exchange the code at all.
		if !claimed.CompareAndSwap(false, true) {
			writeSISCIMDCallbackPage(w, http.StatusConflict, "Sign-in response already received", "You can close this page.")
			return
		}
		// Exchange before reporting success: the browser's "Sign-in complete" page must
		// not lie about an outcome that is still unknown -- reporting success first and
		// finding out about a token-exchange failure afterward (via the async goroutine
		// below) left the user with no reliable signal from either the browser tab or the
		// Observer UI that anything had gone wrong.
		session, err := exchangeSISCIMDAuthorizationCode(attemptCtx, client, tokenEndpoint, config, code, verifier)
		if err != nil {
			writeSISCIMDCallbackPage(w, http.StatusBadGateway, "Sign-in could not be completed", "Return to Observer and try again.")
			settled.Do(func() { resultCh <- callbackResult{err: err} })
			return
		}
		writeSISCIMDCallbackPage(w, http.StatusOK, "Sign-in complete", "You can return to Observer.")
		settled.Do(func() { resultCh <- callbackResult{session: session} })
	})

	address := fmt.Sprintf("%s:%d", sisCIMDCallbackHost, sisCIMDCallbackPort)
	listener, err := net.Listen("tcp", address)
	if err != nil {
		cancelAttempt()
		return nil, fmt.Errorf("could not start the SIS OAuth callback server: %w", err)
	}

	closeFunc := func() error { return listener.Close() }
	cancelFunc := func() {
		settled.Do(func() { resultCh <- callbackResult{err: errors.New("SIS sign-in was cancelled")} })
	}

	run := func(generation uint64) {
		go func() { _ = server.Serve(listener) }()
		go func() {
			defer cancelAttempt()
			timer := time.NewTimer(sisCIMDLoginTimeout)
			defer timer.Stop()
			var result callbackResult
			select {
			case result = <-resultCh:
			case <-timer.C:
				result = callbackResult{err: errors.New("timed out waiting for SIS authorization")}
			}
			// Cancel before the drain delay/shutdown below: a claimed callback may still
			// be exchanging (e.g. disconnect fired while it was in flight), and its
			// outbound request to SIS must be aborted now, not left to complete on its own
			// after Observer has already reported this attempt cancelled or timed out.
			cancelAttempt()
			time.Sleep(sisCIMDCallbackDrainDelay)
			shutdownCtx, cancelShutdown := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancelShutdown()
			_ = server.Shutdown(shutdownCtx)

			if result.err != nil {
				globalSISCIMDLoginState.fail(generation, result.err)
				return
			}
			globalSISCIMDLoginState.succeed(generation, result.session)
		}()
	}

	return &sisCIMDCallbackListener{server: server, cancel: cancelFunc, close: closeFunc, run: run}, nil
}

func exchangeSISCIMDAuthorizationCode(
	ctx context.Context,
	client *http.Client,
	tokenEndpoint string,
	config sisCIMDRegistrationConfig,
	code string,
	verifier string,
) (*sisCIMDSession, error) {
	form := url.Values{}
	form.Set("grant_type", "authorization_code")
	form.Set("code", code)
	form.Set("code_verifier", verifier)
	form.Set("redirect_uri", sisCIMDRedirectURI)
	form.Set("client_id", config.clientID)

	request, err := http.NewRequestWithContext(ctx, http.MethodPost, tokenEndpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, fmt.Errorf("build SIS token request: %w", err)
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	request.Header.Set("Accept", "application/json")

	response, err := client.Do(request)
	if err != nil {
		return nil, wrapSISCIMDRequestError("call SIS token endpoint", err, config)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		// This error surfaces to the browser via GET /api/splunk/cimd/session, so the
		// response body -- which could contain token material or sensitive
		// error_description content from a malformed or compromised SIS -- must never be
		// reflected in it, only the status code.
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, sisCIMDMaxResponseBodyBytes))
		return nil, fmt.Errorf("SIS token endpoint returned HTTP %d", response.StatusCode)
	}

	var token struct {
		AccessToken string `json:"access_token"`
		TokenType   string `json:"token_type"`
		Scope       string `json:"scope"`
		ExpiresIn   int    `json:"expires_in"`
	}
	if err := sisCIMDDecodeJSON(response, &token); err != nil {
		return nil, fmt.Errorf("SIS token endpoint response: %w", err)
	}
	if token.AccessToken == "" || !strings.EqualFold(token.TokenType, "bearer") {
		return nil, errors.New("SIS token endpoint returned an invalid bearer token response")
	}
	if token.ExpiresIn <= 0 {
		return nil, errors.New("SIS token endpoint returned an invalid expires_in value")
	}

	// Mirrors sis-cimd-oauth.ts: an omitted scope means "identical to what was
	// requested" (RFC 6749 5.1), but an explicit scope must match the requested set
	// exactly in both directions -- a narrowed response could grant less than Observer
	// needs, and an expanded one could grant more than it asked for.
	scope := token.Scope
	if scope == "" {
		scope = config.scope
	}
	grantedScopes := sisCIMDScopeSet(scope)
	requestedScopes := sisCIMDScopeSet(config.scope)
	for _, requestedScope := range requestedScopes {
		if !sisCIMDContains(grantedScopes, requestedScope) {
			return nil, fmt.Errorf("SIS token response omitted requested scope %q", requestedScope)
		}
	}
	for _, grantedScope := range grantedScopes {
		if !sisCIMDContains(requestedScopes, grantedScope) {
			return nil, fmt.Errorf("SIS token response included unrequested scope %q", grantedScope)
		}
	}
	connectedAt := time.Now()
	return &sisCIMDSession{
		accessToken: token.AccessToken,
		scope:       scope,
		issuer:      config.issuer,
		clientID:    config.clientID,
		connectedAt: connectedAt,
		expiresAt:   connectedAt.Add(time.Duration(token.ExpiresIn) * time.Second),
	}, nil
}

func isSISCIMDSafeErrorCode(value string) bool {
	if value == "" {
		return false
	}
	for _, r := range value {
		if !(r == '_' || r == '-' || r == '.' ||
			(r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9')) {
			return false
		}
	}
	return len(value) <= 64
}

func writeSISCIMDCallbackHeaders(w http.ResponseWriter) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; sandbox")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("X-Content-Type-Options", "nosniff")
}

func writeSISCIMDCallbackPage(w http.ResponseWriter, statusCode int, title string, message string) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(statusCode)
	_, _ = w.Write([]byte(fmt.Sprintf(
		"<!doctype html><html><head><meta charset=\"utf-8\"><title>%s</title></head>"+
			"<body><h1>%s</h1><p>%s</p></body></html>",
		htmlEscape(title), htmlEscape(title), htmlEscape(message),
	)))
}

func htmlEscape(value string) string {
	var b strings.Builder
	for _, r := range value {
		switch r {
		case '&':
			b.WriteString("&amp;")
		case '<':
			b.WriteString("&lt;")
		case '>':
			b.WriteString("&gt;")
		case '"':
			b.WriteString("&quot;")
		case '\'':
			b.WriteString("&#39;")
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// registerSISCIMDLoginRoutes wires the gated registration/login/session routes onto mux.
// Registration is included here, not left ungated, because an unauthenticated cross-site
// POST could otherwise trigger the outbound SIS authorization probe (and any shadow-client
// creation/refresh it causes SIS to perform) and read back its redirect/cookie details --
// see registerSISCIMDClientHandler's doc comment.
func registerSISCIMDLoginRoutes(mux *http.ServeMux) {
	controlToken := strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN"))
	gate := func(next http.HandlerFunc) http.HandlerFunc {
		return requireObserverControlToken(controlToken, next, writeSISCIMDRegistrationError)
	}
	mux.HandleFunc("POST /api/splunk/cimd/register", gate(registerSISCIMDClientHandler))
	mux.HandleFunc("POST /api/splunk/cimd/login", gate(startSISCIMDLoginHandler))
	mux.HandleFunc("GET /api/splunk/cimd/session", gate(sisCIMDSessionStatusHandler))
	mux.HandleFunc("POST /api/splunk/cimd/session/disconnect", gate(disconnectSISCIMDSessionHandler))
}
