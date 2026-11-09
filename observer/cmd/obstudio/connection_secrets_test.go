package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/credentials"
	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"testing"

	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"time"
)

type testCredentialBackend struct {
	values     map[string]string
	fail       bool
	setError   error
	deleteFail bool
	readFail   bool
	readBlock  <-chan struct{}
	beforeSet  func()
	afterSet   func()
}

func waitForCredentialSignal(t *testing.T, signal <-chan struct{}, operation string) {
	t.Helper()
	select {
	case <-signal:
	case <-time.After(5 * time.Second):
		t.Fatalf("timed out waiting for %s", operation)
	}
}

func (b *testCredentialBackend) Get(key string) (string, error) {
	if b.readBlock != nil {
		<-b.readBlock
	}
	if b.fail || b.readFail {
		return "", credentials.ErrUnavailable
	}
	value, ok := b.values[key]
	if !ok {
		return "", credentials.ErrNotFound
	}
	return value, nil
}

func TestCloudBlockedCredentialReadLeavesLocalReceiverUsable(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), vault)
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "token", Enabled: true}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "token", Enabled: true}
	if err := settings.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	release := make(chan struct{})
	backend.readBlock = release
	defer close(release)
	started := time.Now()
	if err := settings.RestoreCloud(&m, &tr); !errors.Is(err, credentials.ErrUnavailable) {
		t.Fatal("blocked native read did not fail safely", err)
	}
	if time.Since(started) > 10*time.Second || m.Enabled || tr.Enabled || m.AccessToken != "" || tr.AccessToken != "" || m.Realm != "us1" {
		t.Fatal("startup did not retain a paused, recoverable connection")
	}
	local := store.New()
	metrics, err := otlp.NewSplunkMetricsExportController(m)
	if err != nil {
		t.Fatal(err)
	}
	traces, err := otlp.NewSplunkTracesExportController(tr)
	if err != nil {
		t.Fatal(err)
	}
	receiver, err := otlp.StartReceiver(context.Background(), local, "127.0.0.1:0", "127.0.0.1:0", otlp.WithMetricsExporter(metrics), otlp.WithTracesExporter(traces))
	if err != nil {
		t.Fatal(err)
	}
	defer receiver.Shutdown(context.Background())
	server := httptest.NewServer(receiver.HTTPHandler())
	defer server.Close()
	client := &http.Client{Timeout: 2 * time.Second}
	response, err := client.Post(server.URL+"/v1/logs", "application/json", strings.NewReader(`{"resourceLogs":[{"scopeLogs":[{"logRecords":[{"body":{"stringValue":"local ingestion while keyring is blocked"}}]}]}]}`))
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusOK || local.Stats().LogCount != 1 {
		t.Fatal("blocked keyring prevented local ingestion", response.StatusCode, local.Stats())
	}
}
func (b *testCredentialBackend) Set(key, value string) error {
	if b.setError != nil {
		return b.setError
	}
	if b.beforeSet != nil {
		b.beforeSet()
	}
	if b.fail {
		return credentials.ErrUnavailable
	}
	b.values[key] = value
	if b.afterSet != nil {
		b.afterSet()
	}
	return nil
}
func (b *testCredentialBackend) Delete(key string) error {
	if b.deleteFail {
		return errors.New("private deletion details")
	}
	if _, exists := b.values[key]; !exists {
		return credentials.ErrNotFound
	}
	delete(b.values, key)
	return nil
}

func newTestConnectionPersistence(t *testing.T, path string, store *credentials.Store) *connectionPersistence {
	t.Helper()
	settings := newConnectionPersistence(path, store)
	settings.journalPath = filepath.Join(filepath.Dir(settings.path), "credential-cleanup", filepath.Base(settings.path)+".json")
	return settings
}

func TestCloudRefusalBeforeWriteKeepsSavedStateWithoutPendingCleanup(t *testing.T) {
	for _, previouslySaved := range []bool{false, true} {
		t.Run(strconv.FormatBool(previouslySaved), func(t *testing.T) {
			backend := &testCredentialBackend{values: map[string]string{}}
			settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
			metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "saved-token"}
			traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "saved-token"}
			if previouslySaved {
				if err := settings.SaveCloud(metrics, traces); err != nil {
					t.Fatal(err)
				}
			}
			before, _ := os.ReadFile(settings.path)
			backend.setError, backend.deleteFail = credentials.ErrWriteNotStarted, true
			metrics.AccessToken, traces.AccessToken = "session-token", "session-token"
			if err := settings.SaveCloud(metrics, traces); !errors.Is(err, api.ErrCredentialStorageUnavailable) {
				t.Fatal(err)
			}
			after, _ := os.ReadFile(settings.path)
			wantCredentials := 0
			if previouslySaved {
				wantCredentials = 1
			}
			if string(before) != string(after) || settings.CloudCleanupPending() || len(backend.values) != wantCredentials {
				t.Fatal("unwritten candidate changed saved settings or required native cleanup")
			}
		})
	}
}

func TestCloudSecureSettingsSaveRestoreAndDisconnect(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newTestConnectionPersistence(t, path, vault)
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
		restoredMetrics := otlp.SplunkMetricsExporterConfig{}
		restoredTraces := otlp.SplunkTracesExporterConfig{}
		reloaded := newTestConnectionPersistence(t, path, vault)
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
		if err := settings.SaveCloud(restoredMetrics, restoredTraces); !errors.Is(err, credentials.ErrUnavailable) {
			t.Fatal("tokenless pause was accepted", err)
		}
		data, _ = os.ReadFile(path)
		if string(data) != before {
			t.Fatal("tokenless pause erased saved credentials")
		}
		backend.fail = false
		if err := writeConnectionSettings(path, map[string]string{"cloudRealm": "eu0"}); err != nil {
			t.Fatal(err)
		}
		if err := reloaded.RestoreCloud(&restoredMetrics, &restoredTraces); err == nil {
			t.Fatal("another destination read the saved token")
		}
		if err := writeConnectionSettings(path, map[string]string{"cloudRealm": "us1"}); err != nil {
			t.Fatal(err)
		}
		if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
			t.Fatal(err)
		}
		if len(backend.values) != 0 || !settings.CloudStorageManaged() {
			t.Fatal("disconnect must delete its token and retain the migration marker")
		}
	}
}

func TestCloudHTTPRefreshRetainsUnchangedLiveCredential(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "synthetic-token", Enabled: true}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: m.AccessToken, Enabled: true}
	if err := settings.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	metrics, err := otlp.NewSplunkMetricsExportController(m)
	if err != nil {
		t.Fatal(err)
	}
	defer metrics.Shutdown(context.Background())
	traces, err := otlp.NewSplunkTracesExportController(tr)
	if err != nil {
		t.Fatal(err)
	}
	defer traces.Shutdown(context.Background())
	mux := http.NewServeMux()
	api.Register(mux, store.New(), metrics, traces, newSplunkExportConfigurationRefresher(metrics, traces, settings))
	for _, unavailable := range []bool{true, false} {
		backend.readFail = unavailable
		request := httptest.NewRequest(http.MethodPost, "/api/splunk/export/refresh", strings.NewReader("{}"))
		request.RemoteAddr = "127.0.0.1:1234"
		request.Header.Set("Content-Type", "application/json")
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, request)
		want := http.StatusOK
		if unavailable {
			want = http.StatusBadRequest
		}
		if response.Code != want || !metrics.Status().Enabled || !traces.Status().Enabled || metrics.Config().AccessToken != m.AccessToken || traces.Config().AccessToken != tr.AccessToken {
			t.Fatal("refresh changed an unchanged live connection", response.Code, response.Body.String())
		}
	}
}

func TestCloudFirstRefreshAllowsSavingTheConnection(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}}))
	metrics, traces := &recordingMetricsExportConfigurator{}, &recordingTracesExportConfigurator{}
	refresh := newSplunkExportConfigurationRefresher(metrics, traces, settings)
	if err := refresh(); err != nil {
		t.Fatal("first refresh blocked a new connection", err)
	}
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "token", Enabled: true}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "token", Enabled: true}
	if err := settings.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	if err := refresh(); err != nil || metrics.Config().AccessToken != "token" || traces.Config().AccessToken != "token" {
		t.Fatal("saved UI connection did not become active", err)
	}
}

func TestCloudStatusReadsPublishedMetadataDuringCredentialSave(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "first"}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "first"}
	if err := settings.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	started, release := make(chan struct{}), make(chan struct{})
	backend.afterSet = func() { close(started); <-release }
	released := false
	defer func() {
		if !released {
			close(release)
		}
	}()
	m.AccessToken, tr.AccessToken = "replacement", "replacement"
	saved := make(chan error, 1)
	go func() { saved <- settings.SaveCloud(m, tr) }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("save did not reach native storage")
	}
	read := make(chan bool, 1)
	go func() { managed := settings.CloudStorageManaged(); _ = settings.CloudCleanupPending(); read <- managed }()
	select {
	case managed := <-read:
		if !managed {
			t.Fatal("status lost the published connection")
		}
	case <-time.After(time.Second):
		t.Fatal("metadata reads waited for a native credential operation")
	}
	close(release)
	released = true
	select {
	case err := <-saved:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("save did not complete")
	}
}

func TestConnectionJournalSyncsCreatedDirectoriesBeforePublication(t *testing.T) {
	for _, fail := range []bool{false, true} {
		t.Run(strconv.FormatBool(fail), func(t *testing.T) {
			path := filepath.Join(t.TempDir(), ".obstudio", "credential-cleanup", "journal.json")
			var calls []string
			syncErr := errors.New("directory sync failed")
			err := writeDurableConnectionFileWithSync(path, []byte("[]"), func(target string) error {
				calls = append(calls, target)
				if target != path {
					if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
						t.Fatal("journal published before ancestor sync", err)
					}
					if fail {
						return syncErr
					}
				}
				return syncConnectionSettingsDirectory(target)
			})
			if fail {
				if !errors.Is(err, syncErr) || len(calls) != 1 || calls[0] == path {
					t.Fatal("ancestor sync failure did not stop publication", err, calls)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			root := filepath.Dir(filepath.Dir(filepath.Dir(path)))
			want := []string{filepath.Join(root, ".obstudio"), filepath.Join(root, ".obstudio", "credential-cleanup"), path}
			if !reflect.DeepEqual(calls, want) {
				t.Fatalf("sync order=%v, want %v", calls, want)
			}
		})
	}
}

func TestConnectionPublicationFlushFailureRetainsRecoveryState(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	err := writeDurableConnectionFileWithSync(path, []byte(`{"schemaVersion":"1"}`), func(target string) error {
		if target == path {
			return errors.New("published file flush failed")
		}
		return syncConnectionSettingsDirectory(target)
	})
	if !errors.Is(err, errConnectionSettingsPublished) {
		t.Fatal("publication uncertainty was reported as a pre-commit failure", err)
	}
	if _, err := readConnectionSettings(path); err != nil {
		t.Fatal("published recovery state was lost", err)
	}
}

func TestCloudSavePreservesUnreadableSettings(t *testing.T) {
	for _, data := range []string{`{`, `{"schemaVersion":"2"}`, `{"schemaVersion":"1","cloudRealm":42}`, strings.Repeat("x", 64*1024+1)} {
		path := filepath.Join(t.TempDir(), "connections.json")
		if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
		backend := &testCredentialBackend{values: map[string]string{}}
		settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
		m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "token"}
		tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "token"}
		if err := settings.SaveCloud(m, tr); err == nil {
			t.Fatal("save replaced unreadable connection settings")
		}
		after, err := os.ReadFile(path)
		if err != nil || string(after) != data || len(backend.values) != 0 {
			t.Fatal("failed save changed connection settings or credentials", err)
		}
	}
}

func TestCloudDisconnectRetainsCleanupAndRefreshesOtherCollectors(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	metrics := &recordingMetricsExportConfigurator{config: otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "test-token", Enabled: true}}
	traces := &recordingTracesExportConfigurator{config: otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "test-token", Enabled: true}}
	if err := settings.SaveCloud(metrics.config, traces.config); err != nil {
		t.Fatal(err)
	}
	backend.deleteFail = true
	if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("cleanup failure was not reported", err)
	}
	values, err := readConnectionSettings(path)
	if err != nil || values[cloudSecretRef] != "" {
		t.Fatal("disconnect lost cleanup state", err)
	}
	reloaded := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	if err := newSplunkExportConfigurationRefresher(metrics, traces, reloaded)(); !errors.Is(err, api.ErrConnectionCleanupPending) || metrics.config.AccessToken != "" || traces.config.AccessToken != "" {
		t.Fatal("external disconnect must stop export even when cleanup fails", err)
	}
	if !settings.CloudCleanupPending() {
		t.Fatal("retired credential cleanup was hidden")
	}
	backend.deleteFail = false
	if err := newSplunkExportConfigurationRefresher(metrics, traces, reloaded)(); err != nil {
		t.Fatal(err)
	}
	if settings.CloudCleanupPending() {
		t.Fatal("successful cleanup stayed pending")
	}
	if metrics.config.AccessToken != "" || traces.config.AccessToken != "" || metrics.config.Enabled || traces.config.Enabled || len(backend.values) != 0 {
		t.Fatal("refresh must stop export and retry credential cleanup")
	}
	if err := newSplunkExportConfigurationRefresher(metrics, traces, reloaded)(); err != nil {
		t.Fatal("cleanup retry must be idempotent", err)
	}
}

func TestConnectionSettingsPreserveSymlinkAndPrivatePermissions(t *testing.T) {
	directory := t.TempDir()
	target, link := filepath.Join(directory, "target"), filepath.Join(directory, "connections-link.json")
	if err := os.WriteFile(target, []byte(`{"schemaVersion":"1","extraSetting":"keep"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, link); err != nil {
		if runtime.GOOS == "windows" {
			t.Skip("symlinks unavailable", err)
		}
		t.Fatal(err)
	}
	settings := newTestConnectionPersistence(t, link, credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}}))
	if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "saved-token"}, otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "saved-token"}); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(link)
	if err != nil || info.Mode()&os.ModeSymlink == 0 {
		t.Fatal("settings symlink replaced", err)
	}
	data, err := readConnectionSettings(target)
	if err != nil || data["extraSetting"] != "keep" || data["cloudRealm"] != "us1" || data[cloudSecretRef] == "" {
		t.Fatal("target settings not updated", err)
	}
	info, err = os.Stat(target)
	if err != nil || (runtime.GOOS != "windows" && info.Mode().Perm() != 0o600) {
		t.Fatal("settings are not private", err)
	}
}

func TestCloudReplacementCleanupDoesNotBlockPauseDisconnectOrRestore(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newTestConnectionPersistence(t, path, vault)
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "first-token", Enabled: true}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metrics.AccessToken, Enabled: true}
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	backend.deleteFail = true
	metrics.AccessToken, traces.AccessToken = "replacement-token", "replacement-token"
	if err := settings.SaveCloud(metrics, traces); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal(err)
	}
	restore := func(enabled bool) {
		t.Helper()
		m := otlp.SplunkMetricsExporterConfig{}
		tr := otlp.SplunkTracesExporterConfig{}
		if err := newTestConnectionPersistence(t, path, vault).RestoreCloud(&m, &tr); !errors.Is(err, api.ErrConnectionCleanupPending) {
			t.Fatal("cleanup pending was not reported", err)
		}
		if m.AccessToken != metrics.AccessToken || tr.AccessToken != traces.AccessToken || m.Enabled != enabled || tr.Enabled != enabled {
			t.Fatal("cleanup blocked restoration of the active connection")
		}
	}
	restore(true)
	metrics.Enabled, traces.Enabled = false, false
	if err := settings.SaveCloud(metrics, traces); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("pause was blocked by cleanup", err)
	}
	restore(false)
	if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("disconnect was blocked by cleanup", err)
	}
	values, err := readConnectionSettings(path)
	if err != nil || values[cloudSecretRef] != "" || len(backend.values) != 2 {
		t.Fatal("disconnect lost active or retired credential cleanup", err)
	}
	backend.deleteFail = false
	m, tr := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
	if err := newTestConnectionPersistence(t, path, vault).RestoreCloud(&m, &tr); err != nil || len(backend.values) != 0 {
		t.Fatal("restart did not finish both deletions", err)
	}
	if m.Enabled || tr.Enabled || m.AccessToken != "" || tr.AccessToken != "" {
		t.Fatal("cleanup revived a disconnected destination")
	}
}

func TestCredentialCleanupSurvivesFailedSaves(t *testing.T) {
	for _, failure := range []string{"readback", "settings publication"} {
		t.Run(failure, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "connections.json")
			backend := &testCredentialBackend{values: map[string]string{}}
			vault := credentials.NewWithBackend(backend)
			settings := newTestConnectionPersistence(t, path, vault)
			metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "candidate-token", Enabled: true}
			traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metrics.AccessToken, Enabled: true}
			wantToken := ""
			wantCount := 0
			if failure == "readback" {
				backend.readFail = true
			} else {
				metrics.AccessToken, traces.AccessToken = "saved-token", "saved-token"
				if err := settings.SaveCloud(metrics, traces); err != nil {
					t.Fatal(err)
				}
				wantToken = "saved-token"
				wantCount = 1
				metrics.AccessToken, traces.AccessToken = "candidate-token", "candidate-token"
				backend.afterSet = func() {
					backend.afterSet = nil
					if err := os.Rename(path, path+".saved"); err != nil {
						t.Fatal(err)
					}
					if err := os.Mkdir(path, 0o700); err != nil {
						t.Fatal(err)
					}
				}
			}
			backend.deleteFail = true
			if err := settings.SaveCloud(metrics, traces); err == nil || errors.Is(err, api.ErrConnectionCleanupPending) {
				t.Fatal("failed save was reported as committed", err)
			}
			if failure == "settings publication" {
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
				if err := os.Rename(path+".saved", path); err != nil {
					t.Fatal(err)
				}
			}
			backend.readFail, backend.deleteFail = false, false
			m := otlp.SplunkMetricsExporterConfig{}
			tr := otlp.SplunkTracesExporterConfig{}
			if err := newTestConnectionPersistence(t, path, vault).RestoreCloud(&m, &tr); err != nil {
				t.Fatal(err)
			}
			if len(backend.values) != wantCount || m.AccessToken != wantToken || tr.AccessToken != wantToken {
				t.Fatal("failed save lost a cleanup reference or changed the active token")
			}
		})
	}
}

func TestCloudRefreshSerializesWithExternalDisconnect(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	vault := credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}})
	writer := newTestConnectionPersistence(t, path, vault)
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "token", Enabled: true}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: m.AccessToken, Enabled: true}
	if err := writer.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	reader := newTestConnectionPersistence(t, path, vault)
	metrics := &recordingMetricsExportConfigurator{config: m}
	traces := &recordingTracesExportConfigurator{config: tr}
	done := make(chan error, 1)
	err := writer.withCredentialLock(func() error {
		go func() { err := newSplunkExportConfigurationRefresher(metrics, traces, reader)(); done <- err }()
		select {
		case err := <-done:
			t.Fatal("refresh bypassed the settings transaction", err)
		case <-time.After(50 * time.Millisecond):
		}
		return writeConnectionSettings(path, map[string]string{
			"cloudStorageVersion": "1", cloudSecretRef: "",
			"cloudRealm": "", "metricsEnabled": "", "tracesEnabled": "",
		})
	})
	if err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("refresh did not finish after settings publication")
	}
	if metrics.config.Enabled || traces.config.Enabled || metrics.config.AccessToken != "" || traces.config.AccessToken != "" {
		t.Fatal("refresh revived the disconnected connection")
	}
}

func TestConnectionSettingsAliasesShareCredentialIdentity(t *testing.T) {
	for _, missing := range []bool{false, true} {
		t.Run(strconv.FormatBool(missing), func(t *testing.T) {
			directory := t.TempDir()
			target, alias := filepath.Join(directory, "target"), filepath.Join(directory, "alias")
			if missing {
				if err := os.Mkdir(target, 0o700); err != nil {
					t.Fatal(err)
				}
			} else if err := os.WriteFile(target, []byte(`{"schemaVersion":"1"}`), 0o600); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(target, alias); err != nil {
				if runtime.GOOS == "windows" {
					t.Skip("symlinks unavailable", err)
				}
				t.Fatal(err)
			}
			if missing {
				target, alias = filepath.Join(target, "new", "connections.json"), filepath.Join(alias, "new", "connections.json")
			}
			backend := &testCredentialBackend{values: map[string]string{}}
			vault := credentials.NewWithBackend(backend)
			first, second := newTestConnectionPersistence(t, alias, vault), newTestConnectionPersistence(t, target, vault)
			metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "token", Enabled: true}
			traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metrics.AccessToken, Enabled: true}
			if err := first.SaveCloud(metrics, traces); err != nil {
				t.Fatal(err)
			}
			metrics.AccessToken, traces.AccessToken = "", ""
			if err := second.RestoreCloud(&metrics, &traces); err != nil || metrics.AccessToken != "token" || traces.AccessToken != "token" {
				t.Fatal("alias could not restore saved credentials", err)
			}
			if err := second.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil || len(backend.values) != 0 {
				t.Fatal("alias could not delete saved credentials", err)
			}
		})
	}
}

func TestCloudRejectsStaleToggleAfterExternalDisconnect(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	writer, stale := newTestConnectionPersistence(t, path, vault), newTestConnectionPersistence(t, path, vault)
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "token", Enabled: true}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metrics.AccessToken, Enabled: true}
	if err := writer.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	if err := stale.RestoreCloud(&metrics, &traces); err != nil {
		t.Fatal(err)
	}
	if err := writer.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(path)
	metrics.Enabled, traces.Enabled = false, false
	if err := stale.SaveCloud(metrics, traces); !errors.Is(err, api.ErrConnectionSettingsChanged) {
		t.Fatal("stale toggle was accepted", err)
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) || len(backend.values) != 0 {
		t.Fatal("stale toggle recreated a disconnected credential")
	}
}

func TestCloudRefreshPausesUntilSavedCredentialsCanBeRead(t *testing.T) {
	for _, change := range []string{"pause", "replace"} {
		t.Run(change, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "connections.json")
			backend := &testCredentialBackend{values: map[string]string{}}
			vault := credentials.NewWithBackend(backend)
			writer, reader := newTestConnectionPersistence(t, path, vault), newTestConnectionPersistence(t, path, vault)
			m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "first", Enabled: true}
			tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: m.AccessToken, Enabled: true}
			if err := writer.SaveCloud(m, tr); err != nil {
				t.Fatal(err)
			}
			metrics, traces := &recordingMetricsExportConfigurator{config: m}, &recordingTracesExportConfigurator{config: tr}
			m.Enabled, tr.Enabled = false, false
			if change == "replace" {
				m.Realm, tr.Realm, m.AccessToken, tr.AccessToken, m.Enabled, tr.Enabled = "eu0", "eu0", "second", "second", true, true
			}
			if err := writer.SaveCloud(m, tr); err != nil {
				t.Fatal(err)
			}
			before, _ := os.ReadFile(path)
			backend.readFail = true
			if err := newSplunkExportConfigurationRefresher(metrics, traces, reader)(); !errors.Is(err, credentials.ErrUnavailable) {
				t.Fatal(err)
			}
			after, _ := os.ReadFile(path)
			if metrics.config.Enabled || traces.config.Enabled || string(before) != string(after) {
				t.Fatal("credential read failure left retired export active or changed settings")
			}
			backend.readFail = false
			if err := newSplunkExportConfigurationRefresher(metrics, traces, reader)(); err != nil {
				t.Fatal(err)
			}
			if metrics.config.Enabled != m.Enabled || traces.config.Enabled != tr.Enabled || metrics.config.AccessToken != m.AccessToken || traces.config.AccessToken != tr.AccessToken || metrics.config.Realm != m.Realm {
				t.Fatal("credential recovery did not load the saved connection")
			}
		})
	}
}

func TestCloudHTTPRefreshPreservesAcceptedCountsThroughCredentialRecovery(t *testing.T) {
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) }))
	defer remote.Close()
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", Endpoint: remote.URL, AccessToken: "test", Enabled: true}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", Endpoint: remote.URL, AccessToken: "test", Enabled: true}
	if err := settings.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	metrics, _ := otlp.NewSplunkMetricsExportController(m)
	traces, _ := otlp.NewSplunkTracesExportController(tr)
	defer metrics.Shutdown(context.Background())
	defer traces.Shutdown(context.Background())
	md := pmetric.NewMetrics()
	metric := md.ResourceMetrics().AppendEmpty().ScopeMetrics().AppendEmpty().Metrics().AppendEmpty()
	metric.SetName("accepted.count")
	metric.SetEmptyGauge().DataPoints().AppendEmpty().SetIntValue(1)
	td := ptrace.NewTraces()
	td.ResourceSpans().AppendEmpty().ScopeSpans().AppendEmpty().Spans().AppendEmpty().SetName("accepted")
	if err := metrics.ExportMetrics(context.Background(), md); err != nil {
		t.Fatal(err)
	}
	if err := traces.ExportTraces(context.Background(), td); err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	api.Register(mux, store.New(), metrics, traces, newSplunkExportConfigurationRefresher(metrics, traces, settings))
	for _, unavailable := range []bool{true, false} {
		backend.readFail = unavailable
		response := connectionTestRequest(t, mux, "POST", "/api/splunk/export/refresh", map[string]any{})
		if unavailable && response.Code != 400 || !unavailable && response.Code != 200 {
			t.Fatal(response.Code, response.Body.String())
		}
		if !metrics.Status().Enabled || !traces.Status().Enabled {
			t.Fatal("an unchanged saved connection must retain its live credential")
		}
		if metrics.Status().ExportedDataPoints != 1 || traces.Status().ExportedSpans != 1 || metrics.Status().ExportedBatches != 1 || traces.Status().ExportedBatches != 1 {
			t.Fatal("reload discarded accepted metrics or traces", metrics.Status(), traces.Status())
		}
	}
}

func TestCloudStartupRestoresOneLockedSnapshot(t *testing.T) {
	for _, change := range []string{"pause", "disconnect", "replace"} {
		t.Run(change, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "connections.json")
			vault := credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}})
			writer, reader := newTestConnectionPersistence(t, path, vault), newTestConnectionPersistence(t, path, vault)
			m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "first", Enabled: true}
			tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: m.AccessToken, Enabled: true}
			if err := writer.SaveCloud(m, tr); err != nil {
				t.Fatal(err)
			}
			var replacement string
			if change == "replace" {
				nextM := otlp.SplunkMetricsExporterConfig{Realm: "eu0"}
				nextT := otlp.SplunkTracesExporterConfig{Realm: "eu0"}
				var err error
				replacement, err = writer.reference("cloud", cloudSecretDestination(nextM, nextT), "second", "")
				if err != nil {
					t.Fatal(err)
				}
			}
			done := make(chan error, 1)
			err := writer.withCredentialLock(func() error {
				go func() { done <- reader.RestoreCloud(&m, &tr) }()
				select {
				case err := <-done:
					t.Fatal("startup bypassed the settings transaction", err)
				case <-time.After(50 * time.Millisecond):
				}
				values := map[string]string{"metricsEnabled": "false", "tracesEnabled": "false"}
				if change == "disconnect" {
					values[cloudSecretRef] = ""
					values["cloudRealm"] = ""
				}
				if change == "replace" {
					values[cloudSecretRef] = replacement
					values["cloudRealm"] = "eu0"
					values["metricsEnabled"] = "true"
					values["tracesEnabled"] = "true"
				}
				return writeConnectionSettings(path, values)
			})
			if err != nil {
				t.Fatal(err)
			}
			select {
			case err := <-done:
				if err != nil {
					t.Fatal(err)
				}
			case <-time.After(5 * time.Second):
				t.Fatal("startup stayed blocked")
			}
			wantToken, wantRealm, wantEnabled := "first", "us1", false
			if change == "disconnect" {
				wantToken, wantRealm = "", ""
			}
			if change == "replace" {
				wantToken, wantRealm, wantEnabled = "second", "eu0", true
			}
			if m.AccessToken != wantToken || tr.AccessToken != wantToken || m.Realm != wantRealm || tr.Realm != wantRealm || m.Enabled != wantEnabled || tr.Enabled != wantEnabled {
				t.Fatal("startup mixed settings from different revisions")
			}
		})
	}
}

func TestSystemCloudConnectionPersistenceLifecycle(t *testing.T) {
	if os.Getenv("OBSTUDIO_TEST_SYSTEM_KEYRING") != "1" {
		t.Skip("requires an unlocked OS credential store")
	}
	path := filepath.Join(t.TempDir(), "connections.json")
	vault := credentials.New()
	settings := newTestConnectionPersistence(t, path, vault)
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "native-lifecycle-test", Enabled: true}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metrics.AccessToken, Enabled: true}
	t.Cleanup(func() {
		if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
			t.Error("could not clean up native test connection", err)
		}
	})
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	read := func() map[string]string {
		t.Helper()
		values, err := readConnectionSettings(path)
		if err != nil {
			t.Fatal(err)
		}
		return values
	}
	original := read()[cloudSecretRef]
	restore := func(enabled bool, token string) {
		t.Helper()
		m, tr := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
		if err := newTestConnectionPersistence(t, path, credentials.New()).RestoreCloud(&m, &tr); err != nil {
			t.Fatal(err)
		}
		if m.AccessToken != token || tr.AccessToken != token || m.Enabled != enabled || tr.Enabled != enabled {
			t.Fatal("restart changed the saved native connection")
		}
		data, err := os.ReadFile(path)
		if err != nil || strings.Contains(string(data), "native-lifecycle-test") || strings.Contains(string(data), "native-replacement-test") {
			t.Fatal("native token appeared in connection settings", err)
		}
	}
	restore(true, metrics.AccessToken)
	metrics.Enabled, traces.Enabled = false, false
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	restore(false, metrics.AccessToken)
	metrics.AccessToken, traces.AccessToken = "native-replacement-test", "native-replacement-test"
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	restore(false, metrics.AccessToken)
	if _, err := vault.Get(settings.path, "cloud", cloudSecretDestination(metrics, traces), original); !errors.Is(err, credentials.ErrNotFound) {
		t.Fatal("replaced native credential remains available", err)
	}
	if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); err != nil {
		t.Fatal(err)
	}
	restore(false, "")
	if read()[cloudSecretRef] != "" {
		t.Fatal("Disconnect retained a native credential reference")
	}
}

func TestCleanupRetainsUnconfirmedCreationReference(t *testing.T) {
	started, release := make(chan struct{}), make(chan struct{})
	backend := &testCredentialBackend{values: map[string]string{}, beforeSet: func() { close(started); <-release }}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	released := false
	defer func() {
		if !released {
			close(release)
		}
	}()
	err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "synthetic-token"}, otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "synthetic-token"})
	if !errors.Is(err, credentials.ErrWritePending) {
		t.Fatal("blocked save did not report uncertain creation", err)
	}
	waitForCredentialSignal(t, started, "credential operation start")
	if len(backend.values) != 0 {
		t.Fatal("provider wrote before release")
	}
	entries, err := settings.credentialJournal()
	if err != nil || len(entries) != 1 || !entries[0].CreationPending {
		t.Fatal("timed-out save lost its creation intent", entries, err)
	}
	close(release)
	released = true
	deadline := time.Now().Add(time.Second)
	entry := entries[0]
	for {
		_, err := settings.store.Get(settings.path, entry.Kind, entry.Destination, entry.Reference)
		if err == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("late credential did not finish", err)
		}
		time.Sleep(time.Millisecond)
	}
	backend.deleteFail = true
	if err := settings.cleanupCredential("cloud", ""); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("deletion failure was hidden", err)
	}
	entries, err = settings.credentialJournal()
	if err != nil || len(entries) != 1 || entries[0].CreationPending {
		t.Fatal("completed creation was not durably acknowledged before deletion", entries, err)
	}
	backend.deleteFail, backend.readFail = false, true
	if err := settings.cleanupCredential("cloud", ""); err != nil {
		t.Fatal("confirmed deletion retry required another credential read", err)
	}
	entries, err = settings.credentialJournal()
	if err != nil || len(entries) != 0 || len(backend.values) != 0 {
		t.Fatal("late credential escaped cleanup", err)
	}
}

func TestCloudHTTPDisconnectAfterFailedReplacementReload(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	path := filepath.Join(t.TempDir(), "connections.json")
	writer, reader := newTestConnectionPersistence(t, path, vault), newTestConnectionPersistence(t, path, vault)
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "first"}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "first"}
	if err := writer.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	if err := reader.RestoreCloud(&m, &tr); err != nil {
		t.Fatal(err)
	}
	metrics, _ := otlp.NewSplunkMetricsExportController(m)
	traces, _ := otlp.NewSplunkTracesExportController(tr)
	m.Realm, tr.Realm, m.AccessToken, tr.AccessToken = "eu0", "eu0", "replacement", "replacement"
	if err := writer.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	backend.readFail = true
	mux := http.NewServeMux()
	api.Register(mux, store.New(), metrics, traces, newSplunkExportConfigurationRefresher(metrics, traces, reader), api.SplunkCloudSettingsSaver(reader.SaveCloud))
	request := func(path, body string) *httptest.ResponseRecorder {
		t.Helper()
		r := httptest.NewRequest("POST", path, strings.NewReader(body))
		r.RemoteAddr = "127.0.0.1:1234"
		r.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, r)
		return w
	}
	if response := request("/api/splunk/export/refresh", "{}"); response.Code != 400 {
		t.Fatal("unavailable storage was hidden", response.Code, response.Body.String())
	}
	if metrics.Config().Realm != "eu0" || metrics.Config().AccessToken != "" || traces.Config().AccessToken != "" {
		t.Fatal("failed reload did not apply the saved paused destination")
	}
	snapshot := httptest.NewRecorder()
	mux.ServeHTTP(snapshot, httptest.NewRequest("GET", "/api/splunk/export", nil))
	var status struct{ Version string }
	if err := json.Unmarshal(snapshot.Body.Bytes(), &status); err != nil {
		t.Fatal(err)
	}
	response := request("/api/splunk/export/forget", `{"expectedVersion":"`+status.Version+`"}`)
	if response.Code != 200 || len(backend.values) != 0 {
		t.Fatal("failed credential reload blocked Disconnect", response.Code, response.Body.String())
	}
}

func TestCleanupReflushesPublishedCreationAcknowledgement(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	_, err := settings.store.Put(settings.path, "cloud", "destination", "synthetic-token", func(ref string) error { return settings.trackCredential("cloud", "destination", ref, true) })
	if err != nil {
		t.Fatal(err)
	}
	flushes := 0
	settings.syncDirectory = func(path string) error {
		if path == settings.journalPath {
			flushes++
			if flushes >= 2 {
				return errors.New("post-rename acknowledgement flush failed")
			}
		}
		return syncConnectionSettingsDirectory(path)
	}
	if err := settings.cleanupCredential("cloud", ""); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("failed acknowledgement flush was hidden", err)
	}
	entries, err := settings.credentialJournal()
	if err != nil || len(entries) != 1 || entries[0].CreationPending || len(backend.values) != 1 {
		t.Fatal("acknowledgement was not published without deleting the credential", entries, err)
	}
	if err := settings.cleanupCredential("cloud", ""); !errors.Is(err, api.ErrConnectionCleanupPending) || len(backend.values) != 1 {
		t.Fatal("retry trusted an unflushed acknowledgement", err)
	}
	settings.syncDirectory = syncConnectionSettingsDirectory
	if err := settings.cleanupCredential("cloud", ""); err != nil || len(backend.values) != 0 {
		t.Fatal("durable acknowledgement did not permit cleanup", err)
	}
	entries, err = settings.credentialJournal()
	if err != nil || len(entries) != 0 {
		t.Fatal("cleanup reference remained after successful deletion", err)
	}
}

func TestCloudHTTPExportPreferencesDoNotRequireCredentialAccess(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "synthetic-token", Enabled: true}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: m.AccessToken, Enabled: true}
	if err := settings.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	readValues := func() map[string]string {
		t.Helper()
		values, err := settings.values()
		if err != nil {
			t.Fatal(err)
		}
		return values
	}
	before := readValues()[cloudSecretRef]
	metrics, err := otlp.NewSplunkMetricsExportController(m)
	if err != nil {
		t.Fatal(err)
	}
	defer metrics.Shutdown(context.Background())
	traces, err := otlp.NewSplunkTracesExportController(tr)
	if err != nil {
		t.Fatal(err)
	}
	defer traces.Shutdown(context.Background())
	mux := http.NewServeMux()
	api.Register(mux, store.New(), nil, nil, metrics, traces, api.SplunkCloudSettingsSaver(settings.SaveCloud), api.SplunkCloudPreferencesSaver(settings.SaveCloudPreferences))
	backend.fail = true
	for _, enabled := range []bool{false, true, false} {
		r := httptest.NewRequest("POST", "http://127.0.0.1/api/splunk/export/enabled", strings.NewReader(fmt.Sprintf(`{"enabled":%t}`, enabled)))
		r.RemoteAddr = "127.0.0.1:1234"
		r.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, r)
		values := readValues()
		if w.Code != http.StatusOK || metrics.Config().Enabled != enabled || traces.Config().Enabled != enabled || values["metricsEnabled"] != strconv.FormatBool(enabled) || values["tracesEnabled"] != strconv.FormatBool(enabled) || values[cloudSecretRef] != before || len(backend.values) != 1 {
			t.Fatal("credential access blocked the export preference", w.Code, w.Body.String())
		}
	}
	m.AccessToken, tr.AccessToken = "replacement-token", "replacement-token"
	if err := settings.SaveCloud(m, tr); !errors.Is(err, credentials.ErrUnavailable) {
		t.Fatal("replacement bypassed secure storage", err)
	}
	if readValues()[cloudSecretRef] != before {
		t.Fatal("failed replacement changed the saved credential")
	}
}

func TestConnectionSaveBelowTraversalOnlyAncestor(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix directory permissions")
	}
	ancestor := filepath.Join(t.TempDir(), "traversal-only")
	home := filepath.Join(ancestor, "home")
	if err := os.MkdirAll(home, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(ancestor, 0111); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(ancestor, 0700) })
	if directory, err := os.Open(ancestor); err == nil {
		directory.Close()
		t.Skip("process bypasses directory read permissions")
	}
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(home, ".obstudio", "connections.json"), credentials.NewWithBackend(backend))
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "synthetic-token", Enabled: true}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: m.AccessToken, Enabled: true}
	if err := settings.SaveCloud(m, tr); err != nil {
		t.Fatal("Connect below traversal-only ancestor failed", err)
	}
	m.Enabled, tr.Enabled = false, false
	if err := settings.SaveCloudPreferences(m, tr); err != nil {
		t.Fatal("Pause below traversal-only ancestor failed", err)
	}
	if err := settings.RestoreCloud(&m, &tr); err != nil || m.Enabled || tr.Enabled || m.AccessToken != "synthetic-token" {
		t.Fatal("saved connection did not restore", err)
	}
}

func TestConnectionLockFlushesNewDirectoriesBeforeCredentialWrite(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "new", "nested", "connections.json"), credentials.NewWithBackend(backend))
	settings.syncDirectory = func(string) error { return errors.New("directory flush failed") }
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "synthetic-token"}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: m.AccessToken}
	if err := settings.SaveCloud(m, tr); err == nil || len(backend.values) != 0 {
		t.Fatal("native write preceded directory durability", err)
	}
	settings.syncDirectory = syncConnectionSettingsDirectory
	if err := settings.SaveCloud(m, tr); err != nil {
		t.Fatal("directory creation could not recover", err)
	}
}

func TestConnectionSecretsSaveAndRestoreIndependently(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newTestConnectionPersistence(t, path, vault)
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud-test-secret", Enabled: true}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: metrics.AccessToken, Enabled: true}
	logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://hec.example/services/collector", Index: "studio", Token: "logs-test-secret", ConnectionVerified: true}
	if err := settings.SaveLogs(logs); err != nil {
		t.Fatal(err)
	}
	if settings.CloudStorageManaged() {
		t.Fatal("saving logs claimed ownership of the Cloud connection")
	}
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), metrics.AccessToken) || strings.Contains(string(data), logs.Token) {
		t.Fatal("settings exposed a token")
	}
	restoredMetrics := otlp.SplunkMetricsExporterConfig{}
	restoredTraces := otlp.SplunkTracesExporterConfig{}
	restoredLogs := otlp.SplunkHECLogsExporterConfig{}
	reloaded := newTestConnectionPersistence(t, path, vault)
	cloudErr, logsErr := reloaded.Restore(&restoredMetrics, &restoredTraces, &restoredLogs)
	if cloudErr != nil || logsErr != nil || restoredMetrics.AccessToken != metrics.AccessToken || restoredTraces.AccessToken != traces.AccessToken || restoredLogs.Token != logs.Token {
		t.Fatal("secure connections did not restore")
	}
	if !restoredMetrics.Enabled || restoredLogs.Enabled {
		t.Fatal("independent export preferences were not restored")
	}
	// A destination edit cannot retrieve the token for the saved destination.
	if err := writeConnectionSettings(path, map[string]string{"logsEndpoint": "https://other.example/services/collector"}); err != nil {
		t.Fatal(err)
	}
	_, logsErr = reloaded.Restore(&restoredMetrics, &restoredTraces, &restoredLogs)
	if logsErr == nil || restoredLogs.Token != "" || restoredLogs.Enabled || restoredMetrics.AccessToken != metrics.AccessToken {
		t.Fatal("credential failure was not isolated to logs")
	}
	if err := writeConnectionSettings(path, map[string]string{"logsEndpoint": logs.Endpoint}); err != nil {
		t.Fatal(err)
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
	values, err := readConnectionSettings(path)
	if err != nil {
		t.Fatal(err)
	}
	return values
}

func TestSecureSaveFailurePreservesSettingsAndPreviousToken(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newTestConnectionPersistence(t, path, vault)
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
	backend.afterSet = func() {
		backend.afterSet = nil
		if err := os.Rename(path, path+".saved"); err != nil {
			t.Fatal(err)
		}
		if err := os.Mkdir(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	backend.deleteFail = true
	if err := settings.SaveLogs(logs); err == nil || errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("failed publication was reported as committed", err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(path+".saved", path); err != nil {
		t.Fatal(err)
	}
	backend.deleteFail = false
	logs.Token = ""
	metrics, traces := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
	_, err := newTestConnectionPersistence(t, path, vault).Restore(&metrics, &traces, &logs)
	if err != nil || logs.Token != "first-secret" || len(backend.values) != 1 {
		t.Fatal("failed save replaced saved credential")
	}
}

func TestLogsRefusalBeforeWriteDoesNotCreateAConnectionOrPendingCleanup(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}, setError: credentials.ErrWriteNotStarted, deleteFail: true}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	config := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "session-token", Index: "studio"}
	if err := settings.SaveLogs(config); !errors.Is(err, api.ErrCredentialStorageUnavailable) {
		t.Fatal(err)
	}
	if settings.HasLogsCredential() || settings.LogsCleanupPending() || len(backend.values) != 0 {
		t.Fatal("unwritten token created a saved connection or required native cleanup")
	}
	if _, err := os.Stat(settings.path); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("refusal published connection settings", err)
	}
}

func TestLogsDisconnectForgetsSecureTokenAndPreservesCloud(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newTestConnectionPersistence(t, path, vault)
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
	if values["logsEndpoint"] != logs.Endpoint || values["logsIndex"] != logs.Index {
		t.Fatal("disconnect lost destination fields")
	}
	reloaded := newTestConnectionPersistence(t, path, vault)
	cloudErr, logsErr := reloaded.Restore(&metrics, &traces, &logs)
	if cloudErr != nil || logsErr != nil || logs.Token != "" || metrics.AccessToken != "cloud-test-token" || reloaded.HasLogsCredential() {
		t.Fatal("restart restored a forgotten token or changed the cloud connection")
	}
}

func TestLogsReplacementCleanupDoesNotBlockPauseDisconnectOrRestore(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	settings := newTestConnectionPersistence(t, path, vault)
	config := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "first-token", Index: "studio", Enabled: true, ConnectionVerified: true}
	if err := settings.SaveLogs(config); err != nil {
		t.Fatal(err)
	}
	backend.deleteFail = true
	config.Token = "replacement-token"
	if err := settings.SaveLogs(config); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal(err)
	}
	restore := func(enabled bool) {
		t.Helper()
		logs := otlp.SplunkHECLogsExporterConfig{}
		metrics, traces := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
		if _, err := newTestConnectionPersistence(t, path, vault).Restore(&metrics, &traces, &logs); !errors.Is(err, api.ErrConnectionCleanupPending) {
			t.Fatal("cleanup warning was not reported", err)
		}
		if logs.Token != config.Token || logs.Enabled != enabled || !logs.ConnectionVerified {
			t.Fatal("cleanup blocked active logs restoration")
		}
	}
	restore(true)
	config.Enabled = false
	if err := settings.SaveLogs(config); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("pause was blocked", err)
	}
	restore(false)
	config.Token, config.ConnectionVerified = "", false
	if err := settings.SaveLogs(config); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("disconnect was blocked", err)
	}
	values, err := readConnectionSettings(path)
	if err != nil || values[logsSecretRef] != "" || len(backend.values) != 2 {
		t.Fatal("disconnect lost cleanup state", err)
	}
	backend.deleteFail = false
	metrics, traces := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
	if _, err := newTestConnectionPersistence(t, path, vault).Restore(&metrics, &traces, &config); err != nil {
		t.Fatal(err)
	}
	if config.Enabled || config.Token != "" || len(backend.values) != 0 {
		t.Fatal("retry revived export or kept a credential")
	}
}

func TestLogsMutationsRespectDestinationState(t *testing.T) {
	for _, change := range []string{"cloud", "disconnect"} {
		t.Run(change, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "connections.json")
			backend := &testCredentialBackend{values: map[string]string{}}
			vault := credentials.NewWithBackend(backend)
			writer, reader := newTestConnectionPersistence(t, path, vault), newTestConnectionPersistence(t, path, vault)
			logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "token", Index: "studio", Enabled: true, ConnectionVerified: true}
			if err := writer.SaveLogs(logs); err != nil {
				t.Fatal(err)
			}
			m, tr := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
			if _, err := reader.Restore(&m, &tr, &logs); err != nil {
				t.Fatal(err)
			}
			if change == "cloud" {
				if err := writer.SaveCloud(otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud"}, otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "cloud"}); err != nil {
					t.Fatal(err)
				}
			} else {
				disconnected := logs
				disconnected.Token, disconnected.Enabled, disconnected.ConnectionVerified = "", false, false
				if err := writer.SaveLogs(disconnected); err != nil {
					t.Fatal(err)
				}
			}
			before, _ := os.ReadFile(path)
			logs.Enabled = false
			err := reader.SaveLogsPreferences(logs)
			if change == "cloud" {
				if err != nil {
					t.Fatal("Cloud changes blocked logs", err)
				}
			} else {
				if !errors.Is(err, api.ErrConnectionSettingsChanged) {
					t.Fatal("stale logs toggle was accepted", err)
				}
				after, _ := os.ReadFile(path)
				if string(before) != string(after) || len(backend.values) != 0 {
					t.Fatal("stale toggle recreated a disconnected logs credential")
				}
			}
		})
	}
}

func TestLogsStartupRestoresFreshDestinationSettings(t *testing.T) {
	for _, change := range []string{"pause", "disconnect", "replace"} {
		t.Run(change, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "connections.json")
			vault := credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}})
			writer, reader := newTestConnectionPersistence(t, path, vault), newTestConnectionPersistence(t, path, vault)
			initial := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "first", Index: "studio", Enabled: true, ConnectionVerified: true}
			if err := writer.SaveLogs(initial); err != nil {
				t.Fatal(err)
			}
			current, next := initial, initial
			current.Token = ""
			switch change {
			case "pause":
				next.Enabled = false
			case "disconnect":
				next.Token, next.Enabled, next.ConnectionVerified = "", false, false
			case "replace":
				next.Endpoint, next.Token, next.Index = "https://other.example/services/collector", "second", "other"
			}
			if err := writer.SaveLogs(next); err != nil {
				t.Fatal(err)
			}
			m, tr := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
			if _, err := reader.Restore(&m, &tr, &current); err != nil {
				t.Fatal(err)
			}
			if current.Endpoint != next.Endpoint || current.Token != next.Token || current.Index != next.Index || current.Enabled != next.Enabled || current.ConnectionVerified != next.ConnectionVerified {
				t.Fatal("logs startup mixed destination settings")
			}
		})
	}
}

func TestLogsUnavailableCredentialKeepsDisconnectAvailable(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	vault := credentials.NewWithBackend(backend)
	writer := newTestConnectionPersistence(t, path, vault)
	logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Index: "studio", Token: "stored-token", Enabled: true, ConnectionVerified: true}
	if err := writer.SaveLogs(logs); err != nil {
		t.Fatal(err)
	}
	backend.readFail = true
	reader := newTestConnectionPersistence(t, path, vault)
	metrics, traces := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
	if _, err := reader.Restore(&metrics, &traces, &logs); !errors.Is(err, credentials.ErrUnavailable) {
		t.Fatal(err)
	}
	if logs.Enabled || logs.Token != "" || logs.ConnectionVerified {
		t.Fatal("unavailable token remained active")
	}
	if err := reader.SaveLogs(logs); err != nil {
		t.Fatal("explicit Disconnect was blocked", err)
	}
	values, err := readConnectionSettings(path)
	if err != nil || values[logsSecretRef] != "" || len(backend.values) != 0 {
		t.Fatal("Disconnect kept the saved credential", err)
	}
}

func TestLogsHTTPDisconnectRecoversStoredCredentialFailures(t *testing.T) {
	for _, failure := range []string{"credential read", "credential cleanup"} {
		t.Run(failure, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "connections.json")
			backend := &testCredentialBackend{values: map[string]string{}}
			vault := credentials.NewWithBackend(backend)
			writer := newTestConnectionPersistence(t, path, vault)
			logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "stored-token", Index: "studio", Enabled: true, ConnectionVerified: true}
			if err := writer.SaveLogs(logs); err != nil {
				t.Fatal(err)
			}
			if failure == "credential cleanup" {
				backend.deleteFail = true
				logs.Token, logs.Enabled, logs.ConnectionVerified = "", false, false
				if err := writer.SaveLogs(logs); !errors.Is(err, api.ErrConnectionCleanupPending) {
					t.Fatal(err)
				}
			} else {
				backend.readFail = true
			}
			reader := newTestConnectionPersistence(t, path, vault)
			metrics, traces := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
			if _, err := reader.Restore(&metrics, &traces, &logs); err == nil {
				t.Fatal("credential failure was not reported")
			}
			controller := otlp.NewSplunkHECLogsExportController(logs)
			defer controller.Shutdown(context.Background())
			mux := http.NewServeMux()
			api.Register(mux, store.New(), api.SplunkLogsSettings{Controller: controller, Save: reader.SaveLogs, HasCredential: reader.HasLogsCredential})
			status := func() struct {
				Version                                   string
				CanDisconnect, TokenConfigured, Connected bool
			} {
				t.Helper()
				response := httptest.NewRecorder()
				mux.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/splunk/logs", nil))
				var value struct {
					Version                                   string
					CanDisconnect, TokenConfigured, Connected bool
				}
				if response.Code != 200 || json.Unmarshal(response.Body.Bytes(), &value) != nil {
					t.Fatal("status failed", response.Code)
				}
				return value
			}
			before := status()
			if !before.CanDisconnect || before.TokenConfigured || before.Connected {
				t.Fatal("saved credential cannot be forgotten from the disconnected state", before)
			}
			backend.readFail, backend.deleteFail = false, false
			body, _ := json.Marshal(map[string]string{"expectedVersion": before.Version})
			request := httptest.NewRequest(http.MethodPost, "/api/splunk/logs/disconnect", strings.NewReader(string(body)))
			request.RemoteAddr = "127.0.0.1:1234"
			request.Header.Set("Content-Type", "application/json")
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, request)
			after := status()
			if response.Code != 200 || after.CanDisconnect || after.Connected || after.TokenConfigured || len(backend.values) != 0 {
				t.Fatal("HTTP Disconnect did not finish credential cleanup", response.Code, after)
			}
		})
	}
}

func connectionTestRequest(t *testing.T, mux *http.ServeMux, method, path string, body map[string]any) *httptest.ResponseRecorder {
	t.Helper()
	encoded, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(method, "http://localhost"+path, strings.NewReader(string(encoded)))
	request.RemoteAddr = "127.0.0.1:1234"
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Obstudio-Browser-Request", "1")
	request.Header.Set("Origin", "http://localhost")
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	return response
}

func TestLogsNativeSaveKeepsCloudHTTPStatusResponsive(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud"}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "cloud"}
	if err := settings.SaveCloud(m, tr); err != nil {
		t.Fatal(err)
	}
	metrics, _ := otlp.NewSplunkMetricsExportController(m)
	traces, _ := otlp.NewSplunkTracesExportController(tr)
	logs := otlp.NewSplunkHECLogsExportController(otlp.SplunkHECLogsExporterConfig{})
	defer logs.Shutdown(context.Background())
	mux := http.NewServeMux()
	api.Register(mux, store.New(), metrics, traces, api.SplunkCloudStorageManaged(settings.CloudStorageManaged), api.SplunkCloudCleanupPending(settings.CloudCleanupPending), api.SplunkLogsSettings{Controller: logs, Save: settings.SaveLogs, HasCredential: settings.HasLogsCredential, CleanupPending: settings.LogsCleanupPending})
	started, release := make(chan struct{}), make(chan struct{})
	backend.afterSet = func() { close(started); <-release }
	released := false
	defer func() {
		if !released {
			close(release)
		}
	}()
	saved := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		saved <- connectionTestRequest(t, mux, "POST", "/api/splunk/logs", map[string]any{"expectedVersion": logs.Status().Version, "endpoint": "https://logs.example/services/collector", "token": "logs", "index": "studio", "enabled": false})
	}()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("save did not reach native storage")
	}
	status := make(chan *httptest.ResponseRecorder, 1)
	go func() { status <- connectionTestRequest(t, mux, "GET", "/api/splunk/export", nil) }()
	select {
	case response := <-status:
		var snapshot struct{ Connected, StorageManaged bool }
		if err := json.Unmarshal(response.Body.Bytes(), &snapshot); err != nil || response.Code != 200 || !snapshot.Connected || !snapshot.StorageManaged {
			t.Fatal("independent Cloud status changed", response.Body.String(), err)
		}
	case <-time.After(time.Second):
		t.Fatal("native logs save blocked independent Cloud status")
	}
	close(release)
	released = true
	select {
	case response := <-saved:
		if response.Code != 200 {
			t.Fatal(response.Body.String())
		}
	case <-time.After(time.Second):
		t.Fatal("save did not finish")
	}
}

func TestLogsHTTPRefreshReconcilesSavedSettings(t *testing.T) {
	for _, failure := range []string{"external change", "credential read", "unchanged credential read", "credential cleanup", "publication flush", "invalid settings", "invalid timeout", "directory sync"} {
		t.Run(failure, func(t *testing.T) {
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"code":0}`)) }))
			defer remote.Close()
			backend := &testCredentialBackend{values: map[string]string{}}
			vault := credentials.NewWithBackend(backend)
			path := filepath.Join(t.TempDir(), "connections.json")
			writer, reader := newTestConnectionPersistence(t, path, vault), newTestConnectionPersistence(t, path, vault)
			config := otlp.SplunkHECLogsExporterConfig{Endpoint: remote.URL + "/services/collector", Token: "first", Index: "studio", Enabled: true, ConnectionVerified: true, Timeout: time.Second}
			if err := writer.SaveLogs(config); err != nil {
				t.Fatal(err)
			}
			m, tr := otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}
			if _, err := reader.Restore(&m, &tr, &config); err != nil {
				t.Fatal(err)
			}
			logs := otlp.NewSplunkHECLogsExportController(config)
			defer logs.Shutdown(context.Background())
			payload := plog.NewLogs()
			payload.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty().LogRecords().AppendEmpty().Body().SetStr("accepted log")
			logs.QueueLogs(payload)
			deadline := time.Now().Add(2 * time.Second)
			for logs.Status().ExportedRecords != 1 && time.Now().Before(deadline) {
				time.Sleep(time.Millisecond)
			}
			if logs.Status().ExportedRecords != 1 {
				t.Fatal("test log did not export")
			}
			mux := http.NewServeMux()
			api.Register(mux, store.New(), api.SplunkLogsSettings{Controller: logs, Save: reader.SaveLogs, SavePreferences: reader.SaveLogsPreferences, HasCredential: reader.HasLogsCredential, CleanupPending: reader.LogsCleanupPending, Refresh: func() error { return reader.RefreshLogs(logs) }})
			if failure != "unchanged credential read" {
				config.Token, config.Index = "replacement", "updated"
			}
			if failure == "credential cleanup" {
				backend.deleteFail = true
			}
			var saveErr error
			if failure != "unchanged credential read" {
				saveErr = writer.SaveLogs(config)
			}
			if failure == "credential cleanup" {
				if !errors.Is(saveErr, api.ErrConnectionCleanupPending) {
					t.Fatal(saveErr)
				}
			} else if saveErr != nil {
				t.Fatal(saveErr)
			}
			if failure == "publication flush" {
				values, err := reader.values()
				if err != nil {
					t.Fatal(err)
				}
				values["logsIndex"] = "published"
				data, _ := json.Marshal(values)
				if err := writeDurableConnectionFileWithSync(path, data, func(target string) error {
					if target == path {
						return errors.New("flush failed")
					}
					return syncConnectionSettingsDirectory(target)
				}); !errors.Is(err, errConnectionSettingsPublished) {
					t.Fatal(err)
				}
				config.Index = "published"
			}
			if failure != "unchanged credential read" {
				stale := connectionTestRequest(t, mux, "POST", "/api/splunk/logs/enabled", map[string]any{"enabled": false, "expectedVersion": logs.Status().Version})
				if stale.Code != 409 {
					t.Fatal("stale settings were overwritten", stale.Body.String())
				}
			}
			var saved []byte
			if failure == "invalid settings" || failure == "invalid timeout" {
				var err error
				saved, err = os.ReadFile(path)
				if err != nil {
					t.Fatal(err)
				}
				if failure == "invalid settings" {
					err = os.WriteFile(path, []byte("{"), 0600)
				} else {
					err = writeConnectionSettings(path, map[string]string{"logsTimeout": "invalid"})
				}
				if err != nil {
					t.Fatal(err)
				}
			}
			if failure == "directory sync" {
				reader.syncDirectory = func(string) error { return errors.New("directory unavailable") }
			}
			if failure == "credential read" || failure == "unchanged credential read" {
				backend.readFail = true
			}
			if failure != "external change" && failure != "publication flush" {
				response := connectionTestRequest(t, mux, "POST", "/api/splunk/logs/refresh", map[string]any{})
				wantCode := 500
				if failure == "credential cleanup" {
					wantCode = 200
				}
				if response.Code != wantCode {
					t.Fatal("unexpected reload result", response.Code, response.Body.String())
				}
				if failure == "credential cleanup" {
					var status struct{ CleanupPending, Connected, Enabled bool }
					if err := json.Unmarshal(response.Body.Bytes(), &status); err != nil || !status.CleanupPending || !status.Connected || !status.Enabled {
						t.Fatal("active cleanup status lost", response.Body.String(), err)
					}
				} else if failure == "unchanged credential read" {
					if !logs.Status().Enabled || !logs.Status().TokenConfigured || logs.Config().Token != config.Token {
						t.Fatal("unchanged active credential was discarded")
					}
				} else if logs.Status().Enabled || logs.Status().TokenConfigured {
					t.Fatal("unreadable credentials remained active")
				}
			}
			backend.deleteFail, backend.readFail = false, false
			reader.syncDirectory = syncConnectionSettingsDirectory
			if saved != nil {
				if err := os.WriteFile(path, saved, 0600); err != nil {
					t.Fatal(err)
				}
			}
			response := connectionTestRequest(t, mux, "POST", "/api/splunk/logs/refresh", map[string]any{})
			if response.Code != 200 {
				t.Fatal(response.Body.String())
			}
			status := logs.Status()
			if !status.Enabled || !status.Connected || status.Index != config.Index || logs.Config().Token != config.Token || reader.LogsCleanupPending() {
				t.Fatal("refresh failed to reconcile saved connection", status)
			}
			if status.ExportedRecords != 1 {
				t.Fatal("cleanup/reload reset export activity", status)
			}
			response = connectionTestRequest(t, mux, "POST", "/api/splunk/logs/enabled", map[string]any{"enabled": false, "expectedVersion": status.Version})
			if response.Code != 200 || logs.Status().Enabled {
				t.Fatal("reconciled revision still rejected mutations", response.Body.String())
			}
		})
	}
}

func TestLogsHTTPReloadAllowsRepairingMalformedSettings(t *testing.T) {
	for _, action := range []string{"connect", "disconnect"} {
		t.Run(action, func(t *testing.T) {
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"code":0}`)) }))
			defer remote.Close()
			settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(&testCredentialBackend{values: map[string]string{}}))
			config := otlp.SplunkHECLogsExporterConfig{Endpoint: remote.URL + "/services/collector", Token: "synthetic-token", Index: "studio", ConnectionVerified: true}
			if err := settings.SaveLogs(config); err != nil {
				t.Fatal(err)
			}
			logs := otlp.NewSplunkHECLogsExportController(config)
			defer logs.Shutdown(context.Background())
			mux := http.NewServeMux()
			api.Register(mux, store.New(), api.SplunkLogsSettings{Controller: logs, Save: settings.SaveLogs, HasCredential: settings.HasLogsCredential, CleanupPending: settings.LogsCleanupPending, Refresh: func() error { return settings.RefreshLogs(logs) }})
			if err := writeConnectionSettings(settings.path, map[string]string{"logsTimeout": "invalid"}); err != nil {
				t.Fatal(err)
			}
			response := connectionTestRequest(t, mux, "POST", "/api/splunk/logs/refresh", map[string]any{})
			if response.Code != 500 {
				t.Fatal("malformed configuration was accepted", response.Body.String())
			}
			path := "/api/splunk/logs/disconnect"
			body := map[string]any{"expectedVersion": logs.Status().Version}
			if action == "connect" {
				path = "/api/splunk/logs"
				body["endpoint"], body["token"], body["index"], body["source"], body["verifyConnection"] = config.Endpoint, config.Token, "studio", "otel", true
			}
			response = connectionTestRequest(t, mux, "POST", path, body)
			if response.Code != 200 {
				t.Fatal("invalid saved settings blocked explicit recovery", response.Code, response.Body.String())
			}
			values, err := settings.values()
			if err != nil {
				t.Fatal(err)
			}
			if _, err := time.ParseDuration(values["logsTimeout"]); err != nil {
				t.Fatal("recovery did not replace malformed settings", err)
			}
			if logs.Status().Connected != (action == "connect") {
				t.Fatal("recovery did not apply the requested connection state")
			}
		})
	}
}

func TestLogsHTTPExportPreferencesDoNotRequireCredentialAccess(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	config := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "synthetic-token", Index: "studio", Enabled: true, ConnectionVerified: true}
	if err := settings.SaveLogs(config); err != nil {
		t.Fatal(err)
	}
	before := mustReadConnectionValues(t, settings.path)[logsSecretRef]
	logs := otlp.NewSplunkHECLogsExportController(config)
	defer logs.Shutdown(context.Background())
	mux := http.NewServeMux()
	api.Register(mux, store.New(), api.SplunkLogsSettings{Controller: logs, Save: settings.SaveLogs, SavePreferences: settings.SaveLogsPreferences})
	backend.fail = true
	for _, enabled := range []bool{false, true, false} {
		w := connectionTestRequest(t, mux, "POST", "/api/splunk/logs/enabled", map[string]any{"enabled": enabled, "expectedVersion": logs.Status().Version})
		values := mustReadConnectionValues(t, settings.path)
		if w.Code != http.StatusOK || logs.Status().Enabled != enabled || values["logsEnabled"] != strconv.FormatBool(enabled) || values[logsSecretRef] != before || len(backend.values) != 1 {
			t.Fatal("credential access blocked logs preference", w.Code, w.Body.String())
		}
	}
	config.Token = "replacement-token"
	if err := settings.SaveLogs(config); !errors.Is(err, credentials.ErrUnavailable) {
		t.Fatal("replacement bypassed secure storage", err)
	}
	if mustReadConnectionValues(t, settings.path)[logsSecretRef] != before {
		t.Fatal("failed replacement changed the saved credential")
	}
}

func TestConcurrentFirstConnectionsFlushJournalDirectoriesBeforeNativeWrite(t *testing.T) {
	for _, blockJournal := range []bool{false, true} {
		t.Run(strconv.FormatBool(blockJournal), func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("HOME", home)
			t.Setenv("USERPROFILE", home)
			root := filepath.Join(home, ".obstudio")
			journalDirectory := filepath.Join(root, "credential-cleanup")
			blockedDirectory := root
			if blockJournal {
				blockedDirectory = journalDirectory
			}
			firstBackend := &testCredentialBackend{values: map[string]string{}}
			secondBackend := &testCredentialBackend{values: map[string]string{}}
			first := newConnectionPersistence("", credentials.NewWithBackend(firstBackend))
			second := newConnectionPersistence(filepath.Join(root, "other.json"), credentials.NewWithBackend(secondBackend))
			created, release := make(chan struct{}), make(chan struct{})
			var once sync.Once
			first.syncDirectory = func(path string) error {
				if path == blockedDirectory {
					once.Do(func() { close(created); <-release })
				}
				return syncConnectionSettingsDirectory(path)
			}
			flushed := map[string]bool{}
			second.syncDirectory = func(path string) error {
				err := syncConnectionSettingsDirectory(path)
				if err == nil {
					flushed[path] = true
				}
				return err
			}
			secondBackend.beforeSet = func() {
				if !flushed[root] || !flushed[journalDirectory] {
					t.Error("native write preceded journal directory publication")
				}
			}
			m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "synthetic-token"}
			tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: m.AccessToken}
			done := make(chan error, 1)
			go func() { done <- first.SaveCloud(m, tr) }()
			t.Cleanup(func() {
				close(release)
				select {
				case err := <-done:
					if err != nil {
						t.Error(err)
					}
				case <-time.After(5 * time.Second):
					t.Error("first connection did not finish")
				}
			})
			select {
			case <-created:
			case <-time.After(5 * time.Second):
				t.Fatal("first connection did not create its directory")
			}
			if err := second.SaveCloud(m, tr); err != nil || len(secondBackend.values) != 1 {
				t.Fatal("concurrent connection could not publish its journal independently", err)
			}
		})
	}
}

func TestCloudPublishedPreferencesRemainConsistentDuringRecovery(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "token"}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "token"}
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	fail := true
	settings.syncDirectory = func(target string) error {
		if fail && target == settings.path {
			return errors.New("directory flush failed")
		}
		return syncConnectionSettingsDirectory(target)
	}
	metrics.Enabled, traces.Enabled = true, true
	if err := settings.SaveCloudPreferences(metrics, traces); !errors.Is(err, api.ErrConnectionCleanupPending) || !settings.CloudCleanupPending() {
		t.Fatal("visible publication must report a committed recovery state", err)
	}
	reopened := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	var restoredMetrics otlp.SplunkMetricsExporterConfig
	var restoredTraces otlp.SplunkTracesExporterConfig
	if err := reopened.RestoreCloud(&restoredMetrics, &restoredTraces); err != nil || !restoredMetrics.Enabled || !restoredTraces.Enabled || restoredMetrics.AccessToken != "token" {
		t.Fatal("restart disagreed with the reported published preference", err, restoredMetrics.Enabled, restoredTraces.Enabled)
	}
	fail = false
	if err := settings.RestoreCloud(&restoredMetrics, &restoredTraces); err != nil || settings.CloudCleanupPending() {
		t.Fatal("confirmed publication did not clear recovery", err)
	}

	fail = true
	metrics.AccessToken, traces.AccessToken = "replacement", "replacement"
	if err := settings.SaveCloud(metrics, traces); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal(err)
	}
	if err := settings.RestoreCloud(&restoredMetrics, &restoredTraces); !errors.Is(err, api.ErrConnectionCleanupPending) || restoredMetrics.AccessToken != "replacement" || len(backend.values) != 2 {
		t.Fatal("uncertain publication discarded rollback credentials or hid the visible connection", err, len(backend.values))
	}
	fail = false
	if err := settings.RestoreCloud(&restoredMetrics, &restoredTraces); err != nil || settings.CloudCleanupPending() || len(backend.values) != 1 {
		t.Fatal("confirmed publication did not finish credential cleanup", err, len(backend.values))
	}
}

func TestLogsPublishedPreferencesRemainConsistentDuringRecovery(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	config := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://stack.splunkcloud.com/services/collector", Token: "token", Index: "studio", ConnectionVerified: true}
	if err := settings.SaveLogs(config); err != nil {
		t.Fatal(err)
	}
	fail := true
	settings.syncDirectory = func(target string) error {
		if fail && target == settings.path {
			return errors.New("directory flush failed")
		}
		return syncConnectionSettingsDirectory(target)
	}
	config.Enabled = true
	if err := settings.SaveLogsPreferences(config); !errors.Is(err, api.ErrConnectionCleanupPending) || !settings.LogsCleanupPending() {
		t.Fatal("visible publication must report a committed recovery state", err)
	}
	reopened := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	var restored otlp.SplunkHECLogsExporterConfig
	if err := reopened.restoreLogs(&restored, nil, true); err != nil || !restored.Enabled || restored.Token != "token" {
		t.Fatal("restart disagreed with the reported published preference", err, restored.Enabled)
	}
	fail = false
	if err := settings.restoreLogs(&restored, nil, true); err != nil || settings.LogsCleanupPending() {
		t.Fatal("confirmed publication did not clear recovery", err)
	}
}

func TestCloudCredentialPublicationRejectsInterveningSettingsAndCleansCandidate(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "original", Enabled: true}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "original", Enabled: true}
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	started, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var once sync.Once
	unblock := func() { once.Do(func() { close(release) }) }
	var saveErr error
	backend.beforeSet = func() { close(started); <-release }
	metrics.AccessToken, traces.AccessToken = "replacement", "replacement"
	go func() { saveErr = settings.SaveCloud(metrics, traces); close(finished) }()
	t.Cleanup(func() {
		unblock()
		select {
		case <-finished:
		case <-time.After(time.Second):
			t.Error("credential writer did not finish")
		}
	})
	waitForCredentialSignal(t, started, "credential operation start")
	if err := settings.withSettingsLock(func() error {
		return writeConnectionSettings(settings.path, map[string]string{"metricsEnabled": "false", "tracesEnabled": "false"})
	}); err != nil {
		t.Fatal(err)
	}
	unblock()
	waitForCredentialSignal(t, finished, "credential operation completion")
	if !errors.Is(saveErr, api.ErrConnectionSettingsChanged) {
		t.Fatal("stale credential publication replaced a newer preference", saveErr)
	}
	values, err := settings.values()
	if err != nil || values["metricsEnabled"] != "false" || values["tracesEnabled"] != "false" || len(backend.values) != 1 {
		t.Fatal("conflicting save lost the preference or leaked its candidate", err, len(backend.values))
	}
	if entries, err := settings.credentialJournal(); err != nil || len(entries) != 1 || entries[0].Reference != values[cloudSecretRef] {
		t.Fatal("candidate cleanup lost the active credential", entries, err)
	}
}

func TestCredentialCleanupRetiresConfirmedSecretsBeforeUnconfirmedWrites(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	for _, ref := range []string{strings.Repeat("a", 43), strings.Repeat("b", 43)} {
		if err := settings.trackCredential("cloud", "destination", ref, true); err != nil {
			t.Fatal(err)
		}
	}
	retired, err := settings.reference("cloud", "destination", "retired-token", "")
	if err != nil {
		t.Fatal(err)
	}
	if err := settings.cleanupCredential("cloud", ""); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("unconfirmed creation must remain pending", err)
	}
	if _, err := settings.store.Get(settings.path, "cloud", "destination", retired); !errors.Is(err, credentials.ErrNotFound) {
		t.Fatal("unconfirmed writes blocked retirement of a confirmed secret", err)
	}
	entries, err := settings.credentialJournal()
	if err != nil || len(entries) != 2 || !entries[0].CreationPending || !entries[1].CreationPending {
		t.Fatal("cleanup lost unconfirmed write references", entries, err)
	}
}

func TestCredentialCleanupBoundsWorkAndRetainsRecoveryReferences(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	for i := 0; i < 3; i++ {
		if _, err := settings.reference("cloud", "", "orphan", ""); err != nil {
			t.Fatal(err)
		}
	}
	if err := settings.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{}); !errors.Is(err, api.ErrConnectionCleanupPending) {
		t.Fatal("cleanup must report unfinished work after its bounded pass", err)
	}
	if len(backend.values) != 1 || !settings.CloudCleanupPending() {
		t.Fatal("cleanup did not bound its native work or retain recovery", len(backend.values))
	}
	var metrics otlp.SplunkMetricsExporterConfig
	var traces otlp.SplunkTracesExporterConfig
	if err := settings.RestoreCloud(&metrics, &traces); err != nil || len(backend.values) != 0 || settings.CloudCleanupPending() {
		t.Fatal("a later recovery did not finish the retained work", err)
	}
}

func TestDestinationPreferencesAndDisconnectProceedDuringAnotherCredentialWrite(t *testing.T) {
	for _, writing := range []string{"cloud", "logs"} {
		for _, action := range []string{"pause", "disconnect"} {
			t.Run(writing+"/"+action, func(t *testing.T) {
				path := filepath.Join(t.TempDir(), "connections.json")
				backend := &testCredentialBackend{values: map[string]string{}}
				settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
				metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud-original", Enabled: true}
				traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "cloud-original", Enabled: true}
				logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "logs-original", Index: "studio", Enabled: true, ConnectionVerified: true}
				if err := settings.SaveCloud(metrics, traces); err != nil {
					t.Fatal(err)
				}
				if err := settings.SaveLogs(logs); err != nil {
					t.Fatal(err)
				}
				started, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
				var once sync.Once
				unblock := func() { once.Do(func() { close(release) }) }
				backend.beforeSet = func() { close(started); <-release }
				var saveErr error
				go func() {
					if writing == "cloud" {
						nextM, nextT := metrics, traces
						nextM.AccessToken, nextT.AccessToken = "cloud-new", "cloud-new"
						saveErr = settings.SaveCloud(nextM, nextT)
					} else {
						next := logs
						next.Token = "logs-new"
						saveErr = settings.SaveLogs(next)
					}
					close(finished)
				}()
				t.Cleanup(func() {
					unblock()
					select {
					case <-finished:
					case <-time.After(time.Second):
						t.Error("credential writer did not finish")
					}
				})
				waitForCredentialSignal(t, started, "credential operation start")
				changed := make(chan error, 1)
				go func() {
					if writing == "cloud" {
						next := logs
						next.Enabled = false
						if action == "disconnect" {
							next.Token, next.ConnectionVerified = "", false
							changed <- settings.SaveLogs(next)
						} else {
							changed <- settings.SaveLogsPreferences(next)
						}
					} else {
						nextM, nextT := metrics, traces
						nextM.Enabled, nextT.Enabled = false, false
						if action == "disconnect" {
							changed <- settings.SaveCloud(otlp.SplunkMetricsExporterConfig{}, otlp.SplunkTracesExporterConfig{})
						} else {
							changed <- settings.SaveCloudPreferences(nextM, nextT)
						}
					}
				}()
				select {
				case err := <-changed:
					if err != nil && !errors.Is(err, api.ErrConnectionCleanupPending) {
						t.Fatal(err)
					}
				case <-time.After(time.Second):
					t.Fatal("another destination's credential write blocked this export control")
				}
				select {
				case <-finished:
					t.Fatal("credential write was not still blocked")
				default:
				}
				unblock()
				waitForCredentialSignal(t, finished, "credential operation completion")
				if saveErr != nil {
					t.Fatal(saveErr)
				}
				values, err := settings.values()
				if err != nil {
					t.Fatal(err)
				}
				if writing == "cloud" {
					if values["logsEnabled"] == "true" || action == "disconnect" && values[logsSecretRef] != "" {
						t.Fatal("later Cloud publication lost the logs control", values)
					}
				} else if values["metricsEnabled"] == "true" || values["tracesEnabled"] == "true" || action == "disconnect" && values[cloudSecretRef] != "" {
					t.Fatal("later logs publication lost the Cloud control", values)
				}
			})
		}
	}
}

type deleteHookCredentialBackend struct {
	*testCredentialBackend
	beforeDelete func(string)
}

func (b *deleteHookCredentialBackend) Delete(key string) error {
	if b.beforeDelete != nil {
		b.beforeDelete(key)
	}
	return b.testCredentialBackend.Delete(key)
}

func TestCredentialCleanupPreservesAnotherDestinationJournalUpdates(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &deleteHookCredentialBackend{testCredentialBackend: &testCredentialBackend{values: map[string]string{}}}
	settings := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "cloud-original"}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "cloud-original"}
	logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "logs-original", Index: "studio"}
	if err := settings.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	if err := settings.SaveLogs(logs); err != nil {
		t.Fatal(err)
	}
	started, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var once sync.Once
	unblock := func() { once.Do(func() { close(release) }) }
	backend.beforeDelete = func(key string) {
		if strings.Contains(key, ".cloud.") {
			close(started)
			<-release
		}
	}
	var cloudErr error
	metrics.AccessToken, traces.AccessToken = "cloud-new", "cloud-new"
	go func() { cloudErr = settings.SaveCloud(metrics, traces); close(finished) }()
	t.Cleanup(func() {
		unblock()
		select {
		case <-finished:
		case <-time.After(time.Second):
			t.Error("credential cleanup did not finish")
		}
	})
	waitForCredentialSignal(t, started, "credential operation start")
	logs.Token = "logs-new"
	parallel := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	if err := parallel.SaveLogs(logs); err != nil {
		t.Fatal(err)
	}
	unblock()
	waitForCredentialSignal(t, finished, "credential operation completion")
	if cloudErr != nil {
		t.Fatal(cloudErr)
	}
	entries, err := settings.credentialJournal()
	if err != nil || len(entries) != 2 || len(backend.values) != 2 {
		t.Fatal("cleanup discarded another destination's references", entries, err)
	}
	reopened := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	var restoredMetrics otlp.SplunkMetricsExporterConfig
	var restoredTraces otlp.SplunkTracesExporterConfig
	var restoredLogs otlp.SplunkHECLogsExporterConfig
	cloudErr, logsErr := reopened.Restore(&restoredMetrics, &restoredTraces, &restoredLogs)
	if cloudErr != nil || logsErr != nil || restoredMetrics.AccessToken != "cloud-new" || restoredLogs.Token != "logs-new" {
		t.Fatal("parallel cleanup lost a saved credential", cloudErr, logsErr)
	}
}

func TestCloudRestoreLockFailureRequiresFreshSnapshotBeforeSave(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	writer := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	metrics := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "original", Enabled: true}
	traces := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "original", Enabled: true}
	if err := writer.SaveCloud(metrics, traces); err != nil {
		t.Fatal(err)
	}
	reader := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	reader.syncDirectory = func(string) error { return errors.New("directory unavailable") }
	if err := reader.RestoreCloud(&metrics, &traces); err == nil {
		t.Fatal("restore must report the lock preflight failure")
	}
	reader.syncDirectory = syncConnectionSettingsDirectory
	nextM := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "replacement", Enabled: true}
	nextT := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: "replacement", Enabled: true}
	if err := reader.SaveCloud(nextM, nextT); !errors.Is(err, api.ErrConnectionSettingsChanged) {
		t.Fatal("save accepted an unread snapshot", err)
	}
	if err := reader.RestoreCloud(&metrics, &traces); err != nil {
		t.Fatal(err)
	}
	if err := reader.SaveCloud(nextM, nextT); err != nil {
		t.Fatal("save failed after recovery", err)
	}
}

func TestLogsRestoreLockFailureRequiresFreshSnapshotBeforeSave(t *testing.T) {
	path := filepath.Join(t.TempDir(), "connections.json")
	backend := &testCredentialBackend{values: map[string]string{}}
	writer := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	logs := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "original", Index: "studio"}
	if err := writer.SaveLogs(logs); err != nil {
		t.Fatal(err)
	}
	reader := newTestConnectionPersistence(t, path, credentials.NewWithBackend(backend))
	reader.syncDirectory = func(string) error { return errors.New("directory unavailable") }
	if err := reader.restoreLogs(&logs, nil, true); err == nil {
		t.Fatal("restore must report the lock preflight failure")
	}
	reader.syncDirectory = syncConnectionSettingsDirectory
	next := otlp.SplunkHECLogsExporterConfig{Endpoint: "https://logs.example/services/collector", Token: "replacement", Index: "studio"}
	if err := reader.SaveLogs(next); !errors.Is(err, api.ErrConnectionSettingsChanged) {
		t.Fatal("save accepted an unread snapshot", err)
	}
	if err := reader.restoreLogs(&logs, nil, true); err != nil {
		t.Fatal(err)
	}
	if err := reader.SaveLogs(next); err != nil {
		t.Fatal("save failed after recovery", err)
	}
}

func TestNativeStorageRefusalOffersSessionFallback(t *testing.T) {
	backend := &testCredentialBackend{values: map[string]string{}, fail: true}
	settings := newTestConnectionPersistence(t, filepath.Join(t.TempDir(), "connections.json"), credentials.NewWithBackend(backend))
	m := otlp.SplunkMetricsExporterConfig{Realm: "us1", AccessToken: "synthetic-token"}
	tr := otlp.SplunkTracesExporterConfig{Realm: "us1", AccessToken: m.AccessToken}
	if err := settings.SaveCloud(m, tr); !errors.Is(err, api.ErrCredentialStorageUnavailable) || !errors.Is(err, credentials.ErrUnavailable) {
		t.Fatal("definite provider failure lost its classification", err)
	}
	if values, err := settings.values(); err != nil || values[cloudSecretRef] != "" {
		t.Fatal("refused token was published", err)
	}
}
