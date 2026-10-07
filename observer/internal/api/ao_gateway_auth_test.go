package api

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func newTestAgentObservabilitySDKAuth(t *testing.T) (*splunkExportService, *http.ServeMux) {
	t.Helper()
	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Enabled: true, Realm: "lab0", AccessToken: testSplunkAccessToken,
	})
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Enabled: true, Realm: "lab0", AccessToken: testSplunkAccessToken,
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		metrics.Shutdown(context.Background())
		traces.Shutdown(context.Background())
	})
	service := newTestSplunkExportService(metrics, traces, nil)
	mux := http.NewServeMux()
	service.register(mux)
	return service, mux
}

func agentObservabilitySDKRequest(method, path, body string) *http.Request {
	request := httptest.NewRequest(method, "http://127.0.0.1:3000"+path, strings.NewReader(body))
	request.RemoteAddr = "127.0.0.1:54321"
	request.Header.Set("Content-Type", "application/json")
	return request
}

func agentObservabilitySDKLogin(t *testing.T, mux *http.ServeMux) string {
	t.Helper()
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, agentObservabilitySDKRequest(http.MethodPost, "/login/api_key", `{"api_key":"local-gateway"}`))
	if response.Code != http.StatusOK {
		t.Fatalf("login failed: %d %s", response.Code, response.Body.String())
	}
	var result struct {
		AccessToken string `json:"access_token"`
		TokenType   string `json:"token_type"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil || result.TokenType != "bearer" || result.AccessToken == "" {
		t.Fatalf("invalid SDK login response: %s, %v", response.Body.String(), err)
	}
	if response.Header().Get("Cache-Control") != "no-store" || response.Header().Get("Access-Control-Allow-Origin") != "" ||
		strings.Contains(response.Body.String(), testSplunkAccessToken) {
		t.Fatal("login response granted browser access, caching, or exposed the cloud credential")
	}
	return result.AccessToken
}

func TestAgentObservabilitySDKAuthProvidesOnlyLocalIdentity(t *testing.T) {
	_, mux := newTestAgentObservabilitySDKAuth(t)
	health := httptest.NewRecorder()
	mux.ServeHTTP(health, agentObservabilitySDKRequest(http.MethodGet, "/healthcheck", ""))
	if health.Code != http.StatusOK || !strings.Contains(health.Body.String(), `"cloud_identity":false`) {
		t.Fatalf("healthcheck failed: %d %s", health.Code, health.Body.String())
	}
	token := agentObservabilitySDKLogin(t, mux)
	request := agentObservabilitySDKRequest(http.MethodGet, "/current_user", "")
	request.Header.Set("Authorization", "Bearer "+token)
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	var user struct {
		ID            string `json:"id"`
		Email         string `json:"email"`
		Role          string `json:"role"`
		IdentityScope string `json:"identity_scope"`
		CloudIdentity bool   `json:"cloud_identity"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &user); err != nil || response.Code != http.StatusOK ||
		user.ID != agentObservabilitySDKSubject || user.Email != "local-sdk-gateway@localhost" || user.Role != "user" ||
		user.IdentityScope != agentObservabilitySDKScope || user.CloudIdentity {
		t.Fatalf("unexpected local SDK identity: %d %s, %v", response.Code, response.Body.String(), err)
	}
	if response.Header().Get("Cache-Control") != "no-store" || response.Header().Get("Access-Control-Allow-Origin") != "" ||
		strings.Contains(response.Body.String(), testSplunkAccessToken) {
		t.Fatal("local user response leaked cloud authentication or allowed browser access")
	}
}

func TestAgentObservabilitySDKAuthRejectsWrongOrMalformedKeys(t *testing.T) {
	_, mux := newTestAgentObservabilitySDKAuth(t)
	for _, test := range []struct {
		name, body string
		status     int
	}{
		{"wrong key", `{"api_key":"untrusted-cloud-key"}`, http.StatusUnauthorized},
		{"missing key", `{}`, http.StatusUnauthorized},
		{"null key", `{"api_key":null}`, http.StatusUnauthorized},
		{"unknown field", `{"api_key":"local-gateway","cloud_token":"do-not-echo"}`, http.StatusBadRequest},
		{"multiple objects", `{"api_key":"local-gateway"}{}`, http.StatusBadRequest},
		{"invalid JSON", `{"api_key":"do-not-echo"`, http.StatusBadRequest},
		{"oversize", `{"api_key":"` + strings.Repeat("a", maxSplunkExportRequestBytes) + `"}`, http.StatusBadRequest},
	} {
		t.Run(test.name, func(t *testing.T) {
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, agentObservabilitySDKRequest(http.MethodPost, "/login/api_key", test.body))
			if response.Code != test.status || strings.Contains(response.Body.String(), "do-not-echo") ||
				strings.Contains(response.Body.String(), "untrusted-cloud-key") || strings.Contains(response.Body.String(), "access_token") {
				t.Fatalf("invalid login response: %d %s", response.Code, response.Body.String())
			}
		})
	}
}

func TestAgentObservabilitySDKAuthRejectsNonProcessRequests(t *testing.T) {
	_, mux := newTestAgentObservabilitySDKAuth(t)
	for _, test := range []struct {
		name   string
		change func(*http.Request)
	}{
		{"remote peer", func(r *http.Request) { r.RemoteAddr = "192.0.2.1:1234" }},
		{"container bridge peer", func(r *http.Request) { r.RemoteAddr = "172.18.0.2:1234" }},
		{"container service Host", func(r *http.Request) { r.Host = "obstudio:3000" }},
		{"malformed peer", func(r *http.Request) { r.RemoteAddr = "127.0.0.1" }},
		{"DNS rebinding Host", func(r *http.Request) { r.Host = "attacker.example:3000" }},
		{"missing Host", func(r *http.Request) { r.Host = "" }},
		{"userinfo Host", func(r *http.Request) { r.Host = "attacker@127.0.0.1:3000" }},
		{"path Host", func(r *http.Request) { r.Host = "127.0.0.1:3000/other" }},
		{"malformed port", func(r *http.Request) { r.Host = "localhost:not-a-port" }},
		{"cross origin", func(r *http.Request) { r.Header.Set("Origin", "https://attacker.example") }},
		{"null origin", func(r *http.Request) { r.Header.Set("Origin", "null") }},
		{"empty origin", func(r *http.Request) { r.Header["Origin"] = []string{""} }},
		{"same origin browser", func(r *http.Request) {
			r.Header.Set("Origin", "http://127.0.0.1:3000")
			r.Header.Set("Sec-Fetch-Site", "same-origin")
			r.Header.Set(splunkBrowserRequestHeader, "1")
		}},
		{"fetch only", func(r *http.Request) { r.Header.Set("Sec-Fetch-Mode", "cors") }},
		{"browser marker only", func(r *http.Request) { r.Header.Set(splunkBrowserRequestHeader, "1") }},
	} {
		t.Run(test.name, func(t *testing.T) {
			for _, endpoint := range []struct{ method, path, body string }{
				{http.MethodGet, "/healthcheck", ""},
				{http.MethodPost, "/login/api_key", `{"api_key":"local-gateway"}`},
				{http.MethodGet, "/current_user", ""},
			} {
				request := agentObservabilitySDKRequest(endpoint.method, endpoint.path, endpoint.body)
				test.change(request)
				response := httptest.NewRecorder()
				mux.ServeHTTP(response, request)
				if response.Code != http.StatusForbidden || response.Header().Get("Access-Control-Allow-Origin") != "" ||
					strings.Contains(response.Body.String(), "access_token") {
					t.Fatalf("%s allowed unsafe client: %d %s", endpoint.path, response.Code, response.Body.String())
				}
			}
		})
	}
	for _, host := range []string{"localhost:3000", "localhost.:3000", "[::1]:3000", "127.0.0.2:3000"} {
		request := agentObservabilitySDKRequest(http.MethodGet, "/healthcheck", "")
		request.Host = host
		if !isLocalAgentObservabilitySDKRequest(request) {
			t.Errorf("rejected loopback Host %q", host)
		}
	}
}

func TestAgentObservabilitySDKAuthRequiresAnEnabledConnection(t *testing.T) {
	service, mux := newTestAgentObservabilitySDKAuth(t)
	config := service.traces.Config()
	config.Enabled = false
	if err := service.traces.Configure(config); err != nil {
		t.Fatal(err)
	}
	for _, endpoint := range []struct{ method, path, body string }{
		{http.MethodGet, "/healthcheck", ""},
		{http.MethodPost, "/login/api_key", `{"api_key":"local-gateway"}`},
		{http.MethodGet, "/current_user", ""},
	} {
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, agentObservabilitySDKRequest(endpoint.method, endpoint.path, endpoint.body))
		if response.Code != http.StatusServiceUnavailable || strings.Contains(response.Body.String(), "access_token") {
			t.Fatalf("%s claimed readiness: %d %s", endpoint.path, response.Code, response.Body.String())
		}
	}
}

func TestAgentObservabilitySDKAuthAllowsTraceOnlyConnection(t *testing.T) {
	service, mux := newTestAgentObservabilitySDKAuth(t)
	config := service.metrics.Config()
	config.Enabled = false
	if err := service.metrics.Configure(config); err != nil {
		t.Fatal(err)
	}
	if _, _, _, ready := service.agentObservabilityProxyDestination(); !ready {
		t.Fatal("trace-only realm destination was rejected")
	}
	health := httptest.NewRecorder()
	mux.ServeHTTP(health, agentObservabilitySDKRequest(http.MethodGet, "/healthcheck", ""))
	if health.Code != http.StatusOK {
		t.Fatalf("trace-only gateway healthcheck failed: %d %s", health.Code, health.Body.String())
	}
	agentObservabilitySDKLogin(t, mux)
}

func TestAgentObservabilitySDKJWTValidatesSignatureScopeAndExpiry(t *testing.T) {
	service, _ := newTestAgentObservabilitySDKAuth(t)
	now := time.Unix(1_800_000_000, 0)
	token := service.issueAgentObservabilitySDKJWT(now)
	if !service.validAgentObservabilitySDKJWT(token, now) || !service.validAgentObservabilitySDKJWT(token, now.Add(time.Minute)) {
		t.Fatal("gateway rejected its valid session")
	}
	if service.validAgentObservabilitySDKJWT(token, now.Add(agentObservabilitySDKJWTExpiry)) ||
		service.validAgentObservabilitySDKJWT(token, now.Add(-time.Second)) ||
		service.validAgentObservabilitySDKJWT(token+"corrupt", now) ||
		service.validAgentObservabilitySDKJWT("not-a-jwt", now) ||
		service.validAgentObservabilitySDKJWT(strings.Repeat("x", 2049), now) {
		t.Fatal("gateway accepted an expired, future, malformed or modified session")
	}
	restarted, _ := newTestAgentObservabilitySDKAuth(t)
	if restarted.validAgentObservabilitySDKJWT(token, now) {
		t.Fatal("new gateway process accepted a prior process session")
	}
	parts := strings.Split(token, ".")
	for _, field := range []string{"iss", "sub", "aud", "scope", "exp"} {
		payload, _ := base64.RawURLEncoding.DecodeString(parts[1])
		var claims map[string]any
		if err := json.Unmarshal(payload, &claims); err != nil {
			t.Fatal(err)
		}
		claims[field] = "other-principal"
		if field == "exp" {
			claims[field] = now.Add(time.Hour).Unix()
		}
		changed, _ := json.Marshal(claims)
		message := parts[0] + "." + base64.RawURLEncoding.EncodeToString(changed)
		modified := message + "." + base64.RawURLEncoding.EncodeToString(service.agentObservabilitySDKSignature(message))
		if service.validAgentObservabilitySDKJWT(modified, now) {
			t.Errorf("gateway accepted signed wrong %s claim", field)
		}
	}
}

func TestAgentObservabilitySDKCurrentUserRequiresASingleBearer(t *testing.T) {
	_, mux := newTestAgentObservabilitySDKAuth(t)
	token := agentObservabilitySDKLogin(t, mux)
	for _, headers := range [][]string{nil, {"Bearer cloud-credential"}, {"Bearer " + token, "Bearer " + token}, {"Basic " + token}} {
		request := agentObservabilitySDKRequest(http.MethodGet, "/current_user", "")
		request.Header["Authorization"] = headers
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, request)
		if response.Code != http.StatusUnauthorized {
			t.Fatalf("current_user accepted invalid authorization: %d %s", response.Code, response.Body.String())
		}
	}
}

// Opt in with a checkout whose locked environment already contains splunk-ao
// 0.4.0. No dependencies are installed and no vendor code is changed. The child
// has an isolated home and refuses non-loopback network connections.
func TestAgentObservabilitySDKInstalledCompatibility(t *testing.T) {
	repo := os.Getenv("OBSTUDIO_AO_SDK_TEST_REPO")
	if repo == "" {
		t.Skip("set OBSTUDIO_AO_SDK_TEST_REPO to an existing locked SDK test checkout")
	}
	uv := os.Getenv("OBSTUDIO_AO_SDK_TEST_UV")
	if uv == "" {
		uv = "uv"
	}
	service, mux := newTestAgentObservabilitySDKAuth(t)
	restarted, restartedMux := newTestAgentObservabilitySDKAuth(t)
	var active atomic.Pointer[http.ServeMux]
	active.Store(mux)
	var mu sync.Mutex
	var loginCalls, projectCalls, streamCalls, exportCalls int
	var exportedStreams []string
	const projectID = "3c90ff2e-f907-42a8-ac30-52e2b67f21a9"
	streamIDs := []string{"02ea43cc-dd21-4081-b6c9-4aa4b843e163", "b40f5613-e45e-4657-8a06-f2d6855bb10e"}
	transport := agentObservabilityProxyRoundTripper(func(r *http.Request) (*http.Response, error) {
		mu.Lock()
		defer mu.Unlock()
		if r.Header.Get("X-SF-Token") != testSplunkAccessToken || r.Header.Get("Authorization") != "" ||
			r.Header.Get("Splunk-AO-API-Key") != "" || r.URL.Host != "app.lab0.observability.splunkcloud.com" {
			return nil, fmt.Errorf("SDK credential or non-cloud destination reached the synthetic cloud boundary")
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			return nil, err
		}
		var payload map[string]any
		if json.Unmarshal(body, &payload) != nil || r.Method != http.MethodPost {
			return nil, fmt.Errorf("unexpected SDK resource request")
		}
		id, name := projectID, "SDK Gateway Compatibility"
		switch r.URL.Path {
		case "/ao/api/projects":
			projectCalls++
			owner, hasOwner := payload["created_by"]
			if !hasOwner || owner != nil || payload["name"] != name || payload["type"] != "gen_ai" {
				return nil, fmt.Errorf("SDK project creation injected a local identity or changed its normal resource payload")
			}
			// A fresh gateway process invalidates the SDK's cached bearer token.
			// Its normal API-key refresh path must obtain a new local session.
			active.Store(restartedMux)
		case "/ao/api/projects/" + projectID + "/log_streams":
			if streamCalls >= len(streamIDs) || payload["created_by"] != nil || len(payload) != 1 {
				return nil, fmt.Errorf("unexpected SDK stream creation or local owner injection")
			}
			id, name = streamIDs[streamCalls], fmt.Sprint(payload["name"])
			streamCalls++
		default:
			return nil, fmt.Errorf("unexpected resource path %s", r.URL.Path)
		}
		response := fmt.Sprintf(`{"id":%q,"name":%q,"project_id":%q,"created_by":null,"type":"gen_ai","created_at":"2026-10-06T00:00:00+00:00","updated_at":"2026-10-06T00:00:00+00:00"}`, id, name, projectID)
		return agentObservabilityProxyResponse(http.StatusOK, response), nil
	})
	service.agentObservabilityProxyClient.Transport = transport
	restarted.agentObservabilityProxyClient.Transport = transport
	for _, target := range []*http.ServeMux{mux, restartedMux} {
		target.HandleFunc("POST /otel/v1/traces", func(w http.ResponseWriter, r *http.Request) {
			mu.Lock()
			defer mu.Unlock()
			body, err := io.ReadAll(r.Body)
			if !isLocalAgentObservabilitySDKRequest(r) || r.Header.Get("Splunk-AO-API-Key") != agentObservabilityLocalSDKKey ||
				r.Header.Get("X-SF-Token") != "" || r.Header.Get("Authorization") != "" ||
				r.Header.Get("Projectid") != projectID || r.Header.Get("Content-Type") != "application/x-protobuf" || err != nil || len(body) == 0 {
				t.Error("normal SDK exporter did not use the local credential-free OTLP contract")
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			exportCalls++
			exportedStreams = append(exportedStreams, r.Header.Get("Logstreamid"))
			w.Header().Set("Content-Type", "application/x-protobuf")
			w.WriteHeader(http.StatusOK)
		})
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/login/api_key" {
			mu.Lock()
			loginCalls++
			mu.Unlock()
		}
		active.Load().ServeHTTP(w, r)
	}))
	defer server.Close()
	const script = `
import importlib.metadata, ipaddress, socket
connect = socket.socket.connect
def local_only(self, address):
    if isinstance(address, tuple):
        try:
            allowed = ipaddress.ip_address(address[0]).is_loopback
        except ValueError:
            allowed = address[0] == "localhost"
        if not allowed:
            raise RuntimeError("SDK compatibility test forbids non-loopback network")
    return connect(self, address)
socket.socket.connect = local_only
assert importlib.metadata.version("splunk-ao") == "0.4.0"
from splunk_ao.projects import Projects
from splunk_ao.agent_streams import AgentStreams
from splunk_ao.otel import SplunkAOOTLPExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
project = Projects().create(name="SDK Gateway Compatibility")
assert project.created_by is None
for name in ("Live One", "Live Two"):
    stream = AgentStreams().create(name=name, project_id=project.id)
    assert stream.created_by is None
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SplunkAOOTLPExporter(project_id=project.id, agent_stream_id=stream.id)))
    with provider.get_tracer("sdk-compatibility").start_as_current_span(name) as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", "credential-free-local-demo")
    assert provider.force_flush()
    provider.shutdown()
print("Installed SDK resource creation, restart reauthentication and per-stream OTLP passed")
`
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, uv, "run", "--locked", "--no-sync", "python", "-c", script)
	command.Dir = repo
	isolatedHome := t.TempDir()
	command.Env = []string{
		"PATH=" + os.Getenv("PATH"), "HOME=" + isolatedHome, "NETRC=" + isolatedHome + "/missing-netrc",
		"XDG_CONFIG_HOME=" + isolatedHome, "UV_OFFLINE=true", "UV_PYTHON_DOWNLOADS=never", "UV_CACHE_DIR=" + isolatedHome + "/uv-cache",
		"SPLUNK_AO_API_URL=" + server.URL, "SPLUNK_AO_CONSOLE_URL=" + server.URL, "SPLUNK_AO_API_KEY=" + agentObservabilityLocalSDKKey,
	}
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("installed SDK compatibility failed: %v\n%s", err, output)
	}
	mu.Lock()
	defer mu.Unlock()
	if projectCalls != 1 || streamCalls != 2 || exportCalls != 2 || loginCalls < 4 ||
		len(exportedStreams) != 2 || exportedStreams[0] != streamIDs[0] || exportedStreams[1] != streamIDs[1] {
		t.Fatalf("unexpected normal SDK requests: project=%d streams=%d exports=%d logins=%d routes=%v", projectCalls, streamCalls, exportCalls, loginCalls, exportedStreams)
	}
	t.Log(strings.TrimSpace(string(output)))
}
