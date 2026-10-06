package api

// Step 1 of the O11y-OAuth-for-MCP-Gateway integration: client registration.
// See docs/o11y-oauth-mcp-gateway-impact.md §9. Step 2 (user authorization /
// token exchange) is not implemented here -- it is still blocked on the O11y
// OAuth team's own design work.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

const (
	o11yOAuthClientName        = "Splunk Observability Studio"
	o11yOAuthClientDescription = "MCP client registration for Splunk Observability Studio (obstudio)"
	// Intentionally the same loopback port CIMD's fixed callback (sisCIMDRedirectURI)
	// uses -- the two protocols are mutually exclusive via
	// OBSTUDIO_REGISTRATION_AND_AUTH_PROTOCOL and never run at once, so there is no
	// conflict. Kept as its own constant so this file has no dependency on CIMD code.
	o11yOAuthRegistrationCallbackURL = "http://127.0.0.1:33418/callback"
	o11yOAuthRequestTimeout          = 15 * time.Second
	o11yOAuthMaxResponseBodyBytes    = 64 * 1024
)

type o11yOAuthRegisterRequest struct {
	Realm      string `json:"realm"`
	AdminToken string `json:"adminToken"`
}

type o11yOAuthRegisterResult struct {
	ClientID string `json:"clientId"`
	// ClientSecret is forwarded once, in-memory only, and only present on a
	// fresh (201) registration -- SIS never returns it again on reuse (200),
	// "secrets are never returned by read/status APIs." Never logged, never
	// persisted server-side. See docs/o11y-oauth-mcp-gateway-impact.md §6/§7
	// (Q1) for why this is forwarded at all despite the public-client
	// secret-handling concern raised there.
	ClientSecret string `json:"clientSecret,omitempty"`
	Created      bool   `json:"created"`
}

type o11yOAuthClientPayload struct {
	Name        string `json:"name"`
	Description string `json:"description"`
	CallbackURL string `json:"callbackUrl"`
}

// o11yOAuthClientResponse decodes what Step 1 needs, including the one-time
// secret on creation. Best-guess field name (clientSecret), unconfirmed
// against the real server -- see docs/o11y-oauth-mcp-gateway-impact.md §7.
type o11yOAuthClientResponse struct {
	ClientID     string `json:"clientId"`
	ClientSecret string `json:"clientSecret"`
}

// resolveO11yOAuthRegistrationURL returns the registration endpoint to call.
// realm is validated by the caller even though it is unused here: the real
// O11y OAuth registration server is still blocked (as of 2026-10-06), so this
// defaults to the local mock (o11y-obstudio-oauth/test-registration-server)
// instead of deriving
// https://api.<realm>.observability.splunkcloud.com/v2/sis/oauth/clients.
// TODO: switch the default to the realm-derived URL once their server is ready.
func resolveO11yOAuthRegistrationURL(realm string) string {
	if override := strings.TrimSpace(os.Getenv("OBSTUDIO_O11Y_OAUTH_REGISTRATION_URL")); override != "" {
		return override
	}
	return "http://127.0.0.1:9294/v2/sis/oauth/clients"
}

func registerO11yOAuthClientHandler(w http.ResponseWriter, r *http.Request) {
	var request o11yOAuthRegisterRequest
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeO11yOAuthRegistrationError(w, http.StatusBadRequest, err.Error())
		return
	}

	realm, err := validateSplunkRealm(request.Realm)
	if err != nil {
		writeO11yOAuthRegistrationError(w, http.StatusBadRequest, "enter a valid Splunk Observability Cloud realm")
		return
	}
	adminToken := strings.TrimSpace(request.AdminToken)
	if adminToken == "" {
		writeO11yOAuthRegistrationError(w, http.StatusBadRequest, "paste the admin X-SF-TOKEN")
		return
	}

	result, err := registerO11yOAuthClient(r.Context(), realm, adminToken)
	if err != nil {
		writeO11yOAuthRegistrationError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeSameOriginJSON(w, result)
}

func registerO11yOAuthClient(ctx context.Context, realm, adminToken string) (*o11yOAuthRegisterResult, error) {
	body, err := json.Marshal(o11yOAuthClientPayload{
		Name:        o11yOAuthClientName,
		Description: o11yOAuthClientDescription,
		CallbackURL: o11yOAuthRegistrationCallbackURL,
	})
	if err != nil {
		return nil, fmt.Errorf("build registration request: %w", err)
	}

	requestCtx, cancel := context.WithTimeout(ctx, o11yOAuthRequestTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(
		requestCtx,
		http.MethodPost,
		resolveO11yOAuthRegistrationURL(realm),
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("build registration request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-SF-TOKEN", adminToken)

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return nil, errors.New("could not reach the O11y OAuth registration server")
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK && response.StatusCode != http.StatusCreated {
		// Never reflect the response body: it may carry sensitive detail from an
		// untrusted or misconfigured server. Mirrors sis_cimd_login.go.
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, o11yOAuthMaxResponseBodyBytes))
		return nil, fmt.Errorf("registration server returned HTTP %d", response.StatusCode)
	}

	var decoded o11yOAuthClientResponse
	if err := json.NewDecoder(io.LimitReader(response.Body, o11yOAuthMaxResponseBodyBytes)).Decode(&decoded); err != nil {
		return nil, errors.New("registration server returned an invalid response")
	}
	if decoded.ClientID == "" {
		return nil, errors.New("registration server did not return a client ID")
	}

	created := response.StatusCode == http.StatusCreated
	result := &o11yOAuthRegisterResult{
		ClientID: decoded.ClientID,
		Created:  created,
	}
	if created {
		// Only ever forward a secret for a fresh creation. If a non-conforming
		// server returned one on a 200 (reuse) response too, drop it rather
		// than pass it through -- the documented contract says that shouldn't
		// happen, and an existing client's secret should never be re-offered.
		result.ClientSecret = decoded.ClientSecret
	}
	return result, nil
}

func writeO11yOAuthRegistrationError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": message})
}

// registerO11yOAuthRoutes wires the local-only registration route onto mux.
// The button that triggers this is intentionally not admin-gated client-side
// (see docs/o11y-oauth-mcp-gateway-impact.md §9) -- the registration server
// itself is expected to enforce that the pasted token actually has admin
// authority.
func registerO11yOAuthRoutes(mux *http.ServeMux) {
	mux.HandleFunc(
		"POST /api/splunk/o11y-oauth/register",
		requireLocalObserverRequest(registerO11yOAuthClientHandler, writeO11yOAuthRegistrationError),
	)
}
