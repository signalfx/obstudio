package main

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/credentials"
	"github.com/signalfx/obstudio/observer/internal/otlp"
)

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
