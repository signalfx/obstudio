package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

const testObserverControlToken = "observer-control-token"
const testSplunkAccessToken = "splunk-access-token-1234"

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
	newSplunkExportService(metrics, traces, nil).register(mux)

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
			newSplunkExportService(metrics, traces, nil).register(mux)

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
	newSplunkExportService(metrics, traces, nil).register(mux)

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

func TestSplunkExportAcceptsOpaquePrintableAccessToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newSplunkExportService(metrics, traces, nil).register(mux)

	response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export",
		`{"realm":"us0","accessToken":"opaque.token+/=123456789"}`, testObserverControlToken)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
}

func TestSplunkExportMutationsRequireControlToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	mux := http.NewServeMux()
	newSplunkExportService(metrics, traces, nil).register(mux)

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
	newSplunkExportService(metrics, traces, nil).register(mux)

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
	newSplunkExportService(metrics, traces, nil).register(mux)

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
	newSplunkExportService(metrics, traces, nil).register(mux)

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
	newSplunkExportService(metrics, traces, nil).register(mux)

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
	newSplunkExportService(metrics, traces, nil).register(mux)

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
	newSplunkExportService(metrics, traces, nil).register(mux)

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
	newSplunkExportService(metrics, traces, nil).register(mux)

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
	mux := http.NewServeMux()
	newSplunkExportService(metrics, traces, nil).register(mux)

	tests := []string{
		`{"realm":"../../etc","accessToken":"` + testSplunkAccessToken + `"}`,
		`{"realm":"us0","accessToken":"short"}`,
		`{"realm":"us0","accessToken":"token with spaces 1234"}`,
		`{"realm":"us0","accessToken":"` + testSplunkAccessToken + `","extra":true}`,
		`{"realm":"us0","accessToken":"` + testSplunkAccessToken + `"} {}`,
	}
	for _, body := range tests {
		response := splunkExportRequest(t, mux, http.MethodPost, "/api/splunk/export", body, testObserverControlToken)
		if response.Code != http.StatusBadRequest {
			t.Fatalf("body %q status = %d, want %d", body, response.Code, http.StatusBadRequest)
		}
	}
}

func TestSplunkExportRefreshUsesConfigurationRefresher(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", testObserverControlToken)
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	calls := 0
	mux := http.NewServeMux()
	newSplunkExportService(metrics, traces, func() (bool, error) {
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
	newSplunkExportService(metrics, traces, func() (bool, error) {
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
