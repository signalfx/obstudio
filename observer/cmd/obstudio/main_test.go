package main

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func TestEnsureObserverControlTokenPreservesConfiguredToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "configured-control-token")

	if err := ensureObserverControlToken(); err != nil {
		t.Fatalf("ensureObserverControlToken() error = %v", err)
	}
	if got := os.Getenv("OBSTUDIO_CONTROL_TOKEN"); got != "configured-control-token" {
		t.Fatalf("OBSTUDIO_CONTROL_TOKEN = %q, want configured token", got)
	}
}

func TestEnsureObserverControlTokenGeneratesStateToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "")

	if err := ensureObserverControlToken(); err != nil {
		t.Fatalf("ensureObserverControlToken() error = %v", err)
	}
	if !regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`).MatchString(os.Getenv("OBSTUDIO_CONTROL_TOKEN")) {
		t.Fatalf("OBSTUDIO_CONTROL_TOKEN = %q, want a 32-byte base64url token", os.Getenv("OBSTUDIO_CONTROL_TOKEN"))
	}
	if state := buildSharedObserverState("127.0.0.1", "3000"); state.ControlToken != os.Getenv("OBSTUDIO_CONTROL_TOKEN") {
		t.Fatalf("shared observer state control token = %q, want generated token", state.ControlToken)
	}
}

func TestEnsureObserverCloudBrowserLaunchTokenReplacesInheritedValue(t *testing.T) {
	inherited := strings.Repeat("A", 43)
	t.Setenv(observerCloudBrowserLaunchTokenEnv, inherited)

	if err := ensureObserverCloudBrowserLaunchToken(); err != nil {
		t.Fatalf("ensureObserverCloudBrowserLaunchToken() error = %v", err)
	}
	got := os.Getenv(observerCloudBrowserLaunchTokenEnv)
	if got == inherited {
		t.Fatal("browser launch token reused an inherited value")
	}
	if !regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`).MatchString(got) {
		t.Fatalf("%s = %q, want a 32-byte base64url token", observerCloudBrowserLaunchTokenEnv, got)
	}
}

func TestObserverBrowserURLOnlyExposesEphemeralLaunchTokenOnLoopbackURL(t *testing.T) {
	launchToken := strings.Repeat("B", 43)
	t.Setenv(observerCloudBrowserLaunchTokenEnv, launchToken)
	t.Setenv(observerHideCloudBrowserLaunchTokenEnv, "")

	for _, test := range []struct {
		name    string
		address string
		wantURL string
	}{
		{
			name:    "loopback",
			address: "127.0.0.1:3000",
			wantURL: "http://127.0.0.1:3000/#obstudio-cloud-control=" + launchToken,
		},
		{
			name:    "wildcard",
			address: "0.0.0.0:3000",
			wantURL: "http://127.0.0.1:3000/#obstudio-cloud-control=" + launchToken,
		},
		{
			name:    "IPv6 wildcard",
			address: "[::]:3000",
			wantURL: "http://[::1]:3000/#obstudio-cloud-control=" + launchToken,
		},
		{
			name:    "non-loopback",
			address: "192.0.2.10:3000",
			wantURL: "http://192.0.2.10:3000",
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			if got := observerBrowserURL(test.address); got != test.wantURL {
				t.Fatalf("observerBrowserURL(%q) = %q, want %q", test.address, got, test.wantURL)
			}
		})
	}
}

func TestObserverBrowserURLCanHideLaunchTokenFromManagedProcessLogs(t *testing.T) {
	launchToken := strings.Repeat("B", 43)
	t.Setenv(observerCloudBrowserLaunchTokenEnv, launchToken)
	t.Setenv(observerHideCloudBrowserLaunchTokenEnv, "true")

	got := observerBrowserURL("127.0.0.1:3000")
	if got != "http://127.0.0.1:3000" {
		t.Fatalf("observerBrowserURL() = %q, want URL without launch token", got)
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
