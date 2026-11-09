package main

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/credentials"
	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func TestRunServesConfigManagerAndSecureCloudConnection(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv(configManagerGateEnv, "true")
	t.Setenv("OBSTUDIO_OWNER", "cli")
	t.Setenv("OBSTUDIO_MODE", "standalone")
	t.Setenv("OBSTUDIO_SHARED_OBSERVER_STATE_PATH", filepath.Join(home, "shared.json"))
	settings := newTestConnectionPersistence(t, filepath.Join(home, ".obstudio", "connections.json"), credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}}))
	if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "connection-test-token"}, otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "connection-test-token"}); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	previousListen := listenObserverHTTP
	listenObserverHTTP = func(_, _ string) (net.Listener, error) { return listener, nil }
	done := make(chan error, 1)
	go func() {
		done <- run(runConfig{host: "127.0.0.1", observerHTTPPort: "0", otlpGRPCHost: "127.0.0.1", otlpGRPCPort: "0", otlpHTTPPort: "0", connectionSettings: settings})
	}()
	t.Cleanup(func() {
		_ = listener.Close()
		select {
		case <-done:
		case <-time.After(10 * time.Second):
			t.Error("collector did not stop")
		}
		listenObserverHTTP = previousListen
	})
	base := "http://" + listener.Addr().String()
	client := &http.Client{Timeout: time.Second}
	deadline := time.Now().Add(10 * time.Second)
	for {
		response, err := client.Get(base + "/api/health")
		if err == nil {
			_ = response.Body.Close()
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("collector did not start: %v", err)
		}
		time.Sleep(10 * time.Millisecond)
	}
	for _, path := range []string{"/api/config", "/api/config/status", "/api/splunk/export"} {
		response, err := client.Get(base + path)
		if err != nil {
			t.Fatal(err)
		}
		_ = response.Body.Close()
		if response.StatusCode != http.StatusOK {
			t.Fatalf("GET %s: status %d", path, response.StatusCode)
		}
	}
	response, err := client.Post(base+"/api/splunk/export/enabled", "application/json", strings.NewReader(`{"enabled":true}`))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(response.Body)
		t.Fatalf("save Cloud connection: status %d, %s", response.StatusCode, body)
	}
	var status struct{ Connected, StorageManaged bool }
	if err := json.NewDecoder(response.Body).Decode(&status); err != nil || !status.Connected || !status.StorageManaged {
		t.Fatalf("saved Cloud status: %+v, %v", status, err)
	}
	var metrics otlp.SplunkMetricsExporterConfig
	var traces otlp.SplunkTracesExporterConfig
	if err := settings.RestoreCloud(&metrics, &traces); err != nil || metrics.AccessToken != "connection-test-token" || traces.AccessToken != metrics.AccessToken || !metrics.Enabled || !traces.Enabled {
		t.Fatalf("Cloud export preference was not saved: %v", err)
	}
	response, err = client.Post(base+"/api/splunk/export/forget", "application/json", strings.NewReader(`{}`))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("disconnect Cloud connection: status %d", response.StatusCode)
	}
	if err := settings.RestoreCloud(&metrics, &traces); err != nil || metrics.AccessToken != "" || traces.AccessToken != "" {
		t.Fatalf("Cloud connection was not removed: %v", err)
	}
}

func TestStartupServesLocalTelemetryWhenBothCredentialReadsBlock(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(home, "connections.json"), credentials.NewWithBackend(backend))
	if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud-token", Enabled: true}, otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "cloud-token", Enabled: true}); err != nil {
		t.Fatal(err)
	}
	if err := settings.SaveLogs(otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "logs-token", Index: "studio", Enabled: true, ConnectionVerified: true}); err != nil {
		t.Fatal(err)
	}
	release := make(chan struct{})
	backend.readBlock = release
	otlpPort := strconv.Itoa(pickSmokePort(t))
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	previousListen := listenObserverHTTP
	listenObserverHTTP = func(_, _ string) (net.Listener, error) { return listener, nil }
	done := make(chan error, 1)
	t.Cleanup(func() {
		close(release)
		_ = listener.Close()
		select {
		case <-done:
		case <-time.After(10 * time.Second):
			t.Error("collector did not stop")
		}
		listenObserverHTTP = previousListen
	})
	go func() {
		done <- run(runConfig{host: "127.0.0.1", observerHTTPPort: "0", otlpGRPCHost: "127.0.0.1", otlpGRPCPort: "0", otlpHTTPPort: otlpPort, connectionSettings: settings})
	}()
	base := "http://" + listener.Addr().String()
	client := &http.Client{Timeout: 200 * time.Millisecond}
	deadline := time.Now().Add(7 * time.Second)
	for {
		response, err := client.Get(base + "/api/health")
		if err == nil {
			_ = response.Body.Close()
			if response.StatusCode != http.StatusOK {
				t.Fatalf("health status = %d", response.StatusCode)
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("blocked credential reads delayed the local listener: %v", err)
		}
	}
	for _, path := range []string{"/api/splunk/export", "/api/splunk/logs"} {
		response, err := client.Get(base + path)
		if err != nil {
			t.Fatal(err)
		}
		var status struct{ Connected, Enabled bool }
		decodeErr := json.NewDecoder(response.Body).Decode(&status)
		_ = response.Body.Close()
		if response.StatusCode != http.StatusOK || decodeErr != nil || status.Connected || status.Enabled {
			t.Fatalf("unavailable connection at %s was not paused: %+v, %v", path, status, decodeErr)
		}
	}
	response, err := client.Post("http://127.0.0.1:"+otlpPort+"/v1/logs", "application/json", strings.NewReader(`{"resourceLogs":[{"scopeLogs":[{"logRecords":[{"body":{"stringValue":"local ingestion while both credentials are blocked"}}]}]}]}`))
	if err != nil {
		t.Fatal(err)
	}
	_ = response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("local logs status = %d", response.StatusCode)
	}
	response, err = client.Get(base + "/api/query/stats")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	var stats struct{ LogCount int }
	if err := json.NewDecoder(response.Body).Decode(&stats); err != nil || response.StatusCode != http.StatusOK || stats.LogCount != 1 {
		t.Fatalf("local logs were not retained: %+v, %v", stats, err)
	}
}

func TestValidateRunConfigRejectsNonLoopbackObserverHost(t *testing.T) {
	t.Setenv("OBSTUDIO_MODE", "")
	t.Setenv(dockerRuntimeEvalAllowNonLoopbackBindEnv, "false")
	config := runConfig{
		host:             "0.0.0.0",
		observerHTTPPort: "3000",
		otlpGRPCHost:     "127.0.0.1",
		otlpGRPCPort:     "4317",
		otlpHTTPPort:     "4318",
	}
	if err := validateRunConfig(config); err == nil || !strings.Contains(err.Error(), "loopback") {
		t.Fatalf("validateRunConfig() = %v, want loopback error", err)
	}
}

func TestValidateRunConfigAllowsNonLoopbackObserverHostOnlyForDockerRuntimeEvals(t *testing.T) {
	t.Setenv("OBSTUDIO_MODE", "")
	config := runConfig{
		host:             "0.0.0.0",
		observerHTTPPort: "3000",
		otlpGRPCHost:     "127.0.0.1",
		otlpGRPCPort:     "4317",
		otlpHTTPPort:     "4318",
	}

	t.Setenv(dockerRuntimeEvalAllowNonLoopbackBindEnv, "true")
	if err := validateRunConfig(config); err == nil || !strings.Contains(err.Error(), "loopback") {
		t.Fatalf("validateRunConfig() without Docker eval mode = %v, want loopback error", err)
	}

	t.Setenv("OBSTUDIO_MODE", dockerRuntimeEvalMode)
	t.Setenv(dockerRuntimeEvalAllowNonLoopbackBindEnv, "false")
	if err := validateRunConfig(config); err == nil || !strings.Contains(err.Error(), "loopback") {
		t.Fatalf("validateRunConfig() without explicit Docker eval opt-in = %v, want loopback error", err)
	}

	t.Setenv(dockerRuntimeEvalAllowNonLoopbackBindEnv, "true")
	if err := validateRunConfig(config); err != nil {
		t.Fatalf("validateRunConfig() for explicit Docker runtime eval opt-in = %v", err)
	}
}

func TestValidateRunConfigRejectsNonLoopbackOTLPGRPCHost(t *testing.T) {
	config := runConfig{
		host:             "127.0.0.1",
		observerHTTPPort: "3000",
		otlpGRPCHost:     "0.0.0.0",
		otlpGRPCPort:     "4317",
		otlpHTTPPort:     "4318",
	}
	if err := validateRunConfig(config); err == nil || !strings.Contains(err.Error(), "loopback") {
		t.Fatalf("validateRunConfig() = %v, want OTLP/gRPC loopback error", err)
	}
}

func TestObserverBrowserURLContainsNoControlCredential(t *testing.T) {
	if got := observerBrowserURL("127.0.0.1:3000"); got != "http://127.0.0.1:3000" {
		t.Fatalf("observerBrowserURL() = %q, want credential-free local URL", got)
	}
}

func TestRenderStartupBannerUsesFullProductName(t *testing.T) {
	got := renderStartupBanner("127.0.0.1:3000", "127.0.0.1:4318", "127.0.0.1:4317")
	if !strings.HasPrefix(got, "\nSplunk Observability Studio (collector)\n") {
		t.Fatalf("renderStartupBanner() = %q, want full product name", got)
	}
}

func TestSplunkExportConfigurationRefreshKeepsUnchangedExporters(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}}))
	metrics := &recordingMetricsExportConfigurator{config: otlp.SplunkMetricsExporterConfig{Enabled: true, Realm: "us1", AccessToken: "configured-token", Timeout: 7 * time.Second}}
	traces := &recordingTracesExportConfigurator{config: otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "configured-token", Timeout: 8 * time.Second}}
	if err := settings.SaveCloud(metrics.config, traces.config); err != nil {
		t.Fatal(err)
	}
	if err := newSplunkExportConfigurationRefresher(metrics, traces, settings)(); err != nil {
		t.Fatal(err)
	}
	if metrics.configureCalls != 0 || traces.configureCalls != 0 {
		t.Fatal("unchanged settings reconfigured exporters")
	}
}

type recordingMetricsExportConfigurator struct {
	config         otlp.SplunkMetricsExporterConfig
	configureCalls int
}

func (c *recordingMetricsExportConfigurator) Config() otlp.SplunkMetricsExporterConfig {
	return c.config
}

func (c *recordingMetricsExportConfigurator) ConfigureKeepingActivity(config otlp.SplunkMetricsExporterConfig) error {
	c.configureCalls++
	c.config = config
	return nil
}

type recordingTracesExportConfigurator struct {
	config         otlp.SplunkTracesExporterConfig
	configureCalls int
}

func (c *recordingTracesExportConfigurator) Config() otlp.SplunkTracesExporterConfig {
	return c.config
}

func (c *recordingTracesExportConfigurator) ConfigureKeepingActivity(config otlp.SplunkTracesExporterConfig) error {
	c.configureCalls++
	c.config = config
	return nil
}
