package main

import (
	"fmt"
	"github.com/signalfx/obstudio/observer/internal/otlp"
	"strconv"
	"time"
)

func logsSettingsValues(config otlp.SplunkHECLogsExporterConfig) map[string]string {
	return map[string]string{
		"logsEnabled":    strconv.FormatBool(config.Enabled),
		"logsVerified":   strconv.FormatBool(config.ConnectionVerified),
		"logsEndpoint":   config.Endpoint,
		"logsIndex":      config.Index,
		"logsSource":     config.Source,
		"logsSourcetype": config.Sourcetype,
		"logsInsecure":   strconv.FormatBool(config.InsecureSkipVerify),
		"logsTimeout":    config.Timeout.String(),
	}
}

func logsConnectionKeys() []string {
	return []string{logsSecretRef, "logsEnabled", "logsVerified", "logsEndpoint", "logsIndex", "logsSource", "logsSourcetype", "logsInsecure", "logsTimeout"}
}

func logsConfigurationFromSettings(values map[string]string) (otlp.SplunkHECLogsExporterConfig, error) {
	var timeout time.Duration
	if value := values["logsTimeout"]; value != "" {
		var err error
		timeout, err = time.ParseDuration(value)
		if err != nil {
			return otlp.SplunkHECLogsExporterConfig{}, fmt.Errorf("saved logs timeout is invalid")
		}
	}
	source, sourcetype := values["logsSource"], values["logsSourcetype"]
	if source == "" {
		source = "otel"
	}
	if sourcetype == "" {
		sourcetype = "otel:logs"
	}
	return otlp.SplunkHECLogsExporterConfig{
		Enabled: values["logsEnabled"] == "true", ConnectionVerified: values["logsVerified"] == "true",
		Endpoint: values["logsEndpoint"], Index: values["logsIndex"], Source: source, Sourcetype: sourcetype,
		InsecureSkipVerify: values["logsInsecure"] == "true", Timeout: timeout,
	}, nil
}
