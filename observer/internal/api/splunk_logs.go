package api

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
)

// SplunkLogsSettings connects local persistence to the live logs controller.
type SplunkLogsSettings struct {
	Controller *otlp.SplunkHECLogsExportController
	Save       func(otlp.SplunkHECLogsExporterConfig) error
}

func registerSplunkLogs(mux *http.ServeMux, local *store.Store, settings SplunkLogsSettings, cloud *splunkExportService) {
	if settings.Controller == nil {
		return
	}
	var mu sync.Mutex
	mux.HandleFunc("GET /api/splunk/logs", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		writeSameOriginJSON(w, settings.Controller.Status())
	})
	save := func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		var request struct {
			Endpoint           string `json:"endpoint"`
			Token              string `json:"token"`
			Index              string `json:"index"`
			Source             string `json:"source"`
			Enabled            *bool  `json:"enabled"`
			VerifyConnection   bool   `json:"verifyConnection"`
			PreserveEnabled    bool   `json:"preserveEnabled"`
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
			config.Enabled = cloud.snapshot().Enabled
		}
		if request.PreserveEnabled {
			config.Enabled = previous.Enabled
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
		if ((config.Enabled || request.VerifyConnection) && config.Index == "") || len(config.Index) > 256 || strings.ContainsAny(config.Index+config.Source, "\r\n") || len(config.Source) > 1024 {
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
		config.ConnectionVerified = previous.ConnectionVerified && config.Endpoint == previous.Endpoint &&
			config.Token == previous.Token && config.Index == previous.Index && config.InsecureSkipVerify == previous.InsecureSkipVerify
		candidate, err := otlp.NewSplunkHECLogsExporter(config)
		if err != nil {
			writeSplunkExportError(w, 400, "Invalid HEC configuration.")
			return
		}
		defer func() {
			if candidate != nil {
				candidate.Shutdown(context.Background())
			}
		}()
		if config.Enabled || request.VerifyConnection {
			logs := plog.NewLogs()
			resource := logs.ResourceLogs().AppendEmpty()
			resource.Resource().Attributes().PutStr("service.name", "obstudio")
			scope := resource.ScopeLogs().AppendEmpty()
			scope.Scope().SetName("obstudio.splunk.logs")
			record := scope.LogRecords().AppendEmpty()
			record.SetTimestamp(pcommon.NewTimestampFromTime(time.Now()))
			record.SetSeverityNumber(plog.SeverityNumberInfo)
			record.SetSeverityText("INFO")
			record.Body().SetStr("Splunk Observability Studio logs connection test")
			local.AddInternalLogs(otlp.ConvertLogs(logs))
			probeCtx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
			defer cancel()
			if err := candidate.ExportLogs(probeCtx, logs); err != nil {
				writeSplunkExportError(w, 502, fmt.Sprintf("HEC connection test failed: %s", err))
				return
			}
			config.ConnectionVerified = true
		}
		if request.ExpectedVersion != settings.Controller.Status().Version {
			writeSplunkExportError(w, http.StatusConflict, "Logs settings changed. Try again.")
			return
		}
		if settings.Save == nil {
			writeSplunkExportError(w, 503, "Saving logs settings is unavailable in this host.")
			return
		}
		if err := settings.Save(config); err != nil {
			writeSplunkExportError(w, 500, "Could not save logs settings. Check secure credential storage, file permissions, and the launch environment.")
			return
		}
		if request.PreserveEnabled {
			settings.Controller.ApplyKeepingActivity(config, candidate)
		} else {
			settings.Controller.Apply(config, candidate)
		}
		candidate = nil
		if cloud != nil {
			cloud.mu.Lock()
			cloud.clearRollbackLocked()
			cloud.mu.Unlock()
		}
		w.Header().Set("Cache-Control", "no-store")
		writeSameOriginJSON(w, settings.Controller.Status())
	}
	if cloud != nil {
		save = cloud.serializeMutation(save)
	}
	mux.HandleFunc("POST /api/splunk/logs", localMutation(save))
	toggle := func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		var request struct {
			Enabled         *bool  `json:"enabled"`
			ExpectedVersion string `json:"expectedVersion"`
		}
		if err := decodeStrictJSON(w, r, &request); err != nil {
			writeSplunkExportError(w, http.StatusBadRequest, err.Error())
			return
		}
		status := settings.Controller.Status()
		if request.Enabled == nil {
			writeSplunkExportError(w, http.StatusBadRequest, "enabled must be a boolean")
			return
		}
		if request.ExpectedVersion != status.Version {
			writeSplunkExportError(w, http.StatusConflict, "Logs settings changed. Try again.")
			return
		}
		if *request.Enabled && !status.Connected {
			writeSplunkExportError(w, http.StatusConflict, "Verify the logs connection before enabling export.")
			return
		}
		previous := settings.Controller.Config()
		config := previous
		config.Enabled = *request.Enabled
		config.ConnectionVerified = status.Connected
		if config.Enabled {
			if err := otlp.ValidateSplunkHECLogsExporterConfig(config); err != nil {
				writeSplunkExportError(w, http.StatusBadRequest, "Reconnect logs with a valid HEC configuration before enabling export.")
				return
			}
		}
		if settings.Save == nil {
			writeSplunkExportError(w, http.StatusServiceUnavailable, "Saving logs settings is unavailable in this host.")
			return
		}
		if err := settings.Save(config); err != nil {
			writeSplunkExportError(w, http.StatusInternalServerError, "Could not save logs export state.")
			return
		}
		if err := settings.Controller.SetEnabled(config.Enabled); err != nil {
			if rollbackErr := settings.Save(previous); rollbackErr != nil {
				writeSplunkExportError(w, http.StatusInternalServerError, "Could not update logs export state or restore the saved settings.")
				return
			}
			writeSplunkExportError(w, http.StatusInternalServerError, "Could not update logs export state.")
			return
		}
		if cloud != nil {
			cloud.mu.Lock()
			cloud.clearRollbackLocked()
			cloud.mu.Unlock()
		}
		w.Header().Set("Cache-Control", "no-store")
		writeSameOriginJSON(w, settings.Controller.Status())
	}
	if cloud != nil {
		toggle = cloud.serializeMutation(toggle)
	}
	mux.HandleFunc("POST /api/splunk/logs/enabled", localMutation(toggle))

	disconnect := func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		var request struct {
			ExpectedVersion string `json:"expectedVersion"`
		}
		if err := decodeStrictJSON(w, r, &request); err != nil {
			writeSplunkExportError(w, http.StatusBadRequest, err.Error())
			return
		}
		if request.ExpectedVersion != settings.Controller.Status().Version {
			writeSplunkExportError(w, http.StatusConflict, "Logs settings changed. Try again.")
			return
		}
		config := settings.Controller.Config()
		config.Enabled, config.ConnectionVerified = false, false
		config.Token = ""
		if settings.Save == nil {
			writeSplunkExportError(w, http.StatusServiceUnavailable, "Saving logs settings is unavailable in this host.")
			return
		}
		if err := settings.Save(config); err != nil {
			writeSplunkExportError(w, http.StatusInternalServerError, "Could not disconnect logs.")
			return
		}
		settings.Controller.Apply(config, nil)
		if cloud != nil {
			cloud.mu.Lock()
			cloud.clearRollbackLocked()
			cloud.mu.Unlock()
		}
		w.Header().Set("Cache-Control", "no-store")
		writeSameOriginJSON(w, settings.Controller.Status())
	}
	if cloud != nil {
		disconnect = cloud.serializeMutation(disconnect)
	}
	mux.HandleFunc("POST /api/splunk/logs/disconnect", localMutation(disconnect))
}
