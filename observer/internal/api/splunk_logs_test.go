package api

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/plog/plogotlp"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func TestSplunkConnectionStatusIsNotReadableCrossOrigin(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{Endpoint: "https://stack.splunkcloud.com/services/collector", Token: "private-token", Index: "studio"})
	defer logs.Shutdown(context.Background())
	mux := http.NewServeMux()
	Register(mux, store.New(), metrics, traces, SplunkLogsSettings{Controller: logs})
	for _, path := range []string{"/api/splunk/logs", "/api/splunk/export"} {
		for _, origin := range []string{"", "http://localhost", "https://unrelated.example"} {
			r := httptest.NewRequest("GET", "http://localhost"+path, nil)
			r.Header.Set("Origin", origin)
			w := httptest.NewRecorder()
			mux.ServeHTTP(w, r)
			if w.Code != 200 || w.Header().Get("Access-Control-Allow-Origin") != "" || w.Header().Get("Cache-Control") != "no-store" {
				t.Fatalf("%s with origin %q: %d %v", path, origin, w.Code, w.Header())
			}
			if strings.Contains(w.Body.String(), "private-token") {
				t.Fatal("status exposed the saved token")
			}
		}
	}
}

func TestSplunkLogsSlowMutationsDoNotBlockCloudStatus(t *testing.T) {
	for _, operation := range []string{"probe", "apply", "toggle", "disconnect"} {
		t.Run(operation, func(t *testing.T) {
			started, saved, release, canceled := make(chan struct{}), make(chan struct{}), make(chan struct{}), make(chan struct{})
			var releaseOnce sync.Once
			unblock := func() { releaseOnce.Do(func() { close(release) }) }
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, _ = io.Copy(io.Discard, r.Body)
				close(started)
				select {
				case <-r.Context().Done():
					close(canceled)
					return
				case <-release:
				}
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			defer unblock()
			fastRemote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"code":0}`)) }))
			defer fastRemote.Close()
			config := otlp.SplunkHECLogsExporterConfig{}
			if operation != "probe" {
				config = otlp.SplunkHECLogsExporterConfig{Endpoint: remote.URL + "/services/collector", Token: "test", Index: "studio", Enabled: true, ConnectionVerified: true, Timeout: time.Minute}
			}
			logs := otlp.NewSplunkHECLogsExportController(config)
			defer logs.Shutdown(context.Background())
			metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
			traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
			mux := http.NewServeMux()
			Register(mux, store.New(), metrics, traces, SplunkLogsSettings{Controller: logs, Save: func(otlp.SplunkHECLogsExporterConfig) error { close(saved); return nil }})
			if operation != "probe" {
				payload := plog.NewLogs()
				payload.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty().LogRecords().AppendEmpty().Body().SetStr("in flight")
				logs.QueueLogs(payload)
				<-started
			}
			path := "/api/splunk/logs"
			body := map[string]any{"expectedVersion": logs.Status().Version}
			switch operation {
			case "probe":
				body["endpoint"], body["token"], body["index"], body["verifyConnection"], body["enabled"] = remote.URL+"/services/collector", "test", "studio", true, false
			case "apply":
				body["endpoint"], body["token"], body["index"], body["verifyConnection"], body["preserveEnabled"] = fastRemote.URL+"/services/collector", "replacement", "studio", true, true
			case "toggle":
				path, body["enabled"] = "/api/splunk/logs/enabled", false
			case "disconnect":
				path = "/api/splunk/logs/disconnect"
			}
			encoded, _ := json.Marshal(body)
			done := make(chan *httptest.ResponseRecorder, 1)
			go func() { done <- splunkExportRequest(t, mux, "POST", path, string(encoded)) }()
			if operation == "probe" {
				<-started
			} else {
				<-saved
			}
			statusDone := make(chan *httptest.ResponseRecorder, 1)
			go func() { statusDone <- splunkExportRequest(t, mux, "GET", "/api/splunk/export", "") }()
			select {
			case response := <-statusDone:
				if response.Code != 200 {
					t.Errorf("status = %d", response.Code)
				}
			case <-time.After(time.Second):
				t.Error("HEC network I/O blocked independent cloud status")
			}
			if operation == "probe" {
				unblock()
			}
			select {
			case response := <-done:
				if response.Code != 200 {
					t.Fatalf("mutation = %d %s", response.Code, response.Body)
				}
			case <-time.After(time.Second):
				t.Fatal("mutation waited for the old 60-second HEC request")
			}
			if operation != "probe" {
				select {
				case <-canceled:
				case <-time.After(time.Second):
					t.Fatal("old export was not canceled")
				}
				if status := logs.Status(); (operation != "apply" && status.Enabled) || (operation == "disconnect" && status.Connected) || status.FailedBatches != 0 {
					t.Fatalf("mutation runtime differs from saved intent: %+v", status)
				}
			}
		})
	}
}

func TestSplunkLogsRechecksVersionAfterProbe(t *testing.T) {
	started, release := make(chan struct{}), make(chan struct{})
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started)
		<-release
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{})
	defer logs.Shutdown(context.Background())
	var saves atomic.Int32
	mux := http.NewServeMux()
	Register(mux, store.New(), SplunkLogsSettings{Controller: logs, Save: func(otlp.SplunkHECLogsExporterConfig) error { saves.Add(1); return nil }})
	body, _ := json.Marshal(map[string]any{"endpoint": remote.URL + "/services/collector", "token": "test", "index": "studio", "enabled": false, "verifyConnection": true, "expectedVersion": logs.Status().Version})
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() { done <- splunkExportRequest(t, mux, "POST", "/api/splunk/logs", string(body)) }()
	<-started
	if err := logs.SetEnabled(false); err != nil {
		t.Fatal(err)
	}
	close(release)
	if response := <-done; response.Code != 409 || saves.Load() != 0 || logs.Status().Configured {
		t.Fatalf("stale probe committed: %d %s", response.Code, response.Body)
	}
}

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
		var body io.Reader = r.Body
		if r.Header.Get("Content-Encoding") == "gzip" {
			reader, err := gzip.NewReader(r.Body)
			if err != nil {
				t.Error(err)
				return
			}
			defer reader.Close()
			body = reader
		}
		if err := json.NewDecoder(body).Decode(&received); err != nil {
			t.Error(err)
		}
		_, _ = w.Write([]byte(`{"text":"Success","code":0}`))
	}))
	defer remote.Close()
	controller := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{Timeout: 30 * time.Second})
	var saved otlp.SplunkHECLogsExporterConfig
	var diskError bool
	saves := 0
	mux := http.NewServeMux()
	local := store.New()
	Register(mux, local, SplunkLogsSettings{Controller: controller, Save: func(c otlp.SplunkHECLogsExporterConfig) error {
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
	if saved.Timeout != 30*time.Second || controller.Config().Timeout != saved.Timeout {
		t.Fatalf("connection settings overwrote the user's HEC timeout: saved=%s runtime=%s", saved.Timeout, controller.Config().Timeout)
	}
	localLogs := local.QueryLogs(10)
	if len(localLogs) != 1 || localLogs[0].Body != received["event"] || localLogs[0].Resource.ServiceName != "obstudio" || localLogs[0].SeverityText != "INFO" {
		t.Fatalf("connection test must be visible locally and remotely: local=%#v remote=%#v", localLogs, received)
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
	if len(local.QueryLogs(10)) != 2 {
		t.Fatal("failed remote test must remain visible locally")
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
	if len(local.QueryLogs(10)) != 2 {
		t.Fatal("saving while paused must not create a connection test")
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
	if !splunkStateVersionPattern.MatchString(initial.CloudVersion) {
		t.Fatal("status must include a Cloud configuration version")
	}
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
	if status().CloudVersion != initial.CloudVersion {
		t.Fatal("saving logs must preserve the Cloud configuration version")
	}
	toggle := func(enabled bool) *httptest.ResponseRecorder {
		body, _ := json.Marshal(map[string]any{"enabled": enabled, "expectedVersion": status().Version})
		return splunkExportRequest(t, mux, "POST", "/api/splunk/export/enabled", string(body))
	}
	if w := toggle(true); w.Code != http.StatusConflict {
		t.Fatal("unverified saved destination was enabled")
	}
	body, _ = json.Marshal(map[string]any{"endpoint": remote.URL + "/services/collector", "token": "", "index": "studio", "source": "otel", "verifyConnection": true, "expectedVersion": logs.Status().Version})
	if w := splunkExportRequest(t, mux, "POST", "/api/splunk/logs", string(body)); w.Code != 200 {
		t.Fatalf("verify logs-only: %d %s", w.Code, w.Body)
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
	if status().Logs.ExportedItems != 2 {
		t.Fatal("exported log count missing from shared activity")
	}
	if w := toggle(false); w.Code != 200 {
		t.Fatalf("disable: %d %s", w.Code, w.Body)
	}
	if err := logs.ExportLogs(context.Background(), data); err != nil {
		t.Fatal(err)
	}
	if requests != 2 || saved.Enabled || status().Enabled || status().Logs.ExportedItems != 2 {
		t.Fatal("disabled logs exported or count was reset")
	}
	if w := toggle(true); w.Code != 200 {
		t.Fatal(w.Body)
	}
	if err := logs.ExportLogs(context.Background(), data); err != nil {
		t.Fatal(err)
	}
	if status().Logs.ExportedItems != 4 {
		t.Fatal("resume must export the paused log and the new log")
	}
	if status().CloudVersion != initial.CloudVersion {
		t.Fatal("logs verification, export toggles, and delivery must preserve the Cloud configuration version")
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

func TestSplunkConnectionsHaveIndependentVerifiedExportControls(t *testing.T) {
	reject := true
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if reject {
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = w.Write([]byte(`{"code":4}`))
			return
		}
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{})
	diskError := false
	var savedConfig otlp.SplunkHECLogsExporterConfig
	settings := SplunkLogsSettings{Controller: logs, Save: func(config otlp.SplunkHECLogsExporterConfig) error {
		if diskError {
			return errors.New("disk unavailable")
		}
		savedConfig = config
		return nil
	}}
	service := newTestSplunkExportService(metrics, traces, nil)
	service.logs = settings
	mux := http.NewServeMux()
	service.register(mux)
	local := store.New()
	registerSplunkLogs(mux, local, settings, service)
	post := func(path string, body any, code int) {
		t.Helper()
		data, _ := json.Marshal(body)
		response := splunkExportRequest(t, mux, "POST", path, string(data))
		if response.Code != code {
			t.Fatalf("%s: %d %s", path, response.Code, response.Body)
		}
	}
	cloudToggle := func(enabled bool, code int) {
		t.Helper()
		post("/api/splunk/export/enabled", map[string]any{"enabled": enabled, "scope": "observability", "expectedVersion": service.snapshot().Version}, code)
	}
	logsToggle := func(enabled bool, code int) {
		t.Helper()
		post("/api/splunk/logs/enabled", map[string]any{"enabled": enabled, "expectedVersion": logs.Status().Version}, code)
	}
	cloudToggle(true, http.StatusConflict)
	logsToggle(true, http.StatusConflict)
	post("/api/splunk/export", map[string]any{"realm": "us1", "accessToken": testSplunkAccessToken}, http.StatusOK)
	cloudToggle(true, http.StatusOK)
	connection := map[string]any{"endpoint": remote.URL + "/services/collector", "token": "private-token", "index": "studio", "source": "otel", "enabled": false, "verifyConnection": true, "expectedVersion": logs.Status().Version}
	post("/api/splunk/logs", connection, http.StatusBadGateway)
	logsToggle(true, http.StatusConflict)
	if !metrics.Status().Enabled || !traces.Status().Enabled {
		t.Fatal("failed logs connection changed Observability Cloud export")
	}
	reject = false
	post("/api/splunk/logs", connection, http.StatusOK)
	if !logs.Status().Connected || !savedConfig.ConnectionVerified {
		t.Fatal("successful verification must persist the connected state")
	}
	if logs.Status().Enabled || logs.Status().LastExportSuccess == "" || len(local.QueryLogs(10)) != 2 {
		t.Fatal("logs connection must verify both paths and leave forwarding off")
	}
	if !metrics.Status().Enabled || !traces.Status().Enabled {
		t.Fatal("successful logs connection changed Observability Cloud export")
	}
	logsToggle(true, http.StatusOK)
	cloudToggle(false, http.StatusOK)
	if !logs.Status().Enabled || metrics.Status().Enabled || traces.Status().Enabled {
		t.Fatal("Observability Cloud pause changed logs export")
	}
	cloudToggle(true, http.StatusOK)
	logsToggle(false, http.StatusOK)
	if !metrics.Status().Enabled || !traces.Status().Enabled || logs.Status().Enabled {
		t.Fatal("logs pause changed Observability Cloud export")
	}
	logsToggle(true, http.StatusOK)
	diskError = true
	cloudToggle(false, http.StatusOK)
	logsToggle(false, http.StatusInternalServerError)
	if !logs.Status().Enabled {
		t.Fatal("failed persistence changed active logs export")
	}
	diskError = false
	post("/api/splunk/logs/enabled", map[string]any{"enabled": false, "expectedVersion": "stale"}, http.StatusConflict)
	verify := service.verifyConnection
	service.verifyConnection = func(context.Context, string, string) error { return errSplunkAccessTokenRejected }
	post("/api/splunk/export", map[string]any{"realm": "us2", "accessToken": testSplunkAccessToken}, http.StatusUnauthorized)
	if !logs.Status().Enabled {
		t.Fatal("failed Observability Cloud connection changed logs export")
	}
	service.verifyConnection = verify
	post("/api/splunk/export", map[string]any{"realm": "us2", "accessToken": testSplunkAccessToken}, http.StatusOK)
	cloudToggle(true, http.StatusOK)
	post("/api/splunk/logs/disconnect", map[string]any{"expectedVersion": "stale"}, http.StatusConflict)
	post("/api/splunk/logs/disconnect", map[string]any{"expectedVersion": logs.Status().Version, "unknown": true}, http.StatusBadRequest)
	diskError = true
	post("/api/splunk/logs/disconnect", map[string]any{"expectedVersion": logs.Status().Version}, http.StatusInternalServerError)
	if !logs.Status().Connected || !logs.Status().Enabled {
		t.Fatal("failed disconnect must preserve the working logs connection")
	}
	if !logs.Status().TokenConfigured || logs.Config().Token != "private-token" {
		t.Fatal("failed disconnect removed the working token")
	}
	diskError = false
	post("/api/splunk/logs/disconnect", map[string]any{"expectedVersion": logs.Status().Version}, http.StatusOK)
	if logs.Status().Connected || logs.Status().Enabled || savedConfig.ConnectionVerified || savedConfig.Enabled {
		t.Fatal("disconnect did not clear connection verification and stop forwarding")
	}
	if logs.Status().TokenConfigured || logs.Config().Token != "" || savedConfig.Token != "" {
		t.Fatal("disconnect did not forget the HEC token")
	}
	if !metrics.Status().Enabled || !traces.Status().Enabled {
		t.Fatal("disconnecting logs changed Observability Cloud export")
	}
	if otlp.NewSplunkHECLogsExportController(savedConfig).Status().Connected {
		t.Fatal("disconnected state did not survive restart")
	}
	logsToggle(true, http.StatusConflict)
	beforeMasterEnable := service.snapshot().Version
	post("/api/splunk/export/enabled", map[string]any{"enabled": true, "expectedVersion": beforeMasterEnable}, http.StatusOK)
	if logs.Status().Enabled || savedConfig.Enabled || savedConfig.ConnectionVerified || service.snapshot().Version != beforeMasterEnable {
		t.Fatal("master enable revived disconnected logs or changed saved state")
	}
	connection["expectedVersion"] = logs.Status().Version
	connection["token"] = ""
	post("/api/splunk/logs", connection, http.StatusBadRequest)
	connection["token"] = "private-token"
	post("/api/splunk/logs", connection, http.StatusOK)
	logsToggle(true, http.StatusOK)
	post("/api/splunk/export/forget", map[string]any{}, http.StatusOK)
	if !logs.Status().Enabled || logs.Status().ExportedRecords != 1 {
		t.Fatal("reconnecting or removing Observability Cloud changed logs export or its counters")
	}
	post("/api/splunk/export/enabled", map[string]any{"enabled": true, "scope": "unknown"}, http.StatusBadRequest)
}

func TestSplunkLogsInvalidPausedConnectionDoesNotPersistEnable(t *testing.T) {
	for _, enabled := range []bool{true, false} {
		t.Run(fmt.Sprint(enabled), func(t *testing.T) {
			controller := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{
				Endpoint: "logs.example/services/collector", Token: "private-token", Index: "studio", ConnectionVerified: true,
			})
			defer controller.Shutdown(context.Background())
			before := controller.Status()
			if !before.Connected || before.Enabled {
				t.Fatal("test requires a restored verified paused connection")
			}
			var saved []otlp.SplunkHECLogsExporterConfig
			mux := http.NewServeMux()
			registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: controller, Save: func(config otlp.SplunkHECLogsExporterConfig) error {
				saved = append(saved, config)
				return nil
			}}, nil)
			body, _ := json.Marshal(map[string]any{"enabled": enabled, "expectedVersion": before.Version})
			response := splunkExportRequest(t, mux, "POST", "/api/splunk/logs/enabled", string(body))
			if enabled {
				if len(saved) != 0 || controller.Config().Enabled || controller.Status().Version != before.Version {
					t.Fatal("failed enable changed the saved or running configuration")
				}
				if response.Code != http.StatusBadRequest {
					t.Fatalf("invalid saved configuration: %d %s", response.Code, response.Body)
				}
			} else if response.Code != http.StatusOK || len(saved) != 1 || saved[0].Enabled || controller.Status().Enabled {
				t.Fatalf("pausing invalid configuration must remain available: %d %s", response.Code, response.Body)
			}
		})
	}
}

func TestSplunkLogsVerifiedPausedConnectionSurvivesRestart(t *testing.T) {
	controller := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{
		Endpoint: "https://logs.example/services/collector", Token: "private-token", Index: "studio", ConnectionVerified: true,
	})
	if !controller.Status().Connected || controller.Status().Enabled || controller.Status().LastExportSuccess != "" {
		t.Fatal("restored paused connection must stay connected without current-session exports")
	}
	mux := http.NewServeMux()
	registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: controller, Save: func(otlp.SplunkHECLogsExporterConfig) error { return nil }}, nil)
	body, _ := json.Marshal(map[string]any{"enabled": true, "expectedVersion": controller.Status().Version})
	response := splunkExportRequest(t, mux, "POST", "/api/splunk/logs/enabled", string(body))
	if response.Code != http.StatusOK || !controller.Status().Enabled || !controller.Status().Connected {
		t.Fatalf("resume restored connection: %d %s", response.Code, response.Body)
	}
	request := httptest.NewRequest("POST", "http://localhost/api/splunk/logs/disconnect", strings.NewReader(`{}`))
	request.RemoteAddr = "127.0.0.1:1234"
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Origin", "https://evil.example")
	request.Header.Set("X-Obstudio-Browser-Request", "1")
	response = httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	if response.Code != http.StatusForbidden || !controller.Status().Connected {
		t.Fatal("cross-origin disconnect was accepted")
	}
}

func TestSplunkLogsInlineEditRetainsQueueActivityAndExportPreference(t *testing.T) {
	for _, enabled := range []bool{false, true} {
		t.Run(fmt.Sprint(enabled), func(t *testing.T) {
			var accepted atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "Splunk replacement" {
					w.WriteHeader(401)
					_, _ = w.Write([]byte(`{"code":4}`))
					return
				}
				accepted.Add(1)
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			config := otlp.SplunkHECLogsExporterConfig{Endpoint: remote.URL + "/services/collector", Token: "original", Index: "studio", Enabled: enabled, ConnectionVerified: true}
			logs := otlp.NewSplunkHECLogsExportController(config)
			defer logs.Shutdown(context.Background())
			payload := plog.NewLogs()
			payload.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty().LogRecords().AppendEmpty().Body().SetStr("queued application log")
			_ = logs.ExportLogs(context.Background(), payload)
			before := logs.Status()
			var saved otlp.SplunkHECLogsExporterConfig
			mux := http.NewServeMux()
			registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: logs, Save: func(c otlp.SplunkHECLogsExporterConfig) error { saved = c; return nil }}, nil)
			request := map[string]any{"endpoint": config.Endpoint, "token": "bad-candidate", "index": "studio", "enabled": !enabled, "preserveEnabled": true, "verifyConnection": true, "expectedVersion": before.Version}
			post := func(code int) {
				t.Helper()
				body, _ := json.Marshal(request)
				response := splunkExportRequest(t, mux, "POST", "/api/splunk/logs", string(body))
				if response.Code != code {
					t.Fatalf("%d %s", response.Code, response.Body)
				}
				if strings.Contains(response.Body.String(), "replacement") {
					t.Fatal("response exposed token")
				}
			}
			post(502)
			if current := logs.Status(); current.Version != before.Version || current.QueuedRecords != 1 || current.Enabled != enabled || logs.Config().Token != "original" {
				t.Fatalf("failed edit changed saved connection %+v", current)
			}
			request["token"] = "replacement"
			post(200)
			if logs.Status().Enabled != enabled || saved.Enabled != enabled || !saved.ConnectionVerified {
				t.Fatal("edit did not preserve export preference")
			}
			deadline := time.Now().Add(3 * time.Second)
			for enabled && logs.Status().QueuedRecords > 0 && time.Now().Before(deadline) {
				time.Sleep(time.Millisecond)
			}
			got := logs.Status()
			if enabled {
				if got.QueuedRecords != 0 || got.ExportedRecords != 2 || got.FailedBatches != before.FailedBatches || accepted.Load() != 2 {
					t.Fatalf("queue recovery lost activity %+v", got)
				}
			} else if got.QueuedRecords != 1 || got.ExportedRecords != 1 || accepted.Load() != 1 {
				t.Fatalf("paused edit drained queue %+v", got)
			}
		})
	}
}

func TestSplunkLogsUnverifiedEditDoesNotReusePreviousConnectionSuccess(t *testing.T) {
	for _, field := range []string{"endpoint", "token", "index", "insecureSkipVerify", "source"} {
		t.Run(field, func(t *testing.T) {
			var requests atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{})
			defer logs.Shutdown(context.Background())
			mux := http.NewServeMux()
			registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: logs, Save: func(otlp.SplunkHECLogsExporterConfig) error { return nil }}, nil)
			settings := map[string]any{"endpoint": remote.URL + "/services/collector", "token": "original", "index": "studio", "source": "otel", "enabled": false, "verifyConnection": true, "expectedVersion": logs.Status().Version}
			post := func(path string, body any, code int) {
				t.Helper()
				encoded, _ := json.Marshal(body)
				response := splunkExportRequest(t, mux, "POST", path, string(encoded))
				if response.Code != code {
					t.Fatalf("%s: %d %s", path, response.Code, response.Body)
				}
			}
			post("/api/splunk/logs", settings, http.StatusOK)
			if !logs.Status().Connected || logs.Status().LastExportSuccess == "" {
				t.Fatal("initial connection was not verified")
			}
			settings["expectedVersion"] = logs.Status().Version
			settings["verifyConnection"], settings["preserveEnabled"] = false, true
			switch field {
			case "endpoint":
				settings[field] = remote.URL + "/services/collector/event"
			case "insecureSkipVerify":
				settings[field] = true
			default:
				settings[field] = "replacement"
			}
			post("/api/splunk/logs", settings, http.StatusOK)
			status := logs.Status()
			if status.ExportedRecords != 1 || requests.Load() != 1 || status.Enabled {
				t.Fatalf("unverified edit changed activity or sent a probe: %+v, requests %d", status, requests.Load())
			}
			if field == "source" {
				if !status.Connected || status.LastExportSuccess == "" {
					t.Fatal("source-only edit discarded a valid connection")
				}
				return
			}
			if logs.Config().ConnectionVerified || status.Connected || status.LastExportSuccess != "" {
				t.Fatalf("changed destination inherited the previous verification: %+v", status)
			}
			post("/api/splunk/logs/enabled", map[string]any{"enabled": true, "expectedVersion": status.Version}, http.StatusConflict)
		})
	}
}

func TestSplunkLogsUpstreamEndToEndDualDeliveryAndRecovery(t *testing.T) {
	var expectedToken atomic.Value
	expectedToken.Store("initial")
	var accepted atomic.Int32
	var receivedMu sync.Mutex
	received := map[string]int{}
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Splunk "+expectedToken.Load().(string) {
			w.WriteHeader(401)
			_, _ = w.Write([]byte(`{"code":4}`))
			return
		}
		if r.URL.Path != "/services/collector" || r.Header.Get("X-Splunk-Request-Channel") == "" || r.Header.Get("Content-Encoding") != "gzip" || r.Header.Get("__splunk_app_name") != "OpenTelemetry Collector Contrib" {
			t.Error("upstream HEC request missing endpoint, channel or compression")
		}
		reader, err := gzip.NewReader(r.Body)
		if err != nil {
			t.Error(err)
			return
		}
		defer reader.Close()
		decoder := json.NewDecoder(reader)
		for {
			var event struct {
				Index string
				Event string
			}
			err := decoder.Decode(&event)
			if err == io.EOF {
				break
			}
			if err != nil {
				t.Error(err)
				return
			}
			if event.Index != "studio" {
				t.Errorf("unexpected index: %s", event.Index)
			}
			receivedMu.Lock()
			received[event.Event]++
			receivedMu.Unlock()
			accepted.Add(1)
		}
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	freeAddr := func() string {
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		addr := ln.Addr().String()
		_ = ln.Close()
		return addr
	}
	local := store.New()
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{})
	defer logs.Shutdown(context.Background())
	var httpAddr, grpcAddr string
	var receiver *otlp.Receiver
	var err error
	// Port discovery releases the listener. Retry only if another listener
	// acquires a selected port before the receiver binds it.
	for range 5 {
		httpAddr, grpcAddr = freeAddr(), freeAddr()
		receiver, err = otlp.StartReceiver(context.Background(), local, grpcAddr, httpAddr, otlp.WithLogsExporter(logs))
		if err == nil || !errors.Is(err, syscall.EADDRINUSE) {
			break
		}
	}
	if err != nil {
		t.Fatal(err)
	}
	defer receiver.Shutdown(context.Background())
	file := filepath.Join(t.TempDir(), "logs-settings.json")
	mux := http.NewServeMux()
	Register(mux, local, SplunkLogsSettings{Controller: logs, Save: func(c otlp.SplunkHECLogsExporterConfig) error {
		b, err := json.Marshal(c)
		if err != nil {
			return err
		}
		return os.WriteFile(file, b, 0600)
	}})
	server := httptest.NewServer(mux)
	defer server.Close()
	post := func(path string, body any, expected int) {
		t.Helper()
		b, _ := json.Marshal(body)
		req, _ := http.NewRequest("POST", server.URL+path, bytes.NewReader(b))
		req.Header.Set("Origin", server.URL)
		req.Header.Set(splunkBrowserRequestHeader, "1")
		req.Header.Set("Content-Type", "application/json")
		response, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		data, _ := io.ReadAll(response.Body)
		if response.StatusCode != expected {
			t.Fatalf("%s: %d %s", path, response.StatusCode, data)
		}
	}
	toggle := func(enabled bool) {
		post("/api/splunk/logs/enabled", map[string]any{"enabled": enabled, "expectedVersion": logs.Status().Version}, 200)
	}
	connect := func(token string, preserve bool, expected int) {
		post("/api/splunk/logs", map[string]any{"endpoint": remote.URL + "/services/collector", "token": token, "index": "studio", "enabled": false, "verifyConnection": true, "preserveEnabled": preserve, "expectedVersion": logs.Status().Version}, expected)
	}
	makeLogs := func(body string) plog.Logs {
		data := plog.NewLogs()
		rl := data.ResourceLogs().AppendEmpty()
		rl.Resource().Attributes().PutStr("service.name", "upstream-e2e")
		rl.ScopeLogs().AppendEmpty().LogRecords().AppendEmpty().Body().SetStr(body)
		return data
	}
	ingest := func(body string) {
		t.Helper()
		request := plogotlp.NewExportRequestFromLogs(makeLogs(body))
		data, err := request.MarshalJSON()
		if err != nil {
			t.Fatal(err)
		}
		response, err := http.Post("http://"+httpAddr+"/v1/logs", "application/json", bytes.NewReader(data))
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		if response.StatusCode != 200 {
			b, _ := io.ReadAll(response.Body)
			t.Fatalf("OTLP ingest: %d %s", response.StatusCode, b)
		}
	}
	wait := func(check func(otlp.SplunkHECLogsExportStatus) bool) {
		t.Helper()
		deadline := time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			if check(logs.Status()) {
				return
			}
			time.Sleep(5 * time.Millisecond)
		}
		t.Fatalf("export did not settle: %+v", logs.Status())
	}
	ingest("before connection")
	connect("incorrect", false, 502)
	if logs.Status().Connected || logs.Status().ExportedRecords != 0 {
		t.Fatal("rejected probe established a connection")
	}
	connect("initial", false, 200)
	if s := logs.Status(); !s.Connected || s.Enabled || s.QueuedRecords != 1 {
		t.Fatalf("verified paused connection: %+v", s)
	}
	toggle(true)
	ingest("http live")
	conn, err := grpc.NewClient(grpcAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, err := plogotlp.NewGRPCClient(conn).Export(ctx, plogotlp.NewExportRequestFromLogs(makeLogs("grpc live"))); err != nil {
		t.Fatal(err)
	}
	wait(func(s otlp.SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 4 && s.QueuedRecords == 0 })
	toggle(false)
	ingest("paused")
	if accepted.Load() != 4 || logs.Status().QueuedRecords != 1 {
		t.Fatal("paused export sent a log or lost its queue")
	}
	expectedToken.Store("replacement")
	toggle(true)
	wait(func(s otlp.SplunkHECLogsExportStatus) bool { return s.LastHTTPStatus == 401 && s.QueuedRecords == 1 })
	connect("replacement", true, 200)
	wait(func(s otlp.SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 6 && s.QueuedRecords == 0 })
	post("/api/splunk/logs/disconnect", map[string]any{"expectedVersion": logs.Status().Version}, 200)
	ingest("after disconnect")
	if s := logs.Status(); s.Connected || s.Enabled || s.QueuedRecords != 1 {
		t.Fatalf("disconnect did not preserve local-only ingest: %+v", s)
	}
	for _, body := range []string{"before connection", "http live", "grpc live", "paused", "after disconnect"} {
		if len(local.QueryLogsFiltered("upstream-e2e", "", body, "", 100)) != 1 {
			t.Fatalf("missing or duplicate local log: %s", body)
		}
	}
	receivedMu.Lock()
	defer receivedMu.Unlock()
	for _, body := range []string{"before connection", "http live", "grpc live", "paused"} {
		if received[body] != 1 {
			t.Fatalf("missing or duplicate HEC log: %s count=%d", body, received[body])
		}
	}
	if received["after disconnect"] != 0 {
		t.Fatal("disconnected export forwarded a log")
	}
	data, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	var saved otlp.SplunkHECLogsExporterConfig
	if err := json.Unmarshal(data, &saved); err != nil {
		t.Fatal(err)
	}
	if saved.Enabled || saved.ConnectionVerified || saved.Token != "" {
		t.Fatal("disconnect did not persist settings")
	}
}

func TestSplunkSharedExportCanPauseInvalidRestoredLogs(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{Endpoint: "missing-scheme/services/collector", Token: "private-token", Index: "studio", Enabled: true, ConnectionVerified: true})
	defer logs.Shutdown(context.Background())
	var saved *otlp.SplunkHECLogsExporterConfig
	service := newTestSplunkExportService(metrics, traces, nil)
	service.logs = SplunkLogsSettings{Controller: logs, Save: func(c otlp.SplunkHECLogsExporterConfig) error { saved = &c; return nil }}
	mux := http.NewServeMux()
	service.register(mux)
	data, _ := json.Marshal(map[string]any{"enabled": false, "expectedVersion": service.snapshot().Version})
	response := splunkExportRequest(t, mux, "POST", "/api/splunk/export/enabled", string(data))
	if response.Code != 200 || saved == nil || saved.Enabled || logs.Config().Enabled {
		t.Fatalf("invalid restored logs could not be paused: %d %s", response.Code, response.Body)
	}
}

func TestSplunkSharedEnableRollsBackWhenLogsControllerStops(t *testing.T) {
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: testSplunkAccessToken})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: testSplunkAccessToken})
	defer metrics.Shutdown(context.Background())
	defer traces.Shutdown(context.Background())
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "test", Index: "studio", ConnectionVerified: true})
	defer logs.Shutdown(context.Background())
	var saved []otlp.SplunkHECLogsExporterConfig
	service := newTestSplunkExportService(metrics, traces, nil)
	service.logs = SplunkLogsSettings{Controller: logs, Save: func(config otlp.SplunkHECLogsExporterConfig) error {
		saved = append(saved, config)
		if len(saved) == 1 {
			logs.Shutdown(context.Background())
		}
		return nil
	}}
	mux := http.NewServeMux()
	service.register(mux)
	body, _ := json.Marshal(map[string]any{"enabled": true, "expectedVersion": service.snapshot().Version})
	response := splunkExportRequest(t, mux, "POST", "/api/splunk/export/enabled", string(body))
	if response.Code != http.StatusInternalServerError {
		t.Fatalf("stopped controller: %d %s", response.Code, response.Body)
	}
	if metrics.Config().Enabled || traces.Config().Enabled || len(saved) != 2 || saved[1].Enabled || !saved[1].ConnectionVerified {
		t.Fatalf("failed enable changed cloud or persisted logs preferences: metrics=%v traces=%v saved=%+v", metrics.Config().Enabled, traces.Config().Enabled, saved)
	}
}

func TestSplunkLogsToggleRollsBackSavedStateWhenControllerStops(t *testing.T) {
	for _, enabled := range []bool{false, true} {
		for _, rollbackFails := range []bool{false, true} {
			t.Run(fmt.Sprintf("enable=%t/rollback-fails=%t", enabled, rollbackFails), func(t *testing.T) {
				controller := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{
					Endpoint: "https://logs.example/services/collector", Token: "private-token", Index: "studio", Enabled: !enabled, ConnectionVerified: true,
				})
				defer controller.Shutdown(context.Background())
				previous := controller.Config()
				stored := previous
				var saves []otlp.SplunkHECLogsExporterConfig
				mux := http.NewServeMux()
				registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: controller, Save: func(config otlp.SplunkHECLogsExporterConfig) error {
					saves = append(saves, config)
					if len(saves) == 1 {
						controller.Shutdown(context.Background())
					}
					if len(saves) == 2 && rollbackFails {
						return errors.New("could not save private-token")
					}
					stored = config
					return nil
				}}, nil)
				body, _ := json.Marshal(map[string]any{"enabled": enabled, "expectedVersion": controller.Status().Version})
				response := splunkExportRequest(t, mux, "POST", "/api/splunk/logs/enabled", string(body))
				if response.Code != http.StatusInternalServerError || len(saves) != 2 || saves[1] != previous {
					t.Fatalf("failed toggle did not restore saved settings: %d %s, saves=%+v", response.Code, response.Body, saves)
				}
				if rollbackFails {
					if stored.Enabled != enabled || !strings.Contains(response.Body.String(), "restore") {
						t.Fatalf("rollback failure was not reported: %d %s", response.Code, response.Body)
					}
				} else if stored != previous {
					t.Fatal("failed toggle changed persisted preferences")
				}
				if strings.Contains(response.Body.String(), "private-token") {
					t.Fatal("rollback error exposed credentials")
				}
			})
		}
	}
}
