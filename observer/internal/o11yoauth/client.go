package o11yoauth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"slices"
	"strings"
	"sync/atomic"
	"time"
)

const (
	callbackPath    = "/callback"
	defaultTimeout  = 5 * time.Minute
	requestTimeout  = 15 * time.Second
	maxResponseSize = 64 * 1024
)

var trustedIssuerHost = regexp.MustCompile(`^app\.[a-z]{2,12}[0-9]+\.(?:observability\.splunkcloud\.com|signalfx\.com)$`)

var trustedInternalIssuerHosts = map[string]string{
	"mon.observability.splunkcloud.com": "mon0",
	"mon.signalfx.com":                  "mon0",
}

type Options struct {
	ClientID      string
	HTTPClient    *http.Client
	IssuerURL     string
	OpenBrowser   func(string) error
	RequiredScope string
	Scope         string
	Timeout       time.Duration
	TokenName     string
}

type Connection struct {
	AccessToken string `json:"accessToken"`
	ConnectedAt string `json:"connectedAt"`
	Endpoint    string `json:"endpoint,omitempty"`
	ExpiresAt   string `json:"expiresAt,omitempty"`
	Issuer      string `json:"issuer"`
	OrgID       string `json:"orgId,omitempty"`
	OrgName     string `json:"orgName,omitempty"`
	Realm       string `json:"realm,omitempty"`
	Scope       string `json:"scope,omitempty"`
	TokenID     string `json:"tokenId,omitempty"`
	TokenName   string `json:"tokenName,omitempty"`
	TokenType   string `json:"tokenType"`
}

type Metadata struct {
	AuthorizationEndpoint string
	Issuer                string
	RevocationEndpoint    string
	ScopesSupported       []string
	TokenEndpoint         string
}

type metadataResponse struct {
	AuthorizationEndpoint                      string   `json:"authorization_endpoint"`
	AuthorizationResponseISSParameterSupported bool     `json:"authorization_response_iss_parameter_supported"`
	CodeChallengeMethodsSupported              []string `json:"code_challenge_methods_supported"`
	GrantTypesSupported                        []string `json:"grant_types_supported"`
	Issuer                                     string   `json:"issuer"`
	ResponseModesSupported                     []string `json:"response_modes_supported"`
	ResponseTypesSupported                     []string `json:"response_types_supported"`
	RevocationEndpoint                         string   `json:"revocation_endpoint"`
	RevocationEndpointAuthMethodsSupported     []string `json:"revocation_endpoint_auth_methods_supported"`
	ScopesSupported                            []string `json:"scopes_supported"`
	TokenEndpoint                              string   `json:"token_endpoint"`
	TokenEndpointAuthMethodsSupported          []string `json:"token_endpoint_auth_methods_supported"`
}

type tokenResponse struct {
	AccessToken          string  `json:"access_token"`
	ExpiresIn            float64 `json:"expires_in"`
	Scope                string  `json:"scope"`
	SplunkIngestEndpoint string  `json:"splunk_ingest_endpoint"`
	SplunkIssuer         string  `json:"splunk_issuer"`
	SplunkOrgID          string  `json:"splunk_org_id"`
	SplunkOrgName        string  `json:"splunk_org_name"`
	SplunkRealm          string  `json:"splunk_realm"`
	SplunkTokenID        string  `json:"splunk_token_id"`
	SplunkTokenName      string  `json:"splunk_token_name"`
	TokenType            string  `json:"token_type"`
}

type oauthError struct {
	Error            string `json:"error"`
	ErrorDescription string `json:"error_description"`
}

type callbackRequest struct {
	code   string
	err    error
	result chan callbackResult
}

type callbackResult struct {
	err error
}

func Login(ctx context.Context, options Options) (Connection, error) {
	options, err := normalizeOptions(options)
	if err != nil {
		return Connection{}, err
	}
	metadata, err := Discover(ctx, options.IssuerURL, options.HTTPClient)
	if err != nil {
		return Connection{}, err
	}
	if err := validateScopes(options.Scope, metadata.ScopesSupported); err != nil {
		return Connection{}, err
	}

	verifier, challenge, err := newPKCEPair()
	if err != nil {
		return Connection{}, err
	}
	state, err := randomBase64URL(32)
	if err != nil {
		return Connection{}, fmt.Errorf("create OAuth state: %w", err)
	}

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return Connection{}, fmt.Errorf("start OAuth callback listener: %w", err)
	}
	redirectURI := "http://" + listener.Addr().String() + callbackPath
	callback := make(chan callbackRequest, 1)
	var accepted atomic.Bool
	server := &http.Server{
		ReadHeaderTimeout: 5 * time.Second,
		Handler: http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
			handleCallback(response, request, metadata.Issuer, redirectURI, state, callback, &accepted)
		}),
	}
	serveDone := make(chan error, 1)
	go func() {
		serveDone <- server.Serve(listener)
	}()
	defer func() {
		shutdownContext, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownContext)
	}()

	authorizationURL, err := buildAuthorizationURL(metadata.AuthorizationEndpoint, map[string]string{
		"client_id":             options.ClientID,
		"code_challenge":        challenge,
		"code_challenge_method": "S256",
		"redirect_uri":          redirectURI,
		"response_type":         "code",
		"scope":                 options.Scope,
		"state":                 state,
		"token_name":            options.TokenName,
	})
	if err != nil {
		return Connection{}, err
	}
	if err := options.OpenBrowser(authorizationURL); err != nil {
		return Connection{}, fmt.Errorf("open Splunk Observability Cloud authorization page: %w", err)
	}

	timeout := options.Timeout
	if timeout <= 0 {
		timeout = defaultTimeout
	}
	waitContext, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	select {
	case request := <-callback:
		if request.err != nil {
			return Connection{}, request.err
		}
		connection, exchangeErr := exchangeCode(waitContext, metadata, options, redirectURI, request.code, verifier)
		request.result <- callbackResult{err: exchangeErr}
		if exchangeErr != nil {
			return Connection{}, exchangeErr
		}
		return connection, nil
	case err := <-serveDone:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			return Connection{}, fmt.Errorf("OAuth callback listener stopped: %w", err)
		}
		return Connection{}, errors.New("OAuth callback listener stopped before authorization completed")
	case <-waitContext.Done():
		return Connection{}, fmt.Errorf("wait for Splunk Observability Cloud authorization: %w", waitContext.Err())
	}
}

func Discover(ctx context.Context, rawIssuer string, client *http.Client) (Metadata, error) {
	issuer, err := NormalizeIssuer(rawIssuer)
	if err != nil {
		return Metadata{}, err
	}
	metadataURL := issuer + "/.well-known/oauth-authorization-server"
	var response metadataResponse
	if err := getJSON(ctx, client, metadataURL, &response); err != nil {
		return Metadata{}, fmt.Errorf("discover OAuth authorization server: %w", err)
	}
	if response.Issuer != issuer {
		return Metadata{}, errors.New("OAuth authorization-server metadata returned an unexpected issuer")
	}
	if !slices.Contains(response.ResponseTypesSupported, "code") || !slices.Contains(response.GrantTypesSupported, "authorization_code") {
		return Metadata{}, errors.New("OAuth authorization server does not support authorization-code grants")
	}
	if !slices.Contains(response.CodeChallengeMethodsSupported, "S256") {
		return Metadata{}, errors.New("OAuth authorization server does not support PKCE S256")
	}
	if !slices.Contains(response.TokenEndpointAuthMethodsSupported, "none") {
		return Metadata{}, errors.New("OAuth authorization server does not support public clients")
	}
	if !slices.Contains(response.ResponseModesSupported, "query") {
		return Metadata{}, errors.New("OAuth authorization server does not support query authorization responses")
	}
	if !slices.Contains(response.RevocationEndpointAuthMethodsSupported, "none") {
		return Metadata{}, errors.New("OAuth authorization server does not support public-client revocation")
	}
	if !response.AuthorizationResponseISSParameterSupported {
		return Metadata{}, errors.New("OAuth authorization server does not support authorization-response issuer validation")
	}
	authorize, err := metadataEndpoint(response.AuthorizationEndpoint, "authorization_endpoint", issuer)
	if err != nil {
		return Metadata{}, err
	}
	token, err := metadataEndpoint(response.TokenEndpoint, "token_endpoint", issuer)
	if err != nil {
		return Metadata{}, err
	}
	revoke, err := metadataEndpoint(response.RevocationEndpoint, "revocation_endpoint", issuer)
	if err != nil {
		return Metadata{}, err
	}
	return Metadata{
		AuthorizationEndpoint: authorize,
		Issuer:                issuer,
		RevocationEndpoint:    revoke,
		ScopesSupported:       response.ScopesSupported,
		TokenEndpoint:         token,
	}, nil
}

func Revoke(ctx context.Context, connection Connection, client *http.Client) error {
	if strings.TrimSpace(connection.AccessToken) == "" {
		return errors.New("OAuth access token is required for revocation")
	}
	metadata, err := Discover(ctx, connection.Issuer, client)
	if err != nil {
		return err
	}
	values := url.Values{
		"token":           {connection.AccessToken},
		"token_type_hint": {"access_token"},
	}
	response, err := doForm(ctx, client, metadata.RevocationEndpoint, values)
	if err != nil {
		return fmt.Errorf("revoke OAuth access token: %w", err)
	}
	defer response.Body.Close()
	if _, err := readBounded(response.Body); err != nil {
		return err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("OAuth revocation endpoint returned HTTP %d", response.StatusCode)
	}
	return nil
}

func NormalizeIssuer(raw string) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return "", errors.New("Splunk Observability Cloud OAuth issuer URL is invalid")
	}
	if parsed.User != nil {
		return "", errors.New("OAuth issuer URL must not contain credentials")
	}
	hostname := strings.ToLower(parsed.Hostname())
	if parsed.Scheme == "http" {
		if !isLoopbackHost(hostname) {
			return "", errors.New("OAuth issuer may use HTTP only for loopback development hosts")
		}
	} else if parsed.Scheme != "https" {
		return "", errors.New("OAuth issuer must use HTTPS")
	} else if !trustedIssuerHost.MatchString(hostname) && trustedInternalIssuerHosts[hostname] == "" {
		return "", errors.New("OAuth issuer must use a registered Splunk Observability Cloud host")
	}
	return parsed.Scheme + "://" + canonicalHost(hostname, parsed.Port()), nil
}

func ValidateConnection(connection Connection) error {
	if strings.TrimSpace(connection.AccessToken) == "" {
		return errors.New("cloud connection is missing its access token")
	}
	issuer, err := NormalizeIssuer(connection.Issuer)
	if err != nil || issuer != connection.Issuer {
		return errors.New("cloud connection has an invalid OAuth issuer")
	}
	if !strings.EqualFold(connection.TokenType, "bearer") {
		return errors.New("cloud connection has an unsupported token type")
	}
	if connection.ExpiresAt != "" {
		if _, err := time.Parse(time.RFC3339Nano, connection.ExpiresAt); err != nil {
			return errors.New("cloud connection has an invalid expiration time")
		}
	}
	return validateIngestEndpoint(connection.Endpoint, connection.Realm)
}

func ConnectionUsable(connection Connection, requiredScope string, now time.Time, expirySkew time.Duration) bool {
	if ValidateConnection(connection) != nil {
		return false
	}
	if connection.ExpiresAt != "" {
		expiresAt, err := time.Parse(time.RFC3339Nano, connection.ExpiresAt)
		if err != nil || !expiresAt.After(now.Add(expirySkew)) {
			return false
		}
	}
	granted := scopeSet(connection.Scope)
	for scope := range scopeSet(requiredScope) {
		if _, ok := granted[scope]; !ok {
			return false
		}
	}
	return true
}

func exchangeCode(ctx context.Context, metadata Metadata, options Options, redirectURI, code, verifier string) (Connection, error) {
	values := url.Values{
		"client_id":     {options.ClientID},
		"code":          {code},
		"code_verifier": {verifier},
		"grant_type":    {"authorization_code"},
		"redirect_uri":  {redirectURI},
	}
	response, err := doForm(ctx, options.HTTPClient, metadata.TokenEndpoint, values)
	if err != nil {
		return Connection{}, fmt.Errorf("exchange OAuth authorization code: %w", err)
	}
	defer response.Body.Close()
	body, err := readBounded(response.Body)
	if err != nil {
		return Connection{}, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		var detail oauthError
		_ = json.Unmarshal(body, &detail)
		if detail.ErrorDescription != "" {
			return Connection{}, fmt.Errorf("OAuth token endpoint returned HTTP %d: %s", response.StatusCode, detail.ErrorDescription)
		}
		return Connection{}, fmt.Errorf("OAuth token endpoint returned HTTP %d", response.StatusCode)
	}
	var token tokenResponse
	if err := json.Unmarshal(body, &token); err != nil {
		return Connection{}, errors.New("OAuth token endpoint returned invalid JSON")
	}
	return connectionFromToken(token, options.Scope, options.RequiredScope, metadata.Issuer)
}

func connectionFromToken(token tokenResponse, requestedScope, requiredScope, expectedIssuer string) (Connection, error) {
	if strings.TrimSpace(token.AccessToken) == "" {
		return Connection{}, errors.New("OAuth token endpoint did not return an access token")
	}
	if !strings.EqualFold(token.TokenType, "bearer") {
		return Connection{}, errors.New("OAuth token endpoint returned an unsupported token type")
	}
	issuer := token.SplunkIssuer
	if issuer == "" {
		issuer = expectedIssuer
	}
	if issuer != expectedIssuer {
		return Connection{}, errors.New("OAuth token endpoint returned an unexpected issuer")
	}
	grantedScope := strings.TrimSpace(token.Scope)
	if grantedScope == "" {
		grantedScope = requestedScope
	}
	if err := validateGrantedScopes(requestedScope, requiredScope, grantedScope); err != nil {
		return Connection{}, err
	}
	if err := validateIngestEndpoint(token.SplunkIngestEndpoint, token.SplunkRealm); err != nil {
		return Connection{}, err
	}
	now := time.Now().UTC()
	connection := Connection{
		AccessToken: token.AccessToken,
		ConnectedAt: now.Format(time.RFC3339Nano),
		Endpoint:    token.SplunkIngestEndpoint,
		Issuer:      issuer,
		OrgID:       token.SplunkOrgID,
		OrgName:     token.SplunkOrgName,
		Realm:       token.SplunkRealm,
		Scope:       grantedScope,
		TokenID:     token.SplunkTokenID,
		TokenName:   token.SplunkTokenName,
		TokenType:   "Bearer",
	}
	if token.ExpiresIn > 0 {
		connection.ExpiresAt = now.Add(time.Duration(token.ExpiresIn * float64(time.Second))).Format(time.RFC3339Nano)
	}
	return connection, nil
}

func handleCallback(response http.ResponseWriter, request *http.Request, expectedIssuer, redirectURI, expectedState string, callbacks chan<- callbackRequest, accepted *atomic.Bool) {
	setCallbackHeaders(response)
	if request.Method != http.MethodGet || request.URL.Path != callbackPath {
		http.Error(response, "Not found.", http.StatusNotFound)
		return
	}
	query := request.URL.Query()
	state, err := exactlyOne(query, "state")
	if err != nil || state != expectedState {
		writeCallbackPage(response, http.StatusBadRequest, "Authorization failed", "Authorization state did not match the local session.")
		return
	}
	issuer, err := exactlyOne(query, "iss")
	if err != nil || issuer != expectedIssuer {
		writeCallbackPage(response, http.StatusBadRequest, "Authorization failed", "Authorization issuer did not match the requested server.")
		return
	}
	if values, ok := query["error"]; ok {
		if len(values) != 1 || strings.TrimSpace(values[0]) == "" {
			writeCallbackPage(response, http.StatusBadRequest, "Authorization failed", "The authorization server returned an invalid error response.")
			return
		}
		description := "Authorization was denied."
		if descriptions, ok := query["error_description"]; ok && len(descriptions) == 1 && strings.TrimSpace(descriptions[0]) != "" {
			description = descriptions[0]
		}
		if !accepted.CompareAndSwap(false, true) {
			writeCallbackPage(response, http.StatusConflict, "Authorization already completed", "Return to your app to continue.")
			return
		}
		writeCallbackPage(response, http.StatusBadRequest, "Authorization failed", description)
		callbacks <- callbackRequest{err: fmt.Errorf("%s: %s", values[0], description)}
		return
	}
	code, err := exactlyOne(query, "code")
	if err != nil || strings.TrimSpace(code) == "" {
		writeCallbackPage(response, http.StatusBadRequest, "Authorization failed", "Authorization callback did not include a code.")
		return
	}
	if !accepted.CompareAndSwap(false, true) {
		writeCallbackPage(response, http.StatusConflict, "Authorization already completed", "Return to your app to continue.")
		return
	}
	result := make(chan callbackResult, 1)
	callbacks <- callbackRequest{code: code, result: result}
	select {
	case outcome := <-result:
		if outcome.err != nil {
			writeCallbackPage(response, http.StatusBadGateway, "Authorization failed", "Return to your app to retry the connection.")
			return
		}
		writeCallbackPage(response, http.StatusOK, "Authorization complete", "You may now close this tab and return to your app.")
	case <-request.Context().Done():
		return
	case <-time.After(requestTimeout + 5*time.Second):
		writeCallbackPage(response, http.StatusGatewayTimeout, "Authorization timed out", "Return to your app to retry the connection.")
	}
}

func buildAuthorizationURL(raw string, params map[string]string) (string, error) {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return "", errors.New("OAuth authorization endpoint is invalid")
	}
	if parsed.Fragment != "" {
		return "", errors.New("OAuth authorization endpoint must not contain a fragment")
	}
	query := parsed.Query()
	for key, value := range params {
		query.Set(key, value)
	}
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}

func metadataEndpoint(raw, field, expectedIssuer string) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return "", fmt.Errorf("OAuth authorization-server metadata is missing %s", field)
	}
	if parsed.User != nil || parsed.Fragment != "" {
		return "", fmt.Errorf("OAuth %s must not contain credentials or a fragment", field)
	}
	issuer, _ := url.Parse(expectedIssuer)
	if parsed.Scheme != issuer.Scheme || !strings.EqualFold(parsed.Host, issuer.Host) {
		return "", fmt.Errorf("OAuth %s must use the configured issuer origin", field)
	}
	return parsed.String(), nil
}

func normalizeOptions(options Options) (Options, error) {
	issuer, err := NormalizeIssuer(options.IssuerURL)
	if err != nil {
		return Options{}, err
	}
	options.IssuerURL = issuer
	options.ClientID = strings.TrimSpace(options.ClientID)
	options.Scope = normalizeScope(options.Scope)
	options.RequiredScope = normalizeScope(options.RequiredScope)
	options.TokenName = strings.TrimSpace(options.TokenName)
	if options.ClientID == "" {
		return Options{}, errors.New("OAuth client ID is required")
	}
	if options.Scope == "" {
		return Options{}, errors.New("OAuth scope is required")
	}
	if options.RequiredScope == "" {
		options.RequiredScope = "ingest"
	}
	if options.TokenName == "" {
		options.TokenName = "Obstudio local agent token"
	}
	if options.OpenBrowser == nil {
		return Options{}, errors.New("OAuth browser opener is required")
	}
	return options, nil
}

func validateScopes(requested string, supported []string) error {
	supportedSet := scopeSet(strings.Join(supported, " "))
	var unsupported []string
	for scope := range scopeSet(requested) {
		if _, ok := supportedSet[scope]; !ok {
			unsupported = append(unsupported, scope)
		}
	}
	slices.Sort(unsupported)
	if len(unsupported) > 0 {
		return fmt.Errorf("OAuth authorization server does not support requested scope: %s", strings.Join(unsupported, " "))
	}
	return nil
}

func validateGrantedScopes(requested, required, granted string) error {
	requestedSet := scopeSet(requested)
	grantedSet := scopeSet(granted)
	for scope := range grantedSet {
		if _, ok := requestedSet[scope]; !ok {
			return fmt.Errorf("OAuth token endpoint returned an unrequested scope: %s", scope)
		}
	}
	for scope := range scopeSet(required) {
		if _, ok := grantedSet[scope]; !ok {
			return fmt.Errorf("OAuth token endpoint did not grant required scope: %s", scope)
		}
	}
	return nil
}

func validateIngestEndpoint(raw, realm string) error {
	if strings.TrimSpace(raw) == "" {
		if strings.TrimSpace(realm) == "" {
			return errors.New("OAuth token endpoint did not return a Splunk realm or ingest endpoint")
		}
		return nil
	}
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme != "https" || parsed.User != nil || parsed.Fragment != "" || parsed.RawQuery != "" || (parsed.Port() != "" && parsed.Port() != "443") || (parsed.Path != "" && parsed.Path != "/") {
		return errors.New("OAuth token endpoint returned an invalid Splunk ingest endpoint")
	}
	host := strings.ToLower(parsed.Hostname())
	expectedRealm := strings.ToLower(strings.TrimSpace(realm))
	standardHost := host == "ingest."+expectedRealm+".signalfx.com" || host == "ingest."+expectedRealm+".observability.splunkcloud.com"
	internalHost := expectedRealm == "mon0" && host == "mon-ingest.signalfx.com"
	if expectedRealm == "" || (!standardHost && !internalHost) {
		return errors.New("OAuth token endpoint returned an ingest endpoint for an unexpected realm")
	}
	return nil
}

func canonicalHost(hostname, port string) string {
	if port != "" {
		return net.JoinHostPort(hostname, port)
	}
	if strings.Contains(hostname, ":") {
		return "[" + hostname + "]"
	}
	return hostname
}

func getJSON(ctx context.Context, client *http.Client, rawURL string, target any) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return err
	}
	request.Header.Set("Accept", "application/json")
	response, err := safeClient(client).Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	body, err := readBounded(response.Body)
	if err != nil {
		return err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("returned HTTP %d", response.StatusCode)
	}
	if err := json.Unmarshal(body, target); err != nil {
		return errors.New("returned invalid JSON")
	}
	return nil
}

func doForm(ctx context.Context, client *http.Client, rawURL string, values url.Values) (*http.Response, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, rawURL, strings.NewReader(values.Encode()))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Accept", "application/json")
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	return safeClient(client).Do(request)
}

func safeClient(source *http.Client) *http.Client {
	client := &http.Client{}
	if source != nil {
		*client = *source
	}
	if client.Timeout == 0 {
		client.Timeout = requestTimeout
	}
	client.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return http.ErrUseLastResponse
	}
	return client
}

func readBounded(reader io.Reader) ([]byte, error) {
	limited := io.LimitReader(reader, maxResponseSize+1)
	body, err := io.ReadAll(limited)
	if err != nil {
		return nil, err
	}
	if len(body) > maxResponseSize {
		return nil, errors.New("OAuth response was too large")
	}
	return body, nil
}

func newPKCEPair() (string, string, error) {
	verifier, err := randomBase64URL(32)
	if err != nil {
		return "", "", fmt.Errorf("create PKCE verifier: %w", err)
	}
	digest := sha256.Sum256([]byte(verifier))
	return verifier, base64.RawURLEncoding.EncodeToString(digest[:]), nil
}

func randomBase64URL(size int) (string, error) {
	data := make([]byte, size)
	if _, err := rand.Read(data); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(data), nil
}

func exactlyOne(values url.Values, key string) (string, error) {
	items, ok := values[key]
	if !ok || len(items) != 1 {
		return "", fmt.Errorf("OAuth callback must contain exactly one %s parameter", key)
	}
	return items[0], nil
}

func normalizeScope(raw string) string {
	items := strings.Fields(strings.ToLower(raw))
	slices.Sort(items)
	return strings.Join(slices.Compact(items), " ")
}

func scopeSet(raw string) map[string]struct{} {
	result := make(map[string]struct{})
	for _, scope := range strings.Fields(strings.ToLower(raw)) {
		result[scope] = struct{}{}
	}
	return result
}

func isLoopbackHost(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func setCallbackHeaders(response http.ResponseWriter) {
	response.Header().Set("Cache-Control", "no-store")
	response.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
	response.Header().Set("Referrer-Policy", "no-referrer")
	response.Header().Set("X-Content-Type-Options", "nosniff")
}

func writeCallbackPage(response http.ResponseWriter, status int, title, message string) {
	response.Header().Set("Content-Type", "text/html; charset=utf-8")
	response.WriteHeader(status)
	_, _ = fmt.Fprintf(response, `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title><style>body{margin:0;background:#0b1118;color:#f7f8fa;font:16px system-ui;display:grid;min-height:100vh;place-items:center}.panel{max-width:560px;padding:40px;border:1px solid #344050;background:#111b29}h1{font-size:28px;margin:0 0 12px}p{color:#b8c2cf;line-height:1.5;margin:0}</style></head><body><main class="panel"><h1>%s</h1><p>%s</p></main></body></html>`, html.EscapeString(title), html.EscapeString(title), html.EscapeString(message))
}
