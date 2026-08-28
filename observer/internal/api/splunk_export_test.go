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

func TestSplunkExportRollbackUsesServerHeldSnapshotAndIsControlTokenOnly(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
		testObserverControlToken, "invalid")
	if invalidRollbackToken.Code != http.StatusBadRequest {
		t.Fatalf("invalid rollback token status = %d, body = %s",
			invalidRollbackToken.Code, invalidRollbackToken.Body.String())
	}
	if verifyCalls != 0 {
		t.Fatalf("invalid rollback token made %d live connection checks", verifyCalls)
	}

	configuredResponse := splunkExportRequestWithRollbackToken(t, mux, http.MethodPost,
		"/api/splunk/export", `{"realm":"us1","accessToken":"replacement-token"}`,
		testObserverControlToken, requestedRollbackToken)
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
	statusResponse := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
	if strings.Contains(statusResponse.Body.String(), "rollbackToken") {
		t.Fatalf("status response exposed rollback capability: %s", statusResponse.Body.String())
	}

	arbitraryRestore := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		`{"realm":"us2","accessToken":"caller-supplied"}`, testObserverControlToken)
	if arbitraryRestore.Code != http.StatusBadRequest {
		t.Fatalf("arbitrary rollback status = %d, body = %s",
			arbitraryRestore.Code, arbitraryRestore.Body.String())
	}
	if got := metrics.Config(); got.Realm != "us1" || got.AccessToken != "replacement-token" {
		t.Fatalf("arbitrary rollback changed metrics config: %+v", got)
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
	browserRollback := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		fmt.Sprintf(`{"rollbackToken":%q}`, configured.RollbackToken), session.BrowserToken)
	if browserRollback.Code != http.StatusUnauthorized {
		t.Fatalf("browser rollback status = %d, body = %s", browserRollback.Code, browserRollback.Body.String())
	}

	rollbackResponse := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		fmt.Sprintf(`{"rollbackToken":%q}`, configured.RollbackToken), testObserverControlToken)
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
		fmt.Sprintf(`{"rollbackToken":%q}`, configured.RollbackToken), testObserverControlToken)
	if replay.Code != http.StatusConflict {
		t.Fatalf("rollback replay status = %d, body = %s", replay.Code, replay.Body.String())
	}
}

func TestSplunkExportBrowserSessionPreservesPendingControlTokenRollback(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
	refreshCalls := 0
	service := newTestSplunkExportService(metrics, traces, func() (bool, error) {
		refreshCalls++
		return false, nil
	})
	mux := http.NewServeMux()
	service.register(mux)

	configuredResponse := splunkExportRequestWithRollbackToken(t, mux, http.MethodPost,
		"/api/splunk/export", `{"realm":"us1","accessToken":"replacement-token"}`,
		testObserverControlToken, strings.Repeat("R", 43))
	if configuredResponse.Code != http.StatusOK {
		t.Fatalf("configure status = %d, body = %s", configuredResponse.Code, configuredResponse.Body.String())
	}
	var configured splunkExportStatusResponse
	if err := json.Unmarshal(configuredResponse.Body.Bytes(), &configured); err != nil {
		t.Fatal(err)
	}

	sessionResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if sessionResponse.Code != http.StatusOK {
		t.Fatalf("session status = %d, body = %s", sessionResponse.Code, sessionResponse.Body.String())
	}
	if refreshCalls != 0 {
		t.Fatalf("browser session refreshed during pending rollback: got %d calls", refreshCalls)
	}

	rollbackResponse := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		fmt.Sprintf(`{"rollbackToken":%q}`, configured.RollbackToken), testObserverControlToken)
	if rollbackResponse.Code != http.StatusOK {
		t.Fatalf("rollback status = %d, body = %s", rollbackResponse.Code, rollbackResponse.Body.String())
	}

	var session struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(sessionResponse.Body.Bytes(), &session); err != nil {
		t.Fatal(err)
	}
	revisitResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", `{}`, session.BrowserToken)
	if revisitResponse.Code != http.StatusOK {
		t.Fatalf("session revisit status = %d, body = %s", revisitResponse.Code, revisitResponse.Body.String())
	}
	if refreshCalls != 1 {
		t.Fatalf("browser session refresh calls after rollback = %d, want 1", refreshCalls)
	}
}

func TestSplunkExportRollbackCapabilityIsInvalidatedByALaterMutation(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	mux := http.NewServeMux()
	service.register(mux)

	configuredResponse := splunkExportRequestWithRollbackToken(t, mux, http.MethodPost,
		"/api/splunk/export", `{"realm":"us1","accessToken":"replacement-token"}`,
		testObserverControlToken, strings.Repeat("R", 43))
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
		`{"enabled":true}`, testObserverControlToken)
	if enabledResponse.Code != http.StatusOK {
		t.Fatalf("enable status = %d, body = %s", enabledResponse.Code, enabledResponse.Body.String())
	}
	rollbackResponse := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		fmt.Sprintf(`{"rollbackToken":%q}`, configured.RollbackToken), testObserverControlToken)
	if rollbackResponse.Code != http.StatusConflict {
		t.Fatalf("stale rollback status = %d, body = %s",
			rollbackResponse.Code, rollbackResponse.Body.String())
	}
	if got := metrics.Config(); !got.Enabled || got.Realm != "us1" || got.AccessToken != "replacement-token" {
		t.Fatalf("stale rollback changed metrics config: %+v", got)
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
					mutation.body, testObserverControlToken),
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

	readStatus := func() splunkExportStatusResponse {
		t.Helper()
		response := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
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
		return splunkExportRequest(t, mux, http.MethodPost, path, string(encoded), testObserverControlToken)
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
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
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
			testObserverControlToken, rollbackToken)
	}()
	<-verificationStarted

	rollbackResponse := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		rollbackResponse <- splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
			fmt.Sprintf(`{"rollbackToken":%q}`, rollbackToken), testObserverControlToken)
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
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)

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
					testObserverControlToken,
					rollbackToken,
				)
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
						`{"realm":"us1","accessToken":"later-token"}`, testObserverControlToken)
					if later.Code != http.StatusOK {
						t.Fatalf("later mutation status = %d, body = %s", later.Code, later.Body.String())
					}
				}
				rollback := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
					fmt.Sprintf(`{"rollbackToken":%q}`, rollbackToken), testObserverControlToken)
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
	var sessionCookie *http.Cookie
	for _, cookie := range sessionResponse.Result().Cookies() {
		if cookie.Name == splunkBrowserCookiePrefix+"3000" {
			sessionCookie = cookie
			break
		}
	}
	if sessionCookie == nil {
		t.Fatal("browser session did not set its process-session cookie")
	}
	if !sessionCookie.HttpOnly || sessionCookie.SameSite != http.SameSiteStrictMode ||
		sessionCookie.Path != "/api/splunk/export" || sessionCookie.Secure {
		t.Fatalf("browser session cookie attributes = %#v", sessionCookie)
	}
	repeatedLaunchResponse := splunkBrowserExportRequestWithCookie(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "", sessionCookie)
	if repeatedLaunchResponse.Code != http.StatusOK {
		t.Fatalf("second-tab launch status = %d, body = %s",
			repeatedLaunchResponse.Code, repeatedLaunchResponse.Body.String())
	}
	var repeatedSession struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(repeatedLaunchResponse.Body.Bytes(), &repeatedSession); err != nil {
		t.Fatal(err)
	}
	if repeatedSession.BrowserToken != session.BrowserToken {
		t.Fatal("second tab did not reattach to the process-lifetime browser session")
	}
	otherPortResponse := splunkBrowserExportRequestWithOriginAndCookie(t, mux, http.MethodPost,
		"http://127.0.0.1:3001/api/splunk/export/browser/session",
		splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "", sessionCookie)
	if otherPortResponse.Code != http.StatusOK {
		t.Fatalf("other-port local page status = %d, body = %s",
			otherPortResponse.Code, otherPortResponse.Body.String())
	}
	var otherPortSession struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(otherPortResponse.Body.Bytes(), &otherPortSession); err != nil {
		t.Fatal(err)
	}
	if otherPortSession.BrowserToken != session.BrowserToken {
		t.Fatal("other-port local page did not attach to the process browser session")
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
		t.Fatalf("reloaded browser token has invalid shape: %q", secondSession.BrowserToken)
	}
	if secondSession.BrowserToken != session.BrowserToken {
		t.Fatal("browser session changed before the Observer process restarted")
	}
	for revisit := 0; revisit < 128; revisit++ {
		revisitResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
			"/api/splunk/export/browser/session", `{}`, session.BrowserToken)
		if revisitResponse.Code != http.StatusOK {
			t.Fatalf("browser session revisit %d status = %d, body = %s",
				revisit, revisitResponse.Code, revisitResponse.Body.String())
		}
		var revisitSession struct {
			BrowserToken string `json:"browserToken"`
		}
		if err := json.Unmarshal(revisitResponse.Body.Bytes(), &revisitSession); err != nil {
			t.Fatal(err)
		}
		if revisitSession.BrowserToken != session.BrowserToken {
			t.Fatalf("browser session changed on revisit %d", revisit)
		}
	}

	connectResponse := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"us1","accessToken":"opaque-browser-token"}`, session.BrowserToken)
	if connectResponse.Code != http.StatusOK {
		t.Fatalf("connect status = %d, body = %s", connectResponse.Code, connectResponse.Body.String())
	}
	if strings.Contains(connectResponse.Body.String(), "rollbackToken") {
		t.Fatalf("browser connect exposed control-token rollback capability: %s", connectResponse.Body.String())
	}
	if got := connectResponse.Header().Get(splunkBrowserTokenHeader); got != "" {
		t.Fatalf("connect unexpectedly rotated the process-lifetime browser token: %q", got)
	}
	enableResponse := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{"enabled":true}`, session.BrowserToken)
	if enableResponse.Code != http.StatusOK {
		t.Fatalf("enable status = %d, body = %s", enableResponse.Code, enableResponse.Body.String())
	}
	if got := enableResponse.Header().Get(splunkBrowserTokenHeader); got != "" {
		t.Fatalf("enable unexpectedly rotated the process-lifetime browser token: %q", got)
	}
	forgetResponse := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export/forget",
		`{}`, session.BrowserToken)
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
		t.Fatalf("post-restart stale session status = %d, body = %s",
			renewedResponse.Code, renewedResponse.Body.String())
	}

	newLaunchToken := strings.Repeat("C", 43)
	newSessionResponse := splunkBrowserExportRequest(t, restartedMux, http.MethodPost,
		"/api/splunk/export/browser/session",
		splunkBrowserLaunchRequestBody(newLaunchToken), "")
	if newSessionResponse.Code != http.StatusOK {
		t.Fatalf("new process launch status = %d, body = %s",
			newSessionResponse.Code, newSessionResponse.Body.String())
	}
	var newSession struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(newSessionResponse.Body.Bytes(), &newSession); err != nil {
		t.Fatal(err)
	}
	if newSession.BrowserToken == firstSession.BrowserToken {
		t.Fatal("restarted Observer reused the prior process browser session")
	}
	var freshCookie *http.Cookie
	for _, cookie := range newSessionResponse.Result().Cookies() {
		if cookie.Name == splunkBrowserCookiePrefix+"3000" {
			freshCookie = cookie
			break
		}
	}
	if freshCookie == nil {
		t.Fatal("new process session did not set a browser cookie")
	}

	staleHeaderResponse := splunkBrowserExportRequestWithCookie(t, restartedMux, http.MethodPost,
		"/api/splunk/export/browser/session", `{}`, firstSession.BrowserToken, freshCookie)
	if staleHeaderResponse.Code != http.StatusOK {
		t.Fatalf("stale-header/fresh-cookie session status = %d, body = %s",
			staleHeaderResponse.Code, staleHeaderResponse.Body.String())
	}
	var reattached struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(staleHeaderResponse.Body.Bytes(), &reattached); err != nil {
		t.Fatal(err)
	}
	if reattached.BrowserToken != newSession.BrowserToken {
		t.Fatalf("stale header masked fresh cookie: got %q, want %q",
			reattached.BrowserToken, newSession.BrowserToken)
	}

	mutationResponse := splunkBrowserExportRequestWithCookie(t, restartedMux, http.MethodPost,
		"/api/splunk/export", `{"realm":"us1","accessToken":"fresh-cookie-token"}`,
		firstSession.BrowserToken, freshCookie)
	if mutationResponse.Code != http.StatusOK {
		t.Fatalf("stale-header/fresh-cookie mutation status = %d, body = %s",
			mutationResponse.Code, mutationResponse.Body.String())
	}
}

func TestSplunkExportBrowserSessionRemainsUsableWhenConfigurationRefreshFails(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, func() (bool, error) {
		return false, errors.New("could not parse the configured env file")
	})
	mux := http.NewServeMux()
	service.register(mux)

	sessionResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if sessionResponse.Code != http.StatusOK {
		t.Fatalf("session status = %d, body = %s", sessionResponse.Code, sessionResponse.Body.String())
	}
	var session struct {
		BrowserToken string `json:"browserToken"`
		Warning      string `json:"warning"`
	}
	if err := json.Unmarshal(sessionResponse.Body.Bytes(), &session); err != nil {
		t.Fatal(err)
	}
	if !splunkBrowserTokenPattern.MatchString(session.BrowserToken) {
		t.Fatalf("browser token has invalid shape: %q", session.BrowserToken)
	}
	if session.Warning != "could not parse the configured env file" {
		t.Fatalf("warning = %q", session.Warning)
	}

	connectResponse := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"us1","accessToken":"opaque-browser-token"}`, session.BrowserToken)
	if connectResponse.Code != http.StatusOK {
		t.Fatalf("connect status = %d, body = %s", connectResponse.Code, connectResponse.Body.String())
	}
}

func TestSplunkExportBrowserSessionReusesProcessSessionAcrossValidLaunchContexts(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	mux := http.NewServeMux()
	service.register(mux)

	requestBody := splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken)
	firstResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", requestBody, "")
	if firstResponse.Code != http.StatusOK {
		t.Fatalf("initial session status = %d, body = %s", firstResponse.Code, firstResponse.Body.String())
	}
	var firstSession struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(firstResponse.Body.Bytes(), &firstSession); err != nil {
		t.Fatal(err)
	}

	// Model a response that was accepted by Observer but never reached the tab.
	retryResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", requestBody, "")
	if retryResponse.Code != http.StatusOK {
		t.Fatalf("retried session status = %d, body = %s", retryResponse.Code, retryResponse.Body.String())
	}
	var retriedSession struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(retryResponse.Body.Bytes(), &retriedSession); err != nil {
		t.Fatal(err)
	}
	if retriedSession.BrowserToken != firstSession.BrowserToken {
		t.Fatal("launch retry minted a different browser session")
	}

	secondContextResponse := splunkBrowserExportRequestWithOriginAndCookie(t, mux, http.MethodPost,
		"http://localhost:3000/api/splunk/export/browser/session",
		requestBody,
		"", nil)
	if secondContextResponse.Code != http.StatusOK {
		t.Fatalf("second-context launch status = %d, body = %s",
			secondContextResponse.Code, secondContextResponse.Body.String())
	}
	var secondContextSession struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(secondContextResponse.Body.Bytes(), &secondContextSession); err != nil {
		t.Fatal(err)
	}
	if secondContextSession.BrowserToken != firstSession.BrowserToken {
		t.Fatal("valid launch context did not reattach to the process session")
	}
}

func TestSplunkExportBrowserSessionSerializesConcurrentValidLaunchContexts(t *testing.T) {
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
			"/api/splunk/export/browser/session",
			splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
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
	if statuses[http.StatusOK] != 2 {
		t.Fatalf("session statuses = %#v, want both valid launch contexts to succeed", statuses)
	}
	if refreshCalls != 2 {
		t.Fatalf("refresh calls = %d, want 2", refreshCalls)
	}
}

func TestSplunkExportBrowserSessionRecoversUnknownTokenWithValidLaunch(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	mux := http.NewServeMux()
	service.register(mux)

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
	currentToken := session.BrowserToken
	last := "A"
	if strings.HasSuffix(currentToken, last) {
		last = "B"
	}
	tamperedToken := currentToken[:len(currentToken)-1] + last
	if service.hasValidBrowserToken(tamperedToken) {
		t.Fatal("tampered browser session token was accepted")
	}
	response := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session",
		splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), tamperedToken)
	if response.Code != http.StatusOK {
		t.Fatalf("tampered session status = %d, body = %s", response.Code, response.Body.String())
	}
	var recovered struct {
		BrowserToken string `json:"browserToken"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &recovered); err != nil {
		t.Fatal(err)
	}
	if recovered.BrowserToken != currentToken {
		t.Fatal("local page did not recover the active process browser session")
	}

	mutationResponse := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/enabled", `{"enabled":true}`, tamperedToken)
	if mutationResponse.Code != http.StatusUnauthorized {
		t.Fatalf("tampered mutation status = %d, body = %s",
			mutationResponse.Code, mutationResponse.Body.String())
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

func TestSplunkExportBrowserSessionRejectsBareLoopbackPage(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	mux := http.NewServeMux()
	service.register(mux)

	response := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(""), "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("session status = %d, body = %s", response.Code, response.Body.String())
	}

	connectResponse := splunkBrowserExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"us1","accessToken":"opaque-browser-token"}`, "")
	if connectResponse.Code != http.StatusUnauthorized {
		t.Fatalf("unauthenticated connect status = %d, body = %s",
			connectResponse.Code, connectResponse.Body.String())
	}
}

func TestSplunkExportBrowserSessionRejectsInvalidLaunchWhenProvided(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	mux := http.NewServeMux()
	service.register(mux)

	response := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", `{}`, "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("missing launch status = %d, body = %s", response.Code, response.Body.String())
	}

	response = splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session",
		splunkBrowserLaunchRequestBody(strings.Repeat("A", 43)), "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("wrong launch status = %d, body = %s", response.Code, response.Body.String())
	}

	service.browserLaunch = ""
	response = splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(testSplunkBrowserLaunchToken), "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("unconfigured launch status = %d, body = %s", response.Code, response.Body.String())
	}

	response = splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", splunkBrowserLaunchRequestBody(""), "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("empty launch status = %d, body = %s", response.Code, response.Body.String())
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

func TestSplunkExportConfigurationSnapshotIsControlTokenOnly(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Enabled: true, Realm: "us1", AccessToken: "snapshot-token",
	})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Enabled: true, Realm: "us1", AccessToken: "snapshot-token",
	})
	mux := http.NewServeMux()
	newTestSplunkExportService(metrics, traces, nil).register(mux)

	unauthorized := splunkExportRequest(
		t,
		mux,
		http.MethodGet,
		"/api/splunk/export/configuration",
		"",
		"",
	)
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized status = %d, body = %s", unauthorized.Code, unauthorized.Body.String())
	}
	if strings.Contains(unauthorized.Body.String(), "snapshot-token") {
		t.Fatal("unauthorized response exposed the access token")
	}

	authorized := splunkExportRequest(
		t,
		mux,
		http.MethodGet,
		"/api/splunk/export/configuration",
		"",
		testObserverControlToken,
	)
	if authorized.Code != http.StatusOK {
		t.Fatalf("authorized status = %d, body = %s", authorized.Code, authorized.Body.String())
	}
	if got := authorized.Header().Get("Cache-Control"); got != "no-store" {
		t.Fatalf("cache control = %q", got)
	}
	var configuration splunkExportConfigurationResponse
	if err := json.Unmarshal(authorized.Body.Bytes(), &configuration); err != nil {
		t.Fatal(err)
	}
	if !configuration.Connected || !configuration.Enabled || configuration.Realm != "us1" ||
		configuration.AccessToken != "snapshot-token" {
		t.Fatalf("configuration = %+v", configuration)
	}
	if configuration.Changed {
		t.Fatal("startup configuration was incorrectly marked as a user mutation")
	}
	if !splunkStateVersionPattern.MatchString(configuration.Version) {
		t.Fatalf("configuration version = %q", configuration.Version)
	}

	publicStatus := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
	if strings.Contains(publicStatus.Body.String(), "snapshot-token") {
		t.Fatal("public status exposed the access token")
	}

	disable := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/enabled",
		`{"enabled":false}`, testObserverControlToken)
	if disable.Code != http.StatusOK {
		t.Fatalf("disable status = %d, body = %s", disable.Code, disable.Body.String())
	}
	if strings.Contains(disable.Body.String(), "rollbackToken") {
		t.Fatalf("ordinary control mutation exposed an unrequested rollback capability: %s", disable.Body.String())
	}
	changed := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export/configuration",
		"", testObserverControlToken)
	if err := json.Unmarshal(changed.Body.Bytes(), &configuration); err != nil {
		t.Fatal(err)
	}
	if !configuration.Changed || configuration.Enabled {
		t.Fatalf("changed configuration = %+v", configuration)
	}
}

func TestSplunkExportShutdownSnapshotQuiescesCloudMutations(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Enabled: true, Realm: "us1", AccessToken: "snapshot-token",
	})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Enabled: true, Realm: "us1", AccessToken: "snapshot-token",
	})
	refreshCalls := 0
	service := newTestSplunkExportService(metrics, traces, func() (bool, error) {
		refreshCalls++
		return false, nil
	})
	verificationCalls := 0
	service.verifyConnection = func(context.Context, string, string) error {
		verificationCalls++
		return nil
	}
	mux := http.NewServeMux()
	service.register(mux)

	snapshot := splunkExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/shutdown-snapshot", `{}`, testObserverControlToken)
	if snapshot.Code != http.StatusOK {
		t.Fatalf("shutdown snapshot status = %d, body = %s", snapshot.Code, snapshot.Body.String())
	}
	var configuration splunkExportConfigurationResponse
	if err := json.Unmarshal(snapshot.Body.Bytes(), &configuration); err != nil {
		t.Fatal(err)
	}
	if !configuration.Connected || !configuration.Enabled || configuration.AccessToken != "snapshot-token" {
		t.Fatalf("shutdown snapshot = %+v", configuration)
	}

	mutations := []struct {
		body string
		path string
	}{
		{path: "/api/splunk/export", body: `{"realm":"eu1","accessToken":"new-token"}`},
		{path: "/api/splunk/export/enabled", body: `{"enabled":false}`},
		{path: "/api/splunk/export/forget", body: `{}`},
		{path: "/api/splunk/export/refresh", body: `{}`},
	}
	for _, mutation := range mutations {
		response := splunkExportRequest(t, mux, http.MethodPost, mutation.path,
			mutation.body, testObserverControlToken)
		if response.Code != http.StatusServiceUnavailable {
			t.Fatalf("quiesced %s status = %d, body = %s",
				mutation.path, response.Code, response.Body.String())
		}
	}
	if verificationCalls != 0 {
		t.Fatalf("quiesced Connect ran %d connection verifications", verificationCalls)
	}
	if refreshCalls != 0 {
		t.Fatalf("quiesced refresh ran %d configuration reloads", refreshCalls)
	}

	rollback := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export/rollback",
		`{"rollbackToken":"`+strings.Repeat("R", 43)+`"}`, testObserverControlToken)
	if rollback.Code != http.StatusServiceUnavailable {
		t.Fatalf("quiesced rollback status = %d, body = %s", rollback.Code, rollback.Body.String())
	}
	browserSession := splunkBrowserExportRequest(t, mux, http.MethodPost,
		"/api/splunk/export/browser/session", `{"launchToken":""}`, "")
	if browserSession.Code != http.StatusServiceUnavailable {
		t.Fatalf("quiesced browser session status = %d, body = %s",
			browserSession.Code, browserSession.Body.String())
	}

	status := splunkExportRequest(t, mux, http.MethodGet, "/api/splunk/export", "", "")
	var current splunkExportStatusResponse
	if err := json.Unmarshal(status.Body.Bytes(), &current); err != nil {
		t.Fatal(err)
	}
	if !current.Connected || !current.Enabled || current.Realm != "us1" {
		t.Fatalf("quiesced mutations changed Observer state: %+v", current)
	}
}

func TestSplunkExportShutdownSnapshotCancelsInFlightConnectBeforeApply(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	service := newTestSplunkExportService(metrics, traces, nil)
	verificationStarted := make(chan struct{})
	releaseVerification := make(chan struct{})
	var releaseOnce sync.Once
	defer releaseOnce.Do(func() { close(releaseVerification) })
	service.verifyConnection = func(context.Context, string, string) error {
		close(verificationStarted)
		<-releaseVerification
		return nil
	}
	mux := http.NewServeMux()
	service.register(mux)

	connectResult := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		connectResult <- splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
			`{"realm":"us1","accessToken":"new-token"}`, testObserverControlToken)
	}()
	<-verificationStarted

	snapshotResult := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		snapshotResult <- splunkExportRequest(t, mux, http.MethodPost,
			"/api/splunk/export/shutdown-snapshot", `{}`, testObserverControlToken)
	}()
	deadline := time.Now().Add(time.Second)
	for !service.mutationsQuiesced.Load() && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if !service.mutationsQuiesced.Load() {
		t.Fatal("shutdown snapshot did not quiesce mutations before waiting for Connect")
	}
	releaseOnce.Do(func() { close(releaseVerification) })

	connect := <-connectResult
	if connect.Code != http.StatusServiceUnavailable {
		t.Fatalf("in-flight Connect status = %d, body = %s", connect.Code, connect.Body.String())
	}
	snapshot := <-snapshotResult
	if snapshot.Code != http.StatusOK {
		t.Fatalf("shutdown snapshot status = %d, body = %s", snapshot.Code, snapshot.Body.String())
	}
	var configuration splunkExportConfigurationResponse
	if err := json.Unmarshal(snapshot.Body.Bytes(), &configuration); err != nil {
		t.Fatal(err)
	}
	if configuration.Connected || configuration.AccessToken != "" {
		t.Fatalf("shutdown snapshot included the cancelled Connect: %+v", configuration)
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
		{name: "invalid expected version", body: `{"realm":"us0","accessToken":"` + testSplunkAccessToken + `","expectedVersion":"stale"}`},
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
	return splunkExportRequestWithRollbackToken(t, handler, method, path, body, controlToken, "")
}

func splunkExportRequestWithRollbackToken(
	t *testing.T,
	handler http.Handler,
	method string,
	path string,
	body string,
	controlToken string,
	rollbackToken string,
) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	request.Header.Set("Content-Type", "application/json")
	if controlToken != "" {
		request.Header.Set("Authorization", "Bearer "+controlToken)
	}
	if rollbackToken != "" {
		request.Header.Set(splunkRollbackTokenHeader, rollbackToken)
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
	return splunkBrowserExportRequestWithCookie(t, handler, method, path, body, browserToken, nil)
}

func splunkBrowserExportRequestWithCookie(
	t *testing.T,
	handler http.Handler,
	method string,
	path string,
	body string,
	browserToken string,
	browserCookie *http.Cookie,
) *httptest.ResponseRecorder {
	t.Helper()
	return splunkBrowserExportRequestWithOriginAndCookie(t, handler, method,
		"http://127.0.0.1:3000"+path, body, browserToken, browserCookie)
}

func splunkBrowserExportRequestWithOriginAndCookie(
	t *testing.T,
	handler http.Handler,
	method string,
	requestURL string,
	body string,
	browserToken string,
	browserCookie *http.Cookie,
) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, requestURL, bytes.NewBufferString(body))
	request.RemoteAddr = "127.0.0.1:54321"
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Origin", "http://"+request.Host)
	request.Header.Set("Sec-Fetch-Site", "same-origin")
	request.Header.Set(splunkBrowserRequestHeader, "1")
	if browserToken != "" {
		request.Header.Set(splunkBrowserTokenHeader, browserToken)
	}
	if browserCookie != nil {
		request.AddCookie(browserCookie)
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
	service.browserLaunch = testSplunkBrowserLaunchToken
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
