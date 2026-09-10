package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
)

const testSplunkAccessToken = "splunk-access-token-1234"

func TestSplunkExportUsesLocalOriginTrustAndHasNoCredentialRecoveryAPI(t *testing.T) {
	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	service := newTestSplunkExportService(metrics, traces, nil)
	mux := http.NewServeMux()
	service.register(mux)

	localRequest := httptest.NewRequest(http.MethodPost, "/api/splunk/export",
		strings.NewReader(`{"realm":"us1","accessToken":"`+testSplunkAccessToken+`"}`))
	localRequest.RemoteAddr = "127.0.0.1:54321"
	localRequest.Header.Set("Content-Type", "application/json")
	localResponse := httptest.NewRecorder()
	mux.ServeHTTP(localResponse, localRequest)
	if localResponse.Code != http.StatusOK {
		t.Fatalf("local configure status = %d, want %d; body=%s", localResponse.Code, http.StatusOK, localResponse.Body.String())
	}
	if strings.Contains(localResponse.Body.String(), testSplunkAccessToken) {
		t.Fatalf("local configure response exposed ingest token: %s", localResponse.Body.String())
	}
	if got := localResponse.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("local configure Access-Control-Allow-Origin = %q, want unset", got)
	}

	for _, endpoint := range []struct {
		method string
		path   string
	}{
		{method: http.MethodGet, path: "/api/splunk/export/configuration"},
		{method: http.MethodPost, path: "/api/splunk/export/shutdown-snapshot"},
	} {
		request := httptest.NewRequest(endpoint.method, endpoint.path, strings.NewReader(`{}`))
		request.RemoteAddr = "127.0.0.1:54321"
		request.Header.Set("Authorization", "Bearer obsolete-local-secret")
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, request)
		if response.Code != http.StatusNotFound {
			t.Fatalf("%s %s status = %d, want %d; body=%s", endpoint.method, endpoint.path, response.Code, http.StatusNotFound, response.Body.String())
		}
		if strings.Contains(response.Body.String(), testSplunkAccessToken) {
			t.Fatalf("%s exposed ingest token: %s", endpoint.path, response.Body.String())
		}
	}

	crossOriginRequest := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:3000/api/splunk/export",
		strings.NewReader(`{"realm":"us2","accessToken":"attacker-token"}`))
	crossOriginRequest.RemoteAddr = "127.0.0.1:54321"
	crossOriginRequest.Header.Set("Content-Type", "application/json")
	crossOriginRequest.Header.Set("Origin", "https://attacker.example")
	crossOriginRequest.Header.Set("Sec-Fetch-Site", "cross-site")
	crossOriginResponse := httptest.NewRecorder()
	mux.ServeHTTP(crossOriginResponse, crossOriginRequest)
	if crossOriginResponse.Code != http.StatusForbidden {
		t.Fatalf("cross-origin configure status = %d, want %d; body=%s", crossOriginResponse.Code, http.StatusForbidden, crossOriginResponse.Body.String())
	}
	if got := metrics.Config(); got.Realm != "us1" || got.AccessToken != testSplunkAccessToken {
		t.Fatalf("cross-origin configure changed metrics config: %+v", got)
	}
}

func TestSplunkExportAcceptsSameOriginLocalhostTrailingDot(t *testing.T) {
	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	request := httptest.NewRequest(http.MethodPost, "http://localhost.:3000/api/splunk/export",
		strings.NewReader(`{"realm":"us1","accessToken":"`+testSplunkAccessToken+`"}`))
	request.RemoteAddr = "127.0.0.1:54321"
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Origin", "http://localhost.:3000")
	request.Header.Set("Sec-Fetch-Site", "same-origin")
	request.Header.Set(splunkBrowserRequestHeader, "1")
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("localhost. same-origin configure status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body.String())
	}
}

func TestSplunkMutationPreflightDoesNotGrantCrossOriginAccess(t *testing.T) {
	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	Register(mux, store.New(), metrics, traces)
	request := httptest.NewRequest(http.MethodOptions, "http://127.0.0.1:3000/api/splunk/export", nil)
	request.RemoteAddr = "127.0.0.1:54321"
	request.Header.Set("Origin", "https://attacker.example")
	request.Header.Set("Access-Control-Request-Method", http.MethodPost)
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	if response.Code != http.StatusForbidden {
		t.Fatalf("preflight status = %d, want %d", response.Code, http.StatusForbidden)
	}
	if got := response.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("preflight Access-Control-Allow-Origin = %q, want unset", got)
	}
}

func TestSplunkExportLifecycleDoesNotExposeToken(t *testing.T) {
	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	statusResponse := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
	if statusResponse.Code != http.StatusOK {
		t.Fatalf("status request = %d, body = %s", statusResponse.Code, statusResponse.Body.String())
	}
	if statusResponse.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("cache control = %q, want no-store", statusResponse.Header().Get("Cache-Control"))
	}

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"us0","accessToken":"`+testSplunkAccessToken+`"}`)

	if response.Code != http.StatusOK {
		t.Fatalf("configure status = %d, body = %s", response.Code, response.Body.String())
	}
	if strings.Contains(response.Body.String(), testSplunkAccessToken) {
		t.Fatal("configure response exposed the access token")
	}
	var configured splunkExportStatusResponse
	if err := json.Unmarshal(response.Body.Bytes(), &configured); err != nil {
		t.Fatal(err)
	}
	if !configured.Connected || configured.Enabled || configured.Realm != "us0" {
		t.Fatalf("unexpected configured state: %+v", configured)
	}
	if !configured.Metrics.Configured || !configured.Traces.Configured {
		t.Fatalf("expected both signals to report configured: %+v", configured)
	}

	response = splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{"enabled":true}`)

	if response.Code != http.StatusOK {
		t.Fatalf("enable status = %d, body = %s", response.Code, response.Body.String())
	}
	var enabled splunkExportStatusResponse
	if err := json.Unmarshal(response.Body.Bytes(), &enabled); err != nil {
		t.Fatal(err)
	}
	if !enabled.Enabled || !enabled.Metrics.Enabled || !enabled.Traces.Enabled {
		t.Fatalf("unexpected enabled state: %+v", enabled)
	}

	response = splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/forget",
		`{}`)

	if response.Code != http.StatusOK {
		t.Fatalf("forget status = %d, body = %s", response.Code, response.Body.String())
	}
	var forgotten splunkExportStatusResponse
	if err := json.Unmarshal(response.Body.Bytes(), &forgotten); err != nil {
		t.Fatal(err)
	}
	if forgotten.Connected || forgotten.Enabled || forgotten.Realm != "" {
		t.Fatalf("unexpected forgotten state: %+v", forgotten)
	}
	if forgotten.Metrics.Configured || forgotten.Traces.Configured {
		t.Fatalf("expected both signals to report unconfigured: %+v", forgotten)
	}
}

func TestSplunkExportStatusReflectsCIMDRegistrationEnvFlag(t *testing.T) {
	newMux := func() *http.ServeMux {
		metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
		if err != nil {
			t.Fatal(err)
		}
		traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
		if err != nil {
			t.Fatal(err)
		}
		mux := http.NewServeMux()
		newSplunkExportService(metrics, traces, nil).register(mux)
		return mux
	}

	statusFor := func(mux *http.ServeMux) splunkExportStatusResponse {
		response := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
		if response.Code != http.StatusOK {
			t.Fatalf("status request = %d, body = %s", response.Code, response.Body.String())
		}
		var status splunkExportStatusResponse
		if err := json.Unmarshal(response.Body.Bytes(), &status); err != nil {
			t.Fatal(err)
		}
		return status
	}

	if status := statusFor(newMux()); status.CIMDRegistrationEnabled {
		t.Fatalf("expected the flag to default to false, got %+v", status)
	}

	t.Setenv("OBSTUDIO_SIS_CIMD_REGISTRATION_ENABLED", "true")
	if status := statusFor(newMux()); !status.CIMDRegistrationEnabled {
		t.Fatalf("expected the flag to be true when the env var is set, got %+v", status)
	}

	t.Setenv("OBSTUDIO_SIS_CIMD_REGISTRATION_ENABLED", "0")
	if status := statusFor(newMux()); status.CIMDRegistrationEnabled {
		t.Fatalf("expected the flag to be false for a falsy value, got %+v", status)
	}
}

func TestSplunkExportStatusRequiresBothSignalsInSameRealm(t *testing.T) {
	tests := []struct {
		name                  string
		configure             func(*testing.T, *otlp.SplunkMetricsExportController, *otlp.SplunkTracesExportController)
		wantRealm             string
		wantConnected         bool
		wantMetricsOn         bool
		wantTracesOn          bool
		wantMetricsConfigured bool
		wantTracesConfigured  bool
	}{
		{
			name: "metrics realm only",
			configure: func(t *testing.T, metrics *otlp.SplunkMetricsExportController, _ *otlp.SplunkTracesExportController) {
				t.Helper()
				err := metrics.Configure(otlp.SplunkMetricsExporterConfig{
					Enabled:     true,
					Realm:       "us0",
					AccessToken: testSplunkAccessToken,
				})
				if err != nil {
					t.Fatal(err)
				}
			},
			wantMetricsOn:         true,
			wantMetricsConfigured: true,
		},
		{
			name: "traces endpoint only",
			configure: func(t *testing.T, _ *otlp.SplunkMetricsExportController, traces *otlp.SplunkTracesExportController) {
				t.Helper()
				err := traces.Configure(otlp.SplunkTracesExporterConfig{
					Enabled:     true,
					Endpoint:    "https://traces.example.com/v2/trace/otlp",
					AccessToken: testSplunkAccessToken,
				})
				if err != nil {
					t.Fatal(err)
				}
			},
			wantTracesOn:         true,
			wantTracesConfigured: true,
		},
		{
			name: "mismatched realms",
			configure: func(t *testing.T, metrics *otlp.SplunkMetricsExportController, traces *otlp.SplunkTracesExportController) {
				t.Helper()
				if err := metrics.Configure(otlp.SplunkMetricsExporterConfig{
					Enabled:     true,
					Realm:       "us0",
					AccessToken: testSplunkAccessToken,
				}); err != nil {
					t.Fatal(err)
				}
				if err := traces.Configure(otlp.SplunkTracesExporterConfig{
					Enabled:     true,
					Realm:       "rc0",
					AccessToken: testSplunkAccessToken,
				}); err != nil {
					t.Fatal(err)
				}
			},
			wantMetricsOn:         true,
			wantTracesOn:          true,
			wantMetricsConfigured: true,
			wantTracesConfigured:  true,
		},
		{
			name: "same realm with endpoint override",
			configure: func(t *testing.T, metrics *otlp.SplunkMetricsExportController, traces *otlp.SplunkTracesExportController) {
				t.Helper()
				if err := metrics.Configure(otlp.SplunkMetricsExporterConfig{
					Enabled:     true,
					Realm:       "us0",
					Endpoint:    "https://metrics.example.com/v2/datapoint/otlp",
					AccessToken: testSplunkAccessToken,
				}); err != nil {
					t.Fatal(err)
				}
				if err := traces.Configure(otlp.SplunkTracesExporterConfig{
					Enabled:     true,
					Realm:       "us0",
					AccessToken: testSplunkAccessToken,
				}); err != nil {
					t.Fatal(err)
				}
			},
			wantMetricsOn:         true,
			wantTracesOn:          true,
			wantMetricsConfigured: true,
			wantTracesConfigured:  true,
		},
		{
			name: "same realm",
			configure: func(t *testing.T, metrics *otlp.SplunkMetricsExportController, traces *otlp.SplunkTracesExportController) {
				t.Helper()
				if err := metrics.Configure(otlp.SplunkMetricsExporterConfig{
					Enabled:     true,
					Realm:       "us0",
					AccessToken: testSplunkAccessToken,
				}); err != nil {
					t.Fatal(err)
				}
				if err := traces.Configure(otlp.SplunkTracesExporterConfig{
					Enabled:     true,
					Realm:       "us0",
					AccessToken: testSplunkAccessToken,
				}); err != nil {
					t.Fatal(err)
				}
			},
			wantRealm:             "us0",
			wantConnected:         true,
			wantMetricsOn:         true,
			wantTracesOn:          true,
			wantMetricsConfigured: true,
			wantTracesConfigured:  true,
		},
		{
			name: "same realm with different tokens",
			configure: func(t *testing.T, metrics *otlp.SplunkMetricsExportController, traces *otlp.SplunkTracesExportController) {
				t.Helper()
				if err := metrics.Configure(otlp.SplunkMetricsExporterConfig{
					Enabled:     true,
					Realm:       "us0",
					AccessToken: testSplunkAccessToken,
				}); err != nil {
					t.Fatal(err)
				}
				if err := traces.Configure(otlp.SplunkTracesExporterConfig{
					Enabled:     true,
					Realm:       "us0",
					AccessToken: "different-token-1234",
				}); err != nil {
					t.Fatal(err)
				}
			},
			wantMetricsOn:         true,
			wantTracesOn:          true,
			wantMetricsConfigured: true,
			wantTracesConfigured:  true,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
			traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
			test.configure(t, metrics, traces)
			mux := http.NewServeMux()
			newTestSplunkExportService(metrics, traces, nil).register(mux)

			response := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
			if response.Code != http.StatusOK {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
			if strings.Contains(response.Body.String(), testSplunkAccessToken) {
				t.Fatal("status response exposed the access token")
			}
			var status splunkExportStatusResponse
			if err := json.Unmarshal(response.Body.Bytes(), &status); err != nil {
				t.Fatal(err)
			}
			if status.Connected != test.wantConnected {
				t.Fatalf("unexpected connected state: %+v", status)
			}
			if status.Enabled != (test.wantConnected && test.wantMetricsOn && test.wantTracesOn) {
				t.Fatalf("unexpected enabled state: %+v", status)
			}
			if status.Realm != test.wantRealm {
				t.Fatalf("realm = %q, want %q", status.Realm, test.wantRealm)
			}
			if status.Metrics.Enabled != test.wantMetricsOn || status.Traces.Enabled != test.wantTracesOn {
				t.Fatalf("unexpected signal state: %+v", status)
			}
			if status.Metrics.Configured != test.wantMetricsConfigured || status.Traces.Configured != test.wantTracesConfigured {
				t.Fatalf("unexpected signal configured state: %+v", status)
			}
		})
	}
}

func TestSplunkExportStatusRequiresTokenAndDestination(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		AccessToken: testSplunkAccessToken,
	})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	response := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
	if response.Code != http.StatusOK {
		t.Fatalf("token-only status = %d, body = %s", response.Code, response.Body.String())
	}
	var tokenOnly splunkExportStatusResponse
	if err := json.Unmarshal(response.Body.Bytes(), &tokenOnly); err != nil {
		t.Fatal(err)
	}
	if tokenOnly.Connected {
		t.Fatalf("token-only state reported connected: %+v", tokenOnly)
	}
	if !tokenOnly.Metrics.Configured || tokenOnly.Traces.Configured {
		t.Fatalf("unexpected token-only configured state: %+v", tokenOnly)
	}

	if err := metrics.Configure(otlp.SplunkMetricsExporterConfig{
		Endpoint:    "https://metrics.example.com/v2/datapoint/otlp",
		AccessToken: testSplunkAccessToken,
	}); err != nil {
		t.Fatal(err)
	}
	response = splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
	if response.Code != http.StatusOK {
		t.Fatalf("endpoint status = %d, body = %s", response.Code, response.Body.String())
	}
	var endpointConfigured splunkExportStatusResponse
	if err := json.Unmarshal(response.Body.Bytes(), &endpointConfigured); err != nil {
		t.Fatal(err)
	}
	if endpointConfigured.Connected || endpointConfigured.Enabled || endpointConfigured.Realm != "" {
		t.Fatalf("unexpected endpoint-backed state: %+v", endpointConfigured)
	}
	if !endpointConfigured.Metrics.Configured || endpointConfigured.Traces.Configured {
		t.Fatalf("unexpected endpoint-backed configured state: %+v", endpointConfigured)
	}
}

func TestSplunkExportAcceptsOpaquePrintableAccessTokens(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	tests := []struct {
		name  string
		token string
	}{
		{name: "short", token: "x"},
		{name: "opaque punctuation", token: "opaque.token+/=123456789"},
		{name: "exact UTF-8 byte boundary", token: strings.Repeat("é", 2048)},
		{name: "escaped JSON body above eight KiB", token: strings.Repeat("<", maxSplunkAccessTokenBytes)},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			body, err := json.Marshal(configureSplunkExportRequest{Realm: "us0", AccessToken: test.token})
			if err != nil {
				t.Fatal(err)
			}
			response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
				string(body))

			if response.Code != http.StatusOK {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
		})
	}
}

func TestSplunkExportDoesNotConfigureWhenConnectionTestFails(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	verifyCalls := 0
	service.verifyConnection = func(_ context.Context, realm, accessToken string) error {
		verifyCalls++
		if realm != "us0" || accessToken != "short" {
			t.Fatalf("connection test received realm %q and token %q", realm, accessToken)
		}
		return errSplunkAccessTokenRejected
	}
	mux := http.NewServeMux()
	service.register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"us0","accessToken":"short"}`)

	if response.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if verifyCalls != 1 {
		t.Fatalf("connection test calls = %d, want 1", verifyCalls)
	}
	if strings.Contains(response.Body.String(), "short") {
		t.Fatal("connection test error exposed the access token")
	}
	if !strings.Contains(response.Body.String(), "Splunk rejected the access token") {
		t.Fatalf("unexpected body: %s", response.Body.String())
	}

	statusResponse := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
	var status splunkExportStatusResponse
	if err := json.Unmarshal(statusResponse.Body.Bytes(), &status); err != nil {
		t.Fatal(err)
	}
	if status.Connected || status.Metrics.Configured || status.Traces.Configured {
		t.Fatalf("failed connection test mutated configuration: %+v", status)
	}
}

func TestSplunkExportConnectionTestErrorsMapWithoutApplying(t *testing.T) {
	for _, test := range []struct {
		name       string
		verifyErr  error
		wantStatus int
	}{
		{
			name:       "deadline exceeded",
			verifyErr:  fmt.Errorf("connection probe: %w", context.DeadlineExceeded),
			wantStatus: http.StatusGatewayTimeout,
		},
		{
			name:       "upstream failure",
			verifyErr:  errors.New("network unavailable"),
			wantStatus: http.StatusBadGateway,
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
			traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
			service := newTestSplunkExportService(metrics, traces, nil)
			service.verifyConnection = func(context.Context, string, string) error {
				return test.verifyErr
			}
			mux := http.NewServeMux()
			service.register(mux)

			response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
				`{"realm":"us1","accessToken":"candidate-token"}`)

			if response.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d, body = %s", response.Code, test.wantStatus, response.Body.String())
			}
			if config := metrics.Config(); config.Realm != "" || config.AccessToken != "" {
				t.Fatalf("failed probe configured metrics export: %+v", config)
			}
			if config := traces.Config(); config.Realm != "" || config.AccessToken != "" {
				t.Fatalf("failed probe configured traces export: %+v", config)
			}
			statusResponse := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
			var status splunkExportStatusResponse
			if err := json.Unmarshal(statusResponse.Body.Bytes(), &status); err != nil {
				t.Fatal(err)
			}
			if status.Connected || status.Metrics.Configured || status.Traces.Configured {
				t.Fatalf("failed probe mutated cloud status: %+v", status)
			}
		})
	}
}

func TestSplunkExportRollbackUsesServerHeldSnapshotAndCallerHeldCapability(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Enabled:     true,
		Realm:       "us0",
		AccessToken: "previous-token",
	})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Enabled:     true,
		Realm:       "us0",
		AccessToken: "previous-token",
	})
	service := newTestSplunkExportService(metrics, traces, nil)
	service.source = splunkExportEnvFileSource
	verifyCalls := 0
	service.verifyConnection = func(context.Context, string, string) error {
		verifyCalls++
		return nil
	}
	mux := http.NewServeMux()
	service.register(mux)

	requestedRollbackToken := strings.Repeat("R", 43)
	invalidRollbackToken := splunkExportRequestWithRollbackToken(t, mux, http.MethodPost,
		"/api/splunk/export", `{"realm":"us1","accessToken":"replacement-token"}`,
		"invalid")

	if invalidRollbackToken.Code != http.StatusBadRequest {
		t.Fatalf("invalid rollback token status = %d, body = %s",
			invalidRollbackToken.Code, invalidRollbackToken.Body.String())
	}
	if verifyCalls != 0 {
		t.Fatalf("invalid rollback token made %d live connection checks", verifyCalls)
	}

	configuredResponse := splunkExportRequestWithRollbackToken(t, mux, http.MethodPost,
		"/api/splunk/export", `{"realm":"us1","accessToken":"replacement-token"}`,
		requestedRollbackToken)

	if configuredResponse.Code != http.StatusOK {
		t.Fatalf("configure status = %d, body = %s", configuredResponse.Code, configuredResponse.Body.String())
	}
	if verifyCalls != 1 {
		t.Fatalf("configure made %d live connection checks, want 1", verifyCalls)
	}
	var configured splunkExportStatusResponse
	if err := json.Unmarshal(configuredResponse.Body.Bytes(), &configured); err != nil {
		t.Fatal(err)
	}
	if configured.RollbackToken != requestedRollbackToken {
		t.Fatalf("configure rollback capability = %q, want the client-held capability",
			configured.RollbackToken)
	}
	if !configured.Connected || configured.Realm != "us1" || configured.Enabled {
		t.Fatalf("unexpected configured status: %+v", configured)
	}
	statusResponse := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
	if strings.Contains(statusResponse.Body.String(), "rollbackToken") {
		t.Fatalf("status response exposed rollback capability: %s", statusResponse.Body.String())
	}

	arbitraryRestore := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		`{"realm":"us2","accessToken":"caller-supplied"}`)

	if arbitraryRestore.Code != http.StatusBadRequest {
		t.Fatalf("arbitrary rollback status = %d, body = %s",
			arbitraryRestore.Code, arbitraryRestore.Body.String())
	}
	if got := metrics.Config(); got.Realm != "us1" || got.AccessToken != "replacement-token" {
		t.Fatalf("arbitrary rollback changed metrics config: %+v", got)
	}

	rollbackResponse := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		fmt.Sprintf(`{"rollbackToken":%q}`, configured.RollbackToken))

	if rollbackResponse.Code != http.StatusOK {
		t.Fatalf("rollback status = %d, body = %s", rollbackResponse.Code, rollbackResponse.Body.String())
	}
	if verifyCalls != 1 {
		t.Fatalf("rollback made a live connection check: got %d total verifier calls, want 1", verifyCalls)
	}
	if got := metrics.Config(); !got.Enabled || got.Realm != "us0" || got.AccessToken != "previous-token" {
		t.Fatalf("rollback did not restore metrics config: %+v", got)
	}
	if got := traces.Config(); !got.Enabled || got.Realm != "us0" || got.AccessToken != "previous-token" {
		t.Fatalf("rollback did not restore traces config: %+v", got)
	}
	if service.source != splunkExportEnvFileSource {
		t.Fatalf("rollback source = %q, want %q", service.source, splunkExportEnvFileSource)
	}

	replay := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		fmt.Sprintf(`{"rollbackToken":%q}`, configured.RollbackToken))

	if replay.Code != http.StatusConflict {
		t.Fatalf("rollback replay status = %d, body = %s", replay.Code, replay.Body.String())
	}
}

func TestSplunkExportRollbackCapabilityIsInvalidatedByALaterMutation(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	mux := http.NewServeMux()
	service.register(mux)

	configuredResponse := splunkExportRequestWithRollbackToken(t, mux, http.MethodPost,
		"/api/splunk/export", `{"realm":"us1","accessToken":"replacement-token"}`,
		strings.Repeat("R", 43))

	if configuredResponse.Code != http.StatusOK {
		t.Fatalf("configure status = %d, body = %s", configuredResponse.Code, configuredResponse.Body.String())
	}
	var configured splunkExportStatusResponse
	if err := json.Unmarshal(configuredResponse.Body.Bytes(), &configured); err != nil {
		t.Fatal(err)
	}
	if !splunkRollbackTokenPattern.MatchString(configured.RollbackToken) {
		t.Fatalf("rollback capability = %q", configured.RollbackToken)
	}

	enabledResponse := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{"enabled":true}`)

	if enabledResponse.Code != http.StatusOK {
		t.Fatalf("enable status = %d, body = %s", enabledResponse.Code, enabledResponse.Body.String())
	}
	rollbackResponse := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		fmt.Sprintf(`{"rollbackToken":%q}`, configured.RollbackToken))

	if rollbackResponse.Code != http.StatusConflict {
		t.Fatalf("stale rollback status = %d, body = %s",
			rollbackResponse.Code, rollbackResponse.Body.String())
	}
	if got := metrics.Config(); !got.Enabled || got.Realm != "us1" || got.AccessToken != "replacement-token" {
		t.Fatalf("stale rollback changed metrics config: %+v", got)
	}
}

func TestSplunkExportAllowsAColdCloudConnectionProbe(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	service.verifyConnection = func(ctx context.Context, _, _ string) error {
		deadline, ok := ctx.Deadline()
		if !ok {
			t.Fatal("connection probe has no deadline")
		}
		if remaining := time.Until(deadline); remaining < 9*time.Second {
			t.Fatalf("connection probe deadline is too short for a cold DNS/TLS handshake: %s", remaining)
		}
		return nil
	}
	mux := http.NewServeMux()
	service.register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"us1","accessToken":"opaque-token"}`)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
}

func TestSplunkExportRejectsConcurrentCloudMutations(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, func() (bool, error) { return false, nil })
	started := make(chan struct{})
	release := make(chan struct{})
	var first sync.Once
	service.verifyConnection = func(context.Context, string, string) error {
		blocked := false
		first.Do(func() {
			close(started)
			blocked = true
		})
		if blocked {
			<-release
		}
		return nil
	}
	mux := http.NewServeMux()
	service.register(mux)

	firstResponse := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		firstResponse <- splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
			`{"realm":"us0","accessToken":"first"}`)

	}()
	<-started

	mutations := []struct {
		path string
		body string
	}{
		{path: "/api/splunk/export", body: `{"realm":"us0","accessToken":"second"}`},
		{path: "/api/splunk/export/enabled", body: `{"enabled":false}`},
		{path: "/api/splunk/export/forget", body: `{}`},
		{path: "/api/splunk/export/refresh", body: `{}`},
	}
	type mutationResponse struct {
		path     string
		response *httptest.ResponseRecorder
	}
	secondResponses := make(chan mutationResponse, len(mutations))
	for _, mutation := range mutations {
		go func() {
			secondResponses <- mutationResponse{
				path: mutation.path,
				response: splunkExportRequest(t, mux, http.MethodPost, mutation.path,
					mutation.body),
			}
		}()
	}
	select {
	case second := <-secondResponses:
		close(release)
		<-firstResponse
		t.Fatalf("concurrent %s returned before the active mutation completed: status = %d, body = %s",
			second.path, second.response.Code, second.response.Body.String())
	case <-time.After(100 * time.Millisecond):
	}
	close(release)
	if first := <-firstResponse; first.Code != http.StatusOK {
		t.Fatalf("first status = %d, body = %s", first.Code, first.Body.String())
	}
	for range mutations {
		second := <-secondResponses
		if second.response.Code != http.StatusConflict {
			t.Fatalf("concurrent %s status = %d, body = %s",
				second.path, second.response.Code, second.response.Body.String())
		}
		if !strings.Contains(second.response.Body.String(), "configuration change is already in progress") {
			t.Fatalf("concurrent %s body = %s", second.path, second.response.Body.String())
		}
	}
	if got := metrics.Config(); got.Realm != "us0" || got.AccessToken != "first" {
		t.Fatalf("winning mutation state = %+v", got)
	}
}

func TestSplunkExportRejectsMutationsFromAStaleObserverVersion(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	verifyCalls := 0
	service.verifyConnection = func(context.Context, string, string) error {
		verifyCalls++
		return nil
	}
	mux := http.NewServeMux()
	service.register(mux)

	readStatus := func() splunkExportStatusResponse {
		t.Helper()
		response := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
		if response.Code != http.StatusOK {
			t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
		}
		var status splunkExportStatusResponse
		if err := json.Unmarshal(response.Body.Bytes(), &status); err != nil {
			t.Fatal(err)
		}
		if !splunkStateVersionPattern.MatchString(status.Version) {
			t.Fatalf("invalid Observer state version %q", status.Version)
		}
		return status
	}
	post := func(path string, body any) *httptest.ResponseRecorder {
		t.Helper()
		encoded, err := json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
		return splunkExportRequest(t, mux, http.MethodPost, path, string(encoded))
	}

	initial := readStatus()
	configuredResponse := post("/api/splunk/export", configureSplunkExportRequest{
		Realm:           "us1",
		AccessToken:     "winning-token",
		ExpectedVersion: initial.Version,
	})
	if configuredResponse.Code != http.StatusOK {
		t.Fatalf("configure status = %d, body = %s", configuredResponse.Code, configuredResponse.Body.String())
	}
	var configured splunkExportStatusResponse
	if err := json.Unmarshal(configuredResponse.Body.Bytes(), &configured); err != nil {
		t.Fatal(err)
	}
	if configured.Version == initial.Version {
		t.Fatal("connecting did not change the Observer state version")
	}
	enabledValue := true

	staleMutations := []struct {
		body any
		name string
		path string
	}{
		{
			name: "connect",
			path: "/api/splunk/export",
			body: configureSplunkExportRequest{
				Realm:           "eu1",
				AccessToken:     "losing-token",
				ExpectedVersion: initial.Version,
			},
		},
		{
			name: "set enabled",
			path: "/api/splunk/export/enabled",
			body: setSplunkExportEnabledRequest{
				Enabled:         &enabledValue,
				ExpectedVersion: initial.Version,
			},
		},
		{
			name: "forget",
			path: "/api/splunk/export/forget",
			body: forgetSplunkExportRequest{ExpectedVersion: initial.Version},
		},
	}
	for _, mutation := range staleMutations {
		t.Run(mutation.name, func(t *testing.T) {
			response := post(mutation.path, mutation.body)
			if response.Code != http.StatusConflict {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
			if !strings.Contains(response.Body.String(), "changed in another session") {
				t.Fatalf("body = %s", response.Body.String())
			}
		})
	}
	if verifyCalls != 1 {
		t.Fatalf("connection verifier calls = %d, want 1", verifyCalls)
	}
	if got := metrics.Config(); got.Realm != "us1" || got.AccessToken != "winning-token" || got.Enabled {
		t.Fatalf("stale mutation changed winning metrics state: %+v", got)
	}

	enabledResponse := post("/api/splunk/export/enabled", setSplunkExportEnabledRequest{
		Enabled:         &enabledValue,
		ExpectedVersion: configured.Version,
	})
	if enabledResponse.Code != http.StatusOK {
		t.Fatalf("enable status = %d, body = %s", enabledResponse.Code, enabledResponse.Body.String())
	}
	var enabled splunkExportStatusResponse
	if err := json.Unmarshal(enabledResponse.Body.Bytes(), &enabled); err != nil {
		t.Fatal(err)
	}
	if enabled.Version == configured.Version {
		t.Fatal("changing export enablement did not change the Observer state version")
	}

	forgottenResponse := post("/api/splunk/export/forget", forgetSplunkExportRequest{
		ExpectedVersion: enabled.Version,
	})
	if forgottenResponse.Code != http.StatusOK {
		t.Fatalf("forget status = %d, body = %s", forgottenResponse.Code, forgottenResponse.Body.String())
	}
	var forgotten splunkExportStatusResponse
	if err := json.Unmarshal(forgottenResponse.Body.Bytes(), &forgotten); err != nil {
		t.Fatal(err)
	}
	if forgotten.Version == enabled.Version {
		t.Fatal("forgetting the connection did not change the Observer state version")
	}
}

func TestSplunkExportRollbackWaitsForTheMutationThatCreatedItsCapability(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Enabled: true, Realm: "us0", AccessToken: "previous-token",
	})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Enabled: true, Realm: "us0", AccessToken: "previous-token",
	})
	service := newTestSplunkExportService(metrics, traces, nil)
	verificationStarted := make(chan struct{})
	releaseVerification := make(chan struct{})
	service.verifyConnection = func(context.Context, string, string) error {
		close(verificationStarted)
		<-releaseVerification
		return nil
	}
	mux := http.NewServeMux()
	service.register(mux)
	rollbackToken := strings.Repeat("R", 43)

	configuredResponse := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		configuredResponse <- splunkExportRequestWithRollbackToken(t, mux, http.MethodPost,
			"/api/splunk/export", `{"realm":"us1","accessToken":"replacement-token"}`,
			rollbackToken)

	}()
	<-verificationStarted

	rollbackResponse := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		rollbackResponse <- splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
			fmt.Sprintf(`{"rollbackToken":%q}`, rollbackToken))

	}()
	select {
	case response := <-rollbackResponse:
		t.Fatalf("rollback returned before configure settled: status = %d, body = %s",
			response.Code, response.Body.String())
	case <-time.After(50 * time.Millisecond):
	}

	close(releaseVerification)
	if response := <-configuredResponse; response.Code != http.StatusOK {
		t.Fatalf("configure status = %d, body = %s", response.Code, response.Body.String())
	}
	if response := <-rollbackResponse; response.Code != http.StatusOK {
		t.Fatalf("rollback status = %d, body = %s", response.Code, response.Body.String())
	}
	if got := metrics.Config(); !got.Enabled || got.Realm != "us0" || got.AccessToken != "previous-token" {
		t.Fatalf("rollback did not restore metrics config: %+v", got)
	}
	if got := traces.Config(); !got.Enabled || got.Realm != "us0" || got.AccessToken != "previous-token" {
		t.Fatalf("rollback did not restore traces config: %+v", got)
	}
}

func TestSplunkExportToggleAndForgetRollbackCannotOverwriteALaterMutation(t *testing.T) {

	tests := []struct {
		body string
		name string
		path string
	}{
		{name: "set enabled", path: "/api/splunk/export/enabled", body: `{"enabled":true}`},
		{name: "forget", path: "/api/splunk/export/forget", body: `{}`},
	}
	for _, test := range tests {
		for _, superseded := range []bool{false, true} {
			name := "restores previous state"
			if superseded {
				name = "cannot overwrite later state"
			}
			t.Run(test.name+"/"+name, func(t *testing.T) {
				metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
					Realm: "us0", AccessToken: "previous-token",
				})
				traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
					Realm: "us0", AccessToken: "previous-token",
				})
				service := newTestSplunkExportService(metrics, traces, nil)
				mux := http.NewServeMux()
				service.register(mux)
				rollbackToken := strings.Repeat("R", 43)

				mutation := splunkExportRequestWithRollbackToken(
					t,
					mux,
					http.MethodPost,
					test.path,
					test.body,

					rollbackToken)

				if mutation.Code != http.StatusOK {
					t.Fatalf("mutation status = %d, body = %s", mutation.Code, mutation.Body.String())
				}
				var mutated splunkExportStatusResponse
				if err := json.Unmarshal(mutation.Body.Bytes(), &mutated); err != nil {
					t.Fatal(err)
				}
				if mutated.RollbackToken != rollbackToken {
					t.Fatalf("rollback capability = %q", mutated.RollbackToken)
				}

				if superseded {
					later := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
						`{"realm":"us1","accessToken":"later-token"}`)

					if later.Code != http.StatusOK {
						t.Fatalf("later mutation status = %d, body = %s", later.Code, later.Body.String())
					}
				}
				rollback := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
					fmt.Sprintf(`{"rollbackToken":%q}`, rollbackToken))

				if superseded && rollback.Code != http.StatusConflict {
					t.Fatalf("stale rollback status = %d, body = %s", rollback.Code, rollback.Body.String())
				}
				if !superseded && rollback.Code != http.StatusOK {
					t.Fatalf("rollback status = %d, body = %s", rollback.Code, rollback.Body.String())
				}
				if superseded {
					if got := metrics.Config(); got.Realm != "us1" || got.AccessToken != "later-token" {
						t.Fatalf("stale rollback changed later metrics state: %+v", got)
					}
					if !service.configurationChanged {
						t.Fatal("later mutation lost its changed marker")
					}
				} else if got := metrics.Config(); got.Realm != "us0" || got.AccessToken != "previous-token" {
					t.Fatalf("rollback did not restore previous metrics state: %+v", got)
				} else if service.configurationChanged {
					t.Fatal("rollback did not restore the previous changed marker")
				}
			})
		}
	}
}

func TestVerifySplunkCloudConnectionSendsEmptyAuthenticatedOTLPRequest(t *testing.T) {
	requests := 0
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requests++
		if request.Method != http.MethodPost {
			t.Fatalf("method = %s", request.Method)
		}
		if request.URL.String() != "https://ingest.us0.observability.splunkcloud.com/v2/datapoint/otlp" {
			t.Fatalf("URL = %s", request.URL)
		}
		if request.Header.Get("Content-Type") != "application/x-protobuf" {
			t.Fatalf("content type = %q", request.Header.Get("Content-Type"))
		}
		if request.Header.Get("X-SF-Token") != "x" {
			t.Fatalf("token header = %q", request.Header.Get("X-SF-Token"))
		}
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Fatal(err)
		}
		if len(body) != 0 {
			t.Fatalf("connection test sent %d body bytes", len(body))
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Body:       io.NopCloser(strings.NewReader("")),
			Header:     make(http.Header),
			Request:    request,
		}, nil
	})}

	if err := verifySplunkCloudConnection(context.Background(), client, "us0", "x"); err != nil {
		t.Fatal(err)
	}
	if requests != 1 {
		t.Fatalf("requests = %d, want 1", requests)
	}
}

func TestVerifySplunkCloudConnectionReportsRejectedToken(t *testing.T) {
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{
			StatusCode: http.StatusUnauthorized,
			Body:       io.NopCloser(strings.NewReader("secret must not be reflected")),
			Header:     make(http.Header),
			Request:    request,
		}, nil
	})}

	err := verifySplunkCloudConnection(context.Background(), client, "us0", "secret")
	if !errors.Is(err, errSplunkAccessTokenRejected) {
		t.Fatalf("error = %v", err)
	}
	if strings.Contains(err.Error(), "secret") {
		t.Fatal("connection test error exposed the access token")
	}
}

func TestSplunkExportSetEnabledRequiresExplicitBoolean(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{}`)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadRequest)
	}
}

func TestSplunkExportSetEnabledRequiresSameRealm(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Realm:       "us0",
		AccessToken: testSplunkAccessToken,
	})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Realm:       "rc0",
		AccessToken: testSplunkAccessToken,
	})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{"enabled":true}`)

	if response.Code != http.StatusConflict {
		t.Fatalf("status = %d, want %d, body = %s", response.Code, http.StatusConflict, response.Body.String())
	}
}

func TestSplunkExportSetEnabledRequiresSameToken(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Realm:       "us0",
		AccessToken: testSplunkAccessToken,
	})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Realm:       "us0",
		AccessToken: "different-token-1234",
	})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{"enabled":true}`)

	if response.Code != http.StatusConflict {
		t.Fatalf("status = %d, want %d, body = %s", response.Code, http.StatusConflict, response.Body.String())
	}
}

func TestSplunkExportSetEnabledRejectsEndpointOverride(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Realm:       "us0",
		Endpoint:    "https://metrics.example.com/v2/datapoint/otlp",
		AccessToken: testSplunkAccessToken,
	})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Realm:       "us0",
		AccessToken: testSplunkAccessToken,
	})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{"enabled":true}`)

	if response.Code != http.StatusConflict {
		t.Fatalf("status = %d, want %d, body = %s", response.Code, http.StatusConflict, response.Body.String())
	}
}

func TestSplunkExportRejectsInvalidConfiguration(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	verifyCalls := 0
	service.verifyConnection = func(context.Context, string, string) error {
		verifyCalls++
		return nil
	}
	mux := http.NewServeMux()
	service.register(mux)
	oversizedTokenBody, err := json.Marshal(configureSplunkExportRequest{
		Realm:       "us0",
		AccessToken: strings.Repeat("é", 2049),
	})
	if err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		body string
		name string
	}{
		{name: "invalid realm", body: `{"realm":"../../etc","accessToken":"` + testSplunkAccessToken + `"}`},
		{name: "empty token", body: `{"realm":"us0","accessToken":""}`},
		{name: "token whitespace", body: `{"realm":"us0","accessToken":"token with spaces 1234"}`},
		{name: "token above UTF-8 byte limit", body: string(oversizedTokenBody)},
		{name: "invalid expected version", body: `{"realm":"us0","accessToken":"` + testSplunkAccessToken + `","expectedVersion":"stale"}`},
		{name: "unknown field", body: `{"realm":"us0","accessToken":"` + testSplunkAccessToken + `","extra":true}`},
		{name: "trailing object", body: `{"realm":"us0","accessToken":"` + testSplunkAccessToken + `"} {}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
				test.body)

			if response.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want %d", response.Code, http.StatusBadRequest)
			}
		})
	}
	if verifyCalls != 0 {
		t.Fatalf("connection verifier called %d times for invalid requests", verifyCalls)
	}
}

func TestSplunkExportRefreshUsesConfigurationRefresher(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	calls := 0
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, func() (bool, error) {
		calls++
		return false, nil
	}).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/refresh", `{}`)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if calls != 1 {
		t.Fatalf("refresh calls = %d, want 1", calls)
	}
}

func TestSplunkExportForgetRefusesEnvManagedConfiguration(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, func() (bool, error) {
		if err := metrics.Configure(otlp.SplunkMetricsExporterConfig{
			Realm:       "us0",
			AccessToken: testSplunkAccessToken,
		}); err != nil {
			return false, err
		}
		if err := traces.Configure(otlp.SplunkTracesExporterConfig{
			Realm:       "us0",
			AccessToken: testSplunkAccessToken,
		}); err != nil {
			return false, err
		}
		return true, nil
	}).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/refresh", `{}`)
	if response.Code != http.StatusOK {
		t.Fatalf("refresh status = %d, body = %s", response.Code, response.Body.String())
	}

	response = splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/forget", `{}`)
	if response.Code != http.StatusConflict {
		t.Fatalf("forget status = %d, body = %s", response.Code, response.Body.String())
	}
	if !strings.Contains(response.Body.String(), "remove SPLUNK_ACCESS_TOKEN") {
		t.Fatalf("forget body = %s", response.Body.String())
	}

	response = splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "")
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	var status splunkExportStatusResponse
	if err := json.Unmarshal(response.Body.Bytes(), &status); err != nil {
		t.Fatal(err)
	}
	if !status.Connected || status.Realm != "us0" {
		t.Fatalf("env-managed config should remain connected: %+v", status)
	}
}

func TestSplunkExportRealmResolvesCanonicalDestinationsWithoutNetwork(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	service.resolveRealmClient = &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		t.Fatal("canonical destination caused a network request")
		return nil, errors.New("unexpected network request")
	})}
	mux := http.NewServeMux()
	service.register(mux)

	tests := []struct {
		destination string
		want        string
	}{
		{destination: " US1 ", want: "us1"},
		{destination: "https://app.eu0.observability.splunkcloud.com/#/signin", want: "eu0"},
		{destination: "https://api.us2.signalfx.com/v2?ignored=yes#fragment", want: "us2"},
		{destination: "https://ingest.au0.observability.splunkcloud.com", want: "au0"},
		{destination: "https://rum-ingest.us1.signalfx.com/v1/rum", want: "us1"},
		{destination: "https://stream.jp0.signalfx.com", want: "jp0"},
		{destination: "https://backfill.us0.observability.splunkcloud.com", want: "us0"},
		{destination: "https://runner.us2.observability.splunkcloud.com", want: "us2"},
		{destination: "https://customer-api.eu0.observability.splunkcloud.com", want: "eu0"},
		{destination: "https://private-api.us1.signalfx.com", want: "us1"},
		{destination: "https://private-ingest.us1.signalfx.com", want: "us1"},
		{destination: "https://private-stream.us1.signalfx.com", want: "us1"},
	}
	for _, test := range tests {
		t.Run(test.destination, func(t *testing.T) {
			body, _ := json.Marshal(splunkExportRealmRequest{Destination: test.destination})
			response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/realm",
				string(body))

			if response.Code != http.StatusOK {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
			if response.Header().Get("Cache-Control") != "no-store" {
				t.Fatalf("cache control = %q", response.Header().Get("Cache-Control"))
			}
			var result map[string]string
			if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
				t.Fatal(err)
			}
			if result["realm"] != test.want {
				t.Fatalf("realm = %q, want %q", result["realm"], test.want)
			}
		})
	}
}

func TestSplunkExportRealmFetchesOnlyNormalizedCustomSplunkPage(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	requests := 0
	service.resolveRealmClient = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		requests++
		if request.Method != http.MethodGet {
			t.Fatalf("method = %s", request.Method)
		}
		if request.URL.String() != "https://pov-rexel-webshop.observability.splunkcloud.com/" {
			t.Fatalf("URL = %s", request.URL)
		}
		for _, name := range []string{"Authorization", "Cookie", "X-SF-Token", "X-Obstudio-Browser-Token"} {
			if value := request.Header.Get(name); value != "" {
				t.Fatalf("%s header = %q", name, value)
			}
		}
		return splunkRealmPageResponse(request, http.StatusOK, "text/html; charset=utf-8",
			`<html><script>window.signalviewConfig = {"realm":"EU0","appDomain":"app.eu0.observability.splunkcloud.com"};</script></html>`), nil
	})}
	mux := http.NewServeMux()
	service.register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/realm",
		`{"destination":"https://pov-rexel-webshop.observability.splunkcloud.com/supplied/path?secret=value#/signin"}`)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if requests != 1 {
		t.Fatalf("requests = %d, want 1", requests)
	}
	var result map[string]string
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result["realm"] != "eu0" {
		t.Fatalf("realm = %q, want eu0", result["realm"])
	}
}

func TestSplunkExportRealmRejectsInvalidDestinationsWithoutNetwork(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	service.resolveRealmClient = &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		t.Fatal("invalid destination caused a network request")
		return nil, errors.New("unexpected network request")
	})}
	mux := http.NewServeMux()
	service.register(mux)

	destinations := []string{
		"realm",
		strings.Repeat("a", maxSplunkDestinationBytes+1),
		"http://app.us1.observability.splunkcloud.com",
		"https://user:password@app.us1.observability.splunkcloud.com",
		"https://app.us1.observability.splunkcloud.com:443",
		"https://127.0.0.1",
		"https://app.us1.observability.splunkcloud.com.example.com",
		"https://customer.evilobservability.splunkcloud.com",
		"https://-invalid.observability.splunkcloud.com",
		"https://bad_name.observability.splunkcloud.com",
		"https://rum-ingest.signalfx.com",
		"https://login.signalfx.com",
		"https://cdn.observability.splunkcloud.com",
		"https://ingest.realm.signalfx.com",
		"https://ingest.realm.observability.splunkcloud.com",
		"https://unknown.us1.signalfx.com",
		"https://too.many.labels.observability.splunkcloud.com",
		"https://private-api.us1.observability.splunkcloud.com",
		"https://customer-api.us1.signalfx.com",
	}
	for _, destination := range destinations {
		t.Run(destination, func(t *testing.T) {
			body, _ := json.Marshal(splunkExportRealmRequest{Destination: destination})
			response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/realm",
				string(body))

			if response.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want %d, body = %s", response.Code, http.StatusBadRequest, response.Body.String())
			}
		})
	}
}

func TestSplunkExportRealmRejectsUnsafeOrUnverifiableCustomPages(t *testing.T) {
	tests := []struct {
		contentType string
		body        string
		name        string
		status      int
	}{
		{
			name:        "redirect",
			status:      http.StatusFound,
			contentType: "text/html",
			body:        `<script>window.signalviewConfig={"realm":"eu0"}</script>`,
		},
		{
			name:        "oversize",
			status:      http.StatusOK,
			contentType: "text/html",
			body:        strings.Repeat("x", maxSplunkRealmPageBytes+1),
		},
		{
			name:        "non HTML",
			status:      http.StatusOK,
			contentType: "application/json",
			body:        `{"realm":"eu0"}`,
		},
		{
			name:        "missing config",
			status:      http.StatusOK,
			contentType: "text/html",
			body:        `<script>window.otherConfig={"realm":"eu0"}</script>`,
		},
		{
			name:        "missing app domain",
			status:      http.StatusOK,
			contentType: "text/html",
			body:        `<script>window.signalviewConfig={"realm":"eu0"}</script>`,
		},
		{
			name:        "mismatched app domain",
			status:      http.StatusOK,
			contentType: "text/html",
			body:        `<script>window.signalviewConfig={"realm":"eu0","appDomain":"app.us1.observability.splunkcloud.com"}</script>`,
		},
		{
			name:        "invalid realm",
			status:      http.StatusOK,
			contentType: "text/html",
			body:        `<script>window.signalviewConfig={"realm":"realm","appDomain":"app.eu0.observability.splunkcloud.com"}</script>`,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
			traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
			service := newTestSplunkExportService(metrics, traces, nil)
			requests := 0
			service.resolveRealmClient = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
				requests++
				response := splunkRealmPageResponse(request, test.status, test.contentType, test.body)
				if test.status == http.StatusFound {
					response.Header.Set("Location", "https://other.observability.splunkcloud.com/")
				}
				return response, nil
			})}
			mux := http.NewServeMux()
			service.register(mux)

			response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/realm",
				`{"destination":"https://customer.observability.splunkcloud.com"}`)

			if response.Code != http.StatusBadGateway {
				t.Fatalf("status = %d, want %d, body = %s", response.Code, http.StatusBadGateway, response.Body.String())
			}
			if requests != 1 {
				t.Fatalf("requests = %d, want 1", requests)
			}
		})
	}
}

func TestSplunkExportConfigurationRemainsRealmOnly(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	verifyCalls := 0
	service.verifyConnection = func(context.Context, string, string) error {
		verifyCalls++
		return nil
	}
	mux := http.NewServeMux()
	service.register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"https://app.us1.observability.splunkcloud.com","accessToken":"token"}`)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d, body = %s", response.Code, http.StatusBadRequest, response.Body.String())
	}
	if verifyCalls != 0 {
		t.Fatalf("connection verifier calls = %d, want 0", verifyCalls)
	}
}

func splunkRealmPageResponse(request *http.Request, status int, contentType, body string) *http.Response {
	header := make(http.Header)
	header.Set("Content-Type", contentType)
	return &http.Response{
		StatusCode: status,
		Header:     header,
		Body:       io.NopCloser(strings.NewReader(body)),
		Request:    request,
	}
}

func splunkExportRequest(
	t *testing.T,
	handler http.Handler,
	method string,
	path string,
	body string,
) *httptest.ResponseRecorder {
	return splunkExportRequestWithRollbackToken(t, handler, method, path, body, "")
}

func splunkExportRequestWithRollbackToken(
	t *testing.T,
	handler http.Handler,
	method string,
	path string,
	body string,
	rollbackToken string,
) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	request.RemoteAddr = "127.0.0.1:54321"
	request.Header.Set("Content-Type", "application/json")
	if rollbackToken != "" {
		request.Header.Set(splunkRollbackTokenHeader, rollbackToken)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func newTestSplunkExportService(
	metrics *otlp.SplunkMetricsExportController,
	traces *otlp.SplunkTracesExportController,
	refresh SplunkExportConfigurationRefresher,
) *splunkExportService {
	service := newSplunkExportService(metrics, traces, refresh)
	service.verifyConnection = func(context.Context, string, string) error { return nil }
	return service
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return f(request)
}
