package api

import (
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
)

// SplunkLogsSettings connects local persistence to the live logs controller.
type SplunkLogsSettings struct {
	Controller *otlp.SplunkHECLogsExportController
	Save       func(otlp.SplunkHECLogsExporterConfig) error
}

func registerSplunkLogs(mux *http.ServeMux, settings SplunkLogsSettings, cloud *splunkExportService) {
	if settings.Controller == nil {
		return
	}
	var mu sync.Mutex
	mux.HandleFunc("GET /api/splunk/logs", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		writeJSON(w, settings.Controller.Status())
	})
	save := func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if cloud != nil {
			cloud.mu.Lock()
			defer cloud.mu.Unlock()
		}
		var request struct {
			Endpoint           string `json:"endpoint"`
			Token              string `json:"token"`
			Index              string `json:"index"`
			Source             string `json:"source"`
			Enabled            *bool  `json:"enabled"`
			InsecureSkipVerify bool   `json:"insecureSkipVerify"`
			ExpectedVersion    string `json:"expectedVersion"`
		}
		if err := decodeStrictJSON(w, r, &request); err != nil {
			writeSplunkExportError(w, 400, err.Error())
			return
		}
		if request.ExpectedVersion != settings.Controller.Status().Version {
			writeSplunkExportError(w, 409, "Logs settings changed. Try saving again.")
			return
		}
		previous := settings.Controller.Config()
		config := previous
		config.Endpoint, config.Index, config.Source = strings.TrimSpace(request.Endpoint), strings.TrimSpace(request.Index), strings.TrimSpace(request.Source)
		config.InsecureSkipVerify = request.InsecureSkipVerify
		if request.Enabled != nil {
			config.Enabled = *request.Enabled
		} else if cloud != nil {
			config.Enabled = cloud.snapshotLocked().Enabled
		}
		if request.Token != "" {
			config.Token = strings.TrimSpace(request.Token)
		} else if config.Endpoint != previous.Endpoint {
			writeSplunkExportError(w, 400, "Paste a HEC token when changing the endpoint.")
			return
		}
		for _, value := range []string{config.Endpoint, config.Token, config.Index, config.Source, config.Sourcetype} {
			if strings.IndexFunc(value, unicode.IsControl) >= 0 {
				writeSplunkExportError(w, http.StatusBadRequest, "Logs settings must not contain control characters.")
				return
			}
		}
		parsed, err := url.Parse(config.Endpoint)
		if err != nil || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" ||
			(parsed.Scheme != "https" && parsed.Scheme != "http") ||
			(parsed.Path != "/services/collector" && parsed.Path != "/services/collector/event") || len(config.Endpoint) > 2048 {
			writeSplunkExportError(w, 400, "Enter a full HTTP or HTTPS HEC endpoint ending in /services/collector or /services/collector/event.")
			return
		}
		if (config.Enabled && config.Index == "") || len(config.Index) > 256 || strings.ContainsAny(config.Index+config.Source, "\r\n") || len(config.Source) > 1024 {
			writeSplunkExportError(w, 400, "Enter a valid index and source.")
			return
		}
		if strings.TrimSpace(config.Token) == "" || len(config.Token) > 4096 || strings.ContainsAny(config.Token, "\r\n\t ") {
			writeSplunkExportError(w, 400, "Paste the complete HEC token.")
			return
		}
		if config.Sourcetype == "" {
			config.Sourcetype = "otel:logs"
		}
		config.Timeout = 8 * time.Second
		candidate, err := otlp.NewSplunkHECLogsExporter(config)
		if err != nil {
			writeSplunkExportError(w, 400, "Invalid HEC configuration.")
			return
		}
		if config.Enabled {
			logs := plog.NewLogs()
			record := logs.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty().LogRecords().AppendEmpty()
			record.SetTimestamp(pcommon.NewTimestampFromTime(time.Now()))
			record.Body().SetStr("Splunk Observability Studio logs connection test")
			if err := candidate.ExportLogs(r.Context(), logs); err != nil {
				writeSplunkExportError(w, 502, fmt.Sprintf("HEC connection test failed: %s", err))
				return
			}
		}
		if settings.Save == nil {
			writeSplunkExportError(w, 503, "Saving logs settings is unavailable in this host.")
			return
		}
		if err := settings.Save(config); err != nil {
			writeSplunkExportError(w, 500, "Could not save logs settings. Check the env file permissions and launch environment.")
			return
		}
		settings.Controller.Apply(config, candidate)
		if cloud != nil {
			cloud.clearRollbackLocked()
		}
		w.Header().Set("Cache-Control", "no-store")
		writeSameOriginJSON(w, settings.Controller.Status())
	}
	if cloud != nil {
		save = cloud.serializeMutation(save)
	}
	mux.HandleFunc("POST /api/splunk/logs", localMutation(save))
}
