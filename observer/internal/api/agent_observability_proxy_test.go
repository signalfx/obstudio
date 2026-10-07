package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

type agentObservabilityProxyRoundTripper func(*http.Request) (*http.Response, error)

func (f agentObservabilityProxyRoundTripper) RoundTrip(r *http.Request) (*http.Response, error) {
	return f(r)
}

func newTestAgentObservabilityProxy(t *testing.T) (*splunkExportService, *http.ServeMux) {
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

func agentObservabilityProxyRequest(method, path, body string) *http.Request {
	request := httptest.NewRequest(method, "http://127.0.0.1:3000"+path, strings.NewReader(body))
	request.RemoteAddr = "127.0.0.1:54321"
	request.Header.Set("X-SF-Token", agentObservabilityLocalSDKKey)
	request.Header.Set("Content-Type", "application/json")
	return request
}

func agentObservabilityProxyResponse(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status, Header: http.Header{"Content-Type": {"application/json"}},
		Body: io.NopCloser(strings.NewReader(body)),
	}
}

func TestAgentObservabilityProxyForwardsProjectAndStreamRequests(t *testing.T) {
	for _, test := range []struct {
		method, path, body string
	}{
		{http.MethodGet, "/ao/api/projects?project_name=Agent%20Demo&type=gen_ai", ""},
		{http.MethodGet, "/ao/api/projects/all?type=gen_ai", ""},
		{http.MethodPost, "/ao/api/projects", `{"name":"Agent Demo","type":"gen_ai"}`},
		{http.MethodGet, "/ao/api/projects/project-1", ""},
		{http.MethodHead, "/ao/api/projects/project-1", ""},
		{http.MethodPatch, "/ao/api/projects/project-1", `{"name":"Updated"}`},
		{http.MethodDelete, "/ao/api/projects/project-1", ""},
		{http.MethodPost, "/ao/api/projects/project-1/log_streams", `{"name":"Production"}`},
		{http.MethodGet, "/ao/api/projects/project-1/log_streams/paginated?include_counts=false&limit=500&starting_token=0", ""},
		{http.MethodGet, "/ao/api/projects/project-1/log_streams/stream-1", ""},
		{http.MethodPut, "/ao/api/projects/project-1/log_streams/stream-1", `{"name":"Renamed"}`},
		{http.MethodDelete, "/ao/api/projects/project-1/log_streams/stream-1", ""},
	} {
		t.Run(test.method+" "+test.path, func(t *testing.T) {
			service, mux := newTestAgentObservabilityProxy(t)
			original := service.traces.Config()
			calls := 0
			service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(request *http.Request) (*http.Response, error) {
				calls++
				if request.URL.Scheme != "https" || request.URL.Host != "app.lab0.observability.splunkcloud.com" || request.URL.RequestURI() != test.path {
					t.Fatalf("unexpected upstream destination: %s", request.URL)
				}
				if request.Method != test.method || request.Header.Get("X-SF-Token") != testSplunkAccessToken {
					t.Fatal("method or Studio authentication was not preserved")
				}
				for _, name := range []string{"Authorization", "Cookie", "Forwarded", "X-Forwarded-Host"} {
					if request.Header.Get(name) != "" {
						t.Fatalf("forwarded untrusted header %s", name)
					}
				}
				gotBody, err := io.ReadAll(request.Body)
				if err != nil || string(gotBody) != test.body {
					t.Fatalf("upstream body changed: %q, %v", gotBody, err)
				}
				if _, ok := request.Context().Deadline(); !ok {
					t.Fatal("cloud request has no deadline")
				}
				return agentObservabilityProxyResponse(http.StatusCreated, `{"id":"cloud-resource"}`), nil
			})
			request := agentObservabilityProxyRequest(test.method, test.path, test.body)
			request.Header.Set("Authorization", "Bearer caller-credential")
			request.Header.Set("Cookie", "cloud_cookie=caller-secret")
			request.Header.Set("Forwarded", "host=attacker.example")
			request.Header.Set("X-Forwarded-Host", "attacker.example")
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, request)
			expectedBody := `{"id":"cloud-resource"}`
			if test.method == http.MethodHead {
				expectedBody = ""
			}
			if response.Code != http.StatusCreated || response.Body.String() != expectedBody || calls != 1 {
				t.Fatalf("response = %d %s, calls=%d", response.Code, response.Body.String(), calls)
			}
			if service.traces.Config() != original {
				t.Fatal("resource request changed the global trace destination")
			}
			if response.Header().Get("Cache-Control") != "no-store" || response.Header().Get("Access-Control-Allow-Origin") != "" {
				t.Fatal("resource response granted browser access or caching")
			}
		})
	}
}

func TestAgentObservabilityProxyPreservesCloudStatusAndSafeHeaders(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden, http.StatusNotFound, http.StatusConflict, http.StatusUnprocessableEntity, http.StatusTooManyRequests, http.StatusServiceUnavailable} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			service, mux := newTestAgentObservabilityProxy(t)
			service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(*http.Request) (*http.Response, error) {
				response := agentObservabilityProxyResponse(status, `{"detail":[{"loc":["body","name"],"msg":"cloud validation"}]}`)
				response.Header.Set("Retry-After", "5")
				response.Header.Set("Set-Cookie", "cloud-secret=hidden")
				response.Header.Set("X-SF-Token", testSplunkAccessToken)
				return response, nil
			})
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, agentObservabilityProxyRequest(http.MethodGet, "/ao/api/projects", ""))
			if response.Code != status || !strings.Contains(response.Body.String(), "cloud validation") || response.Header().Get("Retry-After") != "5" {
				t.Fatalf("cloud semantics changed: %d %s", response.Code, response.Body.String())
			}
			if response.Header().Get("Set-Cookie") != "" || response.Header().Get("X-SF-Token") != "" {
				t.Fatal("cloud authentication escaped in response headers")
			}
		})
	}
}

func TestAgentObservabilityProxyStandaloneSDKLoginAndAliases(t *testing.T) {
	service, mux := newTestAgentObservabilityProxy(t)
	login := agentObservabilityProxyRequest(http.MethodPost, "/login/api_key", `{"api_key":"local-gateway"}`)
	loginResponse := httptest.NewRecorder()
	mux.ServeHTTP(loginResponse, login)
	var credentials struct {
		AccessToken string `json:"access_token"`
	}
	if err := json.Unmarshal(loginResponse.Body.Bytes(), &credentials); err != nil || loginResponse.Code != http.StatusOK || credentials.AccessToken == "" {
		t.Fatalf("local SDK login failed: status=%d, error=%v", loginResponse.Code, err)
	}
	for _, path := range []string{"/projects?project_name=Agent%20Demo&type=gen_ai", "/projects/project-1/log_streams/paginated?include_counts=false&limit=500", "/projects/project-1/log_streams/stream-1"} {
		service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(request *http.Request) (*http.Response, error) {
			if request.URL.RequestURI() != "/ao/api"+path || request.Header.Get("Authorization") != "" || request.Header.Get("X-SF-Token") != testSplunkAccessToken {
				t.Fatal("standalone alias or private cloud authentication contract changed")
			}
			return agentObservabilityProxyResponse(http.StatusOK, `{"id":"cloud-resource"}`), nil
		})
		request := agentObservabilityProxyRequest(http.MethodGet, path, "")
		request.Header.Del("X-SF-Token")
		request.Header.Set("Authorization", "Bearer "+credentials.AccessToken)
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, request)
		if response.Code != http.StatusOK {
			t.Fatalf("standalone alias %s status=%d", path, response.Code)
		}
		request.Header.Del("Authorization")
		response = httptest.NewRecorder()
		mux.ServeHTTP(response, request)
		if response.Code != http.StatusUnauthorized {
			t.Fatalf("unauthenticated standalone alias %s status=%d", path, response.Code)
		}
	}
}

func TestAgentObservabilityProxyRejectsSuccessAfterConnectionChange(t *testing.T) {
	for _, test := range []struct {
		name, realm, token string
	}{
		{"realm changed", "us1", testSplunkAccessToken},
		{"token changed", "lab0", "replacement-test-token"},
	} {
		t.Run(test.name, func(t *testing.T) {
			service, mux := newTestAgentObservabilityProxy(t)
			calls := 0
			service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(*http.Request) (*http.Response, error) {
				calls++
				if err := service.apply(
					otlp.SplunkMetricsExporterConfig{Enabled: true, Realm: test.realm, AccessToken: test.token},
					otlp.SplunkTracesExporterConfig{Enabled: true, Realm: test.realm, AccessToken: test.token},
				); err != nil {
					t.Fatal(err)
				}
				return agentObservabilityProxyResponse(http.StatusCreated, `{"id":"old-cloud-resource"}`), nil
			})
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, agentObservabilityProxyRequest(http.MethodPost, "/ao/api/projects", `{"name":"Agent Demo"}`))
			if response.Code != http.StatusConflict || calls != 1 || strings.Contains(response.Body.String(), "old-cloud-resource") || !strings.Contains(response.Body.String(), "Reconcile before retrying") {
				t.Fatalf("stale cloud response was not safely rejected: status=%d calls=%d", response.Code, calls)
			}
		})
	}
}

func TestAgentObservabilityProxyBindsStreamsOnlyToResolvingConnection(t *testing.T) {
	const projectID = "3c90ff2e-f907-42a8-ac30-52e2b67f21a9"
	const firstStreamID = "02ea43cc-dd21-4081-b6c9-4aa4b843e163"
	const secondStreamID = "b40f5613-e45e-4657-8a06-f2d6855bb10e"
	service, mux := newTestAgentObservabilityProxy(t)
	service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(request *http.Request) (*http.Response, error) {
		streamID := firstStreamID
		if request.URL.Host == "app.us1.observability.splunkcloud.com" {
			streamID = secondStreamID
		}
		return agentObservabilityProxyResponse(http.StatusOK, `{"id":"`+streamID+`","project_id":"`+projectID+`"}`), nil
	})
	resolve := func(method, path string) {
		t.Helper()
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, agentObservabilityProxyRequest(method, path, `{}`))
		if response.Code != http.StatusOK {
			t.Fatalf("resource resolution failed: %d %s", response.Code, response.Body.String())
		}
	}
	isBound := func(streamID string) bool {
		t.Helper()
		ctx, cancel := context.WithCancel(context.Background())
		cancel() // A bound route reaches the canceled transport; an unbound one does not.
		_, err := service.traces.ExportAgentTraces(ctx, ptrace.NewTraces(), otlp.AgentTraceRoute{ProjectID: projectID, AgentStreamID: streamID})
		return err != nil && !strings.Contains(err.Error(), "unresolved for the active cloud connection")
	}
	streamPath := "/ao/api/projects/" + projectID + "/log_streams"
	resolve(http.MethodPost, streamPath)
	if !isBound(firstStreamID) || isBound(secondStreamID) {
		t.Fatal("cloud response did not bind only its resolved stream")
	}
	if err := service.apply(
		otlp.SplunkMetricsExporterConfig{Enabled: true, Realm: "lab0", AccessToken: testSplunkAccessToken},
		otlp.SplunkTracesExporterConfig{Enabled: true, Realm: "lab0", AccessToken: testSplunkAccessToken},
	); err != nil || !isBound(firstStreamID) {
		t.Fatalf("unchanged cloud destination invalidated its resolved stream: %v", err)
	}
	configure := func(realm string) {
		t.Helper()
		if err := service.apply(
			otlp.SplunkMetricsExporterConfig{Enabled: true, Realm: realm, AccessToken: testSplunkAccessToken},
			otlp.SplunkTracesExporterConfig{Enabled: true, Realm: realm, AccessToken: testSplunkAccessToken},
		); err != nil {
			t.Fatal(err)
		}
	}
	configure("us1")
	if isBound(firstStreamID) {
		t.Fatal("old realm stream remained bound after connection switch")
	}
	resolve(http.MethodPost, streamPath)
	if !isBound(secondStreamID) || isBound(firstStreamID) {
		t.Fatal("new realm did not require and accept its own resolved stream")
	}
	configure("lab0")
	if isBound(firstStreamID) || isBound(secondStreamID) {
		t.Fatal("A-to-B-to-A switch revived a stale stream")
	}
	resolve(http.MethodGet, streamPath+"/"+firstStreamID)
	if !isBound(firstStreamID) {
		t.Fatal("exact stream lookup did not rebind the current cloud route")
	}
}

func TestAgentObservabilityProxyRevokesDeletedStreamAndProjectRoutes(t *testing.T) {
	const firstProject = "3c90ff2e-f907-42a8-ac30-52e2b67f21a9"
	const secondProject = "a64a888f-7836-4c1d-b343-56df558d42f6"
	const firstStream = "02ea43cc-dd21-4081-b6c9-4aa4b843e163"
	const secondStream = "b40f5613-e45e-4657-8a06-f2d6855bb10e"
	service, mux := newTestAgentObservabilityProxy(t)
	service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(request *http.Request) (*http.Response, error) {
		if request.Method == http.MethodDelete {
			if request.URL.Query().Get("fail") == "1" {
				return agentObservabilityProxyResponse(http.StatusNotFound, `{}`), nil
			}
			return agentObservabilityProxyResponse(http.StatusNoContent, ""), nil
		}
		parts := strings.Split(strings.Trim(request.URL.Path, "/"), "/")
		return agentObservabilityProxyResponse(http.StatusOK, `{"id":"`+parts[5]+`","project_id":"`+parts[3]+`"}`), nil
	})
	request := func(method, path string, expected int) {
		t.Helper()
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, agentObservabilityProxyRequest(method, path, ""))
		if response.Code != expected {
			t.Fatalf("%s %s: status=%d body=%s", method, path, response.Code, response.Body.String())
		}
	}
	bound := func(projectID, streamID string) bool {
		t.Helper()
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		_, err := service.traces.ExportAgentTraces(ctx, ptrace.NewTraces(), otlp.AgentTraceRoute{ProjectID: projectID, AgentStreamID: streamID})
		return err != nil && !strings.Contains(err.Error(), "unresolved for the active cloud connection")
	}
	firstPath := "/ao/api/projects/" + firstProject
	secondPath := "/ao/api/projects/" + secondProject
	request(http.MethodGet, firstPath+"/log_streams/"+firstStream, http.StatusOK)
	request(http.MethodGet, firstPath+"/log_streams/"+secondStream, http.StatusOK)
	request(http.MethodGet, secondPath+"/log_streams/"+firstStream, http.StatusOK)
	request(http.MethodDelete, firstPath+"/log_streams/"+firstStream+"?fail=1", http.StatusNotFound)
	if !bound(firstProject, firstStream) {
		t.Fatal("failed stream deletion revoked an active route")
	}
	request(http.MethodDelete, firstPath+"/log_streams/"+firstStream, http.StatusNoContent)
	if bound(firstProject, firstStream) || !bound(firstProject, secondStream) || !bound(secondProject, firstStream) {
		t.Fatal("stream deletion did not revoke only the deleted route")
	}
	request(http.MethodDelete, firstPath+"?fail=1", http.StatusNotFound)
	if !bound(firstProject, secondStream) {
		t.Fatal("failed project deletion revoked an active route")
	}
	request(http.MethodDelete, firstPath, http.StatusNoContent)
	if bound(firstProject, secondStream) || !bound(secondProject, firstStream) {
		t.Fatal("project deletion did not revoke only its stream routes")
	}
}

func TestAgentObservabilityProxyRejectsInFlightStreamAfterRoundTripConnectionChange(t *testing.T) {
	service, mux := newTestAgentObservabilityProxy(t)
	service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(*http.Request) (*http.Response, error) {
		for _, realm := range []string{"us1", "lab0"} {
			if err := service.apply(
				otlp.SplunkMetricsExporterConfig{Enabled: true, Realm: realm, AccessToken: testSplunkAccessToken},
				otlp.SplunkTracesExporterConfig{Enabled: true, Realm: realm, AccessToken: testSplunkAccessToken},
			); err != nil {
				t.Fatal(err)
			}
		}
		return agentObservabilityProxyResponse(http.StatusOK, `{"id":"02ea43cc-dd21-4081-b6c9-4aa4b843e163","project_id":"3c90ff2e-f907-42a8-ac30-52e2b67f21a9"}`), nil
	})
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, agentObservabilityProxyRequest(http.MethodPost, "/ao/api/projects/3c90ff2e-f907-42a8-ac30-52e2b67f21a9/log_streams", `{}`))
	if response.Code != http.StatusConflict || strings.Contains(response.Body.String(), "02ea43cc") {
		t.Fatalf("round-trip destination change exposed stale stream: %d %s", response.Code, response.Body.String())
	}
}

func TestAgentObservabilityProxyDoesNotBindStreamFromDifferentProject(t *testing.T) {
	const projectID = "3c90ff2e-f907-42a8-ac30-52e2b67f21a9"
	const streamID = "02ea43cc-dd21-4081-b6c9-4aa4b843e163"
	service, mux := newTestAgentObservabilityProxy(t)
	service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(*http.Request) (*http.Response, error) {
		return agentObservabilityProxyResponse(http.StatusOK, `{"id":"`+streamID+`","project_id":"b40f5613-e45e-4657-8a06-f2d6855bb10e"}`), nil
	})
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, agentObservabilityProxyRequest(http.MethodGet, "/ao/api/projects/"+projectID+"/log_streams/"+streamID, ""))
	if response.Code != http.StatusOK {
		t.Fatalf("cloud response status changed: %d", response.Code)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := service.traces.ExportAgentTraces(ctx, ptrace.NewTraces(), otlp.AgentTraceRoute{ProjectID: projectID, AgentStreamID: streamID})
	if err == nil || !strings.Contains(err.Error(), "unresolved for the active cloud connection") {
		t.Fatalf("foreign project stream was bound: %v", err)
	}
}

func TestAgentObservabilityProxyRejectsUnsafeAndUnauthenticatedClients(t *testing.T) {
	for _, test := range []struct {
		name   string
		change func(*http.Request)
		status int
	}{
		{"remote", func(r *http.Request) { r.RemoteAddr = "192.0.2.1:9000" }, http.StatusForbidden},
		{"non-loopback Host", func(r *http.Request) { r.Host = "attacker.example" }, http.StatusForbidden},
		{"cross-origin", func(r *http.Request) { r.Header.Set("Origin", "https://attacker.example") }, http.StatusForbidden},
		{"same-origin browser", func(r *http.Request) {
			r.Header.Set("Origin", "http://127.0.0.1:3000")
			r.Header.Set(splunkBrowserRequestHeader, "1")
		}, http.StatusForbidden},
		{"fetch metadata", func(r *http.Request) {
			r.Header.Set("Sec-Fetch-Site", "same-origin")
			r.Header.Set(splunkBrowserRequestHeader, "1")
		}, http.StatusForbidden},
		{"missing marker", func(r *http.Request) { r.Header.Del("X-SF-Token") }, http.StatusUnauthorized},
		{"cloud token is not local auth", func(r *http.Request) { r.Header.Set("X-SF-Token", testSplunkAccessToken) }, http.StatusUnauthorized},
		{"unsupported method", func(r *http.Request) { r.Method = http.MethodOptions }, http.StatusMethodNotAllowed},
	} {
		t.Run(test.name, func(t *testing.T) {
			service, mux := newTestAgentObservabilityProxy(t)
			service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(*http.Request) (*http.Response, error) {
				t.Fatal("rejected request reached the cloud transport")
				return nil, errors.New("unexpected cloud call")
			})
			request := agentObservabilityProxyRequest(http.MethodGet, "/ao/api/projects", "")
			test.change(request)
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, request)
			if response.Code != test.status {
				t.Fatalf("status = %d, want %d", response.Code, test.status)
			}
		})
	}
}

func TestAgentObservabilityProxyUnavailableDestinations(t *testing.T) {
	for _, test := range []struct {
		name      string
		configure func(*splunkExportService) error
	}{
		{"disconnected", func(s *splunkExportService) error {
			return s.apply(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{})
		}},
		{"disabled", func(s *splunkExportService) error {
			config := s.traces.Config()
			config.Enabled = false
			return s.traces.Configure(config)
		}},
		{"different realms", func(s *splunkExportService) error {
			config := s.traces.Config()
			config.Realm = "us1"
			return s.traces.Configure(config)
		}},
		{"custom endpoint", func(s *splunkExportService) error {
			config := s.traces.Config()
			config.Endpoint = "https://attacker.example/ingest"
			return s.traces.Configure(config)
		}},
		{"shutdown", func(s *splunkExportService) error { s.traces.Shutdown(context.Background()); return nil }},
	} {
		t.Run(test.name, func(t *testing.T) {
			service, mux := newTestAgentObservabilityProxy(t)
			if err := test.configure(service); err != nil {
				t.Fatal(err)
			}
			service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(*http.Request) (*http.Response, error) {
				t.Fatal("unavailable destination reached the cloud transport")
				return nil, errors.New("unexpected cloud call")
			})
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, agentObservabilityProxyRequest(http.MethodGet, "/ao/api/projects", ""))
			if response.Code != http.StatusServiceUnavailable {
				t.Fatalf("status = %d, want 503", response.Code)
			}
		})
	}
}

func TestAgentObservabilityProxyBoundsFailuresAndDoesNotFollowRedirects(t *testing.T) {
	for _, test := range []struct {
		name, requestBody string
		upstream          func(*http.Request) (*http.Response, error)
		status            int
	}{
		{"large request", strings.Repeat("x", maxAgentObservabilityProxyRequestBytes+1), func(*http.Request) (*http.Response, error) { t.Fatal("oversized request forwarded"); return nil, nil }, http.StatusRequestEntityTooLarge},
		{"large response", "", func(*http.Request) (*http.Response, error) {
			return agentObservabilityProxyResponse(http.StatusOK, strings.Repeat("x", maxAgentObservabilityProxyResponseBytes+1)), nil
		}, http.StatusBadGateway},
		{"transport error", "", func(*http.Request) (*http.Response, error) {
			return nil, errors.New("transport echoed " + testSplunkAccessToken)
		}, http.StatusBadGateway},
		{"timeout", "", func(*http.Request) (*http.Response, error) {
			return nil, context.DeadlineExceeded
		}, http.StatusGatewayTimeout},
		{"redirect", "", func(*http.Request) (*http.Response, error) {
			response := agentObservabilityProxyResponse(http.StatusTemporaryRedirect, `{"detail":"redirect"}`)
			response.Header.Set("Location", "https://attacker.example/secrets")
			return response, nil
		}, http.StatusTemporaryRedirect},
		{"credential echo", "", func(*http.Request) (*http.Response, error) {
			response := agentObservabilityProxyResponse(http.StatusBadRequest, `{"detail":"`+testSplunkAccessToken+`"}`)
			response.Header.Set("ETag", testSplunkAccessToken)
			return response, nil
		}, http.StatusBadRequest},
	} {
		t.Run(test.name, func(t *testing.T) {
			service, mux := newTestAgentObservabilityProxy(t)
			calls := 0
			service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(request *http.Request) (*http.Response, error) {
				calls++
				return test.upstream(request)
			})
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, agentObservabilityProxyRequest(http.MethodPost, "/ao/api/projects", test.requestBody))
			if response.Code != test.status || calls > 1 {
				t.Fatalf("status = %d, calls = %d", response.Code, calls)
			}
			if strings.Contains(response.Body.String(), testSplunkAccessToken) || response.Header().Get("Location") != "" || response.Header().Get("ETag") == testSplunkAccessToken {
				t.Fatal("cloud credential or redirect target was disclosed")
			}
		})
	}
}

func TestAgentObservabilityProxyRejectsOversizedQuery(t *testing.T) {
	service, mux := newTestAgentObservabilityProxy(t)
	service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(*http.Request) (*http.Response, error) {
		t.Fatal("oversized query forwarded")
		return nil, nil
	})
	request := agentObservabilityProxyRequest(http.MethodGet, "/ao/api/projects?name="+strings.Repeat("x", maxAgentObservabilityProxyQueryBytes), "")
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", response.Code)
	}
}

func TestAgentObservabilityProxyCoexistsWithWebFallback(t *testing.T) {
	service, mux := newTestAgentObservabilityProxy(t)
	mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("web fallback"))
	})
	service.agentObservabilityProxyClient.Transport = agentObservabilityProxyRoundTripper(func(*http.Request) (*http.Response, error) {
		return agentObservabilityProxyResponse(http.StatusOK, `{"id":"cloud-resource"}`), nil
	})
	resourceResponse := httptest.NewRecorder()
	mux.ServeHTTP(resourceResponse, agentObservabilityProxyRequest(http.MethodGet, "/ao/api/projects/project-1", ""))
	if resourceResponse.Code != http.StatusOK || resourceResponse.Body.String() != `{"id":"cloud-resource"}` {
		t.Fatal("specific resource route was hidden by the web fallback")
	}
	webResponse := httptest.NewRecorder()
	mux.ServeHTTP(webResponse, agentObservabilityProxyRequest(http.MethodGet, "/", ""))
	if webResponse.Code != http.StatusOK || webResponse.Body.String() != "web fallback" {
		t.Fatal("resource route changed the existing web fallback")
	}
}

func TestAgentObservabilityProxyPathValidation(t *testing.T) {
	for _, test := range []struct {
		path  string
		valid bool
	}{
		{"/projects", true}, {"/projects/project-1/log_streams/stream-1", true}, {"/ao/api/projects/", true},
		{"/ao/api/projects/../api_keys", false}, {"/ao/api/projects/%2e%2e/api_keys", false},
		{"/ao/api/projects/id%2f..%2fapi_keys", false}, {"/ao/api/projects/id%5c..", false},
		{"/ao/api/projects/id%252f..", false}, {"/ao/api/projects/project-1/api_keys", false},
		{"/ao/api/projects/project-1/log_streams/stream-1/api_keys", false},
		{"/ao/api/projects//stream", false}, {"/ao/api/api_keys", false}, {"/healthcheck", false},
	} {
		t.Run(test.path, func(t *testing.T) {
			request := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:3000"+test.path, nil)
			path, valid := agentObservabilityProxyPath(request.URL)
			if valid != test.valid {
				t.Fatalf("path validity = %v, want %v", valid, test.valid)
			}
			if valid && !strings.HasPrefix(path, "/ao/api/projects") {
				t.Fatalf("alias did not resolve to canonical cloud path: %s", path)
			}
		})
	}
}
