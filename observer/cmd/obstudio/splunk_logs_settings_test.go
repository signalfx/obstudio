package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/credentials"
	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func TestSaveLogsSettingsPreservesOtherConfigurationAndReloads(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "env")
	original := "# my settings\nSPLUNK_ACCESS_TOKEN=unrelated-cloud-token\nOTHER_SETTING=preserved\nOBSTUDIO_SPLUNK_HEC_TOKEN=old\nOBSTUDIO_SPLUNK_HEC_TOKEN=duplicate\n"
	if err := os.WriteFile(path, []byte(original), 0644); err != nil {
		t.Fatal(err)
	}
	vault := credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}})
	persistence := newConnectionPersistence(path, vault)
	config := otlp.SplunkHECLogsExporterConfig{Enabled: true, ConnectionVerified: true, Endpoint: "https://logs.example/services/collector", Token: "new-secret", Index: "studio", Source: `service "orders"\prod`, Sourcetype: "otel:logs"}
	if err := persistence.SaveLogs(config); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "# my settings\nSPLUNK_ACCESS_TOKEN=unrelated-cloud-token\nOTHER_SETTING=preserved\n") || strings.Contains(string(data), config.Token) || strings.Contains(string(data), "OBSTUDIO_SPLUNK_HEC_TOKEN=") {
		t.Fatal("unrelated settings changed or duplicate retained")
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0600 {
		t.Fatalf("mode %o", info.Mode().Perm())
	}
	values, err := readEnvFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if values["OBSTUDIO_SPLUNK_LOGS_SOURCE"] != config.Source || values[logsSecretRef] == "" {
		t.Fatal("settings did not round-trip")
	}
	if values["OBSTUDIO_SPLUNK_LOGS_VERIFIED"] != "true" {
		t.Fatal("verified connection did not persist")
	}
	for key, value := range values {
		t.Setenv(key, value)
	}
	restored, err := splunkHECLogsExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	metrics, traces := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
	_, restoreErr := newConnectionPersistence(path, vault).Restore(&metrics, &traces, &restored)
	if restoreErr != nil || restored.Token != config.Token || !otlp.NewSplunkHECLogsExportController(restored).Status().Connected {
		t.Fatal("saved connection did not restore as connected")
	}
	before := string(data)
	markEnvFileShellPrecedence("OBSTUDIO_SPLUNK_HEC_TOKEN")
	if err := persistence.SaveLogs(config); err == nil {
		t.Fatal("shell-controlled settings overwritten")
	}
	after, _ := os.ReadFile(path)
	if string(after) != before {
		t.Fatal("failed save changed file")
	}
}
