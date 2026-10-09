package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func newO11yOAuthTestMux() *http.ServeMux {
	mux := http.NewServeMux()
	registerO11yOAuthRoutes(mux)
	return mux
}

func TestRegisterO11yOAuthClientRequiresRealm(t *testing.T) {
	response := splunkExportRequest(t, newO11yOAuthTestMux(), http.MethodPost, "/api/splunk/o11y-oauth/register",
		`{"realm":"","adminToken":"admin-token"}`)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
}

func TestRegisterO11yOAuthClientRequiresAdminToken(t *testing.T) {
	response := splunkExportRequest(t, newO11yOAuthTestMux(), http.MethodPost, "/api/splunk/o11y-oauth/register",
		`{"realm":"lab0","adminToken":""}`)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	var body map[string]string
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body["error"] != "paste the admin X-SF-TOKEN" {
		t.Fatalf("unexpected error message: %+v", body)
	}
}

func TestRegisterO11yOAuthClientSucceedsOnNewClient(t *testing.T) {
	var gotAdminToken, gotName, gotDescription, gotCallbackURL string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAdminToken = r.Header.Get("X-SF-TOKEN")
		var payload o11yOAuthClientPayload
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		gotName = payload.Name
		gotDescription = payload.Description
		gotCallbackURL = payload.CallbackURL
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(map[string]string{
			"clientId":     "new-client-id",
			"clientSecret": "one-time-secret",
		})
	}))
	defer upstream.Close()
	t.Setenv("OBSTUDIO_O11Y_OAUTH_REGISTRATION_URL", upstream.URL)

	response := splunkExportRequest(t, newO11yOAuthTestMux(), http.MethodPost, "/api/splunk/o11y-oauth/register",
		`{"realm":"lab0","adminToken":"the-admin-token"}`)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}

	var result o11yOAuthRegisterResult
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result.ClientID != "new-client-id" || !result.Created {
		t.Fatalf("unexpected result: %+v", result)
	}
	if result.ClientSecret != "one-time-secret" {
		t.Fatalf("expected the one-time secret to be forwarded on creation, got %+v", result)
	}
	if gotAdminToken != "the-admin-token" {
		t.Fatalf("admin token not forwarded correctly: %q", gotAdminToken)
	}
	if gotName != o11yOAuthClientName || gotDescription != o11yOAuthClientDescription || gotCallbackURL != o11yOAuthRegistrationCallbackURL {
		t.Fatalf("unexpected registration payload: name=%q description=%q callbackUrl=%q", gotName, gotDescription, gotCallbackURL)
	}
}

func TestRegisterO11yOAuthClientSucceedsOnExistingClientWithoutSecret(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]string{"clientId": "existing-client-id"})
	}))
	defer upstream.Close()
	t.Setenv("OBSTUDIO_O11Y_OAUTH_REGISTRATION_URL", upstream.URL)

	response := splunkExportRequest(t, newO11yOAuthTestMux(), http.MethodPost, "/api/splunk/o11y-oauth/register",
		`{"realm":"lab0","adminToken":"the-admin-token"}`)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}

	var result o11yOAuthRegisterResult
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result.ClientID != "existing-client-id" || result.Created {
		t.Fatalf("unexpected result: %+v", result)
	}
	if result.ClientSecret != "" {
		t.Fatalf("expected no secret for an existing (reused) client, got %+v", result)
	}
}

func TestRegisterO11yOAuthClientDropsSecretFromNonConformingReuseResponse(t *testing.T) {
	// Defensive: the documented contract says a 200 (reuse) response never
	// carries a secret. If a non-conforming server sends one anyway, it must
	// still be dropped rather than passed through.
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]string{
			"clientId":     "existing-client-id",
			"clientSecret": "should-never-be-forwarded",
		})
	}))
	defer upstream.Close()
	t.Setenv("OBSTUDIO_O11Y_OAUTH_REGISTRATION_URL", upstream.URL)

	response := splunkExportRequest(t, newO11yOAuthTestMux(), http.MethodPost, "/api/splunk/o11y-oauth/register",
		`{"realm":"lab0","adminToken":"the-admin-token"}`)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if containsSecret(response.Body.String()) {
		t.Fatalf("secret from a non-conforming reuse response must be dropped: %s", response.Body.String())
	}
}

func TestRegisterO11yOAuthClientSurfacesUpstreamFailureWithoutReflectingBody(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte("sensitive upstream detail that must not leak"))
	}))
	defer upstream.Close()
	t.Setenv("OBSTUDIO_O11Y_OAUTH_REGISTRATION_URL", upstream.URL)

	response := splunkExportRequest(t, newO11yOAuthTestMux(), http.MethodPost, "/api/splunk/o11y-oauth/register",
		`{"realm":"lab0","adminToken":"the-admin-token"}`)
	if response.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if containsSecret(response.Body.String()) {
		t.Fatalf("upstream body must never be reflected: %s", response.Body.String())
	}
}

func TestRegisterO11yOAuthClientDefaultsToLocalMockWithoutOverride(t *testing.T) {
	// No OBSTUDIO_O11Y_OAUTH_REGISTRATION_URL set: resolves to the PoC-stage
	// default rather than a realm-derived production URL, since the real
	// registration server is still blocked. See docs/o11y-oauth-mcp-gateway-impact.md §9.
	if url := resolveO11yOAuthRegistrationURL("lab0"); url != "http://127.0.0.1:9294/v2/sis/oauth/clients" {
		t.Fatalf("unexpected default registration URL: %s", url)
	}
}

func containsSecret(body string) bool {
	return strings.Contains(strings.ToLower(body), "secret")
}
