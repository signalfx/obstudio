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
