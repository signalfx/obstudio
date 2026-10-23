package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func TestSaveLogsSettingsPreservesOtherConfigurationAndReloads(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "env")
	original := "# my settings\nSPLUNK_ACCESS_TOKEN=unrelated-cloud-token\nOTHER_SETTING=preserved\nOBSTUDIO_SPLUNK_HEC_TOKEN=old\nOBSTUDIO_SPLUNK_HEC_TOKEN=duplicate\n"
	if err := os.WriteFile(path, []byte(original), 0644); err != nil {
		t.Fatal(err)
	}
	config := otlp.SplunkHECLogsExporterConfig{Enabled: true, Endpoint: "https://logs.example/services/collector", Token: "new-secret", Index: "studio", Source: `service "orders"\prod`, Sourcetype: "otel:logs"}
	if err := newSplunkLogsSettingsSaver(path)(config); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "# my settings\nSPLUNK_ACCESS_TOKEN=unrelated-cloud-token\nOTHER_SETTING=preserved\n") || strings.Count(string(data), "OBSTUDIO_SPLUNK_HEC_TOKEN=") != 1 {
		t.Fatal("unrelated settings changed or duplicate retained")
	}
	info, _ := os.Stat(path)
	if info.Mode().Perm() != 0600 {
		t.Fatalf("mode %o", info.Mode().Perm())
	}
	values, err := readEnvFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if values["OBSTUDIO_SPLUNK_LOGS_SOURCE"] != config.Source || values["OBSTUDIO_SPLUNK_HEC_TOKEN"] != config.Token {
		t.Fatal("settings did not round-trip")
	}
	before := string(data)
	markEnvFileShellPrecedence("OBSTUDIO_SPLUNK_HEC_TOKEN")
	if err := newSplunkLogsSettingsSaver(path)(config); err == nil {
		t.Fatal("shell-controlled settings overwritten")
	}
	after, _ := os.ReadFile(path)
	if string(after) != before {
		t.Fatal("failed save changed file")
	}
}
