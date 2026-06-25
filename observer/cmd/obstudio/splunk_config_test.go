package main

import (
	"testing"
	"time"
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
