package main

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/credentials"
	"github.com/signalfx/obstudio/observer/internal/otlp"
)

var errConnectionSettingsPublished = errors.New("settings were published but durability could not be confirmed")

const cloudSecretRef = "cloudTokenRef"
const logsSecretRef = "logsTokenRef"

type connectionSnapshot struct {
	revision [32]byte
	ready    bool
}

type connectionPersistence struct {
	mu                 sync.Mutex
	path               string
	store              *credentials.Store
	journalPath        string
	syncDirectory      func(string) error
	revisions          sync.Map
	operationLocks     sync.Map
	publicationPending sync.Map
}

func newConnectionPersistence(settingsPath string, store *credentials.Store) *connectionPersistence {
	path := settingsPath
	if path == "" {
		home, err := os.UserHomeDir()
		if err != nil || home == "" {
			return &connectionPersistence{store: store, syncDirectory: syncConnectionSettingsDirectory}
		}
		path = filepath.Join(home, ".obstudio", "connections.json")
	}
	path, _ = filepath.Abs(path)
	canonical, pathErr := canonicalConnectionSettingsPath(path)
	if pathErr == nil {
		path = canonical
	}
	if store == nil {
		store = credentials.New()
	}
	home, _ := os.UserHomeDir()
	var journalPath string
	if home != "" && pathErr == nil {
		journalPath = filepath.Join(home, ".obstudio", "credential-cleanup", fmt.Sprintf("%x.json", sha256.Sum256([]byte(path))))
	}
	return &connectionPersistence{path: path, store: store, journalPath: journalPath, syncDirectory: syncConnectionSettingsDirectory}
}

func canonicalConnectionSettingsPath(path string) (string, error) {
	resolved, err := filepath.EvalSymlinks(path)
	if err == nil {
		return resolved, nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	// A missing file can still have a symlinked parent. A dangling file symlink is not writable.
	if info, statErr := os.Lstat(path); statErr == nil && info.Mode()&os.ModeSymlink != 0 {
		return "", err
	}
	parent := filepath.Dir(path)
	if parent == path {
		return "", err
	}
	resolved, err = canonicalConnectionSettingsPath(parent)
	if err != nil {
		return "", err
	}
	return filepath.Join(resolved, filepath.Base(path)), nil
}

func cloudSecretDestination(metrics otlp.SplunkMetricsExporterConfig, traces otlp.SplunkTracesExporterConfig) string {
	return strings.Join([]string{metrics.Realm, metrics.Endpoint, traces.Realm, traces.Endpoint}, "\x00")
}

func (p *connectionPersistence) reference(kind, destination, value, current string) (string, error) {
	if current != "" {
		if existing, err := p.store.Get(p.path, kind, destination, current); err == nil && existing == value {
			return current, nil
		}
	}
	var candidate string
	ref, err := p.store.Put(p.path, kind, destination, value, func(ref string) error {
		candidate = ref
		return p.withSettingsLock(func() error { return p.trackCredential(kind, destination, ref, true) })
	})
	if candidate != "" && errors.Is(err, credentials.ErrWriteNotStarted) {
		if cleanupErr := p.withSettingsLock(func() error {
			entries, err := p.credentialJournal()
			if err != nil {
				return err
			}
			entries = slices.DeleteFunc(entries, func(entry credentialReference) bool {
				return entry.Kind == kind && entry.Destination == destination && entry.Reference == candidate
			})
			return p.writeCredentialJournal(entries)
		}); cleanupErr != nil {
			return "", cleanupErr
		}
	} else if candidate != "" && !errors.Is(err, credentials.ErrWritePending) {
		if confirmErr := p.withSettingsLock(func() error { return p.trackCredential(kind, destination, candidate, false) }); confirmErr != nil {
			return "", confirmErr
		}
	}
	if errors.Is(err, credentials.ErrStorageRefused) {
		return "", errors.Join(api.ErrCredentialStorageUnavailable, err)
	}
	return ref, err
}

func (p *connectionPersistence) values() (map[string]string, error) {
	values, err := readConnectionSettings(p.path)
	if errors.Is(err, os.ErrNotExist) {
		return map[string]string{}, nil
	}
	return values, err
}

type credentialReference struct {
	Kind            string `json:"kind"`
	Destination     string `json:"destination"`
	Reference       string `json:"reference"`
	CreationPending bool   `json:"creationPending,omitempty"`
}

// Operations serialize per destination; only metadata transactions share a lock.
func (p *connectionPersistence) withConnectionLock(kind string, operation func() error) error {
	if p.path == "" {
		return credentials.ErrUnavailable
	}
	mutex, _ := p.operationLocks.LoadOrStore(kind, &sync.Mutex{})
	mutex.(*sync.Mutex).Lock()
	defer mutex.(*sync.Mutex).Unlock()
	if err := p.withSettingsLock(func() error { return nil }); err != nil {
		return err
	}
	return withTokenTelemetryStateLock(p.path+".connection-"+kind, operation)
}

const maxCredentialCleanupReferences = 2

func (p *connectionPersistence) withCredentialLock(operation func() error) error {
	if p.journalPath == "" || p.path == "" {
		return credentials.ErrUnavailable
	}
	return p.withSettingsLock(operation)
}

func (p *connectionPersistence) withSettingsLock(operation func() error) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.path == "" {
		return credentials.ErrUnavailable
	}
	if err := createConnectionDirectory(filepath.Dir(p.path), p.syncDirectory); err != nil {
		return err
	}
	// Another collector may have created either journal directory without yet
	// flushing it. Confirm both entries ourselves before native writes can start.
	if p.journalPath != "" {
		directory := filepath.Dir(p.journalPath)
		for _, path := range []string{filepath.Dir(directory), directory} {
			if err := createConnectionDirectory(path, p.syncDirectory); err != nil {
				return err
			}
			if err := p.syncDirectory(path); err != nil {
				return err
			}
		}
	}
	return withTokenTelemetryStateLock(p.path+".connection-state", func() error {
		pending := false
		p.publicationPending.Range(func(_, _ any) bool { pending = true; return false })
		if pending {
			if err := p.syncDirectory(p.path); err == nil {
				p.publicationPending.Clear()
			}
		}
		return operation()
	})
}

func (p *connectionPersistence) credentialJournal() ([]credentialReference, error) {
	data, err := os.ReadFile(p.journalPath)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var entries []credentialReference
	if json.Unmarshal(data, &entries) != nil || len(entries) > 256 {
		return nil, credentials.ErrUnavailable
	}
	return entries, nil
}

func (p *connectionPersistence) writeCredentialJournal(entries []credentialReference) error {
	data, err := json.Marshal(entries)
	if err != nil {
		return err
	}
	return writeDurableConnectionFileWithSync(p.journalPath, data, p.syncDirectory)
}

// The caller holds the connection lock across credential creation and settings publication.
func (p *connectionPersistence) trackCredential(kind, destination, ref string, creationPending bool) error {
	if ref == "" {
		return nil
	}
	entries, err := p.credentialJournal()
	if err != nil {
		return err
	}
	entry := credentialReference{Kind: kind, Destination: destination, Reference: ref, CreationPending: creationPending}
	for i, existing := range entries {
		if existing.Kind == kind && existing.Destination == destination && existing.Reference == ref {
			if existing == entry {
				return nil
			}
			entries[i] = entry
			return p.writeCredentialJournal(entries)
		}
	}
	if len(entries) >= 256 {
		return credentials.ErrUnavailable
	}
	return p.writeCredentialJournal(append(entries, entry))
}

func (p *connectionPersistence) cleanupCredential(kind, activeReference string) error {
	if _, pending := p.publicationPending.Load(kind); pending {
		return api.ErrConnectionCleanupPending
	}
	var entries []credentialReference
	if err := p.withSettingsLock(func() error {
		var err error
		entries, err = p.credentialJournal()
		return err
	}); err != nil {
		return api.ErrConnectionCleanupPending
	}
	removed := make(map[credentialReference]bool)
	// Unconfirmed writes must not consume the budget before known retirements.
	sort.SliceStable(entries, func(i, j int) bool { return !entries[i].CreationPending && entries[j].CreationPending })
	pending, synced, attempts := false, false, 0
	for _, entry := range entries {
		if entry.Kind != kind || entry.Reference == activeReference {
			continue
		}
		if attempts == maxCredentialCleanupReferences {
			pending = true
			continue
		}
		attempts++
		if !synced {
			if p.syncDirectory(p.path) != nil || p.syncDirectory(p.journalPath) != nil {
				return api.ErrConnectionCleanupPending
			}
			synced = true
		}
		var err error
		if entry.CreationPending {
			err = p.store.DeleteUnconfirmed(p.path, entry.Kind, entry.Destination, entry.Reference, func() error {
				return p.withSettingsLock(func() error { return p.trackCredential(entry.Kind, entry.Destination, entry.Reference, false) })
			})
		} else {
			err = p.store.Delete(p.path, entry.Kind, entry.Destination, entry.Reference)
		}
		if err != nil {
			pending = true
			continue
		}
		entry.CreationPending = false
		removed[entry] = true
	}
	if len(removed) > 0 {
		if err := p.withSettingsLock(func() error {
			current, err := p.credentialJournal()
			if err != nil {
				return err
			}
			remaining := make([]credentialReference, 0, len(current))
			for _, entry := range current {
				key := entry
				key.CreationPending = false
				if !removed[key] {
					remaining = append(remaining, entry)
				}
			}
			return p.writeCredentialJournal(remaining)
		}); err != nil {
			pending = true
		}
	}
	if pending {
		return api.ErrConnectionCleanupPending
	}
	return nil
}

func cloudConnectionKeys() []string {
	return []string{cloudSecretRef, "cloudStorageVersion", "cloudRealm", "metricsEnabled", "tracesEnabled", "metricsEndpoint", "tracesEndpoint"}
}

func connectionRevision(values map[string]string, keys []string) [32]byte {
	snapshot := make([]string, 0, len(keys)*2)
	for _, key := range keys {
		snapshot = append(snapshot, key, values[key])
	}
	data, _ := json.Marshal(snapshot)
	return sha256.Sum256(data)
}

func (p *connectionPersistence) rememberRevision(kind string, values map[string]string, keys []string) {
	p.revisions.Store(kind, connectionSnapshot{revision: connectionRevision(values, keys), ready: true})
}

func (p *connectionPersistence) checkRevision(kind string, values map[string]string, keys []string) error {
	if value, ok := p.revisions.Load(kind); ok {
		expected := value.(connectionSnapshot)
		if !expected.ready || expected.revision != connectionRevision(values, keys) {
			return api.ErrConnectionSettingsChanged
		}
	}
	return nil
}

func (p *connectionPersistence) SaveLogs(config otlp.SplunkHECLogsExporterConfig) error {
	return p.saveLogs(config, false)
}

func (p *connectionPersistence) SaveLogsPreferences(config otlp.SplunkHECLogsExporterConfig) error {
	return p.saveLogs(config, true)
}

func (p *connectionPersistence) saveLogs(config otlp.SplunkHECLogsExporterConfig, preferencesOnly bool) error {
	return p.withConnectionLock("logs", func() error {
		var previous map[string]string
		if err := p.withCredentialLock(func() error {
			var err error
			previous, err = p.values()
			if err != nil {
				return err
			}
			if err := p.checkRevision("logs", previous, logsConnectionKeys()); err != nil {
				return err
			}
			return p.trackCredential("logs", previous["logsEndpoint"], previous[logsSecretRef], false)
		}); err != nil {
			return err
		}
		values := logsSettingsValues(config)
		var ref string
		if preferencesOnly {
			if previous[logsSecretRef] == "" || previous["logsEndpoint"] != config.Endpoint {
				return api.ErrConnectionSettingsChanged
			}
			values = map[string]string{"logsEnabled": strconv.FormatBool(config.Enabled)}
			ref = previous[logsSecretRef]
		} else if config.Token != "" {
			var err error
			ref, err = p.reference("logs", config.Endpoint, config.Token, previous[logsSecretRef])
			if err != nil {
				_ = p.cleanupCurrentCredential("logs", logsSecretRef)
				return err
			}
		} else if config.Enabled || config.ConnectionVerified {
			return errors.New("a connected logs destination requires a HEC token")
		}
		values[logsSecretRef] = ref
		if err := p.publishConnection("logs", logsConnectionKeys(), previous, values); err != nil {
			if !errors.Is(err, api.ErrConnectionCleanupPending) {
				_ = p.cleanupCurrentCredential("logs", logsSecretRef)
			}
			return err
		}
		return p.cleanupCredential("logs", ref)
	})
}

func (p *connectionPersistence) HasLogsCredential() bool {
	values, err := p.values()
	if err != nil || values[logsSecretRef] != "" {
		return true
	}
	if p.journalPath == "" {
		return false
	}
	entries, err := p.credentialJournal()
	if err != nil {
		return true
	}
	for _, entry := range entries {
		if entry.Kind == "logs" {
			return true
		}
	}
	return false
}

func (p *connectionPersistence) publishConnection(kind string, keys []string, previous, changes map[string]string) error {
	return p.withSettingsLock(func() error {
		current, err := p.values()
		if err != nil {
			return err
		}
		if connectionRevision(current, keys) != connectionRevision(previous, keys) {
			return api.ErrConnectionSettingsChanged
		}
		publishErr := writeConnectionSettingsWithSync(p.path, changes, p.syncDirectory)
		if publishErr != nil && !errors.Is(publishErr, errConnectionSettingsPublished) {
			return publishErr
		}
		for key, value := range changes {
			current[key] = value
		}
		p.rememberRevision(kind, current, keys)
		if publishErr != nil {
			p.publicationPending.Store(kind, true)
			return api.ErrConnectionCleanupPending
		}
		p.publicationPending.Clear()
		return nil
	})
}

func (p *connectionPersistence) cleanupCurrentCredential(kind, referenceKey string) error {
	var active string
	if err := p.withSettingsLock(func() error {
		current, err := p.values()
		if err == nil {
			active = current[referenceKey]
		}
		return err
	}); err != nil {
		return api.ErrConnectionCleanupPending
	}
	return p.cleanupCredential(kind, active)
}

func (p *connectionPersistence) revision(kind string) connectionSnapshot {
	value, _ := p.revisions.Load(kind)
	snapshot, _ := value.(connectionSnapshot)
	return snapshot
}

func (p *connectionPersistence) SaveCloud(metrics otlp.SplunkMetricsExporterConfig, traces otlp.SplunkTracesExporterConfig) error {
	return p.saveCloud(metrics, traces, false)
}

func (p *connectionPersistence) SaveCloudPreferences(metrics otlp.SplunkMetricsExporterConfig, traces otlp.SplunkTracesExporterConfig) error {
	return p.saveCloud(metrics, traces, true)
}

func (p *connectionPersistence) saveCloud(metrics otlp.SplunkMetricsExporterConfig, traces otlp.SplunkTracesExporterConfig, preferencesOnly bool) error {
	if metrics.AccessToken == "" && (metrics.Realm != "" || traces.Realm != "" || metrics.Endpoint != "" || traces.Endpoint != "") {
		return credentials.ErrUnavailable
	}
	return p.withConnectionLock("cloud", func() error {
		var previous map[string]string
		err := p.withCredentialLock(func() error {
			var err error
			previous, err = p.values()
			if err != nil {
				return err
			}
			if err := p.checkRevision("cloud", previous, cloudConnectionKeys()); err != nil {
				return err
			}
			realm := previous["cloudRealm"]
			destination := cloudSecretDestination(otlp.SplunkMetricsExporterConfig{Realm: realm, Endpoint: previous["metricsEndpoint"]}, otlp.SplunkTracesExporterConfig{Realm: realm, Endpoint: previous["tracesEndpoint"]})
			return p.trackCredential("cloud", destination, previous[cloudSecretRef], false)
		})
		if err != nil {
			return err
		}
		values := map[string]string{
			"cloudStorageVersion": "1", "cloudRealm": metrics.Realm,
			"metricsEnabled": strconv.FormatBool(metrics.Enabled), "tracesEnabled": strconv.FormatBool(traces.Enabled),
			"metricsEndpoint": metrics.Endpoint, "tracesEndpoint": traces.Endpoint,
		}
		if preferencesOnly {
			realm := previous["cloudRealm"]
			destination := cloudSecretDestination(otlp.SplunkMetricsExporterConfig{Realm: realm, Endpoint: previous["metricsEndpoint"]}, otlp.SplunkTracesExporterConfig{Realm: realm, Endpoint: previous["tracesEndpoint"]})
			if previous[cloudSecretRef] == "" || cloudSecretDestination(metrics, traces) != destination {
				return api.ErrConnectionSettingsChanged
			}
			values[cloudSecretRef] = previous[cloudSecretRef]
		} else if metrics.AccessToken != "" {
			ref, err := p.reference("cloud", cloudSecretDestination(metrics, traces), metrics.AccessToken, previous[cloudSecretRef])
			if err != nil {
				_ = p.cleanupCurrentCredential("cloud", cloudSecretRef)
				return err
			}
			values[cloudSecretRef] = ref
		} else {
			for key := range values {
				if key != "cloudStorageVersion" {
					values[key] = ""
				}
			}
			values[cloudSecretRef] = ""
		}
		if err := p.publishConnection("cloud", cloudConnectionKeys(), previous, values); err != nil {
			if !errors.Is(err, api.ErrConnectionCleanupPending) {
				_ = p.cleanupCurrentCredential("cloud", cloudSecretRef)
			}
			return err
		}
		return p.cleanupCredential("cloud", values[cloudSecretRef])
	})
}

func (p *connectionPersistence) cloudConfiguration(values map[string]string, previousMetrics otlp.SplunkMetricsExporterConfig, previousTraces otlp.SplunkTracesExporterConfig) (otlp.SplunkMetricsExporterConfig, otlp.SplunkTracesExporterConfig, error) {
	metrics := otlp.SplunkMetricsExporterConfig{Enabled: values["metricsEnabled"] == "true", Realm: values["cloudRealm"], Endpoint: values["metricsEndpoint"]}
	traces := otlp.SplunkTracesExporterConfig{Enabled: values["tracesEnabled"] == "true", Realm: values["cloudRealm"], Endpoint: values["tracesEndpoint"]}
	var err error
	var token string
	if ref := values[cloudSecretRef]; ref != "" {
		token, err = p.store.Get(p.path, "cloud", cloudSecretDestination(metrics, traces), ref)
		if err != nil {
			metrics.Enabled, traces.Enabled = false, false
			return metrics, traces, credentials.ErrUnavailable
		}
	} else {
		metrics.Enabled, traces.Enabled = false, false
	}
	metrics.AccessToken, traces.AccessToken = token, token
	metrics.Timeout, traces.Timeout = previousMetrics.Timeout, previousTraces.Timeout
	return metrics, traces, nil
}

func (p *connectionPersistence) refreshCloud(values map[string]string, metrics splunkMetricsExportConfigurator, traces splunkTracesExportConfigurator) error {
	if _, err := os.Stat(p.path); err == nil {
		if err := syncConnectionSettingsDirectory(p.path); err != nil {
			return err
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	previousMetrics, previousTraces := metrics.Config(), traces.Config()
	metricsConfig, tracesConfig, loadErr := p.cloudConfiguration(values, previousMetrics, previousTraces)
	previousRevision := p.revision("cloud")
	if loadErr != nil && previousMetrics.AccessToken != "" && previousTraces.AccessToken != "" && previousRevision.ready && previousRevision.revision == connectionRevision(values, cloudConnectionKeys()) {
		return loadErr
	}
	metricsChanged := metricsConfig != previousMetrics
	if metricsChanged {
		if err := metrics.ConfigureKeepingActivity(metricsConfig); err != nil {
			return errors.Join(loadErr, err)
		}
	}
	if tracesConfig != previousTraces {
		if err := traces.ConfigureKeepingActivity(tracesConfig); err != nil {
			if metricsChanged {
				return errors.Join(loadErr, err, metrics.ConfigureKeepingActivity(previousMetrics))
			}
			return errors.Join(loadErr, err)
		}
	}
	p.rememberRevision("cloud", values, cloudConnectionKeys())
	if loadErr != nil {
		return loadErr
	}
	return p.cleanupCredential("cloud", values[cloudSecretRef])
}

func (p *connectionPersistence) RestoreCloud(metrics *otlp.SplunkMetricsExporterConfig, traces *otlp.SplunkTracesExporterConfig) error {
	return p.restoreCloud(metrics, traces, true)
}

func (p *connectionPersistence) restoreCloud(metrics *otlp.SplunkMetricsExporterConfig, traces *otlp.SplunkTracesExporterConfig, cleanup bool) error {
	p.revisions.Store("cloud", connectionSnapshot{})
	restore := func() error {
		var values map[string]string
		if err := p.withSettingsLock(func() error {
			var err error
			values, err = p.values()
			if err == nil {
				p.rememberRevision("cloud", values, cloudConnectionKeys())
			}
			return err
		}); err != nil {
			return err
		}
		if _, err := os.Stat(p.path); err == nil {
			if err := syncConnectionSettingsDirectory(p.path); err != nil {
				return err
			}
		} else if !errors.Is(err, os.ErrNotExist) {
			return err
		}
		nextMetrics, nextTraces, err := p.cloudConfiguration(values, *metrics, *traces)
		*metrics, *traces = nextMetrics, nextTraces
		if err != nil {
			return err
		}
		if cleanup {
			return p.cleanupCredential("cloud", values[cloudSecretRef])
		}
		return nil
	}
	var err error
	if cleanup {
		err = p.withConnectionLock("cloud", restore)
	} else {
		// The atomically saved snapshot and immutable reference can be read
		// without waiting for another collector's credential mutation.
		err = restore()
	}
	if err != nil && !errors.Is(err, api.ErrConnectionCleanupPending) {
		metrics.AccessToken, traces.AccessToken = "", ""
		metrics.Enabled, traces.Enabled = false, false
	}
	return err
}

func readConnectionSettings(path string) (map[string]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, 64*1024+1))
	if err != nil || len(data) > 64*1024 {
		return nil, credentials.ErrUnavailable
	}
	var values map[string]string
	if json.Unmarshal(data, &values) != nil || values == nil || values["schemaVersion"] != "1" {
		return nil, credentials.ErrUnavailable
	}
	return values, nil
}

func writeConnectionSettings(path string, changes map[string]string) error {
	return writeConnectionSettingsWithSync(path, changes, syncConnectionSettingsDirectory)
}

func writeConnectionSettingsWithSync(path string, changes map[string]string, syncDirectory func(string) error) error {
	values, err := readConnectionSettings(path)
	if errors.Is(err, os.ErrNotExist) {
		values = make(map[string]string)
	} else if err != nil {
		return err
	}
	for key, value := range changes {
		if value == "" {
			delete(values, key)
		} else {
			values[key] = value
		}
	}
	values["schemaVersion"] = "1"
	data, err := json.Marshal(values)
	if err != nil {
		return err
	}
	return writeDurableConnectionFileWithSync(path, data, syncDirectory)
}

func writeDurableConnectionFile(path string, data []byte) error {
	return writeDurableConnectionFileWithSync(path, data, syncConnectionSettingsDirectory)
}

func writeDurableConnectionFileWithSync(path string, data []byte, syncDirectory func(string) error) error {
	if err := createConnectionDirectory(filepath.Dir(path), syncDirectory); err != nil {
		return err
	}
	published := false
	err := writeConfigFileWith(path, data, 0o600, false, func(temporary, target string) error {
		if err := os.Rename(temporary, target); err != nil {
			return err
		}
		published = true
		return syncDirectory(target)
	})
	if err != nil && published {
		return fmt.Errorf("%w: %v", errConnectionSettingsPublished, err)
	}
	return err
}

func createConnectionDirectory(path string, syncDirectory func(string) error) error {
	info, err := os.Stat(path)
	if err == nil {
		if !info.IsDir() {
			return fmt.Errorf("connection path is not a directory")
		}
		return nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if err := createConnectionDirectory(filepath.Dir(path), syncDirectory); err != nil {
		return err
	}
	if err := os.Mkdir(path, 0700); err != nil && !errors.Is(err, os.ErrExist) {
		return err
	}
	return syncDirectory(path)
}

func syncConnectionSettingsDirectory(path string) error {
	if runtime.GOOS == "windows" {
		info, err := os.Stat(path)
		if errors.Is(err, os.ErrNotExist) {
			return syncConnectionSettingsDirectory(filepath.Dir(path))
		}
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		file, err := os.OpenFile(path, os.O_RDWR, 0)
		if err != nil {
			return err
		}
		defer file.Close()
		return file.Sync()
	}
	target, err := filepath.EvalSymlinks(path)
	if errors.Is(err, os.ErrNotExist) {
		target = path
	} else if err != nil {
		return err
	}
	directory, err := os.Open(filepath.Dir(target))
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}

// Status reads use atomically published files without waiting for native credential operations.
func (p *connectionPersistence) CloudStorageManaged() bool {
	values, err := p.values()
	return err == nil && values["cloudStorageVersion"] == "1"
}

func (p *connectionPersistence) Restore(metrics *otlp.SplunkMetricsExporterConfig, traces *otlp.SplunkTracesExporterConfig, logs *otlp.SplunkHECLogsExporterConfig) (error, error) {
	return p.restoreConnections(metrics, traces, logs, true)
}

func (p *connectionPersistence) restoreConnections(metrics *otlp.SplunkMetricsExporterConfig, traces *otlp.SplunkTracesExporterConfig, logs *otlp.SplunkHECLogsExporterConfig, cleanup bool) (error, error) {
	cloudDone := make(chan error, 1)
	go func() { cloudDone <- p.restoreCloud(metrics, traces, cleanup) }()
	logsErr := p.restoreLogs(logs, nil, cleanup)
	return <-cloudDone, logsErr
}

func (p *connectionPersistence) RefreshLogs(controller *otlp.SplunkHECLogsExportController) error {
	current := controller.Config()
	restored := current
	return p.restoreLogs(&restored, func(next otlp.SplunkHECLogsExporterConfig) error {
		next.Channel = current.Channel
		if next.Timeout <= 0 {
			next.Timeout = current.Timeout
		}
		if next == current {
			return nil
		}
		var exporter *otlp.SplunkHECLogsExporter
		var err error
		if next.Token != "" {
			exporter, err = otlp.NewSplunkHECLogsExporter(next)
			if err != nil {
				next.Token, next.Enabled, next.ConnectionVerified = "", false, false
			}
		}
		controller.ApplyKeepingActivity(next, exporter)
		return err
	}, true)
}

func (p *connectionPersistence) restoreLogs(logs *otlp.SplunkHECLogsExporterConfig, apply func(otlp.SplunkHECLogsExporterConfig) error, cleanup bool) error {
	reconciled := false
	previousRevision := p.revision("logs")
	p.revisions.Store("logs", connectionSnapshot{})
	restore := func() error {
		var values map[string]string
		if err := p.withSettingsLock(func() error {
			var err error
			values, err = p.values()
			return err
		}); err != nil {
			return err
		}
		if _, err := os.Stat(p.path); err == nil {
			if err := syncConnectionSettingsDirectory(p.path); err != nil {
				return err
			}
		} else if !errors.Is(err, os.ErrNotExist) {
			return err
		}
		p.rememberRevision("logs", values, logsConnectionKeys())
		next, err := logsConfigurationFromSettings(values)
		if err != nil {
			return err
		}
		var credentialErr error
		if ref := values[logsSecretRef]; ref != "" {
			next.Token, credentialErr = p.store.Get(p.path, "logs", next.Endpoint, ref)
		}
		if credentialErr != nil && apply != nil && logs.Token != "" && previousRevision.ready && previousRevision == p.revision("logs") {
			reconciled = true
			return credentials.ErrUnavailable
		}
		if credentialErr != nil || next.Token == "" {
			next.Token, next.Enabled, next.ConnectionVerified = "", false, false
		}
		if apply != nil {
			reconciled = true
			if err := apply(next); err != nil {
				return err
			}
		}
		*logs = next
		if credentialErr != nil {
			return credentials.ErrUnavailable
		}
		if cleanup {
			return p.cleanupCredential("logs", values[logsSecretRef])
		}
		return nil
	}
	var err error
	if cleanup {
		err = p.withConnectionLock("logs", restore)
	} else {
		err = restore()
	}
	if err != nil && !errors.Is(err, api.ErrConnectionCleanupPending) && !reconciled {
		logs.Token, logs.Enabled, logs.ConnectionVerified = "", false, false
		if apply != nil {
			return errors.Join(err, apply(*logs))
		}
	}
	return err
}

func (p *connectionPersistence) LogsCleanupPending() bool {
	return p.connectionCleanupPending("logs", logsSecretRef)
}

func (p *connectionPersistence) CloudCleanupPending() bool {
	return p.connectionCleanupPending("cloud", cloudSecretRef)
}

func (p *connectionPersistence) connectionCleanupPending(kind, referenceKey string) bool {
	if _, pending := p.publicationPending.Load(kind); pending {
		return true
	}
	values, err := p.values()
	if err != nil {
		return true
	}
	entries, err := p.credentialJournal()
	if err != nil {
		return true
	}
	for _, entry := range entries {
		if entry.Kind == kind && entry.Reference != values[referenceKey] {
			return true
		}
	}
	return false
}
