package main

import (
	"os"
	"strconv"

	"github.com/signalfx/obstudio/observer/internal/otlp"
)

func logsSettingsValues(config otlp.SplunkHECLogsExporterConfig) map[string]string {
	values := map[string]string{
		"OBSTUDIO_SPLUNK_LOGS_EXPORT":     strconv.FormatBool(config.Enabled),
		"OBSTUDIO_SPLUNK_LOGS_VERIFIED":   strconv.FormatBool(config.ConnectionVerified),
		"OBSTUDIO_SPLUNK_HEC_URL":         config.Endpoint,
		"OBSTUDIO_SPLUNK_LOGS_INDEX":      config.Index,
		"OBSTUDIO_SPLUNK_LOGS_SOURCE":     config.Source,
		"OBSTUDIO_SPLUNK_LOGS_SOURCETYPE": config.Sourcetype,
		"OBSTUDIO_SPLUNK_HEC_INSECURE":    strconv.FormatBool(config.InsecureSkipVerify),
		"OBSTUDIO_SPLUNK_LOGS_TIMEOUT":    config.Timeout.String(),
	}
	if _, ok := os.LookupEnv("SPLUNK_LOGS_EXPORT"); ok {
		values["SPLUNK_LOGS_EXPORT"] = strconv.FormatBool(config.Enabled)
	}
	return values
}
