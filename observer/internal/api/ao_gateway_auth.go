package api

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	// This public marker selects the local gateway, not a cloud account. Access
	// is granted by the loopback process boundary, not possession of the marker.
	agentObservabilityLocalSDKKey  = "local-gateway"
	agentObservabilitySDKIssuer    = "local-agent-observability-gateway"
	agentObservabilitySDKSubject   = "8b55cdcf-7c16-4dc7-9e69-43795d8d61a9"
	agentObservabilitySDKAudience  = "local-sdk"
	agentObservabilitySDKScope     = "local-only"
	agentObservabilitySDKJWTExpiry = 2 * time.Minute
)

type agentObservabilitySDKClaims struct {
	Issuer    string `json:"iss"`
	Subject   string `json:"sub"`
	Audience  string `json:"aud"`
	Scope     string `json:"scope"`
	IssuedAt  int64  `json:"iat"`
	ExpiresAt int64  `json:"exp"`
}

// These SDK-only routes implement the standalone SDK's normal login contract.
// They never authenticate a cloud user or expose Studio's cloud credential.
func (s *splunkExportService) registerAgentObservabilitySDKAuth(mux *http.ServeMux) {
	mux.HandleFunc("GET /healthcheck", s.agentObservabilitySDKHealthcheck)
	mux.HandleFunc("POST /login/api_key", s.agentObservabilitySDKLogin)
	mux.HandleFunc("GET /current_user", s.agentObservabilitySDKCurrentUser)
}

// Reject browser requests, including same-origin requests, and DNS-rebinding
// Host values. Local SDK access follows Studio's existing loopback trust model;
// this is not an authentication boundary between processes on the same host.
func isLocalAgentObservabilitySDKRequest(r *http.Request) bool {
	if !isLocalObserverRequest(r) || r.Host == "" {
		return false
	}
	for name := range r.Header {
		if strings.EqualFold(name, "Origin") || strings.HasPrefix(strings.ToLower(name), "sec-fetch-") ||
			strings.EqualFold(name, splunkBrowserRequestHeader) {
			return false
		}
	}
	host, err := url.Parse("//" + r.Host)
	return err == nil && host.User == nil && host.Path == "" && host.RawQuery == "" && host.Fragment == "" &&
		isLoopbackHostname(host.Hostname())
}

func (s *splunkExportService) agentObservabilitySDKReady(w http.ResponseWriter, r *http.Request) bool {
	if !isLocalAgentObservabilitySDKRequest(r) {
		writeSplunkExportError(w, http.StatusForbidden, "Agent Observability SDK requests must come from a local process")
		return false
	}
	if _, _, ready := s.agentObservabilityProxyDestination(); !ready {
		writeSplunkExportError(w, http.StatusServiceUnavailable, "connect and enable a realm-based Splunk Observability Cloud destination before using the local Agent Observability gateway")
		return false
	}
	w.Header().Set("Cache-Control", "no-store")
	return true
}

func (s *splunkExportService) agentObservabilitySDKHealthcheck(w http.ResponseWriter, r *http.Request) {
	if !s.agentObservabilitySDKReady(w, r) {
		return
	}
	writeSameOriginJSON(w, map[string]any{"status": "ok", "identity_scope": agentObservabilitySDKScope, "cloud_identity": false})
}

func (s *splunkExportService) agentObservabilitySDKLogin(w http.ResponseWriter, r *http.Request) {
	if !s.agentObservabilitySDKReady(w, r) {
		return
	}
	var request struct {
		APIKey string `json:"api_key"`
	}
	if err := decodeStrictJSON(w, r, &request); err != nil {
		// Do not echo malformed credential input in an error response.
		writeSplunkExportError(w, http.StatusBadRequest, "invalid local Agent Observability SDK login request")
		return
	}
	if request.APIKey != agentObservabilityLocalSDKKey {
		writeSplunkExportError(w, http.StatusUnauthorized, "the local Agent Observability gateway requires the local-gateway compatibility marker, not a cloud API key")
		return
	}
	writeSameOriginJSON(w, map[string]string{
		"access_token": s.issueAgentObservabilitySDKJWT(time.Now()),
		"token_type":   "bearer", "identity_scope": agentObservabilitySDKScope,
	})
}

func (s *splunkExportService) agentObservabilitySDKCurrentUser(w http.ResponseWriter, r *http.Request) {
	if !s.agentObservabilitySDKReady(w, r) {
		return
	}
	if !s.validAgentObservabilitySDKBearer(r) {
		writeSplunkExportError(w, http.StatusUnauthorized, "local Agent Observability SDK authentication is required")
		return
	}
	// The SDK requires a UUID4 and email to validate its local login session.
	// These identify only this gateway principal; resource creation leaves the
	// optional cloud created_by field unset and uses server-held cloud auth.
	writeSameOriginJSON(w, map[string]any{
		"id": agentObservabilitySDKSubject, "email": "local-sdk-gateway@localhost", "role": "user",
		"identity_scope": agentObservabilitySDKScope, "cloud_identity": false,
	})
}

func (s *splunkExportService) agentObservabilitySDKSignature(message string) []byte {
	key := hmac.New(sha256.New, s.stateVersionKey[:])
	_, _ = key.Write([]byte("agent-observability-sdk-jwt"))
	signature := hmac.New(sha256.New, key.Sum(nil))
	_, _ = signature.Write([]byte(message))
	return signature.Sum(nil)
}

func (s *splunkExportService) issueAgentObservabilitySDKJWT(now time.Time) string {
	claims := agentObservabilitySDKClaims{
		Issuer: agentObservabilitySDKIssuer, Subject: agentObservabilitySDKSubject,
		Audience: agentObservabilitySDKAudience, Scope: agentObservabilitySDKScope,
		IssuedAt: now.Unix(), ExpiresAt: now.Add(agentObservabilitySDKJWTExpiry).Unix(),
	}
	payload, _ := json.Marshal(claims)
	message := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"HS256","typ":"JWT"}`)) + "." +
		base64.RawURLEncoding.EncodeToString(payload)
	return message + "." + base64.RawURLEncoding.EncodeToString(s.agentObservabilitySDKSignature(message))
}

func (s *splunkExportService) validAgentObservabilitySDKBearer(r *http.Request) bool {
	values := r.Header.Values("Authorization")
	if len(values) != 1 || !strings.HasPrefix(values[0], "Bearer ") || !isLocalAgentObservabilitySDKRequest(r) {
		return false
	}
	return s.validAgentObservabilitySDKJWT(strings.TrimPrefix(values[0], "Bearer "), time.Now())
}

func (s *splunkExportService) validAgentObservabilitySDKJWT(token string, now time.Time) bool {
	if len(token) > 2048 {
		return false
	}
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return false
	}
	header, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil || string(header) != `{"alg":"HS256","typ":"JWT"}` {
		return false
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil || !hmac.Equal(signature, s.agentObservabilitySDKSignature(parts[0]+"."+parts[1])) {
		return false
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return false
	}
	var claims agentObservabilitySDKClaims
	if json.Unmarshal(payload, &claims) != nil {
		return false
	}
	return claims.Issuer == agentObservabilitySDKIssuer && claims.Subject == agentObservabilitySDKSubject &&
		claims.Audience == agentObservabilitySDKAudience && claims.Scope == agentObservabilitySDKScope &&
		claims.IssuedAt <= now.Unix() && claims.ExpiresAt > now.Unix() &&
		claims.ExpiresAt-claims.IssuedAt == int64(agentObservabilitySDKJWTExpiry/time.Second)
}
