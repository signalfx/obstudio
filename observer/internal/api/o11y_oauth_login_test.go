package api

import (
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"
)

// mockO11yOAuthForLogin serves a discovery document, an authorize endpoint that
// redirects straight to our fixed local callback with a code (login tests only need to
// exercise what happens once a code comes back, not the federation hop itself), a token
// endpoint, and the second-hop O11y access-token exchange endpoint.
type mockO11yOAuthForLogin struct {
	server                 *httptest.Server
	discovery              map[string]any
	tokenResponse          map[string]any
	tokenStatus            int
	exchangeStatus         int
	exchangeResponse       map[string]any
	authorizeCode          string
	authorizeErr           string
	lastTokenForm          url.Values
	lastTokenAuthHeader    string
	lastExchangeAuthHeader string
}

func startMockO11yOAuthForLogin(t *testing.T) *mockO11yOAuthForLogin {
	t.Helper()
	mock := &mockO11yOAuthForLogin{
		tokenResponse: map[string]any{
			"access_token": "sis-access-token",
			"token_type":   "Bearer",
			"expires_in":   3600,
		},
		tokenStatus:    http.StatusOK,
		exchangeStatus: http.StatusCreated,
		exchangeResponse: map[string]any{
			"accessToken": "o11y-access-token",
		},
		authorizeCode: "test-authorization-code",
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/rg/test-org/.well-known/openid-configuration", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, mock.discovery)
	})
	mux.HandleFunc("/rg/test-org/oauth2/authorize", func(w http.ResponseWriter, r *http.Request) {
		callback, err := url.Parse(o11yOAuthRegistrationCallbackURL)
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
	mux.HandleFunc("/rg/test-org/oauth2/token", func(w http.ResponseWriter, r *http.Request) {
		mock.lastTokenAuthHeader = r.Header.Get("Authorization")
		if err := r.ParseForm(); err != nil {
			t.Fatalf("parse token request form: %v", err)
		}
		mock.lastTokenForm = r.Form
		w.WriteHeader(mock.tokenStatus)
		if mock.tokenStatus >= 200 && mock.tokenStatus < 300 {
			writeJSON(w, mock.tokenResponse)
		}
	})
	mux.HandleFunc("/o11y-access-token", func(w http.ResponseWriter, r *http.Request) {
		mock.lastExchangeAuthHeader = r.Header.Get("Authorization")
		w.WriteHeader(mock.exchangeStatus)
		if mock.exchangeStatus == http.StatusCreated {
			writeJSON(w, mock.exchangeResponse)
		}
	})

	mock.server = httptest.NewServer(mux)
	t.Cleanup(mock.server.Close)

	issuer := mock.server.URL + "/rg/test-org"
	mock.discovery = map[string]any{
		"issuer":                           issuer,
		"authorization_endpoint":           issuer + "/oauth2/authorize",
		"token_endpoint":                   issuer + "/oauth2/token",
		"code_challenge_methods_supported": []string{"S256"},
	}
	return mock
}

// setEnv points resolveO11yOAuthIssuer/resolveO11yOAuthExchangeURL's env-driven
// overrides at the mock server, since startO11yOAuthLoginHandler (an HTTP handler) has
// no way to take a config directly.
func (m *mockO11yOAuthForLogin) setEnv(t *testing.T) {
	t.Helper()
	t.Setenv("OBSTUDIO_O11Y_OAUTH_ISSUER_URL", m.server.URL+"/rg/test-org")
	t.Setenv("OBSTUDIO_O11Y_OAUTH_EXCHANGE_URL", m.server.URL+"/o11y-access-token")
}

// resetGlobalO11yOAuthLoginState ensures each test starts from a clean slate. Login
// state is process-wide (one fixed callback port, shared with CIMD's), so these tests
// cannot run in parallel with each other or with the CIMD login tests.
func resetGlobalO11yOAuthLoginState(t *testing.T) {
	t.Helper()
	globalO11yOAuthLoginState.disconnect()
	t.Cleanup(func() { globalO11yOAuthLoginState.disconnect() })
}

func simulateO11yOAuthBrowserFollowingAuthorizationURL(t *testing.T, authorizationURL string) *http.Response {
	t.Helper()
	response, err := http.Get(authorizationURL) //nolint:gosec,noctx
	if err != nil {
		t.Fatalf("follow authorization URL: %v", err)
	}
	return response
}

func waitForO11yOAuthLoginPhase(t *testing.T, want o11yOAuthLoginPhase) o11yOAuthSessionStatus {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		status := globalO11yOAuthLoginState.status()
		if status.Phase == want {
			return status
		}
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for login phase %q, last status: %+v", want, status)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

const o11yOAuthTestOrgID = "test-org-id"

func startO11yOAuthLogin(t *testing.T, loginMux *http.ServeMux) o11yOAuthLoginStartResult {
	t.Helper()
	body := `{"realm":"lab0","orgId":"` + o11yOAuthTestOrgID + `","clientId":"the-client-id","clientSecret":"the-client-secret"}`
	response := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/o11y-oauth/login", body)
	if response.Code != http.StatusOK {
		t.Fatalf("login start status = %d, body = %s", response.Code, response.Body.String())
	}
	var start o11yOAuthLoginStartResult
	if err := json.Unmarshal(response.Body.Bytes(), &start); err != nil {
		t.Fatal(err)
	}
	return start
}

func TestO11yOAuthLoginRequiresAllFields(t *testing.T) {
	loginMux := http.NewServeMux()
	registerO11yOAuthLoginRoutes(loginMux)

	cases := []string{
		`{"realm":"","orgId":"org","clientId":"id","clientSecret":"secret"}`,
		`{"realm":"lab0","orgId":"","clientId":"id","clientSecret":"secret"}`,
		`{"realm":"lab0","orgId":"org","clientId":"","clientSecret":"secret"}`,
		`{"realm":"lab0","orgId":"org","clientId":"id","clientSecret":""}`,
	}
	for _, body := range cases {
		response := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/o11y-oauth/login", body)
		if response.Code != http.StatusBadRequest {
			t.Fatalf("body %s: status = %d, want 400", body, response.Code)
		}
	}
}

func TestO11yOAuthLoginSucceedsAfterCallback(t *testing.T) {
	resetGlobalO11yOAuthLoginState(t)
	mock := startMockO11yOAuthForLogin(t)
	mock.setEnv(t)

	loginMux := http.NewServeMux()
	registerO11yOAuthLoginRoutes(loginMux)

	start := startO11yOAuthLogin(t, loginMux)

	pending := splunkExportRequest(t, loginMux, http.MethodGet, "/api/splunk/o11y-oauth/session", "")
	var pendingStatus o11yOAuthSessionStatus
	if err := json.Unmarshal(pending.Body.Bytes(), &pendingStatus); err != nil {
		t.Fatal(err)
	}
	if pendingStatus.Phase != o11yOAuthLoginPhasePending {
		t.Fatalf("phase before callback = %q, want pending", pendingStatus.Phase)
	}

	callbackResponse := simulateO11yOAuthBrowserFollowingAuthorizationURL(t, start.AuthorizationURL)
	defer callbackResponse.Body.Close()
	if callbackResponse.StatusCode != http.StatusOK {
		t.Fatalf("callback status = %d", callbackResponse.StatusCode)
	}

	connected := waitForO11yOAuthLoginPhase(t, o11yOAuthLoginPhaseConnected)
	if connected.Realm != "lab0" || connected.OrgID != o11yOAuthTestOrgID {
		t.Fatalf("connected realm/orgId = %q/%q, want lab0/%s", connected.Realm, connected.OrgID, o11yOAuthTestOrgID)
	}
	if connected.ExpiresAt == "" {
		t.Fatal("expected a non-empty expiresAt")
	}

	// The token endpoint must receive both HTTP Basic clientId:clientSecret and a PKCE
	// code_verifier -- the confirmed lab0 model, not either alone.
	wantBasic := "Basic " + base64.StdEncoding.EncodeToString([]byte("the-client-id:the-client-secret"))
	if mock.lastTokenAuthHeader != wantBasic {
		t.Fatalf("token request Authorization = %q, want %q", mock.lastTokenAuthHeader, wantBasic)
	}
	if mock.lastTokenForm.Get("code_verifier") == "" {
		t.Fatal("token request missing PKCE code_verifier")
	}
	if mock.lastTokenForm.Get("client_id") != "the-client-id" {
		t.Fatalf("token request client_id = %q", mock.lastTokenForm.Get("client_id"))
	}

	// The O11y exchange call must present the SIS access token as a Bearer credential.
	if mock.lastExchangeAuthHeader != "Bearer sis-access-token" {
		t.Fatalf("exchange request Authorization = %q", mock.lastExchangeAuthHeader)
	}

	body := pending.Body.String() + start.AuthorizationURL
	if containsString(body, "sis-access-token") || containsString(body, "o11y-access-token") {
		t.Fatal("an access token leaked into an HTTP response body")
	}

	disconnect := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/o11y-oauth/session/disconnect", "")
	var disconnected o11yOAuthSessionStatus
	if err := json.Unmarshal(disconnect.Body.Bytes(), &disconnected); err != nil {
		t.Fatal(err)
	}
	if disconnected.Phase != o11yOAuthLoginPhaseDisconnected {
		t.Fatalf("phase after disconnect = %q, want disconnected", disconnected.Phase)
	}
}

func TestO11yOAuthLoginSurfacesExchangeFailureWithoutReflectingBody(t *testing.T) {
	resetGlobalO11yOAuthLoginState(t)
	mock := startMockO11yOAuthForLogin(t)
	mock.exchangeStatus = http.StatusUnauthorized
	mock.setEnv(t)

	loginMux := http.NewServeMux()
	registerO11yOAuthLoginRoutes(loginMux)

	start := startO11yOAuthLogin(t, loginMux)

	callbackResponse := simulateO11yOAuthBrowserFollowingAuthorizationURL(t, start.AuthorizationURL)
	defer callbackResponse.Body.Close()
	if callbackResponse.StatusCode != http.StatusBadGateway {
		t.Fatalf("callback status = %d, want 502", callbackResponse.StatusCode)
	}

	failed := waitForO11yOAuthLoginPhase(t, o11yOAuthLoginPhaseError)
	if want := "HTTP 401"; !containsString(failed.Error, want) {
		t.Fatalf("error = %q, want to contain %q", failed.Error, want)
	}
}

func TestO11yOAuthLoginRoutesRejectCrossOriginRequests(t *testing.T) {
	resetGlobalO11yOAuthLoginState(t)
	mock := startMockO11yOAuthForLogin(t)
	mock.setEnv(t)

	loginMux := http.NewServeMux()
	registerO11yOAuthLoginRoutes(loginMux)

	for _, route := range []struct {
		method string
		path   string
	}{
		{http.MethodPost, "/api/splunk/o11y-oauth/login"},
		{http.MethodGet, "/api/splunk/o11y-oauth/session"},
		{http.MethodPost, "/api/splunk/o11y-oauth/session/disconnect"},
	} {
		request := httptest.NewRequest(route.method, "http://127.0.0.1:3000"+route.path, nil)
		request.RemoteAddr = "127.0.0.1:54321"
		request.Header.Set("Origin", "https://attacker.example")
		request.Header.Set("Sec-Fetch-Site", "cross-site")
		response := httptest.NewRecorder()
		loginMux.ServeHTTP(response, request)
		if response.Code != http.StatusForbidden {
			t.Fatalf("%s %s cross-origin = %d, want 403", route.method, route.path, response.Code)
		}
	}
}

func TestO11yOAuthLoginRejectsAConcurrentLoginAttempt(t *testing.T) {
	resetGlobalO11yOAuthLoginState(t)
	mock := startMockO11yOAuthForLogin(t)
	mock.setEnv(t)

	loginMux := http.NewServeMux()
	registerO11yOAuthLoginRoutes(loginMux)

	startO11yOAuthLogin(t, loginMux)

	body := `{"realm":"lab0","orgId":"test-org-id","clientId":"the-client-id","clientSecret":"the-client-secret"}`
	second := splunkExportRequest(t, loginMux, http.MethodPost, "/api/splunk/o11y-oauth/login", body)
	if second.Code != http.StatusConflict {
		t.Fatalf("second login start status = %d, want 409", second.Code)
	}

	// The first attempt is still pending (its callback never fired) when this test ends.
	// disconnect() only signals cancellation; the listener's own goroutine releases the
	// fixed port asynchronously afterward (drain delay + Shutdown). Wait for that too, or
	// a later test reusing the same fixed port (including CIMD's) can race this one's
	// teardown. Mirrors sis_cimd_login_test.go's analogous cancellation test.
	globalO11yOAuthLoginState.disconnect()
	waitForSISCIMDCallbackPortRelease(t)
}
