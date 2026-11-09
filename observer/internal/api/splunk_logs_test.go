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
	"runtime"
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
			fastRemote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"code":0}`)) }))
			defer fastRemote.Close()
			config := otlp.SplunkHECLogsExporterConfig{}
			if operation != "probe" {
				config = otlp.SplunkHECLogsExporterConfig{Endpoint: remote.URL + "/services/collector", Token: "test", Index: "studio", Enabled: true, ConnectionVerified: true, Timeout: time.Minute}
			}
			logs := otlp.NewSplunkHECLogsExportController(config)
			defer logs.Shutdown(context.Background())
			defer unblock()
			metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
			traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
			mux := http.NewServeMux()
			Register(mux, store.New(), metrics, traces, SplunkLogsSettings{Controller: logs, Save: func(otlp.SplunkHECLogsExporterConfig) error { close(saved); return nil }})
			if operation != "probe" {
				payload := plog.NewLogs()
				payload.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty().LogRecords().AppendEmpty().Body().SetStr("in flight")
				logs.QueueLogs(payload)
				select {
				case <-started:
				case <-time.After(2 * time.Second):
					t.Fatal("log export did not reach the HEC endpoint")
				}
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
			ready := saved
			if operation == "probe" {
				ready = started
			}
			select {
			case <-ready:
			case response := <-done:
				t.Fatalf("mutation finished before the expected probe or save: %d %s", response.Code, response.Body)
			case <-time.After(2 * time.Second):
				t.Fatal("mutation did not reach the expected probe or save")
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
	var releaseOnce sync.Once
	unblock := func() { releaseOnce.Do(func() { close(release) }) }
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started)
		<-release
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{})
	defer logs.Shutdown(context.Background())
	defer unblock()
	var saves atomic.Int32
	mux := http.NewServeMux()
	Register(mux, store.New(), SplunkLogsSettings{Controller: logs, Save: func(otlp.SplunkHECLogsExporterConfig) error { saves.Add(1); return nil }})
	body, _ := json.Marshal(map[string]any{"endpoint": remote.URL + "/services/collector", "token": "test", "index": "studio", "enabled": false, "verifyConnection": true, "expectedVersion": logs.Status().Version})
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() { done <- splunkExportRequest(t, mux, "POST", "/api/splunk/logs", string(body)) }()
	select {
	case <-started:
	case response := <-done:
		t.Fatalf("mutation finished before its probe: %d %s", response.Code, response.Body)
	case <-time.After(2 * time.Second):
		t.Fatal("connection probe did not reach HEC")
	}
	if err := logs.SetEnabled(false); err != nil {
		t.Fatal(err)
	}
	unblock()
	select {
	case response := <-done:
		if response.Code != 409 || saves.Load() != 0 || logs.Status().Configured {
			t.Fatalf("stale probe committed: %d %s", response.Code, response.Body)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("mutation did not finish after its probe")
	}
}

func TestSplunkConnectionProbesDoNotBlockOtherDestinationPause(t *testing.T) {
	for _, probing := range []string{"logs", "cloud"} {
		t.Run(probing, func(t *testing.T) {
			started, release := make(chan struct{}), make(chan struct{})
			var once sync.Once
			unblock := func() { once.Do(func() { close(release) }) }
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				close(started)
				<-release
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			defer unblock()
			metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud", Enabled: true})
			traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "cloud", Enabled: true})
			defer metrics.Shutdown(context.Background())
			defer traces.Shutdown(context.Background())
			logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{Endpoint: remote.URL + "/services/collector", Token: "logs", Index: "studio", Enabled: true, ConnectionVerified: true})
			defer logs.Shutdown(context.Background())
			settings := SplunkLogsSettings{Controller: logs, Save: func(otlp.SplunkHECLogsExporterConfig) error { return nil }}
			service := newTestSplunkExportService(metrics, traces, nil)
			service.logs = settings
			if probing == "cloud" {
				service.verifyConnection = func(context.Context, string, string) error { close(started); <-release; return nil }
			}
			mux := http.NewServeMux()
			service.register(mux)
			registerSplunkLogs(mux, store.New(), settings)
			probePath, pausePath := "/api/splunk/logs", "/api/splunk/export/enabled"
			probeBody := map[string]any{"endpoint": logs.Config().Endpoint, "token": "replacement", "index": "studio", "verifyConnection": true, "enabled": true, "expectedVersion": logs.Status().Version}
			pauseVersion := service.snapshot().CloudVersion
			if probing == "cloud" {
				probePath, pausePath = "/api/splunk/export", "/api/splunk/logs/enabled"
				probeBody = map[string]any{"realm": "us1", "accessToken": "replacement", "enabled": true, "expectedVersion": service.snapshot().CloudVersion}
				pauseVersion = logs.Status().Version
			}
			probeJSON, _ := json.Marshal(probeBody)
			probeDone := make(chan *httptest.ResponseRecorder, 1)
			go func() { probeDone <- splunkExportRequest(t, mux, "POST", probePath, string(probeJSON)) }()
			select {
			case <-started:
			case <-time.After(time.Second):
				t.Fatal("connection probe did not start")
			}
			pauseDone := make(chan *httptest.ResponseRecorder, 1)
			go func() {
				pauseDone <- splunkExportRequest(t, mux, "POST", pausePath, fmt.Sprintf(`{"enabled":false,"expectedVersion":%q}`, pauseVersion))
			}()
			select {
			case response := <-pauseDone:
				if response.Code != 200 || probing == "logs" && (metrics.Status().Enabled || traces.Status().Enabled) || probing == "cloud" && logs.Status().Enabled {
					t.Fatal("independent pause failed", response.Code, response.Body.String())
				}
			case <-time.After(time.Second):
				t.Fatal("connection probe blocked the other destination's pause")
			}
			unblock()
			select {
			case response := <-probeDone:
				if response.Code != 200 {
					t.Fatal("unrelated pause invalidated the probe", response.Code, response.Body.String())
				}
			case <-time.After(time.Second):
				t.Fatal("probe did not finish")
			}
		})
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
	cleanupPending := false
	var savedConfig otlp.SplunkHECLogsExporterConfig
	settings := SplunkLogsSettings{Controller: logs, Save: func(config otlp.SplunkHECLogsExporterConfig) error {
		if diskError {
			return errors.New("disk unavailable")
		}
		savedConfig = config
		if cleanupPending {
			return ErrConnectionCleanupPending
		}
		return nil
	}}
	service := newTestSplunkExportService(metrics, traces, nil)
	service.logs = settings
	mux := http.NewServeMux()
	service.register(mux)
	local := store.New()
	registerSplunkLogs(mux, local, settings)
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
		post("/api/splunk/export/enabled", map[string]any{"enabled": enabled, "expectedVersion": service.snapshot().Version}, code)
	}
	logsToggle := func(enabled bool, code int) {
		t.Helper()
		post("/api/splunk/logs/enabled", map[string]any{"enabled": enabled, "expectedVersion": logs.Status().Version}, code)
	}
	cloudToggle(true, http.StatusConflict)
	logsToggle(true, http.StatusConflict)
	post("/api/splunk/export", map[string]any{"realm": "us1", "accessToken": testSplunkAccessToken}, http.StatusOK)
	cloudToggle(true, http.StatusOK)
	cloudVersion := service.snapshot().CloudVersion
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
	if service.snapshot().CloudVersion != cloudVersion {
		t.Fatal("logs changes altered the Cloud configuration version")
	}
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
	cleanupPending = true
	post("/api/splunk/logs/disconnect", map[string]any{"expectedVersion": logs.Status().Version}, http.StatusInternalServerError)
	cleanupPending = false
	if logs.Status().Connected || logs.Status().Enabled || savedConfig.ConnectionVerified || savedConfig.Enabled {
		t.Fatal("disconnect did not clear connection verification and stop forwarding")
	}
	if logs.Status().TokenConfigured || logs.Config().Token != "" || savedConfig.Token != "" {
		t.Fatal("disconnect did not forget the HEC token")
	}
	if !metrics.Status().Enabled || !traces.Status().Enabled {
		t.Fatal("disconnecting logs changed Observability Cloud export")
	}
	restored := otlp.NewSplunkHECLogsExportController(savedConfig)
	t.Cleanup(func() { restored.Shutdown(context.Background()) })
	if restored.Status().Connected {
		t.Fatal("disconnected state did not survive restart")
	}
	logsToggle(true, http.StatusConflict)
	beforeCloudEnable := service.snapshot().Version
	post("/api/splunk/export/enabled", map[string]any{"enabled": true, "expectedVersion": beforeCloudEnable}, http.StatusOK)
	if logs.Status().Enabled || savedConfig.Enabled || savedConfig.ConnectionVerified || service.snapshot().Version != beforeCloudEnable {
		t.Fatal("Cloud enable changed the independent logs connection")
	}
	connection["expectedVersion"] = logs.Status().Version
	connection["token"] = ""
	post("/api/splunk/logs", connection, http.StatusBadRequest)
	connection["token"] = "private-token"
	post("/api/splunk/logs", connection, http.StatusOK)
	logsToggle(true, http.StatusOK)
	for _, operation := range []string{"save", "toggle", "disconnect"} {
		rollbackToken := strings.Repeat("b", 43)
		response := splunkExportRequestWithRollbackToken(t, mux, "POST", "/api/splunk/export/enabled", `{"enabled":false}`, rollbackToken)
		if response.Code != http.StatusOK || metrics.Status().Enabled || traces.Status().Enabled {
			t.Fatal("Cloud pause failed")
		}
		switch operation {
		case "save":
			connection["expectedVersion"], connection["preserveEnabled"], connection["index"] = logs.Status().Version, true, "updated"
			post("/api/splunk/logs", connection, http.StatusOK)
		case "toggle":
			logsToggle(false, http.StatusOK)
		case "disconnect":
			post("/api/splunk/logs/disconnect", map[string]any{"expectedVersion": logs.Status().Version}, http.StatusOK)
		}
		logsAfter := logs.Config()
		post("/api/splunk/export/rollback", map[string]any{"rollbackToken": rollbackToken}, http.StatusOK)
		if !metrics.Status().Enabled || !traces.Status().Enabled || logs.Config() != logsAfter {
			t.Fatal("Cloud rollback changed the independent logs state after", operation)
		}
	}
	delete(connection, "preserveEnabled")
	connection["expectedVersion"], connection["enabled"] = logs.Status().Version, true
	post("/api/splunk/logs", connection, http.StatusOK)
	post("/api/splunk/export/forget", map[string]any{}, http.StatusOK)
	if !logs.Status().Enabled || logs.Status().ExportedRecords != 1 {
		t.Fatal("reconnecting or removing Observability Cloud changed logs export or its counters")
	}
	current := service.snapshot()
	if current.Enabled || current.Connected || current.Logs == nil || !current.Logs.Enabled || current.Logs.ExportedItems != 1 {
		t.Fatal("status mixed the independent destination states")
	}
}

func TestSplunkLogsRequiresTLSForRemoteEndpoints(t *testing.T) {
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{})
	defer logs.Shutdown(context.Background())
	var saves atomic.Int32
	mux := http.NewServeMux()
	Register(mux, store.New(), SplunkLogsSettings{Controller: logs, Save: func(otlp.SplunkHECLogsExporterConfig) error { saves.Add(1); return nil }})
	for _, insecure := range []bool{false, true} {
		body, _ := json.Marshal(map[string]any{"endpoint": "http://hec.example:8088/services/collector", "token": "test-token", "index": "studio", "insecureSkipVerify": insecure, "expectedVersion": logs.Status().Version})
		response := splunkExportRequest(t, mux, "POST", "/api/splunk/logs", string(body))
		if response.Code != 400 || !strings.Contains(response.Body.String(), "HTTPS") || saves.Load() != 0 || logs.Status().TokenConfigured {
			t.Fatal("unsafe endpoint was not rejected before saving", response.Code, response.Body.String())
		}
	}
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
			}})

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
	registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: controller, Save: func(otlp.SplunkHECLogsExporterConfig) error { return nil }})
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

func TestSplunkLogsInlineEditPreservesExportPreferenceAndActivity(t *testing.T) {
	for _, enabled := range []bool{false, true} {
		t.Run(fmt.Sprint(enabled), func(t *testing.T) {
			var accepted atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") == "Splunk bad-candidate" {
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
			payload.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty().LogRecords().AppendEmpty().Body().SetStr("application log")
			if err := logs.ExportLogs(context.Background(), payload); err != nil {
				t.Fatal(err)
			}
			wait := func(count uint64) {
				t.Helper()
				deadline := time.Now().Add(3 * time.Second)
				for logs.Status().ExportedRecords != count {
					if time.Now().After(deadline) {
						t.Fatal("delivery", logs.Status())
					}
					time.Sleep(time.Millisecond)
				}
			}
			beforeCount := uint64(0)
			if enabled {
				beforeCount = 1
				wait(beforeCount)
			}
			before := logs.Status()
			var saved otlp.SplunkHECLogsExporterConfig
			mux := http.NewServeMux()
			registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: logs, Save: func(c otlp.SplunkHECLogsExporterConfig) error { saved = c; return nil }})
			request := map[string]any{"endpoint": config.Endpoint, "token": "bad-candidate", "index": "studio", "enabled": !enabled, "preserveEnabled": true, "verifyConnection": true, "expectedVersion": before.Version}
			post := func(code int) {
				t.Helper()
				body, _ := json.Marshal(request)
				response := splunkExportRequest(t, mux, "POST", "/api/splunk/logs", string(body))
				if response.Code != code {
					t.Fatal(response.Code, response.Body.String())
				}
			}
			post(502)
			if current := logs.Status(); current.Version != before.Version || current.Enabled != enabled || current.ExportedRecords != beforeCount || logs.Config().Token != "original" {
				t.Fatal("failed edit changed connection", current)
			}
			request["token"] = "replacement"
			post(200)
			if logs.Status().Enabled != enabled || saved.Enabled != enabled || !saved.ConnectionVerified {
				t.Fatal("edit changed export preference")
			}
			wait(beforeCount + 1)
			if accepted.Load() != int32(beforeCount+1) {
				t.Fatal("unexpected remote records", accepted.Load())
			}
		})
	}
}

func TestSplunkLogsUnchangedSavePreservesNativeRetry(t *testing.T) {
	var attempts atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reader, err := gzip.NewReader(r.Body)
		if err != nil {
			t.Error(err)
			return
		}
		defer reader.Close()
		var event struct{ Event string }
		if err := json.NewDecoder(reader).Decode(&event); err != nil {
			t.Error(err)
			return
		}
		if event.Event == "pending application log" && attempts.Add(1) == 1 {
			w.Header().Set("Retry-After", "1")
			w.WriteHeader(503)
			_, _ = w.Write([]byte(`{"code":9}`))
			return
		}
		if event.Event == "new rejection" {
			w.WriteHeader(403)
			_, _ = w.Write([]byte(`{"code":4}`))
			return
		}
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	config := otlp.SplunkHECLogsExporterConfig{Endpoint: remote.URL + "/services/collector", Token: "test", Index: "studio", Source: "otel", Sourcetype: "otel:logs", Enabled: true, ConnectionVerified: true}
	logs := otlp.NewSplunkHECLogsExportController(config)
	defer logs.Shutdown(context.Background())
	payload := plog.NewLogs()
	payload.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty().LogRecords().AppendEmpty().Body().SetStr("pending application log")
	logs.QueueLogs(payload)
	wait := func(check func() bool) {
		t.Helper()
		deadline := time.Now().Add(12 * time.Second)
		for !check() {
			if time.Now().After(deadline) {
				t.Fatal("native retry did not settle", logs.Status(), attempts.Load())
			}
			time.Sleep(time.Millisecond)
		}
	}
	wait(func() bool { return logs.Status().LastHTTPStatus == 503 })
	mux := http.NewServeMux()
	registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: logs, Save: func(otlp.SplunkHECLogsExporterConfig) error { return nil }})
	request, _ := json.Marshal(map[string]any{"endpoint": config.Endpoint, "index": config.Index, "source": config.Source, "preserveEnabled": true, "verifyConnection": true, "expectedVersion": logs.Status().Version})
	response := splunkExportRequest(t, mux, "POST", "/api/splunk/logs", string(request))
	if response.Code != 200 {
		t.Fatal(response.Code, response.Body.String())
	}
	if logs.Status().LastExportSuccess == "" {
		t.Fatal("unchanged save lost the accepted connection probe")
	}
	if logs.Status().LastExportError != "" {
		t.Fatal("successful connection probe retained an earlier error", logs.Status())
	}
	later := plog.NewLogs()
	payload.CopyTo(later)
	later.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords().At(0).Body().SetStr("new rejection")
	logs.QueueLogs(later)
	wait(func() bool { return logs.Status().LastHTTPStatus == 403 })
	if logs.Status().LastExportError == "" {
		t.Fatal("a previous successful probe hid a newer delivery failure")
	}
	wait(func() bool { return logs.Status().ExportedRecords == 2 })
	if attempts.Load() != 2 || !logs.Status().Enabled {
		t.Fatal("unchanged save lost or duplicated the pending log", logs.Status(), attempts.Load())
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
			registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: logs, Save: func(otlp.SplunkHECLogsExporterConfig) error { return nil }})
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
	if s := logs.Status(); !s.Connected || s.Enabled || s.ExportedRecords != 1 {
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
	wait(func(s otlp.SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 3 })
	toggle(false)
	ingest("paused")
	if accepted.Load() != 3 {
		t.Fatal("paused export sent a log")
	}
	expectedToken.Store("replacement")
	toggle(true)
	ingest("rejected with old token")
	wait(func(s otlp.SplunkHECLogsExportStatus) bool { return s.LastHTTPStatus == 401 })
	connect("replacement", true, 200)
	ingest("after credential update")
	wait(func(s otlp.SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 5 })
	post("/api/splunk/logs/disconnect", map[string]any{"expectedVersion": logs.Status().Version}, 200)
	ingest("after disconnect")
	if s := logs.Status(); s.Connected || s.Enabled || s.ExportedRecords != 0 {
		t.Fatalf("disconnect did not preserve local-only ingest: %+v", s)
	}
	for _, body := range []string{"before connection", "http live", "grpc live", "paused", "rejected with old token", "after credential update", "after disconnect"} {
		if len(local.QueryLogsFiltered("upstream-e2e", "", body, "", 100)) != 1 {
			t.Fatalf("missing or duplicate local log: %s", body)
		}
	}
	receivedMu.Lock()
	defer receivedMu.Unlock()
	for _, body := range []string{"http live", "grpc live", "after credential update"} {
		if received[body] != 1 {
			t.Fatalf("missing or duplicate HEC log: %s count=%d", body, received[body])
		}
	}
	for _, body := range []string{"before connection", "paused", "rejected with old token", "after disconnect"} {
		if received[body] != 0 {
			t.Fatal("unexpected remote delivery", body, received[body])
		}
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
				}})

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

func TestLogsStaleSettingsReturnConflictWithoutChangingRuntime(t *testing.T) {
	for _, route := range []string{"configure", "enabled", "disconnect"} {
		t.Run(route, func(t *testing.T) {
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, _ = io.Copy(io.Discard, r.Body)
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			controller := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{Endpoint: remote.URL + "/services/collector", Token: "token", Index: "studio", Enabled: true, ConnectionVerified: true})
			defer controller.Shutdown(context.Background())
			mux := http.NewServeMux()
			registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: controller, Save: func(otlp.SplunkHECLogsExporterConfig) error { return ErrConnectionSettingsChanged }})
			path := "/api/splunk/logs"
			body := map[string]any{"expectedVersion": controller.Status().Version}
			if route == "configure" {
				body["endpoint"] = remote.URL + "/services/collector"
				body["token"] = "new-token"
				body["index"] = "studio"
			} else {
				path += "/" + route
			}
			if route == "enabled" {
				body["enabled"] = false
			}
			data, _ := json.Marshal(body)
			request := httptest.NewRequest(http.MethodPost, path, bytes.NewReader(data))
			request.RemoteAddr = "127.0.0.1:1234"
			request.Header.Set("Content-Type", "application/json")
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, request)
			if response.Code != http.StatusConflict || !strings.Contains(response.Body.String(), "changed in another session") {
				t.Fatal(response.Code, response.Body.String())
			}
			if !controller.Config().Enabled || controller.Config().Token != "token" {
				t.Fatal("stale settings changed the live controller")
			}
		})
	}
}

func TestLogsPauseDoesNotForgetUnavailableCredentials(t *testing.T) {
	controller := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Index: "studio"})
	defer controller.Shutdown(context.Background())
	saves := 0
	mux := http.NewServeMux()
	registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: controller, Save: func(otlp.SplunkHECLogsExporterConfig) error { saves++; return nil }})
	post := func(path string, enabled bool) *httptest.ResponseRecorder {
		body := map[string]any{"expectedVersion": controller.Status().Version}
		if enabled {
			body["enabled"] = false
		}
		data, _ := json.Marshal(body)
		request := httptest.NewRequest(http.MethodPost, path, bytes.NewReader(data))
		request.RemoteAddr = "127.0.0.1:1234"
		request.Header.Set("Content-Type", "application/json")
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, request)
		return response
	}
	response := post("/api/splunk/logs/enabled", true)
	if response.Code != 409 || saves != 0 {
		t.Fatal("pause reached credential removal", response.Code, response.Body.String())
	}
	response = post("/api/splunk/logs/disconnect", false)
	if response.Code != 200 || saves != 1 {
		t.Fatal("explicit disconnect was blocked", response.Code, response.Body.String())
	}
}

func TestLogsSessionConnectionDoesNotUsePersistence(t *testing.T) {
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	original := otlp.SplunkHECLogsExporterConfig{Endpoint: remote.URL + "/services/collector", Index: "studio", Token: "saved-token", ConnectionVerified: true}
	controller := otlp.NewSplunkHECLogsExportController(original)
	defer controller.Shutdown(context.Background())
	saves := 0
	refused := true
	saved := original
	mux := http.NewServeMux()
	registerSplunkLogs(mux, store.New(), SplunkLogsSettings{Controller: controller, Save: func(config otlp.SplunkHECLogsExporterConfig) error {
		saves++
		if refused {
			return ErrCredentialStorageUnavailable
		}
		saved = config
		return nil
	}, Refresh: func() error { t.Fatal("session Refresh accessed persistence"); return nil }, HasCredential: func() bool { return true }})
	request := func(path string, body map[string]any) *httptest.ResponseRecorder {
		if !strings.HasSuffix(path, "/refresh") {
			body["expectedVersion"] = controller.Status().Version
		}
		data, _ := json.Marshal(body)
		r := httptest.NewRequest("POST", path, bytes.NewReader(data))
		r.RemoteAddr = "127.0.0.1:1234"
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, r)
		return w
	}
	body := map[string]any{"endpoint": original.Endpoint, "token": "session-token", "index": "session-index", "verifyConnection": true, "enabled": true}
	response := request("/api/splunk/logs", body)
	if response.Code != 503 || !strings.Contains(response.Body.String(), `"code":"credential_storage_unavailable"`) || !strings.Contains(response.Body.String(), fmt.Sprintf(`"platform":%q`, runtime.GOOS)) || controller.Config().Token != original.Token {
		t.Fatal("refused save changed the connection", response.Body.String())
	}
	body["sessionOnly"] = true
	response = request("/api/splunk/logs", body)
	if response.Code != 200 || !controller.Status().SessionOnly || !controller.Status().Connected || saves != 1 || saved != original {
		t.Fatal("session connect used persistence", response.Body.String(), saves)
	}
	if strings.Contains(response.Body.String(), "session-token") {
		t.Fatal("status exposed token")
	}
	if response = request("/api/splunk/logs/refresh", map[string]any{}); response.Code != 200 || controller.Config().Token != "session-token" {
		t.Fatal("Refresh replaced session", response.Body.String())
	}
	for _, enabled := range []bool{false, true} {
		response = request("/api/splunk/logs/enabled", map[string]any{"enabled": enabled})
		if response.Code != 200 || controller.Status().Enabled != enabled || !controller.Status().SessionOnly || saves != 1 {
			t.Fatal("session toggle used persistence", response.Body.String())
		}
	}
	response = request("/api/splunk/logs/disconnect", map[string]any{})
	if response.Code != 200 || controller.Config().Token != "" || controller.Status().Connected || controller.Status().Enabled || saves != 1 || saved != original {
		t.Fatal("session Disconnect changed saved settings", response.Body.String())
	}
	refused = false
	body["sessionOnly"] = false
	response = request("/api/splunk/logs", body)
	if response.Code != 200 || controller.Status().SessionOnly || saved.Token != "session-token" || saves != 2 {
		t.Fatal("persistent save retained session mode", response.Body.String())
	}
}
