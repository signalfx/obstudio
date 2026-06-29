package main

import (
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/o11yoauth"
	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func TestSplunkMetricsExporterConfigFromEnvDisabledByDefault(t *testing.T) {
	config, err := splunkMetricsExporterConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if config.Enabled {
		t.Fatal("expected Splunk metrics export disabled by default")
	}
}

func TestSplunkMetricsExporterConfigFromEnvUsesSplunkEnv(t *testing.T) {
	t.Setenv("OBSTUDIO_SPLUNK_METRICS_EXPORT", "true")
	t.Setenv("SPLUNK_REALM", "us1")
	t.Setenv("SPLUNK_ACCESS_TOKEN", "test-token")
	t.Setenv("OBSTUDIO_SPLUNK_METRICS_TIMEOUT", "7s")

	config, err := splunkMetricsExporterConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !config.Enabled {
		t.Fatal("expected Splunk metrics export enabled")
	}
	if config.Realm != "us1" {
		t.Fatalf("realm = %q, want us1", config.Realm)
	}
	if config.AccessToken != "test-token" {
		t.Fatal("expected access token from environment")
	}
	if config.Timeout != 7*time.Second {
		t.Fatalf("timeout = %s, want 7s", config.Timeout)
	}
}

func TestSplunkMetricsExporterConfigFromEnvUsesExplicitEndpoint(t *testing.T) {
	t.Setenv("SPLUNK_METRICS_EXPORT", "1")
	t.Setenv("OBSTUDIO_SPLUNK_METRICS_ENDPOINT", "https://example.test/v2/datapoint/otlp")
	t.Setenv("SPLUNK_ACCESS_TOKEN", "test-token")
	t.Setenv("OBSTUDIO_SPLUNK_METRICS_TIMEOUT", "3")

	config, err := splunkMetricsExporterConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !config.Enabled {
		t.Fatal("expected Splunk metrics export enabled")
	}
	if config.Endpoint != "https://example.test/v2/datapoint/otlp" {
		t.Fatalf("endpoint = %q", config.Endpoint)
	}
	if config.Timeout != 3*time.Second {
		t.Fatalf("timeout = %s, want 3s", config.Timeout)
	}
}

func TestSplunkMetricsExporterConfigFromEnvRejectsBadTimeout(t *testing.T) {
	t.Setenv("OBSTUDIO_SPLUNK_METRICS_TIMEOUT", "soon")

	if _, err := splunkMetricsExporterConfigFromEnv(); err == nil {
		t.Fatal("expected bad timeout error")
	}
}

func TestSplunkTracesExporterConfigFromEnvDisabledByDefault(t *testing.T) {
	config, err := splunkTracesExporterConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if config.Enabled {
		t.Fatal("expected Splunk traces export disabled by default")
	}
}

func TestSplunkTracesExporterConfigFromEnvUsesSplunkEnv(t *testing.T) {
	t.Setenv("OBSTUDIO_SPLUNK_TRACES_EXPORT", "true")
	t.Setenv("SPLUNK_REALM", "us1")
	t.Setenv("SPLUNK_ACCESS_TOKEN", "test-token")
	t.Setenv("OBSTUDIO_SPLUNK_TRACES_TIMEOUT", "7s")

	config, err := splunkTracesExporterConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !config.Enabled {
		t.Fatal("expected Splunk traces export enabled")
	}
	if config.Realm != "us1" {
		t.Fatalf("realm = %q, want us1", config.Realm)
	}
	if config.AccessToken != "test-token" {
		t.Fatal("expected access token from environment")
	}
	if config.Timeout != 7*time.Second {
		t.Fatalf("timeout = %s, want 7s", config.Timeout)
	}
}

func TestSplunkTracesExporterConfigFromEnvUsesExplicitEndpoint(t *testing.T) {
	t.Setenv("SPLUNK_TRACES_EXPORT", "1")
	t.Setenv("OBSTUDIO_SPLUNK_TRACES_ENDPOINT", "https://example.test/v2/trace/otlp")
	t.Setenv("SPLUNK_ACCESS_TOKEN", "test-token")
	t.Setenv("OBSTUDIO_SPLUNK_TRACES_TIMEOUT", "3")

	config, err := splunkTracesExporterConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !config.Enabled {
		t.Fatal("expected Splunk traces export enabled")
	}
	if config.Endpoint != "https://example.test/v2/trace/otlp" {
		t.Fatalf("endpoint = %q", config.Endpoint)
	}
	if config.Timeout != 3*time.Second {
		t.Fatalf("timeout = %s, want 3s", config.Timeout)
	}
}

func TestSplunkTracesExporterConfigFromEnvRejectsBadTimeout(t *testing.T) {
	t.Setenv("OBSTUDIO_SPLUNK_TRACES_TIMEOUT", "soon")

	if _, err := splunkTracesExporterConfigFromEnv(); err == nil {
		t.Fatal("expected bad timeout error")
	}
}

func TestStoredCloudConnectionConfiguresDisabledExporters(t *testing.T) {
	connection := o11yoauth.Connection{
		AccessToken: "stored-token",
		Endpoint:    "https://ingest.lab0.signalfx.com",
		Realm:       "lab0",
	}
	metrics := applyStoredCloudConnectionToMetrics(otlp.SplunkMetricsExporterConfig{}, connection)
	traces := applyStoredCloudConnectionToTraces(otlp.SplunkTracesExporterConfig{}, connection)

	if metrics.Enabled || traces.Enabled {
		t.Fatal("loading a stored connection must not enable export")
	}
	if metrics.AccessToken != "stored-token" || traces.AccessToken != "stored-token" {
		t.Fatal("stored access token was not applied to both exporters")
	}
	if metrics.Realm != "lab0" || traces.Realm != "lab0" {
		t.Fatal("stored realm was not applied to both exporters")
	}
	if metrics.Endpoint != connection.Endpoint || traces.Endpoint != connection.Endpoint {
		t.Fatal("stored endpoint was not applied to both exporters")
	}
}

func TestExplicitExporterCredentialsTakePrecedenceOverStoredConnection(t *testing.T) {
	connection := o11yoauth.Connection{
		AccessToken: "stored-token",
		Endpoint:    "https://ingest.lab0.signalfx.com",
		Realm:       "lab0",
	}
	metricsInput := otlp.SplunkMetricsExporterConfig{
		AccessToken: "environment-token",
		Endpoint:    "https://ingest.us1.signalfx.com",
		Realm:       "us1",
	}
	tracesInput := otlp.SplunkTracesExporterConfig{
		AccessToken: "environment-token",
		Endpoint:    "https://ingest.us1.signalfx.com",
		Realm:       "us1",
	}
	metrics := applyStoredCloudConnectionToMetrics(metricsInput, connection)
	traces := applyStoredCloudConnectionToTraces(tracesInput, connection)
	if metrics != metricsInput || traces != tracesInput {
		t.Fatalf("explicit exporter settings were changed: metrics=%+v traces=%+v", metrics, traces)
	}
}

func TestStoredCloudConnectionOnlyLoadsForStandaloneWithoutExplicitToken(t *testing.T) {
	if !shouldLoadStoredCloudConnection("standalone", "") {
		t.Fatal("standalone Observer should load its OS-keychain connection")
	}
	if shouldLoadStoredCloudConnection("extension", "") {
		t.Fatal("extension-managed Observer must wait for IDE SecretStorage restoration")
	}
	if shouldLoadStoredCloudConnection("standalone", "environment-token") {
		t.Fatal("explicit environment credentials must take precedence over the OS keychain")
	}
}
