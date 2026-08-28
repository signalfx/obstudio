package main

import (
	"encoding/base64"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
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

func TestEnsureObserverCloudBrowserSigningKeyPreservesConfiguredKey(t *testing.T) {
	configured := strings.Repeat("A", 43)
	t.Setenv(observerCloudBrowserSigningKeyEnv, configured)

	if err := ensureObserverCloudBrowserSigningKey(); err != nil {
		t.Fatalf("ensureObserverCloudBrowserSigningKey() error = %v", err)
	}
	if got := os.Getenv(observerCloudBrowserSigningKeyEnv); got != configured {
		t.Fatalf("%s = %q, want configured key", observerCloudBrowserSigningKeyEnv, got)
	}
}

func TestEnsureObserverCloudBrowserSigningKeyGeneratesKey(t *testing.T) {
	t.Setenv(observerCloudBrowserSigningKeyEnv, "")

	if err := ensureObserverCloudBrowserSigningKeyAt(filepath.Join(t.TempDir(), "browser-key")); err != nil {
		t.Fatalf("ensureObserverCloudBrowserSigningKeyAt() error = %v", err)
	}
	if got := os.Getenv(observerCloudBrowserSigningKeyEnv); !regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`).MatchString(got) {
		t.Fatalf("%s = %q, want a 32-byte base64url key", observerCloudBrowserSigningKeyEnv, got)
	}
}

func TestEnsureObserverCloudBrowserSigningKeyPersistsAcrossRestarts(t *testing.T) {
	keyPath := filepath.Join(t.TempDir(), "browser-key")
	t.Setenv(observerCloudBrowserSigningKeyEnv, "")

	if err := ensureObserverCloudBrowserSigningKeyAt(keyPath); err != nil {
		t.Fatalf("first ensureObserverCloudBrowserSigningKeyAt() error = %v", err)
	}
	first := os.Getenv(observerCloudBrowserSigningKeyEnv)
	if first == "" {
		t.Fatal("first browser signing key is empty")
	}

	t.Setenv(observerCloudBrowserSigningKeyEnv, "")
	if err := ensureObserverCloudBrowserSigningKeyAt(keyPath); err != nil {
		t.Fatalf("second ensureObserverCloudBrowserSigningKeyAt() error = %v", err)
	}
	if got := os.Getenv(observerCloudBrowserSigningKeyEnv); got != first {
		t.Fatalf("browser signing key after restart = %q, want persisted key %q", got, first)
	}
	info, err := os.Stat(keyPath)
	if err != nil {
		t.Fatalf("stat browser signing key: %v", err)
	}
	if mode := info.Mode().Perm(); mode != 0o600 {
		t.Fatalf("browser signing key mode = %#o, want 0600", mode)
	}
}

func TestPersistObserverCloudBrowserSigningKeyHasOneConcurrentWinner(t *testing.T) {
	keyPath := filepath.Join(t.TempDir(), "browser-key")
	const writers = 16
	start := make(chan struct{})
	results := make(chan error, writers)
	keys := make(map[string]struct{}, writers)
	var waitGroup sync.WaitGroup
	for index := 0; index < writers; index++ {
		raw := make([]byte, 32)
		for position := range raw {
			raw[position] = byte(index + 1)
		}
		key := base64.RawURLEncoding.EncodeToString(raw)
		keys[key] = struct{}{}
		waitGroup.Add(1)
		go func() {
			defer waitGroup.Done()
			<-start
			results <- persistObserverCloudBrowserSigningKey(keyPath, key)
		}()
	}
	close(start)
	waitGroup.Wait()
	close(results)

	succeeded := 0
	alreadyExists := 0
	for err := range results {
		switch {
		case err == nil:
			succeeded++
		case errors.Is(err, os.ErrExist):
			alreadyExists++
		default:
			t.Fatalf("persistObserverCloudBrowserSigningKey() error = %v", err)
		}
	}
	if succeeded != 1 || alreadyExists != writers-1 {
		t.Fatalf("concurrent results = %d succeeded, %d existing; want 1 and %d", succeeded, alreadyExists, writers-1)
	}
	persisted, err := os.ReadFile(keyPath)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := keys[strings.TrimSpace(string(persisted))]; !ok {
		t.Fatal("persisted browser signing key was incomplete or unexpected")
	}
}

func TestEnsureObserverCloudBrowserSigningKeyRejectsInvalidConfiguredKey(t *testing.T) {
	t.Setenv(observerCloudBrowserSigningKeyEnv, "not-a-32-byte-base64url-key")

	if err := ensureObserverCloudBrowserSigningKey(); err == nil {
		t.Fatal("ensureObserverCloudBrowserSigningKey() error = nil, want invalid-key error")
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
	signingKey := strings.Repeat("A", 43)
	launchToken := strings.Repeat("B", 43)
	t.Setenv(observerCloudBrowserSigningKeyEnv, signingKey)
	t.Setenv(observerCloudBrowserLaunchTokenEnv, launchToken)

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
			name:    "non-loopback",
			address: "192.0.2.10:3000",
			wantURL: "http://192.0.2.10:3000",
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			if got := observerBrowserURL(test.address); got != test.wantURL {
				t.Fatalf("observerBrowserURL(%q) = %q, want %q", test.address, got, test.wantURL)
			}
			if strings.Contains(observerBrowserURL(test.address), signingKey) {
				t.Fatalf("observerBrowserURL(%q) exposed the persisted browser signing key", test.address)
			}
		})
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
