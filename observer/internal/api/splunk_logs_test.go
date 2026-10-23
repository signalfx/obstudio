package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/plog"
)

func TestSplunkLogsSaveTestPauseAndFailureIsolation(t *testing.T) {
	var received map[string]any
	var reject bool
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if (!reject && r.Header.Get("Authorization") != "Splunk private-token") || r.Header.Get("X-Splunk-Request-Channel") == "" {
			t.Error("missing credentials or channel")
		}
		if reject {
			w.WriteHeader(403)
			_, _ = w.Write([]byte(`{"text":"Invalid token","code":4}`))
			return
		}
		if err := json.NewDecoder(r.Body).Decode(&received); err != nil {
			t.Error(err)
		}
		_, _ = w.Write([]byte(`{"text":"Success","code":0}`))
	}))
	defer remote.Close()
	controller := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{})
	var saved otlp.SplunkHECLogsExporterConfig
	var diskError bool
	saves := 0
	mux := http.NewServeMux()
	Register(mux, store.New(), SplunkLogsSettings{Controller: controller, Save: func(c otlp.SplunkHECLogsExporterConfig) error {
		if diskError {
			return errors.New("disk full")
		}
		saved = c
		saves++
		return nil
	}})
	post := func(endpoint, token, version string, enabled bool, origin string) *httptest.ResponseRecorder {
		body, _ := json.Marshal(map[string]any{"endpoint": endpoint, "token": token, "index": "studio", "source": "http:studio-test", "enabled": enabled, "expectedVersion": version})
		r := httptest.NewRequest("POST", "http://localhost/api/splunk/logs", strings.NewReader(string(body)))
		r.RemoteAddr = "127.0.0.1:1234"
		r.Header.Set("Content-Type", "application/json")
		if origin != "" {
			r.Header.Set("Origin", origin)
			r.Header.Set("X-Obstudio-Browser-Request", "1")
		}
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, r)
		return w
	}
	endpoint := remote.URL + "/services/collector"
	initial := controller.Status().Version
	if w := post(endpoint, "private-token", initial, true, "https://evil.example"); w.Code != 403 {
		t.Fatalf("cross origin: %d %s", w.Code, w.Body)
	}
	if w := post(endpoint, "private-token", initial, true, ""); w.Code != 200 {
		t.Fatalf("save: %d %s", w.Code, w.Body)
	} else if strings.Contains(w.Body.String(), "private-token") {
		t.Fatal("status leaked token")
	}
	if !controller.Status().Enabled || saves != 1 || saved.Index != "studio" || received["index"] != "studio" || received["source"] != "http:studio-test" {
		t.Fatal("configuration or probe envelope incorrect")
	}
	version := controller.Status().Version
	if w := post(endpoint, "", initial, false, ""); w.Code != 409 {
		t.Fatal("stale update was accepted")
	}
	if w := post(remote.URL+"/services/collector/event", "", version, true, ""); w.Code != 400 {
		t.Fatal("stored token reused for changed endpoint")
	}
	reject = true
	if w := post(endpoint, "bad-token", version, true, ""); w.Code != 502 {
		t.Fatalf("bad token result: %d", w.Code)
	}
	if controller.Config().Token != "private-token" || !controller.Status().Enabled || saves != 1 {
		t.Fatal("failed probe changed working connection")
	}
	reject = false
	diskError = true
	if w := post(endpoint, "", version, false, ""); w.Code != 500 {
		t.Fatal("persistence failure hidden")
	}
	if !controller.Status().Enabled {
		t.Fatal("disk failure changed active config")
	}
	diskError = false
	if w := post(endpoint, "", version, false, ""); w.Code != 200 {
		t.Fatalf("pause: %d %s", w.Code, w.Body)
	}
	if controller.Status().Enabled || saved.Enabled || saved.Token != "private-token" {
		t.Fatal("pause did not retain credential")
	}
	if w := post(endpoint, "", controller.Status().Version, true, ""); w.Code != 200 {
		t.Fatal("resume failed")
	}
	if w := post("https://user:secret@example.test/services/collector", "private-token", controller.Status().Version, true, ""); w.Code != 400 {
		t.Fatal("userinfo accepted")
	}
	request := httptest.NewRequest("GET", "/api/query/stats", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, request)
	if w.Code != 200 {
		t.Fatal("logs failure broke core API")
	}
}

func TestSplunkLogsFollowSharedExportSwitch(t *testing.T) {
	requests := 0
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{})
	var saved otlp.SplunkHECLogsExporterConfig
	diskError := false
	mux := http.NewServeMux()
	Register(mux, store.New(), metrics, traces, SplunkLogsSettings{Controller: logs, Save: func(config otlp.SplunkHECLogsExporterConfig) error {
		if diskError {
			return errors.New("disk unavailable")
		}
		saved = config
		return nil
	}})
	status := func() splunkExportStatusResponse {
		var status splunkExportStatusResponse
		response := splunkExportRequest(t, mux, "GET", "/api/splunk/export", "")
		if err := json.Unmarshal(response.Body.Bytes(), &status); err != nil {
			t.Fatal(err)
		}
		return status
	}
	initial := status()
	body, _ := json.Marshal(map[string]any{"endpoint": remote.URL + "/services/collector", "token": "private-token", "index": "studio", "source": "otel", "expectedVersion": logs.Status().Version})
	if w := splunkExportRequest(t, mux, "POST", "/api/splunk/logs", string(body)); w.Code != 200 {
		t.Fatalf("save: %d %s", w.Code, w.Body)
	}
	if saved.Enabled || logs.Status().Enabled || requests != 0 {
		t.Fatal("Save enabled forwarding or sent a log while export was off")
	}
	if !status().Logs.Configured || status().Version == initial.Version {
		t.Fatal("logs destination missing from shared state/version")
	}
	toggle := func(enabled bool) *httptest.ResponseRecorder {
		body, _ := json.Marshal(map[string]any{"enabled": enabled, "expectedVersion": status().Version})
		return splunkExportRequest(t, mux, "POST", "/api/splunk/export/enabled", string(body))
	}
	if w := toggle(true); w.Code != 200 {
		t.Fatalf("enable logs-only: %d %s", w.Code, w.Body)
	}
	if !status().Enabled || !saved.Enabled || !logs.Status().Enabled || status().Connected {
		t.Fatal("logs-only switch state incorrect")
	}
	data := plog.NewLogs()
	data.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty().LogRecords().AppendEmpty().Body().SetStr("application log")
	if err := logs.ExportLogs(context.Background(), data); err != nil {
		t.Fatal(err)
	}
	if status().Logs.ExportedItems != 1 {
		t.Fatal("exported log count missing from shared activity")
	}
	if w := toggle(false); w.Code != 200 {
		t.Fatalf("disable: %d %s", w.Code, w.Body)
	}
	if err := logs.ExportLogs(context.Background(), data); err != nil {
		t.Fatal(err)
	}
	if requests != 1 || saved.Enabled || status().Enabled || status().Logs.ExportedItems != 1 {
		t.Fatal("disabled logs exported or count was reset")
	}
	if w := toggle(true); w.Code != 200 {
		t.Fatal(w.Body)
	}
	if err := logs.ExportLogs(context.Background(), data); err != nil {
		t.Fatal(err)
	}
	if status().Logs.ExportedItems != 2 {
		t.Fatal("resume lost the exported log count")
	}

	if err := metrics.Configure(otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud-token", Enabled: true}); err != nil {
		t.Fatal(err)
	}
	if err := traces.Configure(otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "cloud-token", Enabled: true}); err != nil {
		t.Fatal(err)
	}
	diskError = true
	if w := toggle(false); w.Code != 500 {
		t.Fatal("logs persistence failure was hidden")
	}
	if !metrics.Status().Enabled || !traces.Status().Enabled || !logs.Status().Enabled {
		t.Fatal("failed switch mutation changed working signals")
	}
	diskError = false
	rollbackToken := strings.Repeat("a", 43)
	w := splunkExportRequestWithRollbackToken(t, mux, "POST", "/api/splunk/export/enabled", `{"enabled":false}`, rollbackToken)
	if w.Code != 200 {
		t.Fatalf("disable with rollback: %d %s", w.Code, w.Body)
	}
	if metrics.Status().Enabled || traces.Status().Enabled || logs.Status().Enabled || saved.Enabled {
		t.Fatal("shared off switch did not stop all three signals")
	}
	w = splunkExportRequest(t, mux, "POST", "/api/splunk/export/rollback", `{"rollbackToken":"`+rollbackToken+`"}`)
	if w.Code != 200 {
		t.Fatalf("rollback: %d %s", w.Code, w.Body)
	}
	if !metrics.Status().Enabled || !traces.Status().Enabled || !logs.Status().Enabled || !saved.Enabled {
		t.Fatal("rollback did not restore all three signals")
	}
}
