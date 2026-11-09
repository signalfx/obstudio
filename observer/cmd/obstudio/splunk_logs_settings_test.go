package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/credentials"
	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func TestSystemLogsConnectionPersistenceLifecycle(t *testing.T) {
	if os.Getenv("OBSTUDIO_TEST_SYSTEM_KEYRING") != "1" {
		t.Skip("requires an unlocked OS credential store")
	}
	path := filepath.Join(t.TempDir(), "connections.json")
	vault := credentials.New()
	settings := newTestConnectionPersistence(t, path, vault)
	config := otlp.SplunkHECLogsExporterConfig{Enabled: true, ConnectionVerified: true,
		Endpoint: "https://logs.example.test:8088/services/collector", Index: "studio-native", Source: "otel", Sourcetype: "otel:logs", Token: "native-logs-test"}
	t.Cleanup(func() {
		if err := settings.SaveLogs(otlp.SplunkHECLogsExporterConfig{}); err != nil {
			t.Error("could not clean up native logs connection", err)
		}
	})
	if err := settings.SaveLogs(config); err != nil {
		t.Fatal(err)
	}
	values, err := readConnectionSettings(path)
	if err != nil {
		t.Fatal(err)
	}
	original := values[logsSecretRef]
	restore := func() {
		t.Helper()
		var restored otlp.SplunkHECLogsExporterConfig
		if err := newTestConnectionPersistence(t, path, credentials.New()).restoreLogs(&restored, nil, true); err != nil {
			t.Fatal(err)
		}
		if restored.Token != config.Token || restored.Enabled != config.Enabled || restored.ConnectionVerified != config.ConnectionVerified || restored.Endpoint != config.Endpoint || restored.Index != config.Index || restored.Source != config.Source {
			t.Fatal("restart changed the saved native logs connection")
		}
		data, err := os.ReadFile(path)
		if err != nil || strings.Contains(string(data), "native-logs-test") || strings.Contains(string(data), "native-logs-replacement") {
			t.Fatal("native logs token appeared in connection settings", err)
		}
	}
	restore()
	config.Enabled = false
	if err := settings.SaveLogsPreferences(config); err != nil {
		t.Fatal(err)
	}
	restore()
	config.Token = "native-logs-replacement"
	if err := settings.SaveLogs(config); err != nil {
		t.Fatal(err)
	}
	restore()
	if _, err := vault.Get(settings.path, "logs", config.Endpoint, original); !errors.Is(err, credentials.ErrNotFound) {
		t.Fatal("replaced native HEC credential remains available", err)
	}
	config.Token, config.ConnectionVerified = "", false
	if err := settings.SaveLogs(config); err != nil {
		t.Fatal(err)
	}
	restore()
	values, err = readConnectionSettings(path)
	if err != nil || values[logsSecretRef] != "" {
		t.Fatal("Disconnect retained a native HEC credential reference", err)
	}
}

func TestSaveLogsSettingsPreservesOtherConfigurationAndReloads(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	if err := writeConnectionSettings(path, map[string]string{"extraSetting": "preserved"}); err != nil {
		t.Fatal(err)
	}
	vault := credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}})
	persistence := newTestConnectionPersistence(t, path, vault)
	config := otlp.SplunkHECLogsExporterConfig{Enabled: true, ConnectionVerified: true, Endpoint: "https://logs.example/services/collector", Token: "new-secret", Index: "studio", Source: `service "orders"\prod`, Sourcetype: "otel:logs"}
	if err := persistence.SaveLogs(config); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), config.Token) {
		t.Fatal("connection settings exposed a token")
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0600 {
		t.Fatalf("mode %o", info.Mode().Perm())
	}
	values, err := readConnectionSettings(path)
	if err != nil {
		t.Fatal(err)
	}
	if values["logsSource"] != config.Source || values[logsSecretRef] == "" {
		t.Fatal("settings did not round-trip")
	}
	if values["logsVerified"] != "true" {
		t.Fatal("verified connection did not persist")
	}
	if values["extraSetting"] != "preserved" {
		t.Fatal("save replaced unrelated settings")
	}
	restored := otlp.SplunkHECLogsExporterConfig{}
	metrics, traces := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
	_, restoreErr := newTestConnectionPersistence(t, path, vault).Restore(&metrics, &traces, &restored)
	if restoreErr != nil || restored.Token != config.Token {
		t.Fatal("saved credential did not restore")
	}
	controller := otlp.NewSplunkHECLogsExportController(restored)
	t.Cleanup(func() { controller.Shutdown(context.Background()) })
	if !controller.Status().Connected {
		t.Fatal("saved connection did not restore as connected")
	}
}
