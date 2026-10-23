package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func newSplunkLogsSettingsSaver(flagValue string) func(otlp.SplunkHECLogsExporterConfig) error {
	return func(config otlp.SplunkHECLogsExporterConfig) error {
		path, _ := configuredEnvFilePath(flagValue)
		content, err := os.ReadFile(path)
		if err != nil && !os.IsNotExist(err) {
			return err
		}
		values := map[string]string{
			"OBSTUDIO_SPLUNK_LOGS_EXPORT":     strconv.FormatBool(config.Enabled),
			"OBSTUDIO_SPLUNK_HEC_URL":         config.Endpoint,
			"OBSTUDIO_SPLUNK_HEC_TOKEN":       config.Token,
			"OBSTUDIO_SPLUNK_LOGS_INDEX":      config.Index,
			"OBSTUDIO_SPLUNK_LOGS_SOURCE":     config.Source,
			"OBSTUDIO_SPLUNK_LOGS_SOURCETYPE": config.Sourcetype,
			"OBSTUDIO_SPLUNK_HEC_INSECURE":    strconv.FormatBool(config.InsecureSkipVerify),
			"OBSTUDIO_SPLUNK_LOGS_TIMEOUT":    config.Timeout.String(),
		}
		if _, ok := os.LookupEnv("SPLUNK_LOGS_EXPORT"); ok {
			values["SPLUNK_LOGS_EXPORT"] = strconv.FormatBool(config.Enabled)
		}
		envFileShellPrecedence.Lock()
		for key := range values {
			if _, shell := envFileShellPrecedence.keys[key]; shell {
				envFileShellPrecedence.Unlock()
				return fmt.Errorf("%s is controlled by the launch environment", key)
			}
		}
		envFileShellPrecedence.Unlock()
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
					output = append(output, key+"="+("\""+value+"\""))
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
			output = append(output, key+"="+("\""+remaining[key]+"\""))
		}
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			return err
		}
		file, err := os.CreateTemp(filepath.Dir(path), ".logs-env-*")
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
}
