package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

const (
	maxAgentObservabilityProxyRequestBytes  = 2 * 1024 * 1024
	maxAgentObservabilityProxyResponseBytes = 8 * 1024 * 1024
	maxAgentObservabilityProxyQueryBytes    = 32 * 1024
)

func newAgentObservabilityProxyHTTPClient() *http.Client {
	return &http.Client{
		Timeout: splunkConnectionTestTimeout,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
}

func (s *splunkExportService) registerAgentObservabilityProxy(mux *http.ServeMux) {
	proxy := func(w http.ResponseWriter, r *http.Request) {
		if !isLocalAgentObservabilitySDKRequest(r) {
			writeSplunkExportError(w, http.StatusForbidden, "Agent Observability SDK requests must come from a local process")
			return
		}
		authorized := false
		if strings.HasPrefix(r.URL.Path, "/ao/api/") {
			authorized = r.Header.Get("X-SF-Token") == agentObservabilityLocalSDKKey
		} else {
			authorized = s.validAgentObservabilitySDKBearer(r)
		}
		if !authorized {
			writeSplunkExportError(w, http.StatusUnauthorized, "local Agent Observability SDK authentication is required")
			return
		}
		s.agentObservabilityProxy(w, r)
	}
	for _, path := range []string{"/ao/api/projects", "/ao/api/projects/", "/projects", "/projects/"} {
		for _, method := range []string{http.MethodGet, http.MethodHead, http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete} {
			mux.HandleFunc(method+" "+path, proxy)
		}
	}
}

// agentObservabilityProxyDestination uses only the active Studio connection;
// callers must not expose the access token or accept an upstream from a request.
func (s *splunkExportService) agentObservabilityProxyDestination() (realm, accessToken string, generation uint64, ready bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	traces, generation, enabled := s.traces.AgentConnectionSnapshot()
	if !enabled || traces.Endpoint != "" ||
		!splunkRealmPattern.MatchString(traces.Realm) || strings.TrimSpace(traces.AccessToken) == "" {
		return "", "", 0, false
	}
	if s.metrics.ExportEnabled() {
		metrics := s.metrics.Config()
		if !sameSplunkCloudRealm(metrics.Realm, metrics.AccessToken, metrics.Endpoint != "",
			traces.Realm, traces.AccessToken, false) {
			return "", "", 0, false
		}
	}
	return traces.Realm, traces.AccessToken, generation, true
}

// A successful cloud stream-resource response is the only source of routes
// accepted by the trace data plane. Project IDs alone do not authorize a route.
func (s *splunkExportService) bindAgentStreamResource(path, method string, body []byte, generation uint64) {
	if method == http.MethodDelete {
		return
	}
	parts := strings.Split(strings.Trim(path, "/"), "/")
	if len(parts) < 5 || parts[0] != "ao" || parts[1] != "api" || parts[2] != "projects" || parts[4] != "log_streams" {
		return
	}
	projectID := parts[3]
	var payload any
	if len(body) > 0 && json.Unmarshal(body, &payload) != nil {
		return
	}
	if len(parts) == 6 && parts[5] != "paginated" {
		if object, ok := payload.(map[string]any); ok {
			if responseProject, hasProject := object["project_id"].(string); hasProject && !strings.EqualFold(responseProject, projectID) {
				return
			}
			if responseID, hasID := object["id"].(string); hasID && !strings.EqualFold(responseID, parts[5]) {
				return
			}
		} else if len(body) > 0 {
			return
		}
		s.traces.BindAgentTraceRoute(otlp.AgentTraceRoute{ProjectID: projectID, AgentStreamID: parts[5]}, generation)
	}
	var visit func(any)
	visit = func(value any) {
		switch entry := value.(type) {
		case map[string]any:
			if streamID, ok := entry["id"].(string); ok {
				if responseProject, hasProject := entry["project_id"].(string); !hasProject || strings.EqualFold(responseProject, projectID) {
					s.traces.BindAgentTraceRoute(otlp.AgentTraceRoute{ProjectID: projectID, AgentStreamID: streamID}, generation)
				}
			}
			for _, field := range []string{"data", "items", "results", "log_streams"} {
				visit(entry[field])
			}
		case []any:
			for _, item := range entry {
				visit(item)
			}
		}
	}
	visit(payload)
}

func agentObservabilityProxyPath(requestURL *url.URL) (string, bool) {
	path := requestURL.Path
	if path == "/projects" || strings.HasPrefix(path, "/projects/") {
		path = "/ao/api" + path
	}
	if path != "/ao/api/projects" && !strings.HasPrefix(path, "/ao/api/projects/") {
		return "", false
	}
	// Decode before checking segments, and reject escaped separators so a cloud
	// router cannot reinterpret a path that the local boundary considered safe.
	escaped := strings.ToLower(requestURL.EscapedPath())
	if strings.Contains(escaped, "%2f") || strings.Contains(escaped, "%5c") || strings.Contains(path, "\\") {
		return "", false
	}
	segments := strings.Split(strings.TrimSuffix(path, "/"), "/")[1:]
	for _, segment := range segments {
		if segment == "" || segment == "." || segment == ".." {
			return "", false
		}
		for _, c := range segment {
			if c < 0x21 || c > 0x7e || c == '%' {
				return "", false
			}
		}
	}
	// Limit the cloud surface to project and stream resources, not credential,
	// authentication, or other control-plane endpoints that could return secrets.
	resource := segments[2:]
	if len(resource) > 4 || (len(resource) >= 3 && resource[2] != "log_streams") {
		return "", false
	}
	return path, true
}

func (s *splunkExportService) agentObservabilityProxy(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	ctx, cancel := context.WithTimeout(r.Context(), splunkConnectionTestTimeout)
	defer cancel()
	deadline, _ := ctx.Deadline()
	controller := http.NewResponseController(w)
	// Native HTTP writers support these deadlines; in-memory test recorders may
	// not. Bound slow request bodies and response readers as well as the cloud hop.
	_ = controller.SetReadDeadline(deadline)
	_ = controller.SetWriteDeadline(deadline)
	defer controller.SetReadDeadline(time.Time{})
	defer controller.SetWriteDeadline(time.Time{})
	defer controller.Flush()
	switch r.Method {
	case http.MethodGet, http.MethodHead, http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
	default:
		w.Header().Set("Allow", "GET, HEAD, POST, PUT, PATCH, DELETE")
		writeSplunkExportError(w, http.StatusMethodNotAllowed, "unsupported Agent Observability resource method")
		return
	}
	path, valid := agentObservabilityProxyPath(r.URL)
	if !valid || len(r.URL.RawQuery) > maxAgentObservabilityProxyQueryBytes {
		writeSplunkExportError(w, http.StatusBadRequest, "invalid Agent Observability resource URL")
		return
	}
	realm, accessToken, generation, ready := s.agentObservabilityProxyDestination()
	if !ready {
		writeSplunkExportError(w, http.StatusServiceUnavailable, "connect and enable a realm-based Splunk Observability Cloud destination before using Agent Observability resources")
		return
	}
	var body []byte
	if r.Body != nil {
		var err error
		body, err = io.ReadAll(http.MaxBytesReader(w, r.Body, maxAgentObservabilityProxyRequestBytes))
		if err != nil {
			var tooLarge *http.MaxBytesError
			var timeout net.Error
			if errors.As(err, &tooLarge) {
				writeSplunkExportError(w, http.StatusRequestEntityTooLarge, "Agent Observability resource request is too large")
			} else if errors.As(err, &timeout) && timeout.Timeout() {
				writeSplunkExportError(w, http.StatusRequestTimeout, "Agent Observability resource request timed out")
			} else {
				writeSplunkExportError(w, http.StatusBadRequest, "could not read Agent Observability resource request")
			}
			return
		}
	}
	upstreamURL := &url.URL{
		Scheme: "https", Host: "app." + realm + ".observability.splunkcloud.com",
		Path: path, RawQuery: r.URL.RawQuery,
	}
	request, err := http.NewRequestWithContext(ctx, r.Method, upstreamURL.String(), bytes.NewReader(body))
	if err != nil {
		writeSplunkExportError(w, http.StatusBadRequest, "invalid Agent Observability resource request")
		return
	}
	request.Header.Set("X-SF-Token", accessToken)
	request.Header.Set("Splunk-AO-SDK", "obstudio")
	for _, name := range []string{"Accept", "Content-Type", "If-Match", "If-None-Match"} {
		if value := r.Header.Get(name); value != "" {
			request.Header.Set(name, value)
		}
	}
	response, err := s.agentObservabilityProxyClient.Do(request)
	if err != nil {
		status := http.StatusBadGateway
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
			status = http.StatusGatewayTimeout
		}
		writeSplunkExportError(w, status, "Agent Observability cloud request failed")
		return
	}
	defer response.Body.Close()
	responseBody, err := io.ReadAll(io.LimitReader(response.Body, maxAgentObservabilityProxyResponseBytes+1))
	if err != nil || len(responseBody) > maxAgentObservabilityProxyResponseBytes {
		writeSplunkExportError(w, http.StatusBadGateway, "invalid or oversized Agent Observability cloud response")
		return
	}
	currentRealm, currentToken, currentGeneration, currentReady := s.agentObservabilityProxyDestination()
	if !currentReady || currentRealm != realm || currentToken != accessToken || currentGeneration != generation {
		writeSplunkExportError(w, http.StatusConflict, "cloud destination changed during the resource request; it may already have completed in the previous destination. Reconcile before retrying")
		return
	}
	if response.StatusCode >= http.StatusOK && response.StatusCode < http.StatusMultipleChoices {
		s.bindAgentStreamResource(path, r.Method, responseBody, generation)
	}
	// Cloud responses are otherwise opaque, including validation errors. Never
	// reflect Studio's credential if an upstream error happens to echo it.
	responseBody = bytes.ReplaceAll(responseBody, []byte(accessToken), []byte("[REDACTED]"))
	for _, name := range []string{"Content-Type", "Retry-After", "ETag", "Last-Modified"} {
		if value := response.Header.Get(name); value != "" && !strings.Contains(value, accessToken) {
			w.Header().Set(name, value)
		}
	}
	w.WriteHeader(response.StatusCode)
	if r.Method != http.MethodHead {
		_, _ = w.Write(responseBody)
	}
}
