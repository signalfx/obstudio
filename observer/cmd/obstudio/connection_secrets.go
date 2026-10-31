package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/credentials"
	"github.com/signalfx/obstudio/observer/internal/otlp"
)

const cloudSecretRef = "OBSTUDIO_SPLUNK_CLOUD_SECRET_REF"

type connectionPersistence struct {
	mu    sync.Mutex
	path  string
	store *credentials.Store
}

func newConnectionPersistence(flagValue string, store *credentials.Store) *connectionPersistence {
	path, _ := configuredEnvFilePath(flagValue)
	path, _ = filepath.Abs(path)
	if store == nil {
		store = credentials.New()
	}
	return &connectionPersistence{path: path, store: store}
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
	return p.store.Put(p.path, kind, destination, value)
}

func (p *connectionPersistence) values() (map[string]string, error) {
	values, err := readEnvFile(p.path)
	if errors.Is(err, os.ErrNotExist) {
		return map[string]string{}, nil
	}
	return values, err
}

func checkConnectionShellControl(keys ...string) error {
	envFileShellPrecedence.Lock()
	defer envFileShellPrecedence.Unlock()
	for _, key := range keys {
		if _, ok := envFileShellPrecedence.keys[key]; ok {
			return fmt.Errorf("%s: %w", key, api.ErrSplunkCloudLaunchControlled)
		}
	}
	return nil
}

func (p *connectionPersistence) SaveCloud(metrics otlp.SplunkMetricsExporterConfig, traces otlp.SplunkTracesExporterConfig) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	keys := append(append([]string{}, splunkEnvFilePrecedenceKeys...), splunkEnvFileLegacyEndpointKeys...)
	if err := checkConnectionShellControl(keys...); err != nil {
		return err
	}
	previous, err := p.values()
	if err != nil {
		return err
	}
	values := map[string]string{
		"OBSTUDIO_SPLUNK_CLOUD_STORAGE_VERSION": "1",
		"OBSTUDIO_SPLUNK_REALM":                 metrics.Realm,
		"OBSTUDIO_SPLUNK_METRICS_EXPORT":        strconv.FormatBool(metrics.Enabled),
		"OBSTUDIO_SPLUNK_TRACES_EXPORT":         strconv.FormatBool(traces.Enabled),
		"OBSTUDIO_SPLUNK_METRICS_ENDPOINT":      metrics.Endpoint,
		"OBSTUDIO_SPLUNK_TRACES_ENDPOINT":       traces.Endpoint,
	}
	for key, value := range map[string]bool{"SPLUNK_METRICS_EXPORT": metrics.Enabled, "SPLUNK_TRACES_EXPORT": traces.Enabled} {
		if _, ok := previous[key]; ok {
			values[key] = strconv.FormatBool(value)
		}
	}
	if metrics.AccessToken != "" {
		ref, err := p.reference("cloud", cloudSecretDestination(metrics, traces), metrics.AccessToken, previous[cloudSecretRef])
		if err != nil {
			return err
		}
		values[cloudSecretRef] = ref
	} else {
		for key := range values {
			if key != "OBSTUDIO_SPLUNK_CLOUD_STORAGE_VERSION" {
				values[key] = ""
			}
		}
		values[cloudSecretRef] = ""
	}
	if err := writeConnectionSettings(p.path, values, "SPLUNK_ACCESS_TOKEN", "SPLUNK_REALM"); err != nil {
		if values[cloudSecretRef] != previous[cloudSecretRef] {
			p.store.Delete(p.path, "cloud", cloudSecretDestination(metrics, traces), values[cloudSecretRef])
		}
		return err
	}
	if values[cloudSecretRef] != previous[cloudSecretRef] {
		realm := firstNonEmpty(previous["OBSTUDIO_SPLUNK_REALM"], previous["SPLUNK_REALM"])
		previousMetrics := otlp.SplunkMetricsExporterConfig{Realm: realm, Endpoint: previous["OBSTUDIO_SPLUNK_METRICS_ENDPOINT"]}
		previousTraces := otlp.SplunkTracesExporterConfig{Realm: realm, Endpoint: previous["OBSTUDIO_SPLUNK_TRACES_ENDPOINT"]}
		p.store.Delete(p.path, "cloud", cloudSecretDestination(previousMetrics, previousTraces), previous[cloudSecretRef])
	}
	return nil
}

func (p *connectionPersistence) RefreshCloud(values map[string]string, metrics splunkMetricsExportConfigurator, traces splunkTracesExportConfigurator) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	metricsConfig, err := splunkMetricsExporterConfigFromValues(values)
	if err != nil {
		return err
	}
	tracesConfig, err := splunkTracesExporterConfigFromValues(values)
	if err != nil {
		return err
	}
	token, err := p.store.Get(p.path, "cloud", cloudSecretDestination(metricsConfig, tracesConfig), values[cloudSecretRef])
	if err != nil {
		return credentials.ErrUnavailable
	}
	metricsConfig.AccessToken, tracesConfig.AccessToken = token, token
	previousMetrics, previousTraces := metrics.Config(), traces.Config()
	metricsConfig.Timeout, tracesConfig.Timeout = previousMetrics.Timeout, previousTraces.Timeout
	metricsChanged := metricsConfig != previousMetrics
	if metricsChanged {
		if err := metrics.Configure(metricsConfig); err != nil {
			return err
		}
	}
	if tracesConfig != previousTraces {
		if err := traces.Configure(tracesConfig); err != nil {
			if metricsChanged {
				return errors.Join(err, metrics.Configure(previousMetrics))
			}
			return err
		}
	}
	return nil
}

func (p *connectionPersistence) restore(kind, destination, key string, launchKeys []string, current string) (string, error) {
	values, err := p.values()
	if err != nil {
		return "", err
	}
	ref := values[key]
	// Explicit launch credentials remain operator-owned and are never copied to a file.
	for _, name := range launchKeys {
		if checkConnectionShellControl(name) != nil {
			return current, nil
		}
	}
	if ref == "" {
		return current, nil
	}
	value, err := p.store.Get(p.path, kind, destination, ref)
	if err != nil {
		return "", credentials.ErrUnavailable
	}
	return value, nil
}

func (p *connectionPersistence) RestoreCloud(metrics *otlp.SplunkMetricsExporterConfig, traces *otlp.SplunkTracesExporterConfig) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	token, err := p.restore("cloud", cloudSecretDestination(*metrics, *traces), cloudSecretRef, []string{"SPLUNK_ACCESS_TOKEN"}, metrics.AccessToken)
	if err != nil {
		metrics.AccessToken, traces.AccessToken = "", ""
		metrics.Enabled, traces.Enabled = false, false
		return err
	}
	metrics.AccessToken, traces.AccessToken = token, token
	return nil
}

func writeConnectionSettings(path string, values map[string]string, removeKeys ...string) error {
	content, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	for _, key := range removeKeys {
		values[key] = ""
	}

	remaining := make(map[string]string, len(values))
	for key, value := range values {
		remaining[key] = value
	}
	var output []string
	for _, line := range strings.Split(strings.TrimSuffix(string(content), "\n"), "\n") {
		key, _, ok, parseErr := parseEnvLine(line)
		if parseErr != nil {
			return parseErr
		}
		if _, replace := values[key]; ok && replace {
			if value, first := remaining[key]; first {
				if value != "" {
					output = append(output, key+"="+("\""+value+"\""))
				}
				delete(remaining, key)
			}
		} else {
			output = append(output, line)
		}
	}
	keys := make([]string, 0, len(remaining))
	for key := range remaining {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		if remaining[key] != "" {
			output = append(output, key+"="+("\""+remaining[key]+"\""))
		}
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	file, err := os.CreateTemp(filepath.Dir(path), ".connections-env-*")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	if _, err = file.WriteString(strings.Join(output, "\n") + "\n"); err != nil {
		file.Close()
		return err
	}
	if err = file.Sync(); err != nil {
		file.Close()
		return err
	}
	if err = file.Close(); err != nil {
		return err
	}
	return os.Rename(file.Name(), path)
}

func (p *connectionPersistence) CloudStorageManaged() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	values, err := p.values()
	return err == nil && values["OBSTUDIO_SPLUNK_CLOUD_STORAGE_VERSION"] == "1"
}
