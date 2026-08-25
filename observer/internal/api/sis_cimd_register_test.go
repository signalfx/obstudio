package api

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"math/big"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type mockSIS struct {
	server              *httptest.Server
	metadata            map[string]any
	discovery           map[string]any
	authorizeStatusCode int
	authorizeLocation   string
	authorizeCookie     string
	caBundlePath        string
}

func startMockSIS(t *testing.T) *mockSIS {
	t.Helper()
	mock := &mockSIS{
		metadata:            map[string]any{},
		discovery:           map[string]any{},
		authorizeStatusCode: http.StatusFound,
		authorizeLocation:   "https://mock-idp.example.test/authorize?client_id=mock-splunkd-client",
		authorizeCookie:     "sis_oauth_session_test-tenant_cimd-demo=cookie-value; Path=/test-tenant/sis/v1/rg/cimd-demo/oauth2; Max-Age=600; HttpOnly; Secure; SameSite=None",
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/oauth/client-metadata.json", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, mock.metadata)
	})
	mux.HandleFunc("/test-tenant/sis/v1/rg/cimd-demo/.well-known/openid-configuration", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, mock.discovery)
	})
	mux.HandleFunc("/test-tenant/sis/v1/rg/cimd-demo/oauth2/authorize", func(w http.ResponseWriter, _ *http.Request) {
		if mock.authorizeLocation != "" {
			w.Header().Set("Location", mock.authorizeLocation)
		}
		if mock.authorizeCookie != "" {
			w.Header().Set("Set-Cookie", mock.authorizeCookie)
		}
		w.WriteHeader(mock.authorizeStatusCode)
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

func writeMockSISCABundle(t *testing.T, server *httptest.Server) string {
	t.Helper()
	certificate := server.Certificate()
	if certificate == nil {
		t.Fatal("mock SIS server has no TLS certificate")
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certificate.Raw})
	path := filepath.Join(t.TempDir(), "mock-sis-ca.pem")
	if err := os.WriteFile(path, pemBytes, 0o600); err != nil {
		t.Fatalf("write mock SIS CA bundle: %v", err)
	}
	return path
}

func (m *mockSIS) config() sisCIMDRegistrationConfig {
	return sisCIMDRegistrationConfig{
		issuer:                  m.server.URL + "/test-tenant/sis/v1/rg/cimd-demo",
		clientID:                m.server.URL + "/oauth/client-metadata.json",
		scope:                   "openid offline_access",
		developmentCABundlePath: m.caBundlePath,
	}
}

func TestRegisterSISCIMDClientReturnsFederatedRedirectAndCookieLifetime(t *testing.T) {
	mock := startMockSIS(t)

	result, err := registerSISCIMDClient(mock.config())
	if err != nil {
		t.Fatalf("registerSISCIMDClient: %v", err)
	}
	if result.Location != mock.authorizeLocation {
		t.Fatalf("location = %q, want %q", result.Location, mock.authorizeLocation)
	}
	if result.CookieMaxAgeSeconds != 600 {
		t.Fatalf("cookieMaxAgeSeconds = %d, want 600", result.CookieMaxAgeSeconds)
	}

	authorizationURL, err := url.Parse(result.AuthorizationURL)
	if err != nil {
		t.Fatal(err)
	}
	query := authorizationURL.Query()
	if query.Get("response_type") != "code" {
		t.Fatalf("response_type = %q, want code", query.Get("response_type"))
	}
	if query.Get("client_id") != mock.config().clientID {
		t.Fatalf("client_id = %q, want %q", query.Get("client_id"), mock.config().clientID)
	}
	if query.Get("code_challenge_method") != "S256" {
		t.Fatalf("code_challenge_method = %q, want S256", query.Get("code_challenge_method"))
	}
}

func TestRegisterSISCIMDClientFailsWhenSISDoesNotRedirect(t *testing.T) {
	mock := startMockSIS(t)
	mock.authorizeStatusCode = http.StatusUnauthorized
	mock.authorizeLocation = ""
	mock.authorizeCookie = ""

	_, err := registerSISCIMDClient(mock.config())
	if err == nil {
		t.Fatal("expected an error")
	}
	if want := "HTTP 401 instead of a redirect"; !containsString(err.Error(), want) {
		t.Fatalf("error = %q, want to contain %q", err.Error(), want)
	}
}

func TestRegisterSISCIMDClientFailsWhenRedirectHasNoSessionCookie(t *testing.T) {
	mock := startMockSIS(t)
	mock.authorizeCookie = ""

	_, err := registerSISCIMDClient(mock.config())
	if err == nil {
		t.Fatal("expected an error")
	}
	if want := "did not return a session cookie"; !containsString(err.Error(), want) {
		t.Fatalf("error = %q, want to contain %q", err.Error(), want)
	}
}

func TestRegisterSISCIMDClientValidatesMetadataAndDiscoveryFirst(t *testing.T) {
	mock := startMockSIS(t)
	mock.metadata["client_id"] = mock.config().clientID + "-different"

	_, err := registerSISCIMDClient(mock.config())
	if err == nil {
		t.Fatal("expected an error")
	}
	if want := "did not exactly match"; !containsString(err.Error(), want) {
		t.Fatalf("error = %q, want to contain %q", err.Error(), want)
	}
}

func TestRegisterSISCIMDClientRejectsMalformedClientID(t *testing.T) {
	mock := startMockSIS(t)
	config := mock.config()
	config.clientID = "not-a-url"

	_, err := registerSISCIMDClient(config)
	if err == nil {
		t.Fatal("expected an error")
	}
	if want := "SIS CIMD client ID"; !containsString(err.Error(), want) {
		t.Fatalf("error = %q, want to contain %q", err.Error(), want)
	}
}

func TestRegisterSISCIMDClientRejectsMalformedExtraRedirectURI(t *testing.T) {
	tests := []struct {
		name  string
		extra string
		want  string
	}{
		{"plaintext non-loopback", "http://evil.example.test/callback", "must use HTTPS or plain loopback HTTP"},
		{"userinfo", "https://user:pass@example.test/callback", "must not contain userinfo"},
		{"malformed", "not a url", "must use HTTPS or plain loopback HTTP"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			mock := startMockSIS(t)
			mock.metadata["redirect_uris"] = []string{sisCIMDRedirectURI, tc.extra}

			_, err := registerSISCIMDClient(mock.config())
			if err == nil {
				t.Fatal("expected an error")
			}
			if !containsString(err.Error(), tc.want) {
				t.Fatalf("error = %q, want to contain %q", err.Error(), tc.want)
			}
		})
	}
}

func TestRegisterSISCIMDClientRejectsUnsafeDiscoveryEndpoints(t *testing.T) {
	tests := []struct {
		name  string
		field string
		value string
		want  string
	}{
		{"authorization endpoint plaintext non-loopback", "authorization_endpoint", "http://evil.example.test/authorize", "may use HTTP only for loopback development hosts"},
		{"token endpoint plaintext non-loopback", "token_endpoint", "http://evil.example.test/token", "may use HTTP only for loopback development hosts"},
		{"token endpoint userinfo", "token_endpoint", "https://user:pass@sis.example.test/token", "must not contain userinfo or a fragment"},
		{"token endpoint fragment", "token_endpoint", "https://sis.example.test/token#frag", "must not contain userinfo or a fragment"},
		{"token endpoint relative", "token_endpoint", "/oauth2/token", "must be an absolute URL"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			mock := startMockSIS(t)
			mock.discovery[tc.field] = tc.value

			_, err := registerSISCIMDClient(mock.config())
			if err == nil {
				t.Fatal("expected an error")
			}
			if !containsString(err.Error(), tc.want) {
				t.Fatalf("error = %q, want to contain %q", err.Error(), tc.want)
			}
		})
	}
}

func TestRegisterSISCIMDClientExplainsAStaleDevelopmentCABundle(t *testing.T) {
	mock := startMockSIS(t)
	config := mock.config()
	// Point at a CA bundle that does not certify the mock server's actual certificate --
	// simulating the real-world case where SIS's or the metadata doc server's self-signed
	// cert was regenerated after the bundle was captured.
	config.developmentCABundlePath = writeUnrelatedCABundle(t)

	_, err := registerSISCIMDClient(config)
	if err == nil {
		t.Fatal("expected an error")
	}
	for _, want := range []string{"not trusted", "regenerated", config.developmentCABundlePath} {
		if !containsString(err.Error(), want) {
			t.Fatalf("error = %q, want to contain %q", err.Error(), want)
		}
	}
}

// writeUnrelatedCABundle writes a PEM bundle containing a self-signed CA certificate that
// does not certify the mock SIS server's certificate, so a client trusting only this
// bundle genuinely fails TLS verification -- unlike httptest.NewTLSServer, which reuses
// one built-in certificate across every server it starts.
func writeUnrelatedCABundle(t *testing.T) string {
	t.Helper()
	template := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "Unrelated Test CA"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(time.Hour),
		IsCA:                  true,
		KeyUsage:              x509.KeyUsageCertSign,
		BasicConstraintsValid: true,
	}
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("generate unrelated CA key: %v", err)
	}
	derBytes, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("create unrelated CA certificate: %v", err)
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: derBytes})
	path := filepath.Join(t.TempDir(), "unrelated-ca.pem")
	if err := os.WriteFile(path, pemBytes, 0o600); err != nil {
		t.Fatalf("write unrelated CA bundle: %v", err)
	}
	return path
}

func TestLoadSISCIMDRegistrationConfigFallsBackToLocalDefaults(t *testing.T) {
	for _, key := range []string{
		"OBSTUDIO_SIS_CIMD_OAUTH_ISSUER",
		"OBSTUDIO_SIS_CIMD_OAUTH_CLIENT_ID",
		"OBSTUDIO_SIS_CIMD_OAUTH_SCOPE",
		"OBSTUDIO_SIS_CIMD_OAUTH_DEVELOPMENT_CA_BUNDLE_PATH",
	} {
		t.Setenv(key, "")
	}
	config := loadSISCIMDRegistrationConfig()
	if config.issuer != "https://127.0.0.1:9090/test-tenant/sis/v1/rg/cimd-demo" {
		t.Fatalf("issuer default = %q", config.issuer)
	}
	if config.clientID != "https://127.0.0.1:9192/oauth/client-metadata.json" {
		t.Fatalf("clientID default = %q", config.clientID)
	}
	if config.scope != "openid offline_access" {
		t.Fatalf("scope default = %q", config.scope)
	}

	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_ISSUER", "https://sis.example.test/tenant/sis/v1/rg/demo")
	overridden := loadSISCIMDRegistrationConfig()
	if overridden.issuer != "https://sis.example.test/tenant/sis/v1/rg/demo" {
		t.Fatalf("issuer override = %q", overridden.issuer)
	}
}

func TestRegisterSISCIMDClientHandlerReportsRegistrationResult(t *testing.T) {
	mock := startMockSIS(t)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_ISSUER", mock.config().issuer)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_CLIENT_ID", mock.config().clientID)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_SCOPE", mock.config().scope)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_DEVELOPMENT_CA_BUNDLE_PATH", mock.config().developmentCABundlePath)
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	mux := http.NewServeMux()
	registerSISCIMDLoginRoutes(mux)
	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/cimd/register", "", testObserverControlToken)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	var result sisCIMDRegistrationResult
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result.CookieMaxAgeSeconds != 600 {
		t.Fatalf("cookieMaxAgeSeconds = %d, want 600", result.CookieMaxAgeSeconds)
	}
	if origin := response.Header().Get("Access-Control-Allow-Origin"); origin != "" {
		t.Fatalf("Access-Control-Allow-Origin = %q, want no wildcard CORS header on this response", origin)
	}
}

func TestRegisterSISCIMDClientHandlerRequiresControlToken(t *testing.T) {
	mock := startMockSIS(t)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_ISSUER", mock.config().issuer)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_CLIENT_ID", mock.config().clientID)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_SCOPE", mock.config().scope)
	t.Setenv("OBSTUDIO_SIS_CIMD_OAUTH_DEVELOPMENT_CA_BUNDLE_PATH", mock.config().developmentCABundlePath)
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

	mux := http.NewServeMux()
	registerSISCIMDLoginRoutes(mux)

	// A cross-site request has no way to obtain the control token (it is injected only
	// into Observer's own same-origin page), so an unauthenticated POST -- as an
	// attacker-controlled page could send -- must not trigger the outbound SIS probe.
	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/cimd/register", "", "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", response.Code)
	}
}

func containsString(haystack, needle string) bool {
	return strings.Contains(haystack, needle)
}
