package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

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
	envFile := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(envFile, []byte(strings.Join([]string{
		"SPLUNK_REALM=us1",
		"SPLUNK_ACCESS_TOKEN=configured-token",
		"SPLUNK_METRICS_EXPORT=true",
		"SPLUNK_TRACES_EXPORT=false",
	}, "\n")), 0o600); err != nil {
		t.Fatal(err)
	}
	metrics := &recordingMetricsExportConfigurator{config: otlp.SplunkMetricsExporterConfig{
		Enabled: true, Realm: "us1", AccessToken: "configured-token", Timeout: 7 * time.Second,
	}}
	traces := &recordingTracesExportConfigurator{config: otlp.SplunkTracesExporterConfig{
		Realm: "us1", AccessToken: "configured-token", Timeout: 8 * time.Second,
	}}

	managed, err := newSplunkExportConfigurationRefresher(envFile, metrics, traces)()
	if err != nil {
		t.Fatalf("refresh unchanged configuration: %v", err)
	}
	if !managed {
		t.Fatal("unchanged env-file configuration was not reported as managed")
	}
	if metrics.configureCalls != 0 || traces.configureCalls != 0 {
		t.Fatalf("unchanged exporters were reconfigured: metrics=%d traces=%d", metrics.configureCalls, traces.configureCalls)
	}
}

type recordingMetricsExportConfigurator struct {
	config         otlp.SplunkMetricsExporterConfig
	configureCalls int
}

func (c *recordingMetricsExportConfigurator) Config() otlp.SplunkMetricsExporterConfig {
	return c.config
}

func (c *recordingMetricsExportConfigurator) Configure(config otlp.SplunkMetricsExporterConfig) error {
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

func (c *recordingTracesExportConfigurator) Configure(config otlp.SplunkTracesExporterConfig) error {
	c.configureCalls++
	c.config = config
	return nil
}
