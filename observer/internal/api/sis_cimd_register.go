package api

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// TODO(CIMD PoC): This mirrors extension/src/sis-cimd-oauth.ts's registerClientWithSIS
// and its metadata/discovery validation, kept as a second implementation so Observer's
// own web UI can probe SIS CIMD registration without a VS Code bridge (e.g. the
// `go run ./cmd/obstudio` + browser dev loop). It deliberately stops at the federated
// authorization redirect -- it does not follow it into IDP login. If these two
// implementations drift, prefer the TypeScript one as the more heavily tested source of
// truth and port fixes here.

const (
	sisCIMDDefaultRequestTimeout = 15 * time.Second
	sisCIMDMaxResponseBodyBytes  = 64 * 1024
	sisCIMDRedirectURI           = "http://127.0.0.1:33418/callback"
)

// sisCIMDRegistrationConfig is read from environment variables so Observer's standalone
// web UI has a source of truth independent of any VS Code settings. When Observer is
// launched by the extension, the extension's own settings take precedence in the
// browser: CloudTab.tsx prefers the bridge's response over this endpoint whenever a
// bridge is present.
type sisCIMDRegistrationConfig struct {
	issuer                  string
	clientID                string
	scope                   string
	developmentCABundlePath string
}

func loadSISCIMDRegistrationConfig() sisCIMDRegistrationConfig {
	issuer := strings.TrimSpace(os.Getenv("OBSTUDIO_SIS_CIMD_OAUTH_ISSUER"))
	if issuer == "" {
		issuer = "https://127.0.0.1:9090/test-tenant/sis/v1/rg/cimd-demo"
	}
	clientID := strings.TrimSpace(os.Getenv("OBSTUDIO_SIS_CIMD_OAUTH_CLIENT_ID"))
	if clientID == "" {
		clientID = "https://127.0.0.1:9192/oauth/client-metadata.json"
	}
	scope := strings.TrimSpace(os.Getenv("OBSTUDIO_SIS_CIMD_OAUTH_SCOPE"))
	if scope == "" {
		scope = "openid offline_access"
	}
	return sisCIMDRegistrationConfig{
		issuer:                  issuer,
		clientID:                clientID,
		scope:                   scope,
		developmentCABundlePath: strings.TrimSpace(os.Getenv("OBSTUDIO_SIS_CIMD_OAUTH_DEVELOPMENT_CA_BUNDLE_PATH")),
	}
}

type sisCIMDRegistrationResult struct {
	AuthorizationURL    string `json:"authorizationUrl"`
	Location            string `json:"location"`
	CookieMaxAgeSeconds int    `json:"cookieMaxAgeSeconds"`
}

type sisCIMDClientMetadata struct {
	ClientID                string   `json:"client_id"`
	RedirectURIs            []string `json:"redirect_uris"`
	GrantTypes              []string `json:"grant_types,omitempty"`
	ResponseTypes           []string `json:"response_types,omitempty"`
	Scope                   string   `json:"scope"`
	TokenEndpointAuthMethod string   `json:"token_endpoint_auth_method,omitempty"`
}

type sisCIMDDiscoveryDocument struct {
	Issuer                            string   `json:"issuer"`
	AuthorizationEndpoint             string   `json:"authorization_endpoint"`
	TokenEndpoint                     string   `json:"token_endpoint"`
	RegistrationEndpoint              *string  `json:"registration_endpoint,omitempty"`
	ClientIDMetadataDocumentSupported bool     `json:"client_id_metadata_document_supported"`
	CodeChallengeMethodsSupported     []string `json:"code_challenge_methods_supported"`
	GrantTypesSupported               []string `json:"grant_types_supported"`
	ResponseTypesSupported            []string `json:"response_types_supported"`
	ScopesSupported                   []string `json:"scopes_supported"`
	TokenEndpointAuthMethodsSupported []string `json:"token_endpoint_auth_methods_supported"`
}

func registerSISCIMDClient(config sisCIMDRegistrationConfig) (*sisCIMDRegistrationResult, error) {
	client, discovery, err := resolveSISCIMDClientAndDiscovery(config)
	if err != nil {
		return nil, err
	}

	authorizationURL, _, _, err := buildSISCIMDAuthorizationURL(discovery.AuthorizationEndpoint, config)
	if err != nil {
		return nil, err
	}

	request, err := http.NewRequest(http.MethodGet, authorizationURL, nil)
	if err != nil {
		return nil, fmt.Errorf("build SIS authorization request: %w", err)
	}
	response, err := client.Do(request)
	if err != nil {
		return nil, wrapSISCIMDRequestError("call SIS authorization endpoint", err, config)
	}
	defer response.Body.Close()
	_, _ = io.CopyN(io.Discard, response.Body, sisCIMDMaxResponseBodyBytes)

	if response.StatusCode != http.StatusFound {
		return nil, fmt.Errorf("SIS authorization endpoint returned HTTP %d instead of a redirect", response.StatusCode)
	}
	location := response.Header.Get("Location")
	if location == "" {
		return nil, errors.New("SIS authorization endpoint did not return a Location header")
	}
	cookieMaxAge, ok := sisCIMDCookieMaxAgeSeconds(response.Header.Values("Set-Cookie"))
	if !ok {
		return nil, errors.New("SIS authorization endpoint did not return a session cookie with a Max-Age")
	}

	return &sisCIMDRegistrationResult{
		AuthorizationURL:    authorizationURL,
		Location:            location,
		CookieMaxAgeSeconds: cookieMaxAge,
	}, nil
}

// wrapSISCIMDRequestError recognizes a TLS trust failure against a configured
// development CA bundle and rewrites it into an actionable message. Untrusted local
// self-signed certs (SIS, the metadata-doc server) are the single most common way this
// probe fails during local dev -- typically because the certs were regenerated after the
// bundle was captured -- so this is worth naming explicitly rather than surfacing Go's
// generic "certificate signed by unknown authority" wrapped inside a network error.
func wrapSISCIMDRequestError(action string, err error, config sisCIMDRegistrationConfig) error {
	var unknownAuthorityErr x509.UnknownAuthorityError
	if errors.As(err, &unknownAuthorityErr) {
		if config.developmentCABundlePath == "" {
			return fmt.Errorf(
				"%s: TLS certificate is not trusted. If SIS and the CIMD metadata document use "+
					"self-signed certificates for local development, set "+
					"OBSTUDIO_SIS_CIMD_OAUTH_DEVELOPMENT_CA_BUNDLE_PATH to a PEM bundle containing them: %w",
				action, err,
			)
		}
		return fmt.Errorf(
			"%s: TLS certificate is not trusted by the configured development CA bundle (%s). "+
				"The certificate may have been regenerated since the bundle was created -- "+
				"refresh it with the current SIS and CIMD metadata document certificates: %w",
			action, config.developmentCABundlePath, err,
		)
	}
	return fmt.Errorf("%s: %w", action, err)
}

// validateSISCIMDClientID mirrors validateClientID in sis-cimd-oauth.ts.
func validateSISCIMDClientID(rawClientID string) error {
	invalid := errors.New("SIS CIMD client ID must be an exact HTTPS URL")
	if rawClientID == "" ||
		len(rawClientID) > 512 ||
		rawClientID != strings.TrimSpace(rawClientID) ||
		!strings.HasPrefix(rawClientID, "https://") ||
		strings.Contains(rawClientID, "?") ||
		strings.Contains(rawClientID, "#") {
		return invalid
	}
	parsed, err := url.Parse(rawClientID)
	if err != nil || parsed.Scheme != "https" || parsed.Hostname() == "" {
		return invalid
	}
	if parsed.User != nil {
		return errors.New("SIS CIMD client ID must not contain userinfo, a query, or a fragment")
	}
	if parsed.Path == "" || parsed.Path == "/" {
		return errors.New("SIS CIMD client ID must include a non-root path")
	}
	return nil
}

// validateSISCIMDIssuer mirrors normalizeIssuer in sis-cimd-oauth.ts (validation only;
// the configured issuer is used as-is rather than re-normalized, since it is
// operator-set, not user-typed).
func validateSISCIMDIssuer(rawIssuer string) error {
	if rawIssuer == "" ||
		rawIssuer != strings.TrimSpace(rawIssuer) ||
		strings.Contains(rawIssuer, "?") ||
		strings.Contains(rawIssuer, "#") {
		return errors.New("SIS issuer is required and must not contain surrounding whitespace")
	}
	parsed, err := url.Parse(rawIssuer)
	if err != nil {
		return errors.New("SIS issuer must be an absolute URL")
	}
	if parsed.User != nil {
		return errors.New("SIS issuer must not contain userinfo, a query, or a fragment")
	}
	if parsed.Scheme == "http" {
		if !sisCIMDIsLoopbackHost(parsed.Hostname()) {
			return errors.New("SIS issuer may use HTTP only for loopback development hosts")
		}
	} else if parsed.Scheme != "https" {
		return errors.New("SIS issuer must use HTTPS")
	}
	return nil
}

// validateSISCIMDOAuthEndpoint mirrors validateOAuthEndpoint in sis-cimd-oauth.ts. A
// discovered endpoint is operator-controlled input (fetched from the configured issuer,
// not typed by a user), but it still must not be trusted blindly: a malicious or
// compromised SIS could otherwise redirect the authorization code and PKCE verifier to
// an arbitrary plaintext or third-party URL via discovery.
func validateSISCIMDOAuthEndpoint(rawURL string, field string) error {
	if rawURL == "" {
		return fmt.Errorf("SIS discovery %s is missing", field)
	}
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return fmt.Errorf("SIS discovery %s is invalid", field)
	}
	if !parsed.IsAbs() || parsed.Host == "" {
		return fmt.Errorf("SIS discovery %s must be an absolute URL", field)
	}
	if parsed.User != nil || parsed.Fragment != "" {
		return fmt.Errorf("SIS discovery %s must not contain userinfo or a fragment", field)
	}
	if parsed.Scheme == "http" {
		if !sisCIMDIsLoopbackHost(parsed.Hostname()) {
			return fmt.Errorf("SIS discovery %s may use HTTP only for loopback development hosts", field)
		}
	} else if parsed.Scheme != "https" {
		return fmt.Errorf("SIS discovery %s must use HTTPS", field)
	}
	return nil
}

// validateSISCIMDMetadataRedirectURI mirrors validateMetadataRedirectUri in
// sis-cimd-oauth.ts. Every declared redirect URI must be validated, not just the fixed
// loopback callback -- otherwise a malformed or malicious extra entry (e.g. a
// non-loopback plaintext URL, or one carrying userinfo) would be accepted as part of a
// document that is only "safe" because it also happens to include our own callback.
func validateSISCIMDMetadataRedirectURI(rawURL string) error {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return fmt.Errorf("CIMD client metadata redirect URI %q is invalid", rawURL)
	}
	if parsed.User != nil {
		return errors.New("CIMD client metadata redirect URIs must not contain userinfo")
	}
	if strings.HasPrefix(rawURL, "https://") && parsed.Scheme == "https" {
		return nil
	}
	if strings.HasPrefix(rawURL, "http://") && parsed.Scheme == "http" && sisCIMDIsLoopbackHost(parsed.Hostname()) {
		return nil
	}
	return errors.New("CIMD client metadata redirect URIs must use HTTPS or plain loopback HTTP")
}

func validateSISCIMDClientMetadata(metadata sisCIMDClientMetadata, config sisCIMDRegistrationConfig) error {
	if metadata.ClientID != config.clientID {
		return errors.New("CIMD client metadata client_id did not exactly match its URL")
	}
	if len(metadata.RedirectURIs) == 0 {
		return errors.New("CIMD client metadata redirect_uris must be a non-empty string array")
	}
	for _, redirectURI := range metadata.RedirectURIs {
		if err := validateSISCIMDMetadataRedirectURI(redirectURI); err != nil {
			return err
		}
	}
	if !sisCIMDContains(metadata.RedirectURIs, sisCIMDRedirectURI) {
		return errors.New("CIMD client metadata does not declare the fixed loopback callback")
	}
	if metadata.TokenEndpointAuthMethod != "" && metadata.TokenEndpointAuthMethod != "none" {
		return errors.New(`CIMD clients must use token_endpoint_auth_method "none"`)
	}
	if len(metadata.GrantTypes) > 0 && !sisCIMDContains(metadata.GrantTypes, "authorization_code") {
		return errors.New("CIMD client metadata must allow the authorization_code grant")
	}
	if len(metadata.ResponseTypes) > 0 && !sisCIMDContains(metadata.ResponseTypes, "code") {
		return errors.New("CIMD client metadata must allow the code response type")
	}
	if metadata.Scope == "" {
		return errors.New("CIMD client metadata scope must be a string")
	}
	declaredScopes := sisCIMDScopeSet(metadata.Scope)
	for _, requestedScope := range sisCIMDScopeSet(config.scope) {
		if !sisCIMDContains(declaredScopes, requestedScope) {
			return fmt.Errorf("CIMD client metadata does not declare requested scope %q", requestedScope)
		}
	}
	return nil
}

func validateSISCIMDDiscoveryDocument(discovery sisCIMDDiscoveryDocument, config sisCIMDRegistrationConfig) error {
	if discovery.Issuer != config.issuer {
		return errors.New("SIS discovery issuer did not exactly match the configured issuer")
	}
	if !discovery.ClientIDMetadataDocumentSupported {
		return errors.New("SIS discovery does not advertise CIMD support")
	}
	if discovery.RegistrationEndpoint != nil {
		return errors.New("SIS discovery unexpectedly advertises dynamic client registration")
	}
	if !sisCIMDContains(discovery.TokenEndpointAuthMethodsSupported, "none") {
		return errors.New(`SIS discovery does not support token endpoint auth method "none"`)
	}
	if !sisCIMDContains(discovery.GrantTypesSupported, "authorization_code") {
		return errors.New("SIS discovery does not support grant type \"authorization_code\"")
	}
	if !sisCIMDContains(discovery.ResponseTypesSupported, "code") {
		return errors.New("SIS discovery does not support response type \"code\"")
	}
	if !sisCIMDContains(discovery.CodeChallengeMethodsSupported, "S256") {
		return errors.New(`SIS discovery does not support PKCE method "S256"`)
	}
	supportedScopes := discovery.ScopesSupported
	for _, requestedScope := range sisCIMDScopeSet(config.scope) {
		if !sisCIMDContains(supportedScopes, requestedScope) {
			return fmt.Errorf("SIS discovery does not support requested scope %q", requestedScope)
		}
	}
	if err := validateSISCIMDOAuthEndpoint(discovery.AuthorizationEndpoint, "authorization_endpoint"); err != nil {
		return err
	}
	if err := validateSISCIMDOAuthEndpoint(discovery.TokenEndpoint, "token_endpoint"); err != nil {
		return err
	}
	return nil
}

// resolveSISCIMDClientAndDiscovery fetches and cross-validates the CIMD client metadata
// document and SIS discovery document, and returns an HTTP client configured for any
// development CA bundle. Shared by the registration probe and the login flow below --
// both must resolve the same trusted endpoints before doing anything else.
func resolveSISCIMDClientAndDiscovery(
	config sisCIMDRegistrationConfig,
) (*http.Client, *sisCIMDDiscoveryDocument, error) {
	if err := validateSISCIMDClientID(config.clientID); err != nil {
		return nil, nil, err
	}
	if err := validateSISCIMDIssuer(config.issuer); err != nil {
		return nil, nil, err
	}

	client, err := sisCIMDHTTPClient(config)
	if err != nil {
		return nil, nil, err
	}

	metadataResponse, err := sisCIMDGet(client, config.clientID)
	if err != nil {
		return nil, nil, wrapSISCIMDRequestError("fetch CIMD client metadata", err, config)
	}
	var metadata sisCIMDClientMetadata
	if err := sisCIMDDecodeJSON(metadataResponse, &metadata); err != nil {
		return nil, nil, fmt.Errorf("CIMD client metadata: %w", err)
	}
	if err := validateSISCIMDClientMetadata(metadata, config); err != nil {
		return nil, nil, err
	}

	discoveryURL := strings.TrimSuffix(config.issuer, "/") + "/.well-known/openid-configuration"
	discoveryResponse, err := sisCIMDGet(client, discoveryURL)
	if err != nil {
		return nil, nil, wrapSISCIMDRequestError("fetch SIS discovery document", err, config)
	}
	var discovery sisCIMDDiscoveryDocument
	if err := sisCIMDDecodeJSON(discoveryResponse, &discovery); err != nil {
		return nil, nil, fmt.Errorf("SIS discovery document: %w", err)
	}
	if err := validateSISCIMDDiscoveryDocument(discovery, config); err != nil {
		return nil, nil, err
	}

	return client, &discovery, nil
}

// buildSISCIMDAuthorizationURL returns the PKCE authorization URL along with the state
// and verifier the caller must retain: state to bind the eventual callback to this
// request, verifier to exchange the returned code for tokens.
func buildSISCIMDAuthorizationURL(
	authorizationEndpoint string,
	config sisCIMDRegistrationConfig,
) (authorizationURL string, state string, verifier string, err error) {
	endpoint, err := url.Parse(authorizationEndpoint)
	if err != nil {
		return "", "", "", fmt.Errorf("SIS discovery authorization_endpoint is invalid: %w", err)
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
	query.Set("client_id", config.clientID)
	query.Set("redirect_uri", sisCIMDRedirectURI)
	query.Set("scope", config.scope)
	query.Set("state", state)
	query.Set("code_challenge", challenge)
	query.Set("code_challenge_method", "S256")
	endpoint.RawQuery = query.Encode()
	return endpoint.String(), state, verifier, nil
}

func sisCIMDHTTPClient(config sisCIMDRegistrationConfig) (*http.Client, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	if config.developmentCABundlePath != "" {
		if err := requireSISCIMDLoopbackDevelopmentHosts(config); err != nil {
			return nil, err
		}
		pool, err := x509.SystemCertPool()
		if err != nil || pool == nil {
			pool = x509.NewCertPool()
		}
		bundle, err := os.ReadFile(config.developmentCABundlePath)
		if err != nil {
			return nil, fmt.Errorf("read SIS development CA bundle: %w", err)
		}
		if !pool.AppendCertsFromPEM(bundle) {
			return nil, errors.New("SIS development CA bundle is not valid PEM certificate data")
		}
		transport.TLSClientConfig = &tls.Config{RootCAs: pool}
	}
	return &http.Client{
		Transport: transport,
		Timeout:   sisCIMDDefaultRequestTimeout,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}, nil
}

func requireSISCIMDLoopbackDevelopmentHosts(config sisCIMDRegistrationConfig) error {
	issuerHost, err := sisCIMDHostname(config.issuer)
	if err != nil {
		return err
	}
	clientHost, err := sisCIMDHostname(config.clientID)
	if err != nil {
		return err
	}
	if !sisCIMDIsLoopbackHost(issuerHost) || !sisCIMDIsLoopbackHost(clientHost) {
		return errors.New(
			"the SIS development CA bundle may be used only when both the issuer and client ID use loopback hosts",
		)
	}
	return nil
}

func sisCIMDHostname(rawURL string) (string, error) {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return "", fmt.Errorf("parse URL %q: %w", rawURL, err)
	}
	return parsed.Hostname(), nil
}

func sisCIMDIsLoopbackHost(hostname string) bool {
	if strings.EqualFold(hostname, "localhost") {
		return true
	}
	ip := net.ParseIP(hostname)
	return ip != nil && ip.IsLoopback()
}

func sisCIMDGet(client *http.Client, rawURL string) (*http.Response, error) {
	request, err := http.NewRequest(http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, err
	}
	return client.Do(request)
}

func sisCIMDDecodeJSON(response *http.Response, destination any) error {
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("request failed with HTTP %d", response.StatusCode)
	}
	limited := io.LimitReader(response.Body, sisCIMDMaxResponseBodyBytes+1)
	body, err := io.ReadAll(limited)
	if err != nil {
		return fmt.Errorf("read response body: %w", err)
	}
	if len(body) > sisCIMDMaxResponseBodyBytes {
		return errors.New("response exceeded the 64 KiB limit")
	}
	if err := json.Unmarshal(body, destination); err != nil {
		return fmt.Errorf("response was not valid JSON: %w", err)
	}
	return nil
}

func sisCIMDCookieMaxAgeSeconds(setCookieHeaders []string) (int, bool) {
	for _, cookie := range setCookieHeaders {
		for _, attribute := range strings.Split(cookie, ";") {
			key, value, found := strings.Cut(strings.TrimSpace(attribute), "=")
			if !found || !strings.EqualFold(strings.TrimSpace(key), "max-age") {
				continue
			}
			var maxAge int
			if _, err := fmt.Sscanf(strings.TrimSpace(value), "%d", &maxAge); err == nil {
				return maxAge, true
			}
		}
	}
	return 0, false
}

func sisCIMDRandomBase64URL(byteCount int) (string, error) {
	buffer := make([]byte, byteCount)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buffer), nil
}

func sisCIMDCodeChallengeS256(verifier string) string {
	sum := sha256.Sum256([]byte(verifier))
	return base64.RawURLEncoding.EncodeToString(sum[:])
}

func sisCIMDScopeSet(scope string) []string {
	fields := strings.Fields(scope)
	seen := make(map[string]struct{}, len(fields))
	scopes := make([]string, 0, len(fields))
	for _, field := range fields {
		if _, ok := seen[field]; ok {
			continue
		}
		seen[field] = struct{}{}
		scopes = append(scopes, field)
	}
	return scopes
}

func sisCIMDContains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

// registerSISCIMDClientHandler probes SIS CIMD client registration and reports the
// federated authorization redirect it returns. Gated by OBSTUDIO_CONTROL_TOKEN (see
// registerSISCIMDLoginRoutes): although this route stores no secret, the probe itself has
// real side effects (SIS may create or refresh a shadow client) and its response reveals
// federation redirect/cookie details, so it must not be cross-site callable. The response
// is same-origin-only for the same reason -- writeJSON's wildcard CORS header would let
// any origin that could reach this route also read the response it triggered.
func registerSISCIMDClientHandler(w http.ResponseWriter, _ *http.Request) {
	result, err := registerSISCIMDClient(loadSISCIMDRegistrationConfig())
	if err != nil {
		writeSISCIMDRegistrationError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeSameOriginJSON(w, result)
}

func writeSISCIMDRegistrationError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": message})
}
