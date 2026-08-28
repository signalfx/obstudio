package main

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func resetEnvFileShellPrecedence(t *testing.T) {
	t.Helper()
	reset := func() {
		envFileShellPrecedence.Lock()
		defer envFileShellPrecedence.Unlock()
		envFileShellPrecedence.keys = map[string]struct{}{}
	}
	reset()
	t.Cleanup(reset)
}

func envFileShellPrecedenceContains(key string) bool {
	envFileShellPrecedence.Lock()
	defer envFileShellPrecedence.Unlock()
	_, ok := envFileShellPrecedence.keys[key]
	return ok
}

func TestLoadEnvFileParsesEnvSyntax(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
# comments and blank lines are ignored
OBSTUDIO_TEST_EXPORT=true
export OBSTUDIO_TEST_REALM=us1
OBSTUDIO_TEST_TOKEN="token with spaces"
OBSTUDIO_TEST_TIMEOUT='7s'
`), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	for _, key := range []string{"OBSTUDIO_TEST_EXPORT", "OBSTUDIO_TEST_REALM", "OBSTUDIO_TEST_TOKEN", "OBSTUDIO_TEST_TIMEOUT"} {
		_ = os.Unsetenv(key)
		t.Cleanup(func() {
			_ = os.Unsetenv(key)
		})
	}

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}

	if got := os.Getenv("OBSTUDIO_TEST_EXPORT"); got != "true" {
		t.Fatalf("OBSTUDIO_TEST_EXPORT = %q", got)
	}
	if got := os.Getenv("OBSTUDIO_TEST_REALM"); got != "us1" {
		t.Fatalf("OBSTUDIO_TEST_REALM = %q", got)
	}
	if got := os.Getenv("OBSTUDIO_TEST_TOKEN"); got != "token with spaces" {
		t.Fatalf("OBSTUDIO_TEST_TOKEN = %q", got)
	}
	if got := os.Getenv("OBSTUDIO_TEST_TIMEOUT"); got != "7s" {
		t.Fatalf("OBSTUDIO_TEST_TIMEOUT = %q", got)
	}
}

func TestLoadEnvFileDoesNotOverrideExistingEnv(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte("SPLUNK_REALM=from-file\n"), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	t.Setenv("SPLUNK_REALM", "from-shell")

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}
	if got := os.Getenv("SPLUNK_REALM"); got != "from-shell" {
		t.Fatalf("SPLUNK_REALM = %q, want from-shell", got)
	}
}

func TestLoadEnvFileDoesNotOverrideEmptyExistingEnv(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte("SPLUNK_ACCESS_TOKEN=from-file-token-123456\n"), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	t.Setenv("SPLUNK_ACCESS_TOKEN", "")

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}
	if got := os.Getenv("SPLUNK_ACCESS_TOKEN"); got != "" {
		t.Fatalf("SPLUNK_ACCESS_TOKEN = %q, want empty shell value", got)
	}
	if !envFileShellPrecedenceContains("SPLUNK_ACCESS_TOKEN") {
		t.Fatal("empty shell SPLUNK_ACCESS_TOKEN was not marked as shell precedence")
	}
}

func TestLoadEnvFileDoesNotMarkDuplicateFileKeysAsShellPrecedence(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=us0
SPLUNK_REALM=eu0
SPLUNK_ACCESS_TOKEN=first-token-123456
SPLUNK_ACCESS_TOKEN=second-token-123456
`), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	for _, key := range []string{"SPLUNK_REALM", "SPLUNK_ACCESS_TOKEN"} {
		key := key
		_ = os.Unsetenv(key)
		t.Cleanup(func() {
			_ = os.Unsetenv(key)
		})
	}

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}

	if got := os.Getenv("SPLUNK_REALM"); got != "us0" {
		t.Fatalf("SPLUNK_REALM = %q, want us0", got)
	}
	if got := os.Getenv("SPLUNK_ACCESS_TOKEN"); got != "first-token-123456" {
		t.Fatalf("SPLUNK_ACCESS_TOKEN = %q, want first-token-123456", got)
	}
	if envFileShellPrecedenceContains("SPLUNK_REALM") {
		t.Fatal("duplicate SPLUNK_REALM in the env file was marked as shell precedence")
	}
	if envFileShellPrecedenceContains("SPLUNK_ACCESS_TOKEN") {
		t.Fatal("duplicate SPLUNK_ACCESS_TOKEN in the env file was marked as shell precedence")
	}
}

func TestSplunkExportConfigurationRefresherPreservesShellEnvOverEnvFile(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=us2
SPLUNK_ACCESS_TOKEN=env-file-token-123456
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
`), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"SPLUNK_ACCESS_TOKEN", "OBSTUDIO_SPLUNK_METRICS_EXPORT"} {
		key := key
		t.Cleanup(func() {
			_ = os.Unsetenv(key)
		})
	}
	t.Setenv("SPLUNK_REALM", "us1")
	t.Setenv("SPLUNK_ACCESS_TOKEN", "shell-token-123456")

	if err := loadConfiguredEnvFile(path); err != nil {
		t.Fatal(err)
	}

	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	refresh := newSplunkExportConfigurationRefresher(path, metrics, traces)
	if applied := mustRefresh(t, refresh); !applied {
		t.Fatal("expected env file refresh to apply")
	}

	if got := metrics.Config(); !got.Enabled || got.Realm != "us1" || got.AccessToken != "shell-token-123456" {
		t.Fatalf("metrics config = %+v", got)
	}
	if got := traces.Config(); got.Enabled || got.Realm != "us1" || got.AccessToken != "shell-token-123456" {
		t.Fatalf("traces config = %+v", got)
	}

	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=eu0
SPLUNK_ACCESS_TOKEN=env-file-token-654321
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
`), 0o600); err != nil {
		t.Fatal(err)
	}
	if applied := mustRefresh(t, refresh); !applied {
		t.Fatal("expected env file refresh to apply")
	}
	if got := metrics.Config(); got.Realm != "us1" || got.AccessToken != "shell-token-123456" {
		t.Fatalf("reloaded metrics config = %+v", got)
	}
}

func TestReadEnvFileKeepsFirstDuplicateValue(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=us0
SPLUNK_REALM=eu0
SPLUNK_ACCESS_TOKEN=first-token-123456
SPLUNK_ACCESS_TOKEN=second-token-123456
`), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}

	values, err := readEnvFile(path)
	if err != nil {
		t.Fatal(err)
	}

	if got := values["SPLUNK_REALM"]; got != "us0" {
		t.Fatalf("SPLUNK_REALM = %q, want us0", got)
	}
	if got := values["SPLUNK_ACCESS_TOKEN"]; got != "first-token-123456" {
		t.Fatalf("SPLUNK_ACCESS_TOKEN = %q, want first-token-123456", got)
	}
}

func TestLoadConfiguredEnvFileIgnoresMissingDefault(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("OBSTUDIO_ENV_FILE", "")

	if err := loadConfiguredEnvFile(""); err != nil {
		t.Fatalf("missing default env file should be ignored: %v", err)
	}
}

func TestLoadConfiguredEnvFileErrorsForMissingExplicitPath(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.env")

	if err := loadConfiguredEnvFile(path); err == nil {
		t.Fatal("expected missing explicit env file to fail")
	}
}

func TestParseEnvLineRejectsInvalidLine(t *testing.T) {
	if _, _, _, err := parseEnvLine("SPLUNK_REALM"); err == nil {
		t.Fatal("expected parse error")
	}
}

func TestSplunkExportConfigurationRefresherLoadsEnvFileWithoutChangingEnvironment(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=us2
SPLUNK_ACCESS_TOKEN=env-file-token-123456
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
`), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SPLUNK_REALM", "shell-realm")
	t.Setenv("SPLUNK_ACCESS_TOKEN", "")

	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	refresh := newSplunkExportConfigurationRefresher(path, metrics, traces)
	if applied := mustRefresh(t, refresh); !applied {
		t.Fatal("expected env file refresh to apply")
	}

	if got := metrics.Config(); !got.Enabled || got.Realm != "us2" || got.AccessToken != "env-file-token-123456" {
		t.Fatalf("metrics config = %+v", got)
	}
	if got := traces.Config(); got.Enabled || got.Realm != "us2" || got.AccessToken != "env-file-token-123456" {
		t.Fatalf("traces config = %+v", got)
	}
	if got := os.Getenv("SPLUNK_REALM"); got != "shell-realm" {
		t.Fatalf("SPLUNK_REALM changed to %q", got)
	}
}

func TestSplunkExportConfigurationRefresherIgnoresMissingDefault(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("OBSTUDIO_ENV_FILE", "")

	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})

	if applied, err := newSplunkExportConfigurationRefresher("", metrics, traces)(); err != nil {
		t.Fatalf("missing default env file should be ignored: %v", err)
	} else if applied {
		t.Fatal("missing default env file should not apply")
	}
}

func TestSplunkExportConfigurationRefresherIgnoresDisabledFlagsWithoutCredentials(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
OBSTUDIO_SPLUNK_METRICS_EXPORT=false
OBSTUDIO_SPLUNK_TRACES_EXPORT=0
`), 0o600); err != nil {
		t.Fatal(err)
	}
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})

	if applied, err := newSplunkExportConfigurationRefresher(path, metrics, traces)(); err != nil {
		t.Fatalf("disabled-only env file should be ignored: %v", err)
	} else if applied {
		t.Fatal("disabled-only env file should not apply")
	}
	if got := metrics.Config(); got.Enabled || got.Realm != "" || got.AccessToken != "" {
		t.Fatalf("metrics config = %+v", got)
	}
	if got := traces.Config(); got.Enabled || got.Realm != "" || got.AccessToken != "" {
		t.Fatalf("traces config = %+v", got)
	}
}

func TestSplunkExportConfigurationRefresherErrorsForMissingExplicitPath(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.env")
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})

	if _, err := newSplunkExportConfigurationRefresher(path, metrics, traces)(); err == nil {
		t.Fatal("expected missing explicit env file to fail")
	}
}

func TestSplunkExportConfigurationRefresherPreservesTraceOnlyExport(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=eu0
SPLUNK_ACCESS_TOKEN=env-file-token-123456
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
`), 0o600); err != nil {
		t.Fatal(err)
	}

	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	refresh := newSplunkExportConfigurationRefresher(path, metrics, traces)
	if applied := mustRefresh(t, refresh); !applied {
		t.Fatal("expected env file refresh to apply")
	}

	if got := metrics.Config(); got.Enabled || got.Realm != "eu0" || got.AccessToken != "env-file-token-123456" {
		t.Fatalf("metrics config = %+v", got)
	}
	if got := traces.Config(); !got.Enabled || got.Realm != "eu0" || got.AccessToken != "env-file-token-123456" {
		t.Fatalf("traces config = %+v", got)
	}
}

func TestSplunkExportConfigurationRefresherReloadsExistingConfiguration(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Enabled:     true,
		Realm:       "us1",
		AccessToken: "old-token-123456",
	})
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Enabled:     true,
		Realm:       "us1",
		AccessToken: "old-token-123456",
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=eu0
SPLUNK_ACCESS_TOKEN=new-token-123456
OBSTUDIO_SPLUNK_METRICS_EXPORT=false
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
`), 0o600); err != nil {
		t.Fatal(err)
	}

	refresh := newSplunkExportConfigurationRefresher(path, metrics, traces)
	if applied := mustRefresh(t, refresh); !applied {
		t.Fatal("expected env file refresh to apply")
	}

	if got := metrics.Config(); got.Enabled || got.Realm != "eu0" || got.AccessToken != "new-token-123456" {
		t.Fatalf("metrics config = %+v", got)
	}
	if got := traces.Config(); !got.Enabled || got.Realm != "eu0" || got.AccessToken != "new-token-123456" {
		t.Fatalf("traces config = %+v", got)
	}
}

func TestSplunkExportConfigurationRefresherProtectsActiveLegacyEnvConfiguration(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=us1
SPLUNK_ACCESS_TOKEN=env-token-123456
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
OBSTUDIO_SPLUNK_METRICS_ENDPOINT=https://metrics.example.com/v2/datapoint/otlp
OBSTUDIO_SPLUNK_TRACES_ENDPOINT=https://traces.example.com/v2/trace/otlp
`), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, key := range append(append([]string{}, splunkEnvFilePrecedenceKeys...), splunkEnvFileLegacyEndpointKeys...) {
		key := key
		_ = os.Unsetenv(key)
		t.Cleanup(func() { _ = os.Unsetenv(key) })
	}
	if err := loadConfiguredEnvFile(path); err != nil {
		t.Fatal(err)
	}
	metricsConfig, err := splunkMetricsExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	metrics, err := otlp.NewSplunkMetricsExportController(metricsConfig)
	if err != nil {
		t.Fatal(err)
	}
	tracesConfig, err := splunkTracesExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(tracesConfig)
	if err != nil {
		t.Fatal(err)
	}

	refresh := newSplunkExportConfigurationRefresher(path, metrics, traces)
	if managed := mustRefresh(t, refresh); !managed {
		t.Fatal("active legacy env configuration should remain managed")
	}

	if got := metrics.Config(); got.Realm != "us1" || got.Endpoint != "https://metrics.example.com/v2/datapoint/otlp" || got.AccessToken != "env-token-123456" {
		t.Fatalf("metrics config = %+v", got)
	}
	if got := traces.Config(); got.Realm != "us1" || got.Endpoint != "https://traces.example.com/v2/trace/otlp" || got.AccessToken != "env-token-123456" {
		t.Fatalf("traces config = %+v", got)
	}

	manualMetrics := otlp.SplunkMetricsExporterConfig{Realm: "eu0", AccessToken: "manual-token-123456"}
	manualTraces := otlp.SplunkTracesExporterConfig{Realm: "eu0", AccessToken: "manual-token-123456"}
	if err := metrics.Configure(manualMetrics); err != nil {
		t.Fatal(err)
	}
	if err := traces.Configure(manualTraces); err != nil {
		t.Fatal(err)
	}
	if managed := mustRefresh(t, refresh); managed {
		t.Fatal("manual cloud configuration should not be marked managed by legacy env settings")
	}
}

func TestSplunkExportConfigurationRefresherUsesFreshFileAfterLegacyEndpointsAreRemoved(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=us1
SPLUNK_ACCESS_TOKEN=old-env-token-123456
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
OBSTUDIO_SPLUNK_METRICS_ENDPOINT=https://metrics.example.com/v2/datapoint/otlp
OBSTUDIO_SPLUNK_TRACES_ENDPOINT=https://traces.example.com/v2/trace/otlp
`), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, key := range append(append([]string{}, splunkEnvFilePrecedenceKeys...), splunkEnvFileLegacyEndpointKeys...) {
		key := key
		_ = os.Unsetenv(key)
		t.Cleanup(func() { _ = os.Unsetenv(key) })
	}
	if err := loadConfiguredEnvFile(path); err != nil {
		t.Fatal(err)
	}
	metricsConfig, err := splunkMetricsExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	metrics, err := otlp.NewSplunkMetricsExportController(metricsConfig)
	if err != nil {
		t.Fatal(err)
	}
	tracesConfig, err := splunkTracesExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(tracesConfig)
	if err != nil {
		t.Fatal(err)
	}

	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=eu1
SPLUNK_ACCESS_TOKEN=new-env-token-123456
OBSTUDIO_SPLUNK_METRICS_EXPORT=false
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
`), 0o600); err != nil {
		t.Fatal(err)
	}
	refresh := newSplunkExportConfigurationRefresher(path, metrics, traces)
	if managed := mustRefresh(t, refresh); !managed {
		t.Fatal("updated env configuration should remain managed")
	}

	if got := metrics.Config(); got.Enabled || got.Realm != "eu1" || got.Endpoint != "" || got.AccessToken != "new-env-token-123456" {
		t.Fatalf("metrics config = %+v", got)
	}
	if got := traces.Config(); !got.Enabled || got.Realm != "eu1" || got.Endpoint != "" || got.AccessToken != "new-env-token-123456" {
		t.Fatalf("traces config = %+v", got)
	}
}

func TestSplunkExportConfigurationRefresherRecognizesActiveShellLegacyConfiguration(t *testing.T) {
	resetEnvFileShellPrecedence(t)
	path := filepath.Join(t.TempDir(), "obstudio.env")
	t.Setenv("OBSTUDIO_SPLUNK_METRICS_ENDPOINT", "https://metrics.example.com/v2/datapoint/otlp")
	if err := os.WriteFile(path, []byte(`
SPLUNK_REALM=us1
SPLUNK_ACCESS_TOKEN=env-token-123456
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
`), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, key := range append(append([]string{}, splunkEnvFilePrecedenceKeys...), splunkEnvFileLegacyEndpointKeys...) {
		if key == "OBSTUDIO_SPLUNK_METRICS_ENDPOINT" {
			continue
		}
		key := key
		_ = os.Unsetenv(key)
		t.Cleanup(func() { _ = os.Unsetenv(key) })
	}
	if err := loadConfiguredEnvFile(path); err != nil {
		t.Fatal(err)
	}
	metricsConfig, err := splunkMetricsExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	metrics, err := otlp.NewSplunkMetricsExportController(metricsConfig)
	if err != nil {
		t.Fatal(err)
	}
	tracesConfig, err := splunkTracesExporterConfigFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(tracesConfig)
	if err != nil {
		t.Fatal(err)
	}

	refresh := newSplunkExportConfigurationRefresher(path, metrics, traces)
	if managed := mustRefresh(t, refresh); !managed {
		t.Fatal("active shell legacy configuration should remain managed")
	}

	if got := metrics.Config(); got.Realm != "us1" || got.Endpoint != "https://metrics.example.com/v2/datapoint/otlp" || got.AccessToken != "env-token-123456" {
		t.Fatalf("metrics config = %+v", got)
	}
	if got := traces.Config(); got.Realm != "us1" || got.AccessToken != "env-token-123456" {
		t.Fatalf("traces config = %+v", got)
	}
}

func TestSplunkExportConfigurationRefresherRequiresRealmAndToken(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte("SPLUNK_REALM=us0\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	metrics, _ := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	traces, _ := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{})

	if _, err := newSplunkExportConfigurationRefresher(path, metrics, traces)(); err == nil {
		t.Fatal("expected partial env configuration to fail")
	}
}

func mustRefresh(t *testing.T, refresh func() (bool, error)) bool {
	t.Helper()
	applied, err := refresh()
	if err != nil {
		t.Fatal(err)
	}
	return applied
}
