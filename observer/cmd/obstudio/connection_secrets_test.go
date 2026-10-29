package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/credentials"
	"github.com/signalfx/obstudio/observer/internal/otlp"
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

func TestConnectionSecretsSaveAndRestoreIndependently(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "env")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newConnectionPersistence(path, vault)
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud-test-secret", Enabled: true}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metrics.AccessToken, Enabled: true}
	logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://hec.example/services/collector", Index: "studio", Token: "logs-test-secret", ConnectionVerified: true}
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	if err := settings.SaveLogs(logs); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), metrics.AccessToken) || strings.Contains(string(data), logs.Token) {
		t.Fatal("settings exposed a token")
	}
	for key, value := range mustReadConnectionValues(t, path) {
		t.Setenv(key, value)
	}
	restoredMetrics, err := splunkMetricsExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	restoredTraces, err := splunkTracesExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	restoredLogs, err := splunkHECLogsExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	reloaded := newConnectionPersistence(path, vault)
	cloudErr, logsErr := reloaded.Restore(&restoredMetrics, &restoredTraces, &restoredLogs)
	if cloudErr != nil || logsErr != nil || restoredMetrics.AccessToken != metrics.AccessToken || restoredTraces.AccessToken != traces.AccessToken || restoredLogs.Token != logs.Token {
		t.Fatal("secure connections did not restore")
	}
	if !restoredMetrics.Enabled || restoredLogs.Enabled {
		t.Fatal("independent export preferences were not restored")
	}
	// A destination edit cannot retrieve the token for the saved destination.
	restoredLogs.Endpoint = "https://other.example/services/collector"
	_, logsErr = reloaded.Restore(&restoredMetrics, &restoredTraces, &restoredLogs)
	if logsErr == nil || restoredLogs.Token != "" || restoredLogs.Enabled || restoredMetrics.AccessToken != metrics.AccessToken {
		t.Fatal("credential failure was not isolated to logs")
	}
	if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
		t.Fatal(err)
	}
	values := mustReadConnectionValues(t, path)
	if values[cloudSecretRef] != "" || values[logsSecretRef] == "" {
		t.Fatal("disconnect changed the other connection")
	}
	// A rollback can restore the previous connection after disconnect.
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
}

func mustReadConnectionValues(t *testing.T, path string) map[string]string {
	t.Helper()
	values, err := readEnvFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return values
}

func TestSecureSaveFailurePreservesSettingsAndPreviousToken(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "env")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newConnectionPersistence(path, vault)
	logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://hec.example/services/collector", Token: "first-secret", Index: "studio"}
	if err := settings.SaveLogs(logs); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(path)
	backend.fail = true
	logs.Token = "replacement-secret"
	if err := settings.SaveLogs(logs); !errors.Is(err, credentials.ErrUnavailable) {
		t.Fatal("unavailable vault accepted a save")
	}
	after, _ := os.ReadFile(path)
	if string(after) != string(before) {
		t.Fatal("failed secure save changed settings")
	}
	backend.fail = false
	broken := newConnectionPersistence(path, vault)
	broken.path = filepath.Join(path, "not-a-directory")
	if err := broken.SaveLogs(logs); err == nil {
		t.Fatal("unwritable settings accepted a save")
	}
	logs.Token = ""
	metrics, traces := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
	_, err := newConnectionPersistence(path, vault).Restore(&metrics, &traces, &logs)
	if err != nil || logs.Token != "first-secret" {
		t.Fatal("failed save replaced saved credential")
	}
}

func TestSecureSettingsRefreshRemainsEditableAndRespectsLaunchToken(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "env")
	vault := credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}})
	settings := newConnectionPersistence(path, vault)
	metricsConfig := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "saved-cloud-token"}
	tracesConfig := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metricsConfig.AccessToken}
	if err := settings.SaveCloud(metricsConfig, tracesConfig); err != nil {
		t.Fatal(err)
	}
	metrics := &recordingMetricsExportConfigurator{}
	traces := &recordingTracesExportConfigurator{}
	managed, err := newSplunkExportConfigurationRefresher(path, metrics, traces, settings)()
	if err != nil || managed || metrics.Config().AccessToken != metricsConfig.AccessToken || traces.Config().AccessToken != metricsConfig.AccessToken {
		t.Fatal("secure settings did not refresh as an editable connection")
	}
	markEnvFileShellPrecedence("SPLUNK_ACCESS_TOKEN")
	t.Setenv("SPLUNK_ACCESS_TOKEN", "launch-token")
	metricsConfig.AccessToken = "launch-token"
	tracesConfig.AccessToken = "launch-token"
	logs := otlp.SplunkHECLogsExporterConfig{}
	cloudErr, _ := settings.Restore(&metricsConfig, &tracesConfig, &logs)
	if cloudErr != nil || metricsConfig.AccessToken != "launch-token" {
		t.Fatal("explicit launch credential lost precedence")
	}
	managed, err = newSplunkExportConfigurationRefresher(path, metrics, traces, settings)()
	if err != nil || !managed || metrics.Config().AccessToken != "launch-token" {
		t.Fatal("refresh replaced the explicit launch credential")
	}
	if err := settings.SaveCloud(metricsConfig, tracesConfig); err == nil {
		t.Fatal("save overwrote launch-controlled settings")
	}
}

func TestLogsDisconnectForgetsSecureTokenAndPreservesCloud(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "env")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newConnectionPersistence(path, vault)
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud-test-token", Enabled: true}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metrics.AccessToken, Enabled: true}
	logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://hec.example/services/collector", Index: "studio", Token: "hec-test-token", ConnectionVerified: true}
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	if err := settings.SaveLogs(logs); err != nil {
		t.Fatal(err)
	}
	previous := mustReadConnectionValues(t, path)
	logs.Token, logs.Enabled, logs.ConnectionVerified = "", false, false
	if err := settings.SaveLogs(logs); err != nil {
		t.Fatal(err)
	}
	values := mustReadConnectionValues(t, path)
	if values[logsSecretRef] != "" || values[cloudSecretRef] != previous[cloudSecretRef] {
		t.Fatal("disconnect did not remove only the logs credential reference")
	}
	if _, err := vault.Get(settings.path, "logs", logs.Endpoint, previous[logsSecretRef]); !errors.Is(err, credentials.ErrNotFound) {
		t.Fatal("HEC token remains in secure storage")
	}
	if len(backend.values) != 1 {
		t.Fatal("disconnect changed the unrelated cloud credential")
	}
	if values["OBSTUDIO_SPLUNK_HEC_URL"] != logs.Endpoint || values["OBSTUDIO_SPLUNK_LOGS_INDEX"] != logs.Index {
		t.Fatal("disconnect lost destination fields")
	}
	reloaded := newConnectionPersistence(path, vault)
	cloudErr, logsErr := reloaded.Restore(&metrics, &traces, &logs)
	if cloudErr != nil || logsErr != nil || logs.Token != "" || metrics.AccessToken != "cloud-test-token" {
		t.Fatal("restart restored a forgotten token or changed the cloud connection")
	}
}

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
