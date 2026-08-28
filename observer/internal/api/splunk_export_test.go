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
)

const testObserverControlToken = "observer-control-token"
const testSplunkAccessToken = "splunk-access-token-1234"

var testSplunkBrowserSigningKey = strings.Repeat("A", 43)
var testSplunkBrowserLaunchToken = strings.Repeat("B", 43)

func TestSplunkExportLifecycleDoesNotExposeToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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

	statusResponse := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
	if statusResponse.Code != http.StatusOK {
		t.Fatalf("status request = %d, body = %s", statusResponse.Code, statusResponse.Body.String())
	}
	if statusResponse.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("cache control = %q, want no-store", statusResponse.Header().Get("Cache-Control"))
	}

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"us0","accessToken":"`+testSplunkAccessToken+`"}`, testObserverControlToken)
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
		`{"enabled":true}`, testObserverControlToken)
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
		`{}`, testObserverControlToken)
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

			response := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
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

	response := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
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
	response = splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
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
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
				string(body), testObserverControlToken)
			if response.Code != http.StatusOK {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
		})
	}
}

func TestSplunkExportDoesNotConfigureWhenConnectionTestFails(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
		`{"realm":"us0","accessToken":"short"}`, testObserverControlToken)
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

	statusResponse := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
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
			t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
			metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
			traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
			service := newTestSplunkExportService(metrics, traces, nil)
			service.verifyConnection = func(context.Context, string, string) error {
				return test.verifyErr
			}
			mux := http.NewServeMux()
			service.register(mux)

			response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
				`{"realm":"us1","accessToken":"candidate-token"}`, testObserverControlToken)
			if response.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d, body = %s", response.Code, test.wantStatus, response.Body.String())
			}
			if config := metrics.Config(); config.Realm != "" || config.AccessToken != "" {
				t.Fatalf("failed probe configured metrics export: %+v", config)
			}
			if config := traces.Config(); config.Realm != "" || config.AccessToken != "" {
				t.Fatalf("failed probe configured traces export: %+v", config)
			}
			statusResponse := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
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

func TestSplunkExportRestoreIsOfflineAndControlTokenOnly(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	verifyCalls := 0
	service.verifyConnection = func(context.Context, string, string) error {
		verifyCalls++
		return errors.New("network unavailable")
	}
	mux := http.NewServeMux()
	service.register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/restore",
		`{"realm":"us1","accessToken":"offline-token"}`, testObserverControlToken)
	if response.Code != http.StatusOK {
		t.Fatalf("restore status = %d, body = %s", response.Code, response.Body.String())
	}
	if verifyCalls != 0 {
		t.Fatalf("restore made %d live connection checks, want 0", verifyCalls)
	}
	var status splunkExportStatusResponse
	if err := json.Unmarshal(response.Body.Bytes(), &status); err != nil {
		t.Fatal(err)
	}
	if !status.Connected || status.Realm != "us1" || status.Enabled {
		t.Fatalf("unexpected restored status: %+v", status)
	}

	sessionResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if sessionResponse.Code != http.StatusOK {
		t.Fatalf("session status = %d, body = %s", sessionResponse.Code, sessionResponse.Body.String())
	}
	var session struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(sessionResponse.Body.Bytes(), &session); err != nil {
		t.Fatal(err)
	}
	response = splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export/restore",
		`{"realm":"us1","accessToken":"offline-token"}`, session.BrowserToken)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("browser restore status = %d, body = %s", response.Code, response.Body.String())
	}
}

func TestSplunkExportAllowsAColdCloudConnectionProbe(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
		`{"realm":"us1","accessToken":"opaque-token"}`, testObserverControlToken)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
}

func TestSplunkExportRejectsConcurrentCloudMutations(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
			`{"realm":"us0","accessToken":"first"}`, testObserverControlToken)
	}()
	<-started

	mutations := []struct {
		path string
		body string
	}{
		{path: "/api/splunk/export", body: `{"realm":"us0","accessToken":"second"}`},
		{path: "/api/splunk/export/restore", body: `{"realm":"us0","accessToken":"second"}`},
		{path: "/api/splunk/export/enabled", body: `{"enabled":false}`},
		{path: "/api/splunk/export/forget", body: `{}`},
		{path: "/api/splunk/export/refresh", body: `{}`},
	}
	for _, mutation := range mutations {
		second := splunkExportRequest(t, mux, http.MethodPost, mutation.path,
			mutation.body, testObserverControlToken)
		if second.Code != http.StatusConflict {
			t.Fatalf("concurrent %s status = %d, body = %s", mutation.path, second.Code, second.Body.String())
		}
		if !strings.Contains(second.Body.String(), "configuration change is already in progress") {
			t.Fatalf("concurrent %s body = %s", mutation.path, second.Body.String())
		}
	}
	close(release)
	if first := <-firstResponse; first.Code != http.StatusOK {
		t.Fatalf("first status = %d, body = %s", first.Code, first.Body.String())
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

func TestSplunkExportBrowserSessionAuthorizesSameOriginLoopbackMutations(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	sessionResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if sessionResponse.Code != http.StatusOK {
		t.Fatalf("session status = %d, body = %s", sessionResponse.Code, sessionResponse.Body.String())
	}
	if got := sessionResponse.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("browser session exposed through CORS: %q", got)
	}
	if got := sessionResponse.Header().Get("Cache-Control"); got != "no-store" {
		t.Fatalf("browser session cache control = %q", got)
	}
	var session struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(sessionResponse.Body.Bytes(), &session); err != nil {
		t.Fatal(err)
	}
	if !splunkBrowserTokenPattern.MatchString(session.BrowserToken) {
		t.Fatalf("browser token has invalid shape: %q", session.BrowserToken)
	}
	if session.BrowserToken == testObserverControlToken {
		t.Fatal("browser session exposed the Observer control token")
	}
	repeatedLaunchResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if repeatedLaunchResponse.Code != http.StatusUnauthorized {
		t.Fatalf("repeated launch status = %d, want %d; body = %s",
			repeatedLaunchResponse.Code, http.StatusUnauthorized, repeatedLaunchResponse.Body.String())
	}

	secondSessionResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", `{}`, session.BrowserToken)
	if secondSessionResponse.Code != http.StatusOK {
		t.Fatalf("renewed session status = %d, body = %s", secondSessionResponse.Code, secondSessionResponse.Body.String())
	}
	var secondSession struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(secondSessionResponse.Body.Bytes(), &secondSession); err != nil {
		t.Fatal(err)
	}
	if !splunkBrowserTokenPattern.MatchString(secondSession.BrowserToken) {
		t.Fatalf("renewed browser token has invalid shape: %q", secondSession.BrowserToken)
	}
	if secondSession.BrowserToken == session.BrowserToken {
		t.Fatal("browser session renewal reused the previous bearer")
	}

	connectResponse := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"us1","accessToken":"opaque-browser-token"}`, session.BrowserToken)
	if connectResponse.Code != http.StatusOK {
		t.Fatalf("connect status = %d, body = %s", connectResponse.Code, connectResponse.Body.String())
	}
	renewedActionToken := connectResponse.Header().Get(splunkBrowserTokenHeader)
	if !splunkBrowserTokenPattern.MatchString(renewedActionToken) || renewedActionToken == session.BrowserToken {
		t.Fatalf("connect did not rotate the browser session token: %q", renewedActionToken)
	}
	enableResponse := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{"enabled":true}`, renewedActionToken)
	if enableResponse.Code != http.StatusOK {
		t.Fatalf("enable status = %d, body = %s", enableResponse.Code, enableResponse.Body.String())
	}
	renewedActionToken = enableResponse.Header().Get(splunkBrowserTokenHeader)
	if !splunkBrowserTokenPattern.MatchString(renewedActionToken) {
		t.Fatalf("enable did not renew the browser session token: %q", renewedActionToken)
	}
	forgetResponse := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export/forget",
		`{}`, renewedActionToken)
	if forgetResponse.Code != http.StatusOK {
		t.Fatalf("forget status = %d, body = %s", forgetResponse.Code, forgetResponse.Body.String())
	}
}

func TestSplunkExportBrowserSessionRequiresNewLaunchAfterObserverRestart(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	firstService := newTestSplunkExportService(metrics, traces, nil)
	firstMux := http.NewServeMux()
	firstService.register(firstMux)

	firstResponse := splunkBrowserExportRequest(t, firstMux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if firstResponse.Code != http.StatusOK {
		t.Fatalf("initial session status = %d, body = %s", firstResponse.Code, firstResponse.Body.String())
	}
	var firstSession struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(firstResponse.Body.Bytes(), &firstSession); err != nil {
		t.Fatal(err)
	}

	restartedService := newTestSplunkExportService(metrics, traces, nil)
	restartedService.browserLaunch = strings.Repeat("C", 43)
	restartedMux := http.NewServeMux()
	restartedService.register(restartedMux)

	renewedResponse := splunkBrowserExportRequest(t, restartedMux, http.MethodPost,
		"/api/splunk/export/browser/session", `{}`, firstSession.BrowserToken)
	if renewedResponse.Code != http.StatusUnauthorized {
		t.Fatalf("post-restart renewal status = %d, want %d; body = %s",
			renewedResponse.Code, http.StatusUnauthorized, renewedResponse.Body.String())
	}
}

func TestSplunkExportBrowserSessionConsumesConcurrentLaunchOnce(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	started := make(chan struct{})
	release := make(chan struct{})
	var releaseOnce sync.Once
	releaseRefresh := func() { releaseOnce.Do(func() { close(release) }) }
	defer releaseRefresh()
	refreshCalls := 0
	service := newTestSplunkExportService(metrics, traces, func() (bool, error) {
		refreshCalls++
		if refreshCalls == 1 {
			close(started)
			<-release
		}
		return false, nil
	})
	mux := http.NewServeMux()
	service.register(mux)

	responses := make(chan *httptest.ResponseRecorder, 2)
	requestSession := func() {
		responses <- splunkBrowserExportRequest(t, mux, http.MethodPost,
			"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	}
	go requestSession()
	<-started
	go requestSession()

	select {
	case response := <-responses:
		releaseRefresh()
		<-responses
		t.Fatalf("concurrent session returned before the active refresh completed: status = %d, body = %s",
			response.Code, response.Body.String())
	case <-time.After(100 * time.Millisecond):
	}

	releaseRefresh()
	statuses := map[int]int{}
	for range 2 {
		response := <-responses
		statuses[response.Code]++
	}
	if statuses[http.StatusOK] != 1 || statuses[http.StatusUnauthorized] != 1 {
		t.Fatalf("session statuses = %#v, want one success and one unauthorized response", statuses)
	}
	if refreshCalls != 1 {
		t.Fatalf("refresh calls = %d, want 1", refreshCalls)
	}
}

func TestSplunkExportBrowserSessionRejectsExpiredLaunchAndPriorProcessTokens(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	service.browserLaunchEnd = time.Now().Add(-time.Second)
	mux := http.NewServeMux()
	service.register(mux)

	expiredLaunchResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if expiredLaunchResponse.Code != http.StatusUnauthorized {
		t.Fatalf("expired launch status = %d, body = %s", expiredLaunchResponse.Code, expiredLaunchResponse.Body.String())
	}

	priorProcessToken, err := service.newBrowserToken()
	if err != nil {
		t.Fatal(err)
	}
	if !service.hasValidBrowserToken(priorProcessToken) {
		t.Fatal("current-process browser session token was rejected")
	}
	service.browserLaunch = strings.Repeat("C", 43)
	if service.hasValidBrowserToken(priorProcessToken) {
		t.Fatal("prior-process browser session token was accepted")
	}
	currentToken, err := service.newBrowserToken()
	if err != nil {
		t.Fatal(err)
	}
	last := "A"
	if strings.HasSuffix(currentToken, last) {
		last = "B"
	}
	tamperedToken := currentToken[:len(currentToken)-1] + last
	if service.hasValidBrowserToken(tamperedToken) {
		t.Fatal("tampered browser session token was accepted")
	}
}

func TestSplunkExportBrowserSessionRemainsValidForObserverProcessLifetime(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)

	token, err := service.newBrowserToken()
	if err != nil {
		t.Fatal(err)
	}
	if !service.hasValidBrowserToken(token) {
		t.Fatal("browser session was not valid for the current Observer process")
	}
}

func TestSplunkExportBrowserSessionProtectsEnvManagedConfigurationBeforeForget(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Enabled:     true,
		Realm:       "us0",
		AccessToken: testSplunkAccessToken,
	})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Enabled:     true,
		Realm:       "us0",
		AccessToken: testSplunkAccessToken,
	})
	refreshCalls := 0
	service := newTestSplunkExportService(metrics, traces, func() (bool, error) {
		refreshCalls++
		return true, nil
	})
	mux := http.NewServeMux()
	service.register(mux)

	sessionResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if sessionResponse.Code != http.StatusOK {
		t.Fatalf("session status = %d, body = %s", sessionResponse.Code, sessionResponse.Body.String())
	}
	if refreshCalls != 1 {
		t.Fatalf("refresh calls = %d, want 1", refreshCalls)
	}
	var session struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(sessionResponse.Body.Bytes(), &session); err != nil {
		t.Fatal(err)
	}

	forgetResponse := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export/forget",
		`{}`, session.BrowserToken)
	if forgetResponse.Code != http.StatusConflict {
		t.Fatalf("forget status = %d, body = %s", forgetResponse.Code, forgetResponse.Body.String())
	}
	if !strings.Contains(forgetResponse.Body.String(), "remove SPLUNK_ACCESS_TOKEN") {
		t.Fatalf("forget body = %s", forgetResponse.Body.String())
	}
	if got := metrics.Config(); got.Realm != "us0" || got.AccessToken != testSplunkAccessToken {
		t.Fatalf("env-managed metrics config was changed: %+v", got)
	}
	if got := traces.Config(); got.Realm != "us0" || got.AccessToken != testSplunkAccessToken {
		t.Fatalf("env-managed traces config was changed: %+v", got)
	}
}

func TestSplunkExportBrowserSessionRequiresLaunchOrSessionToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	mux := http.NewServeMux()
	service.register(mux)

	for _, test := range []struct {
		name string
		body string
	}{
		{name: "missing", body: `{}`},
		{name: "wrong", body: splunkBrowserLaunchRequestBody(strings.Repeat("A", 43))},
	} {
		t.Run(test.name, func(t *testing.T) {
			response := splunkBrowserExportRequest(t, mux, http.MethodPost,
				"/api/splunk/export/browser/session", test.body, "")
			if response.Code != http.StatusUnauthorized {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
		})
	}

	service.browserSigningKey = ""
	response := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("unconfigured status = %d, body = %s", response.Code, response.Body.String())
	}
}

func TestSplunkExportBrowserSessionRejectsNonLocalOrCrossOriginRequests(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	for _, test := range []struct {
		name       string
		origin     string
		remoteAddr string
		marker     string
		fetchSite  string
	}{
		{name: "cross origin", origin: "https://attacker.example", remoteAddr: "127.0.0.1:54321", marker: "1"},
		{name: "remote client", origin: "http://127.0.0.1:3000", remoteAddr: "192.0.2.10:54321", marker: "1"},
		{name: "missing marker", origin: "http://127.0.0.1:3000", remoteAddr: "127.0.0.1:54321"},
		{name: "cross-site fetch metadata", origin: "http://127.0.0.1:3000", remoteAddr: "127.0.0.1:54321", marker: "1", fetchSite: "cross-site"},
	} {
		t.Run(test.name, func(t *testing.T) {
			request := httptest.NewRequest(http.MethodPost,
				"http://127.0.0.1:3000/api/splunk/export/browser/session",
				strings.NewReader(splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken)))
			request.RemoteAddr = test.remoteAddr
			request.Header.Set("Content-Type", "application/json")
			request.Header.Set("Origin", test.origin)
			if test.marker != "" {
				request.Header.Set(splunkBrowserRequestHeader, test.marker)
			}
			if test.fetchSite != "" {
				request.Header.Set("Sec-Fetch-Site", test.fetchSite)
			}
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, request)
			if response.Code != http.StatusForbidden {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
		})
	}
}

func TestSplunkExportBrowserSessionCannotRegisterAnIDEBridge(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	sessionResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if sessionResponse.Code != http.StatusOK {
		t.Fatalf("session status = %d, body = %s", sessionResponse.Code, sessionResponse.Body.String())
	}
	var session struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(sessionResponse.Body.Bytes(), &session); err != nil {
		t.Fatal(err)
	}
	response := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export/bridge",
		`{"bridgeToken":"bridge-token-123456789012345"}`, session.BrowserToken)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
}

func TestSplunkExportMutationsRequireControlToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	for name, token := range map[string]string{
		"missing": "",
		"wrong":   "wrong-control-token",
	} {
		t.Run(name, func(t *testing.T) {
			response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
				`{"realm":"us0","accessToken":"`+testSplunkAccessToken+`"}`, token)
			if response.Code != http.StatusUnauthorized {
				t.Fatalf("status = %d, want %d", response.Code, http.StatusUnauthorized)
			}
		})
	}
}

func TestSplunkExportControlFailsClosedWhenUnconfigured(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "")
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/forget", `{}`, "")
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusServiceUnavailable)
	}
}

func TestSplunkExportBridgeTokenRequiresControlTokenRegistration(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	const bridgeToken = "bridge-token-123456789012345"
	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/bridge/verify",
		`{"bridgeToken":"`+bridgeToken+`"}`, "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("verify before registration status = %d, want %d", response.Code, http.StatusUnauthorized)
	}

	response = splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/bridge",
		`{"bridgeToken":"`+bridgeToken+`"}`, "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("register without control status = %d, want %d", response.Code, http.StatusUnauthorized)
	}

	response = splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/bridge",
		`{"bridgeToken":"`+bridgeToken+`"}`, testObserverControlToken)
	if response.Code != http.StatusOK {
		t.Fatalf("register status = %d, body = %s", response.Code, response.Body.String())
	}
	if response.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("cache control = %q, want no-store", response.Header().Get("Cache-Control"))
	}

	response = splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/bridge/verify",
		`{"bridgeToken":"`+bridgeToken+`"}`, "")
	if response.Code != http.StatusOK {
		t.Fatalf("verify status = %d, body = %s", response.Code, response.Body.String())
	}
	if response.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("verify cache control = %q, want no-store", response.Header().Get("Cache-Control"))
	}
}

func TestSplunkExportBridgeTokenRejectsInvalidShape(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/bridge",
		`{"bridgeToken":"short"}`, testObserverControlToken)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("register invalid token status = %d, want %d", response.Code, http.StatusBadRequest)
	}
	response = splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/bridge/verify",
		`{"bridgeToken":"short"}`, "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("verify invalid token status = %d, want %d", response.Code, http.StatusUnauthorized)
	}
}

func TestSplunkExportSetEnabledRequiresExplicitBoolean(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{}`, testObserverControlToken)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadRequest)
	}
}

func TestSplunkExportSetEnabledRequiresSameRealm(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
		`{"enabled":true}`, testObserverControlToken)
	if response.Code != http.StatusConflict {
		t.Fatalf("status = %d, want %d, body = %s", response.Code, http.StatusConflict, response.Body.String())
	}
}

func TestSplunkExportSetEnabledRequiresSameToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
		`{"enabled":true}`, testObserverControlToken)
	if response.Code != http.StatusConflict {
		t.Fatalf("status = %d, want %d, body = %s", response.Code, http.StatusConflict, response.Body.String())
	}
}

func TestSplunkExportSetEnabledRejectsEndpointOverride(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
		`{"enabled":true}`, testObserverControlToken)
	if response.Code != http.StatusConflict {
		t.Fatalf("status = %d, want %d, body = %s", response.Code, http.StatusConflict, response.Body.String())
	}
}

func TestSplunkExportRejectsInvalidConfiguration(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
		{name: "unknown field", body: `{"realm":"us0","accessToken":"` + testSplunkAccessToken + `","extra":true}`},
		{name: "trailing object", body: `{"realm":"us0","accessToken":"` + testSplunkAccessToken + `"} {}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
				test.body, testObserverControlToken)
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
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	calls := 0
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, func() (bool, error) {
		calls++
		return false, nil
	}).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/refresh", `{}`, testObserverControlToken)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if calls != 1 {
		t.Fatalf("refresh calls = %d, want 1", calls)
	}
}

func TestSplunkExportForgetRefusesEnvManagedConfiguration(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/refresh", `{}`, testObserverControlToken)
	if response.Code != http.StatusOK {
		t.Fatalf("refresh status = %d, body = %s", response.Code, response.Body.String())
	}

	response = splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/forget", `{}`, testObserverControlToken)
	if response.Code != http.StatusConflict {
		t.Fatalf("forget status = %d, body = %s", response.Code, response.Body.String())
	}
	if !strings.Contains(response.Body.String(), "remove SPLUNK_ACCESS_TOKEN") {
		t.Fatalf("forget body = %s", response.Body.String())
	}

	response = splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
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

func splunkExportRequest(
	t *testing.T,
	handler http.Handler,
	method string,
	path string,
	body string,
	controlToken string,
) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	request.Header.Set("Content-Type", "application/json")
	if controlToken != "" {
		request.Header.Set("Authorization", "Bearer "+controlToken)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func splunkBrowserExportRequest(
	t *testing.T,
	handler http.Handler,
	method string,
	path string,
	body string,
	browserToken string,
) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, "http://127.0.0.1:3000"+path, bytes.NewBufferString(body))
	request.RemoteAddr = "127.0.0.1:54321"
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Origin", "http://127.0.0.1:3000")
	request.Header.Set("Sec-Fetch-Site", "same-origin")
	request.Header.Set(splunkBrowserRequestHeader, "1")
	if browserToken != "" {
		request.Header.Set(splunkBrowserTokenHeader, browserToken)
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
	service.browserSigningKey = testSplunkBrowserSigningKey
	service.browserLaunch = testSplunkBrowserLaunchToken
	service.browserLaunchEnd = time.Now().Add(splunkBrowserLaunchTokenTTL)
	service.verifyConnection = func(context.Context, string, string) error { return nil }
	return service
}

func splunkBrowserLaunchRequestBody(token string) string {
	return fmt.Sprintf(`{"launchToken":%q}`, token)
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return f(request)
}
