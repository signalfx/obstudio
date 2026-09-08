package api

import (
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// mockSISForLogin serves a CIMD metadata doc, discovery document, and token endpoint.
// Its authorize endpoint redirects straight to our fixed local callback with a code, as
// if a federated IDP login had already completed -- registration tests already cover
// the federation hop itself, so login tests only need to exercise what happens once a
// code comes back to sisCIMDRedirectURI.
type mockSISForLogin struct {
	server            *httptest.Server
	metadata          map[string]any
	discovery         map[string]any
	tokenResponse     map[string]any
	tokenStatus       int
	tokenErrorBody    string
	authorizeCode     string
	authorizeErr      string
	caBundlePath      string
	lastTokenForm     url.Values
	tokenRequestCount atomic.Int32
	// tokenRequestBlock, when non-nil, holds the token handler open until either it is
	// closed or the request's own context is cancelled -- letting a test hold an
	// exchange "in flight".
	tokenRequestBlock chan struct{}
}

func startMockSISForLogin(t *testing.T) *mockSISForLogin {
	t.Helper()
	mock := &mockSISForLogin{
		metadata:  map[string]any{},
		discovery: map[string]any{},
		tokenResponse: map[string]any{
			"access_token": "sis-access-token",
			"token_type":   "Bearer",
			"scope":        "openid offline_access",
			"expires_in":   3600,
		},
		tokenStatus:   http.StatusOK,
		authorizeCode: "test-authorization-code",
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/oauth/client-metadata.json", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, mock.metadata)
	})
	mux.HandleFunc("/test-tenant/sis/v1/rg/cimd-demo/.well-known/openid-configuration", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, mock.discovery)
	})
	mux.HandleFunc("/test-tenant/sis/v1/rg/cimd-demo/oauth2/authorize", func(w http.ResponseWriter, r *http.Request) {
		callback, err := url.Parse(sisCIMDRedirectURI)
		if err != nil {
			t.Fatalf("parse redirect URI: %v", err)
		}
		query := callback.Query()
		query.Set("state", r.URL.Query().Get("state"))
		if mock.authorizeErr != "" {
			query.Set("error", mock.authorizeErr)
		} else {
			query.Set("code", mock.authorizeCode)
		}
		callback.RawQuery = query.Encode()
		w.Header().Set("Location", callback.String())
		w.WriteHeader(http.StatusFound)
	})
	mux.HandleFunc("/test-tenant/sis/v1/rg/cimd-demo/oauth2/token", func(w http.ResponseWriter, r *http.Request) {
		mock.tokenRequestCount.Add(1)
		if mock.tokenRequestBlock != nil {
			select {
			case <-mock.tokenRequestBlock:
			case <-r.Context().Done():
				return
			}
		}
		if err := r.ParseForm(); err != nil {
			t.Fatalf("parse token request form: %v", err)
		}
		mock.lastTokenForm = r.Form
		w.WriteHeader(mock.tokenStatus)
		if mock.tokenStatus >= 200 && mock.tokenStatus < 300 {
			writeJSON(w, mock.tokenResponse)
			return
		}
		if mock.tokenErrorBody != "" {
			_, _ = w.Write([]byte(mock.tokenErrorBody))
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"error": "invalid_grant"})
	})

	mock.server = httptest.NewTLSServer(mux)
	t.Cleanup(mock.server.Close)

	issuer := mock.server.URL + "/test-tenant/sis/v1/rg/cimd-demo"
	clientID := mock.server.URL + "/oauth/client-metadata.json"
	mock.metadata = map[string]any{
		"client_id":      clientID,
		"client_name":    "Obstudio (CIMD)",
		"grant_types":    []string{"authorization_code", "refresh_token"},
		"redirect_uris":  []string{sisCIMDRedirectURI},
		"response_types": []string{"code"},
		"scope":          "openid offline_access",
	}
	mock.discovery = map[string]any{
		"authorization_endpoint":                fmt.Sprintf("%s/oauth2/authorize", issuer),
		"client_id_metadata_document_supported": true,
		"code_challenge_methods_supported":      []string{"S256", "plain"},
		"grant_types_supported":                 []string{"authorization_code", "refresh_token"},
		"issuer":                                issuer,
		"response_types_supported":              []string{"code"},
		"scopes_supported":                      []string{"openid", "offline_access"},
		"token_endpoint":                        fmt.Sprintf("%s/oauth2/token", issuer),
		"token_endpoint_auth_methods_supported": []string{"private_key_jwt", "none"},
	}
	mock.caBundlePath = writeMockSISCABundle(t, mock.server)
	return mock
}

func (m *mockSISForLogin) config() sisCIMDRegistrationConfig {
	return sisCIMDRegistrationConfig{
		issuer:                  m.server.URL + "/test-tenant/sis/v1/rg/cimd-demo",
		clientID:                m.server.URL + "/oauth/client-metadata.json",
		scope:                   "openid offline_access",
		developmentCABundlePath: m.caBundlePath,
	}
}

// setSISCIMDLoginConfigEnv points loadSISCIMDRegistrationConfig's env-driven defaults
// at the mock server, since startSISCIMDLoginHandler (unlike registerSISCIMDClient) has
// no way to take a config directly -- it is an HTTP handler.
func setSISCIMDLoginConfigEnv(t *testing.T, config sisCIMDRegistrationConfig) {
	t.Helper()
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_ISSUER", config.issuer)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_CLIENT_ID", config.clientID)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_SCOPE", config.scope)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_DEVELOPMENT_CA_BUNDLE_PATH", config.developmentCABundlePath)
}

// resetGlobalSISCIMDLoginState ensures each test starts from a clean slate. Login state
// is process-wide (one fixed callback port), so tests cannot run in parallel with each
// other, but must still not leak state between sequential tests.
func resetGlobalSISCIMDLoginState(t *testing.T) {
	t.Helper()
	globalSISCIMDLoginState.disconnect()
	t.Cleanup(func() { globalSISCIMDLoginState.disconnect() })
}

// simulateBrowserFollowingAuthorizationURL performs the same two hops a real browser
// tab would after window.open(authorizationURL): fetch the authorization URL (the mock
// IDP-equivalent redirect straight to our loopback callback), then let that redirect
// resolve, delivering the code to Observer's callback listener. Cookies are irrelevant
// here since sisCIMDCallbackListener validates via the OAuth `state` query parameter,
// not a cookie.
func simulateBrowserFollowingAuthorizationURL(t *testing.T, authorizationURL string) *http.Response {
	t.Helper()
	client := &http.Client{
		// The mock IDP/SIS server uses a self-signed cert; skipping verification here
		// mirrors what a real browser would do only after a user manually trusts a dev
		// cert -- acceptable for this test, which is exercising the loopback callback,
		// not certificate trust (that is covered by TestRegisterSISCIMDClient... tests).
		Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}, //nolint:gosec
	}
	response, err := client.Get(authorizationURL)
	if err != nil {
		t.Fatalf("follow authorization URL: %v", err)
	}
	return response
}

func waitForSISCIMDLoginPhase(t *testing.T, want sisCIMDLoginPhase) sisCIMDSessionStatus {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		status := globalSISCIMDLoginState.status()
		if status.Phase == want {
			return status
		}
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for login phase %q, last status: %+v", want, status)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestSISCIMDLoginSucceedsAfterCallback(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)
	mock := startMockSISForLogin(t)
	setSISCIMDLoginConfigEnv(t, mock.config())
	// registerSISCIMDLoginRoutes reads OBSTUDIO_CONTROL_TOKEN when it wires the gate, so
	// this must be set before that call, not just before the request.
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	loginMux := http.NewServeMux()
	registerSISCIMDLoginRoutes(loginMux)

	startResponse := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
	if startResponse.Code != http.StatusOK {
		t.Fatalf("login start status = %d, body = %s", startResponse.Code, startResponse.Body.String())
	}
	var start sisCIMDLoginStartResult
	if err := json.Unmarshal(startResponse.Body.Bytes(), &start); err != nil {
		t.Fatal(err)
	}

	pending := splunkExportRequest(t, loginMux, http.MethodGet, "/api/splunk/cimd/session", "", testObserverControlToken)
	var pendingStatus sisCIMDSessionStatus
	if err := json.Unmarshal(pending.Body.Bytes(), &pendingStatus); err != nil {
		t.Fatal(err)
	}
	if pendingStatus.Phase != sisCIMDLoginPhasePending {
		t.Fatalf("phase before callback = %q, want pending", pendingStatus.Phase)
	}

	callbackResponse := simulateBrowserFollowingAuthorizationURL(t, start.AuthorizationURL)
	defer callbackResponse.Body.Close()
	if callbackResponse.StatusCode != http.StatusOK {
		t.Fatalf("callback status = %d", callbackResponse.StatusCode)
	}

	connected := waitForSISCIMDLoginPhase(t, sisCIMDLoginPhaseConnected)
	if connected.Scope != "openid offline_access" {
		t.Fatalf("connected scope = %q", connected.Scope)
	}
	if connected.Issuer != mock.config().issuer {
		t.Fatalf("connected issuer = %q, want %q", connected.Issuer, mock.config().issuer)
	}
	if connected.ExpiresAt == "" {
		t.Fatal("expected a non-empty expiresAt")
	}

	body := pending.Body.String() + startResponse.Body.String()
	if containsString(body, "sis-access-token") {
		t.Fatal("access token leaked into an HTTP response body")
	}

	disconnect := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/session/disconnect", "", testObserverControlToken)
	var disconnected sisCIMDSessionStatus
	if err := json.Unmarshal(disconnect.Body.Bytes(), &disconnected); err != nil {
		t.Fatal(err)
	}
	if disconnected.Phase != sisCIMDLoginPhaseDisconnected {
		t.Fatalf("phase after disconnect = %q, want disconnected", disconnected.Phase)
	}
}

func TestSISCIMDLoginIgnoresADriveByCallbackRequestWithTheWrongState(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)
	mock := startMockSISForLogin(t)
	setSISCIMDLoginConfigEnv(t, mock.config())
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	loginMux := http.NewServeMux()
	registerSISCIMDLoginRoutes(loginMux)

	startResponse := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
	var start sisCIMDLoginStartResult
	if err := json.Unmarshal(startResponse.Body.Bytes(), &start); err != nil {
		t.Fatal(err)
	}

	// The callback port is fixed and well-known, so any unrelated local request or a
	// drive-by page open in another tab can hit it without ever knowing the real state
	// nonce. This must be rejected without ending the flow for the real callback still
	// to come.
	driveByURL := fmt.Sprintf("http://%s:%d/callback?state=not-the-real-state", sisCIMDCallbackHost, sisCIMDCallbackPort)
	driveBy, err := http.Get(driveByURL) //nolint:gosec
	if err != nil {
		t.Fatalf("drive-by callback request: %v", err)
	}
	defer driveBy.Body.Close()
	if driveBy.StatusCode != http.StatusBadRequest {
		t.Fatalf("drive-by callback status = %d, want 400", driveBy.StatusCode)
	}

	if pending := globalSISCIMDLoginState.status(); pending.Phase != sisCIMDLoginPhasePending {
		t.Fatalf("phase after drive-by request = %q, want pending", pending.Phase)
	}

	callbackResponse := simulateBrowserFollowingAuthorizationURL(t, start.AuthorizationURL)
	defer callbackResponse.Body.Close()
	if callbackResponse.StatusCode != http.StatusOK {
		t.Fatalf("real callback status = %d, want 200", callbackResponse.StatusCode)
	}

	connected := waitForSISCIMDLoginPhase(t, sisCIMDLoginPhaseConnected)
	if connected.Issuer != mock.config().issuer {
		t.Fatalf("connected issuer = %q, want %q", connected.Issuer, mock.config().issuer)
	}
}

func TestSISCIMDLoginClaimsOnlyTheFirstOfTwoConcurrentValidCallbacks(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)
	mock := startMockSISForLogin(t)
	setSISCIMDLoginConfigEnv(t, mock.config())
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	loginMux := http.NewServeMux()
	registerSISCIMDLoginRoutes(loginMux)

	startResponse := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
	var start sisCIMDLoginStartResult
	if err := json.Unmarshal(startResponse.Body.Bytes(), &start); err != nil {
		t.Fatal(err)
	}

	// Simulates a reload of the SIS redirect landing page while the first request's
	// exchange is still in flight: two requests with the identical, genuinely valid
	// state and code hit the callback concurrently. Only one may claim the callback and
	// attempt the exchange; a fast duplicate-code failure from SIS must not be able to
	// settle the whole attempt as an error while the original goes on to succeed.
	var wg sync.WaitGroup
	statuses := make([]int, 2)
	errs := make([]error, 2)
	for i := range statuses {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			client := &http.Client{
				Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}, //nolint:gosec
			}
			response, err := client.Get(start.AuthorizationURL)
			if err != nil {
				errs[i] = err
				return
			}
			defer response.Body.Close()
			statuses[i] = response.StatusCode
		}(i)
	}
	wg.Wait()

	for i, err := range errs {
		if err != nil {
			t.Fatalf("follow authorization URL (goroutine %d): %v", i, err)
		}
	}

	var okCount, conflictCount int
	for _, status := range statuses {
		switch status {
		case http.StatusOK:
			okCount++
		case http.StatusConflict:
			conflictCount++
		}
	}
	if okCount != 1 || conflictCount != 1 {
		t.Fatalf("callback statuses = %v, want exactly one 200 and one 409", statuses)
	}
	if got := mock.tokenRequestCount.Load(); got != 1 {
		t.Fatalf("token endpoint was requested %d times, want exactly 1", got)
	}

	connected := waitForSISCIMDLoginPhase(t, sisCIMDLoginPhaseConnected)
	if connected.Issuer != mock.config().issuer {
		t.Fatalf("connected issuer = %q, want %q", connected.Issuer, mock.config().issuer)
	}
}

func TestSISCIMDLoginCancelsAnInFlightExchangeOnDisconnect(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)
	mock := startMockSISForLogin(t)
	mock.tokenRequestBlock = make(chan struct{})
	t.Cleanup(func() { close(mock.tokenRequestBlock) }) // let the mock's handler return so Close() doesn't hang
	setSISCIMDLoginConfigEnv(t, mock.config())
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	loginMux := http.NewServeMux()
	registerSISCIMDLoginRoutes(loginMux)

	startResponse := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
	var start sisCIMDLoginStartResult
	if err := json.Unmarshal(startResponse.Body.Bytes(), &start); err != nil {
		t.Fatal(err)
	}

	callbackDone := make(chan *http.Response, 1)
	go func() {
		client := &http.Client{
			Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}, //nolint:gosec
		}
		response, err := client.Get(start.AuthorizationURL)
		if err != nil {
			t.Errorf("follow authorization URL: %v", err)
			callbackDone <- nil
			return
		}
		callbackDone <- response
	}()

	deadline := time.Now().Add(2 * time.Second)
	for mock.tokenRequestCount.Load() == 0 {
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for the token exchange to start")
		}
		time.Sleep(5 * time.Millisecond)
	}

	// The exchange is now genuinely in flight (blocked in the mock's token handler,
	// which never releases it in this test). Disconnecting here must cancel Observer's
	// outbound request rather than leave it running in the background -- otherwise SIS
	// could still mint a token after Observer has already reported disconnection.
	globalSISCIMDLoginState.disconnect()

	// If the exchange were left to run instead of being cancelled, this would hang until
	// the mock's block channel closes at test cleanup -- it only completes promptly here
	// because disconnect cancelled Observer's own outbound request.
	select {
	case response := <-callbackDone:
		if response == nil {
			t.Fatal("callback request failed; see prior test log")
		}
		defer response.Body.Close()
		if response.StatusCode != http.StatusBadGateway {
			t.Fatalf("callback status = %d, want 502 (exchange cancelled)", response.StatusCode)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for the callback request to complete after disconnect -- " +
			"the token exchange was not cancelled")
	}

	if status := globalSISCIMDLoginState.status(); status.Phase != sisCIMDLoginPhaseDisconnected {
		t.Fatalf("phase after disconnect = %q, want disconnected", status.Phase)
	}

	// disconnect() sets phase synchronously, but the callback listener's own goroutine
	// releases the fixed port asynchronously afterward (drain delay + Shutdown). Wait for
	// that too, or a later test reusing the same fixed port can race this one's teardown.
	waitForSISCIMDCallbackPortRelease(t)
}

func waitForSISCIMDCallbackPortRelease(t *testing.T) {
	t.Helper()
	address := fmt.Sprintf("%s:%d", sisCIMDCallbackHost, sisCIMDCallbackPort)
	deadline := time.Now().Add(3 * time.Second)
	for {
		probe, err := net.Listen("tcp", address)
		if err == nil {
			_ = probe.Close()
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for the callback listener to release %s: %v", address, err)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestSISCIMDLoginStatusExpiresAConnectedSession(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)
	mock := startMockSISForLogin(t)
	setSISCIMDLoginConfigEnv(t, mock.config())
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	loginMux := http.NewServeMux()
	registerSISCIMDLoginRoutes(loginMux)

	startResponse := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
	var start sisCIMDLoginStartResult
	if err := json.Unmarshal(startResponse.Body.Bytes(), &start); err != nil {
		t.Fatal(err)
	}
	callbackResponse := simulateBrowserFollowingAuthorizationURL(t, start.AuthorizationURL)
	defer callbackResponse.Body.Close()
	waitForSISCIMDLoginPhase(t, sisCIMDLoginPhaseConnected)

	globalSISCIMDLoginState.mu.Lock()
	globalSISCIMDLoginState.session.expiresAt = time.Now().Add(-time.Minute)
	globalSISCIMDLoginState.mu.Unlock()

	expired := globalSISCIMDLoginState.status()
	if expired.Phase != sisCIMDLoginPhaseDisconnected {
		t.Fatalf("phase after expiry = %q, want disconnected", expired.Phase)
	}

	session := splunkExportRequest(t, loginMux, http.MethodGet, "/api/splunk/cimd/session", "", testObserverControlToken)
	var sessionStatus sisCIMDSessionStatus
	if err := json.Unmarshal(session.Body.Bytes(), &sessionStatus); err != nil {
		t.Fatal(err)
	}
	if sessionStatus.Phase != sisCIMDLoginPhaseDisconnected {
		t.Fatalf("/api/splunk/cimd/session phase = %q, want disconnected", sessionStatus.Phase)
	}
}

func TestSISCIMDLoginStaleAttemptCannotClobberNewerState(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)

	staleGeneration, ok := globalSISCIMDLoginState.beginPending(func() {})
	if !ok {
		t.Fatal("expected beginPending to succeed for the stale attempt")
	}
	globalSISCIMDLoginState.disconnect()

	currentGeneration, ok := globalSISCIMDLoginState.beginPending(func() {})
	if !ok {
		t.Fatal("expected beginPending to succeed for the current attempt")
	}

	// Simulates the stale attempt's callback listener goroutine finally waking up (e.g.
	// after being cancelled by disconnect() above) and reporting its own outcome -- this
	// must not affect the newer, still-pending attempt.
	globalSISCIMDLoginState.succeed(staleGeneration, &sisCIMDSession{issuer: "stale"})
	if status := globalSISCIMDLoginState.status(); status.Phase != sisCIMDLoginPhasePending {
		t.Fatalf("phase after stale succeed = %q, want pending", status.Phase)
	}
	globalSISCIMDLoginState.fail(staleGeneration, errors.New("stale failure"))
	if status := globalSISCIMDLoginState.status(); status.Phase != sisCIMDLoginPhasePending {
		t.Fatalf("phase after stale fail = %q, want pending", status.Phase)
	}

	// The current attempt's own completion must still apply normally.
	globalSISCIMDLoginState.succeed(currentGeneration, &sisCIMDSession{
		issuer:      "current",
		connectedAt: time.Now(),
		expiresAt:   time.Now().Add(time.Hour),
	})
	status := globalSISCIMDLoginState.status()
	if status.Phase != sisCIMDLoginPhaseConnected || status.Issuer != "current" {
		t.Fatalf("status after current succeed = %+v, want connected/current", status)
	}
}

func TestSISCIMDLoginFailsOnOAuthError(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)
	mock := startMockSISForLogin(t)
	mock.authorizeErr = "access_denied"
	setSISCIMDLoginConfigEnv(t, mock.config())
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	loginMux := http.NewServeMux()
	registerSISCIMDLoginRoutes(loginMux)

	startResponse := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
	var start sisCIMDLoginStartResult
	if err := json.Unmarshal(startResponse.Body.Bytes(), &start); err != nil {
		t.Fatal(err)
	}

	callbackResponse := simulateBrowserFollowingAuthorizationURL(t, start.AuthorizationURL)
	defer callbackResponse.Body.Close()
	if callbackResponse.StatusCode != http.StatusBadRequest {
		t.Fatalf("callback status = %d, want 400", callbackResponse.StatusCode)
	}

	failed := waitForSISCIMDLoginPhase(t, sisCIMDLoginPhaseError)
	if want := "access_denied"; !containsString(failed.Error, want) {
		t.Fatalf("error = %q, want to contain %q", failed.Error, want)
	}
}

func TestSISCIMDLoginTokenExchangeFailureDoesNotReflectResponseBody(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)
	mock := startMockSISForLogin(t)
	mock.tokenStatus = http.StatusBadRequest
	const leakedSecret = "leaked-secret-error-description-xyz"
	mock.tokenErrorBody = fmt.Sprintf(`{"error":"invalid_grant","error_description":%q}`, leakedSecret)
	setSISCIMDLoginConfigEnv(t, mock.config())
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	loginMux := http.NewServeMux()
	registerSISCIMDLoginRoutes(loginMux)

	startResponse := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
	var start sisCIMDLoginStartResult
	if err := json.Unmarshal(startResponse.Body.Bytes(), &start); err != nil {
		t.Fatal(err)
	}

	callbackResponse := simulateBrowserFollowingAuthorizationURL(t, start.AuthorizationURL)
	defer callbackResponse.Body.Close()
	if callbackResponse.StatusCode != http.StatusBadGateway {
		t.Fatalf("callback status = %d, want 502 -- the exchange happens before the callback responds, "+
			"so a failed exchange must not still report success to the browser", callbackResponse.StatusCode)
	}
	callbackBody, err := io.ReadAll(callbackResponse.Body)
	if err != nil {
		t.Fatal(err)
	}
	if containsString(string(callbackBody), leakedSecret) {
		t.Fatal("callback error page reflects the SIS token endpoint's response body")
	}

	failed := waitForSISCIMDLoginPhase(t, sisCIMDLoginPhaseError)
	if containsString(failed.Error, leakedSecret) {
		t.Fatalf("error %q reflects the SIS token endpoint's response body", failed.Error)
	}
	if want := "HTTP 400"; !containsString(failed.Error, want) {
		t.Fatalf("error = %q, want to contain %q", failed.Error, want)
	}
}

func TestSISCIMDLoginRejectsAMismatchedGrantedScope(t *testing.T) {
	tests := []struct {
		name         string
		grantedScope string
		want         string
	}{
		{"narrowed scope omits a requested scope", "openid", "omitted requested scope \"offline_access\""},
		{"expanded scope grants an unrequested scope", "openid offline_access admin", "included unrequested scope \"admin\""},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			resetGlobalSISCIMDLoginState(t)
			mock := startMockSISForLogin(t)
			mock.tokenResponse["scope"] = tc.grantedScope
			setSISCIMDLoginConfigEnv(t, mock.config())
			t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

			loginMux := http.NewServeMux()
			registerSISCIMDLoginRoutes(loginMux)

			startResponse := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
			var start sisCIMDLoginStartResult
			if err := json.Unmarshal(startResponse.Body.Bytes(), &start); err != nil {
				t.Fatal(err)
			}

			callbackResponse := simulateBrowserFollowingAuthorizationURL(t, start.AuthorizationURL)
			defer callbackResponse.Body.Close()
			if callbackResponse.StatusCode != http.StatusBadGateway {
				t.Fatalf("callback status = %d, want 502", callbackResponse.StatusCode)
			}

			failed := waitForSISCIMDLoginPhase(t, sisCIMDLoginPhaseError)
			if !containsString(failed.Error, tc.want) {
				t.Fatalf("error = %q, want to contain %q", failed.Error, tc.want)
			}
		})
	}
}

func TestSISCIMDLoginRoutesRequireControlToken(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)
	mock := startMockSISForLogin(t)
	setSISCIMDLoginConfigEnv(t, mock.config())
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	loginMux := http.NewServeMux()
	registerSISCIMDLoginRoutes(loginMux)

	for _, route := range []struct {
		method string
		path   string
	}{
		{http.MethodPost, "/api/splunk/cimd/login"},
		{http.MethodGet, "/api/splunk/cimd/session"},
		{http.MethodPost, "/api/splunk/cimd/session/disconnect"},
	} {
		response := splunkExportRequest(t, loginMux, route.method, route.path, "", "")
		if response.Code != http.StatusUnauthorized {
			t.Fatalf("%s %s without a token = %d, want 401", route.method, route.path, response.Code)
		}
	}
}

func TestSISCIMDLoginRejectsAConcurrentLoginAttempt(t *testing.T) {
	resetGlobalSISCIMDLoginState(t)
	mock := startMockSISForLogin(t)
	setSISCIMDLoginConfigEnv(t, mock.config())
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	loginMux := http.NewServeMux()
	registerSISCIMDLoginRoutes(loginMux)

	first := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
	if first.Code != http.StatusOK {
		t.Fatalf("first login start status = %d, body = %s", first.Code, first.Body.String())
	}
	defer globalSISCIMDLoginState.disconnect()

	second := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/cimd/login", "", testObserverControlToken)
	if second.Code != http.StatusConflict {
		t.Fatalf("second login start status = %d, want 409", second.Code)
	}
}
