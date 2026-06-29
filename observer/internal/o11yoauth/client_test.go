package o11yoauth

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestLoginAuthorizationCodePKCE(t *testing.T) {
	t.Parallel()

	var issuer string
	var challenge string
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/.well-known/oauth-authorization-server":
			writeTestJSON(t, response, metadataFixture(issuer))
		case "/v2/oauth/token":
			if err := request.ParseForm(); err != nil {
				t.Fatalf("parse token form: %v", err)
			}
			if request.Form.Get("grant_type") != "authorization_code" || request.Form.Get("client_id") != "obstudio-cli" {
				t.Errorf("unexpected token form: %v", request.Form)
			}
			digest := sha256.Sum256([]byte(request.Form.Get("code_verifier")))
			if base64.RawURLEncoding.EncodeToString(digest[:]) != challenge {
				t.Error("token exchange did not use the PKCE verifier from the authorization request")
			}
			response.Header().Set("Cache-Control", "no-store")
			writeTestJSON(t, response, map[string]any{
				"access_token":           "secret-token",
				"expires_in":             3600,
				"scope":                  "ingest api",
				"splunk_ingest_endpoint": "https://ingest.lab0.signalfx.com",
				"splunk_issuer":          issuer,
				"splunk_org_id":          "org-1",
				"splunk_org_name":        "Example Org",
				"splunk_realm":           "lab0",
				"splunk_token_id":        "token-1",
				"splunk_token_name":      "Obstudio test",
				"token_type":             "Bearer",
			})
		default:
			http.NotFound(response, request)
		}
	}))
	defer server.Close()
	issuer = server.URL

	callbackDone := make(chan error, 1)
	connection, err := Login(context.Background(), Options{
		ClientID:   "obstudio-cli",
		HTTPClient: server.Client(),
		IssuerURL:  issuer,
		OpenBrowser: func(rawAuthorizationURL string) error {
			authorizationURL, err := url.Parse(rawAuthorizationURL)
			if err != nil {
				return err
			}
			query := authorizationURL.Query()
			challenge = query.Get("code_challenge")
			if query.Get("code_challenge_method") != "S256" || query.Get("response_type") != "code" {
				t.Errorf("unexpected authorization request: %v", query)
			}
			go func() {
				callbackURL, parseErr := url.Parse(query.Get("redirect_uri"))
				if parseErr != nil {
					callbackDone <- parseErr
					return
				}
				callbackQuery := callbackURL.Query()
				callbackQuery.Set("code", "authorization-code")
				callbackQuery.Set("iss", issuer)
				callbackQuery.Set("state", query.Get("state"))
				callbackURL.RawQuery = callbackQuery.Encode()
				response, getErr := http.Get(callbackURL.String())
				if getErr == nil {
					_ = response.Body.Close()
				}
				callbackDone <- getErr
			}()
			return nil
		},
		RequiredScope: "ingest",
		Scope:         "ingest api",
		Timeout:       2 * time.Second,
		TokenName:     "Obstudio test",
	})
	if err != nil {
		t.Fatalf("Login() error = %v", err)
	}
	if err := <-callbackDone; err != nil {
		t.Fatalf("callback error = %v", err)
	}
	if connection.AccessToken != "secret-token" || connection.OrgID != "org-1" || connection.Realm != "lab0" {
		t.Fatalf("unexpected connection: %+v", connection)
	}
}

func TestDiscoverRejectsRedirect(t *testing.T) {
	t.Parallel()
	redirectTarget := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		writeTestJSON(t, response, map[string]string{"issuer": "attacker"})
	}))
	defer redirectTarget.Close()
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		http.Redirect(response, request, redirectTarget.URL, http.StatusFound)
	}))
	defer server.Close()

	_, err := Discover(context.Background(), server.URL, server.Client())
	if err == nil || !strings.Contains(err.Error(), "HTTP 302") {
		t.Fatalf("Discover() error = %v, want redirect rejection", err)
	}
}

func TestNormalizeIssuer(t *testing.T) {
	t.Parallel()
	tests := []struct {
		raw  string
		want string
	}{
		{"https://APP.EU0.observability.splunkcloud.com/#/home", "https://app.eu0.observability.splunkcloud.com"},
		{"https://app.us1.signalfx.com/path", "https://app.us1.signalfx.com"},
		{"https://mon.signalfx.com/#/signin", "https://mon.signalfx.com"},
		{"http://127.0.0.1:3000/#/home", "http://127.0.0.1:3000"},
	}
	for _, test := range tests {
		got, err := NormalizeIssuer(test.raw)
		if err != nil || got != test.want {
			t.Errorf("NormalizeIssuer(%q) = %q, %v; want %q", test.raw, got, err, test.want)
		}
	}
	for _, raw := range []string{"https://attacker.example", "http://app.us0.signalfx.com", "file:///tmp/issuer"} {
		if _, err := NormalizeIssuer(raw); err == nil {
			t.Errorf("NormalizeIssuer(%q) unexpectedly succeeded", raw)
		}
	}
}

func TestConnectionFromTokenRequiresApprovedScopesAndRealm(t *testing.T) {
	t.Parallel()
	base := tokenResponse{
		AccessToken:          "secret",
		Scope:                "ingest",
		SplunkIngestEndpoint: "https://ingest.us1.signalfx.com",
		SplunkIssuer:         "https://app.us1.signalfx.com",
		SplunkRealm:          "us1",
		TokenType:            "Bearer",
	}
	if _, err := connectionFromToken(base, "ingest api", "ingest", base.SplunkIssuer); err != nil {
		t.Fatalf("connectionFromToken() error = %v", err)
	}
	missingRequired := base
	missingRequired.Scope = "api"
	if _, err := connectionFromToken(missingRequired, "ingest api", "ingest", base.SplunkIssuer); err == nil {
		t.Fatal("connectionFromToken() accepted a token without the required scope")
	}
	wrongRealm := base
	wrongRealm.SplunkIngestEndpoint = "https://ingest.eu0.signalfx.com"
	if _, err := connectionFromToken(wrongRealm, "ingest", "ingest", base.SplunkIssuer); err == nil {
		t.Fatal("connectionFromToken() accepted an endpoint for a different realm")
	}
}

func TestHandleCallbackRejectsDuplicateState(t *testing.T) {
	t.Parallel()
	request := httptest.NewRequest(http.MethodGet, "http://127.0.0.1/callback?state=expected&state=duplicate&iss=http%3A%2F%2F127.0.0.1&code=code", nil)
	response := httptest.NewRecorder()
	callbacks := make(chan callbackRequest, 1)
	var accepted atomic.Bool
	handleCallback(response, request, "http://127.0.0.1", "http://127.0.0.1/callback", "expected", callbacks, &accepted)
	if response.Code != http.StatusBadRequest || accepted.Load() {
		t.Fatalf("duplicate state response = %d, accepted = %v", response.Code, accepted.Load())
	}
}

func TestHandleCallbackReportsProviderDenial(t *testing.T) {
	t.Parallel()
	request := httptest.NewRequest(http.MethodGet, "http://127.0.0.1/callback?state=expected&iss=http%3A%2F%2F127.0.0.1&error=access_denied&error_description=Denied", nil)
	response := httptest.NewRecorder()
	callbacks := make(chan callbackRequest, 1)
	var accepted atomic.Bool
	handleCallback(response, request, "http://127.0.0.1", "http://127.0.0.1/callback", "expected", callbacks, &accepted)
	callback := <-callbacks
	if response.Code != http.StatusBadRequest || callback.err == nil || !strings.Contains(callback.err.Error(), "access_denied") {
		t.Fatalf("provider denial response = %d, callback error = %v", response.Code, callback.err)
	}
}

func TestValidateConnectionRejectsUntrustedIngestEndpoint(t *testing.T) {
	t.Parallel()
	connection := Connection{
		AccessToken: "secret",
		Endpoint:    "https://attacker.example",
		Issuer:      "https://app.us1.signalfx.com",
		Realm:       "us1",
		TokenType:   "Bearer",
	}
	if err := ValidateConnection(connection); err == nil {
		t.Fatal("ValidateConnection() accepted an untrusted ingest endpoint")
	}
}

func TestValidateConnectionAcceptsTrustedInternalIssuerAndIngestEndpoint(t *testing.T) {
	t.Parallel()
	connection := Connection{
		AccessToken: "secret",
		Endpoint:    "https://mon-ingest.signalfx.com",
		Issuer:      "https://mon.signalfx.com",
		Realm:       "mon0",
		TokenType:   "Bearer",
	}
	if err := ValidateConnection(connection); err != nil {
		t.Fatalf("ValidateConnection() rejected trusted internal connection: %v", err)
	}
}

func TestValidateConnectionRejectsNonCanonicalIngestEndpoint(t *testing.T) {
	t.Parallel()
	for _, endpoint := range []string{
		"https://ingest.us1.signalfx.com:8443",
		"https://ingest.us1.signalfx.com/v2/datapoint/otlp",
		"https://ingest.us1.signalfx.com?token=unexpected",
	} {
		connection := Connection{
			AccessToken: "secret",
			Endpoint:    endpoint,
			Issuer:      "https://app.us1.signalfx.com",
			Realm:       "us1",
			TokenType:   "Bearer",
		}
		if err := ValidateConnection(connection); err == nil {
			t.Errorf("ValidateConnection() accepted non-canonical endpoint %q", endpoint)
		}
	}
}

func TestConnectionUsableRequiresScopeAndUnexpiredToken(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, time.June, 29, 12, 0, 0, 0, time.UTC)
	connection := Connection{
		AccessToken: "secret",
		Endpoint:    "https://ingest.us1.signalfx.com",
		ExpiresAt:   now.Add(10 * time.Minute).Format(time.RFC3339Nano),
		Issuer:      "https://app.us1.signalfx.com",
		Realm:       "us1",
		Scope:       "api ingest",
		TokenType:   "Bearer",
	}
	if !ConnectionUsable(connection, "ingest", now, time.Minute) {
		t.Fatal("ConnectionUsable() rejected a valid connection")
	}
	if ConnectionUsable(connection, "admin", now, time.Minute) {
		t.Fatal("ConnectionUsable() accepted a connection without the required scope")
	}
	connection.ExpiresAt = now.Add(30 * time.Second).Format(time.RFC3339Nano)
	if ConnectionUsable(connection, "ingest", now, time.Minute) {
		t.Fatal("ConnectionUsable() accepted a connection inside the expiry skew")
	}
}

func metadataFixture(issuer string) map[string]any {
	return map[string]any{
		"authorization_endpoint":                         issuer + "/oauth/authorize",
		"authorization_response_iss_parameter_supported": true,
		"code_challenge_methods_supported":               []string{"S256"},
		"grant_types_supported":                          []string{"authorization_code"},
		"issuer":                                         issuer,
		"response_modes_supported":                       []string{"query"},
		"response_types_supported":                       []string{"code"},
		"revocation_endpoint":                            issuer + "/v2/oauth/revoke",
		"revocation_endpoint_auth_methods_supported":     []string{"none"},
		"scopes_supported":                               []string{"ingest", "api"},
		"token_endpoint":                                 issuer + "/v2/oauth/token",
		"token_endpoint_auth_methods_supported":          []string{"none"},
	}
}

func writeTestJSON(t *testing.T, response http.ResponseWriter, value any) {
	t.Helper()
	response.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(response).Encode(value); err != nil {
		t.Fatalf("encode test response: %v", err)
	}
}
