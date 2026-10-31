package main

import (
	"errors"
	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/credentials"
	"github.com/signalfx/obstudio/observer/internal/otlp"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type testCredentialBackend struct {
	values map[string]string
	fail   bool
}

func (b *testCredentialBackend) Get(key string) (string, error) {
	if b.fail {
		return "", credentials.ErrUnavailable
	}
	value, ok := b.values[key]
	if !ok {
		return "", credentials.ErrNotFound
	}
	return value, nil
}
func (b *testCredentialBackend) Set(key, value string) error {
	if b.fail {
		return credentials.ErrUnavailable
	}
	b.values[key] = value
	return nil
}
func (b *testCredentialBackend) Delete(key string) error { delete(b.values, key); return nil }

func TestCloudSecureSettingsSaveRestoreAndDisconnect(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "env")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newConnectionPersistence(path, vault)
	for _, enabled := range []bool{false, true} {
		metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud-test-token", Enabled: enabled}
		traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metrics.AccessToken, Enabled: enabled}
		if err := settings.SaveCloud(metrics, traces); err != nil {
			t.Fatal(err)
		}
		data, err := os.ReadFile(path)
		if err != nil || strings.Contains(string(data), metrics.AccessToken) {
			t.Fatal("settings must contain only a token reference", err)
		}
		values, err := readEnvFile(path)
		if err != nil {
			t.Fatal(err)
		}
		restoredMetrics, _ := splunkMetricsExporterConfigFromValues(values)
		restoredTraces, _ := splunkTracesExporterConfigFromValues(values)
		reloaded := newConnectionPersistence(path, vault)
		if err := reloaded.RestoreCloud(&restoredMetrics, &restoredTraces); err != nil {
			t.Fatal(err)
		}
		if restoredMetrics.AccessToken != metrics.AccessToken || restoredTraces.AccessToken != traces.AccessToken || restoredMetrics.Enabled != enabled || restoredTraces.Enabled != enabled {
			t.Fatal("restart changed credentials or export state")
		}
		before := string(data)
		backend.fail = true
		metrics.AccessToken, traces.AccessToken = "replacement", "replacement"
		if err := settings.SaveCloud(metrics, traces); !errors.Is(err, credentials.ErrUnavailable) {
			t.Fatal("failed secure storage accepted a save")
		}
		data, _ = os.ReadFile(path)
		if string(data) != before {
			t.Fatal("failed secure save changed persisted settings")
		}
		if err := reloaded.RestoreCloud(&restoredMetrics, &restoredTraces); err == nil || restoredMetrics.Enabled || restoredTraces.Enabled || restoredMetrics.AccessToken != "" {
			t.Fatal("unavailable secure storage must pause export")
		}
		backend.fail = false
		restoredMetrics.Realm, restoredTraces.Realm = "eu0", "eu0"
		if err := reloaded.RestoreCloud(&restoredMetrics, &restoredTraces); err == nil {
			t.Fatal("another destination read the saved token")
		}
		if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
			t.Fatal(err)
		}
		if len(backend.values) != 0 || !settings.CloudStorageManaged() {
			t.Fatal("disconnect must delete its token and retain the migration marker")
		}
	}
}

func TestCloudSecureSaveIdentifiesLaunchControlledSettings(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	markEnvFileShellPrecedence("SPLUNK_METRICS_EXPORT")
	backend := &testCredentialBackend{values: map[string]string{}}
	path := filepath.Join(t.TempDir(), "env")
	settings := newConnectionPersistence(path, credentials.NewWithBackend(backend))
	err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "test-token"}, otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "test-token"})
	if !errors.Is(err, api.ErrSplunkCloudLaunchControlled) || len(backend.values) != 0 {
		t.Fatal("launch ownership was not preserved and classified", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("failed save wrote settings", err)
	}
}
