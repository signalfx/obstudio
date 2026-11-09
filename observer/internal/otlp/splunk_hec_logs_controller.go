package otlp

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/collector/pdata/plog"
)

// The controller owns connection state. The HEC component owns queued delivery.
type SplunkHECLogsExportController struct {
	mu                   sync.RWMutex
	config               SplunkHECLogsExporterConfig
	exporter             *SplunkHECLogsExporter
	activity             SplunkHECLogsExportStatus
	version, configError string
	closed               bool
	sessionOnly          bool
}

func NewSplunkHECLogsExportController(config SplunkHECLogsExporterConfig) *SplunkHECLogsExportController {
	config = normalizeSplunkHECLogsExporterConfig(config)
	c := &SplunkHECLogsExportController{config: config, version: newRequestChannel()}
	if config.Enabled {
		var err error
		c.exporter, err = NewSplunkHECLogsExporter(config)
		if err != nil {
			c.configError = "Could not start HEC export."
		}
	}
	return c
}

func (c *SplunkHECLogsExportController) Config() SplunkHECLogsExporterConfig {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.config
}

func (c *SplunkHECLogsExportController) retire(exp *SplunkHECLogsExporter, ctx context.Context) {
	if exp == nil {
		return
	}
	exp.Shutdown(ctx)
	last := exp.Status()
	c.activity.ExportedBatches += last.ExportedBatches
	c.activity.ExportedRecords += last.ExportedRecords
	c.activity.FailedBatches += last.FailedBatches
	if last.LastExportSuccess > c.activity.LastExportSuccess {
		c.activity.LastExportSuccess = last.LastExportSuccess
	}
	if last.lastAttempt.After(c.activity.lastAttempt) {
		c.activity.lastAttempt = last.lastAttempt
		c.activity.LastExportError = last.LastExportError
		c.activity.LastHTTPStatus, c.activity.LastHECCode = last.LastHTTPStatus, last.LastHECCode
	}
}

func (c *SplunkHECLogsExportController) SetEnabled(enabled bool) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return fmt.Errorf("logs exporter is shutting down")
	}
	if enabled && c.exporter == nil {
		config := c.config
		config.Enabled = true
		exp, err := NewSplunkHECLogsExporter(config)
		if err != nil {
			return err
		}
		c.exporter = exp
	}
	if !enabled {
		c.retire(c.exporter, context.Background())
		c.exporter = nil
	}
	c.config.Enabled, c.version, c.configError = enabled, newRequestChannel(), ""
	return nil
}

func (c *SplunkHECLogsExportController) Apply(config SplunkHECLogsExporterConfig, exp *SplunkHECLogsExporter) {
	c.apply(config, exp, false, false)
}

func (c *SplunkHECLogsExportController) ApplyKeepingActivity(config SplunkHECLogsExporterConfig, exp *SplunkHECLogsExporter) {
	c.apply(config, exp, true, false)
}

func (c *SplunkHECLogsExportController) ApplySession(config SplunkHECLogsExporterConfig, exp *SplunkHECLogsExporter, keepActivity bool) {
	c.apply(config, exp, keepActivity, true)
}

func (c *SplunkHECLogsExportController) apply(config SplunkHECLogsExporterConfig, exp *SplunkHECLogsExporter, keep, sessionOnly bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		exp.Shutdown(context.Background())
		return
	}
	c.sessionOnly = sessionOnly
	delivery := config
	delivery.ConnectionVerified = c.config.ConnectionVerified
	// An unchanged save must leave the active component's pending sends intact.
	if keep && c.exporter != nil && exp != nil && exp != c.exporter && delivery == c.config {
		c.retire(exp, context.Background())
		c.config, c.version = config, newRequestChannel()
		return
	}
	if c.exporter != exp {
		c.retire(c.exporter, context.Background())
	}
	if !keep {
		c.activity = SplunkHECLogsExportStatus{}
	} else if config.Endpoint != c.config.Endpoint || config.Token != c.config.Token || config.Index != c.config.Index || config.InsecureSkipVerify != c.config.InsecureSkipVerify {
		c.activity.LastExportSuccess, c.activity.LastExportError = "", ""
		c.activity.LastHTTPStatus, c.activity.LastHECCode = 0, 0
		c.activity.lastAttempt = time.Time{}
	}
	if !config.Enabled {
		c.retire(exp, context.Background())
		exp = nil
	}
	c.config, c.exporter, c.version, c.configError = config, exp, newRequestChannel(), ""
}

func (c *SplunkHECLogsExportController) Status() SplunkHECLogsExportStatus {
	c.mu.RLock()
	defer c.mu.RUnlock()
	status := c.exporter.Status()
	status.ExportedBatches += c.activity.ExportedBatches
	status.ExportedRecords += c.activity.ExportedRecords
	status.FailedBatches += c.activity.FailedBatches
	if c.activity.lastAttempt.After(status.lastAttempt) {
		status.lastAttempt = c.activity.lastAttempt
		status.LastExportError = c.activity.LastExportError
		status.LastHTTPStatus, status.LastHECCode = c.activity.LastHTTPStatus, c.activity.LastHECCode
	}
	if c.activity.LastExportSuccess > status.LastExportSuccess {
		status.LastExportSuccess = c.activity.LastExportSuccess
	}
	status.SessionOnly = c.sessionOnly
	status.Version, status.Source, status.Sourcetype = c.version, c.config.Source, c.config.Sourcetype
	status.Endpoint, status.Index = c.config.Endpoint, c.config.Index
	status.SearchURL = splunkPlatformSearchURL(c.config.Endpoint, c.config.Index)
	status.TokenConfigured = strings.TrimSpace(c.config.Token) != ""
	status.Configured = status.TokenConfigured && status.Endpoint != ""
	status.Connected = status.Configured && (c.config.ConnectionVerified || status.LastExportSuccess != "")
	status.InsecureSkipVerify = c.config.InsecureSkipVerify
	status.Timeout = c.config.Timeout.String()
	status.Enabled = c.config.Enabled && c.exporter != nil && !c.closed
	if c.configError != "" {
		status.LastExportError = c.configError
	}
	return status
}

func (c *SplunkHECLogsExportController) ExportEnabled() bool { return c.Status().Enabled }

func (c *SplunkHECLogsExportController) QueueLogs(logs plog.Logs) {
	_ = c.ExportLogs(context.Background(), logs)
}

// Capture the active component before local storage can trigger state changes.
// A stopped component cannot send; it is never replaced with a new destination.
func logsExporterForIngest(exp LogsExporter) LogsExporter {
	if c, ok := exp.(*SplunkHECLogsExportController); ok {
		c.mu.RLock()
		defer c.mu.RUnlock()
		if c.closed || !c.config.Enabled || c.exporter == nil {
			return nil
		}
		return c.exporter
	}
	return exp
}

func (c *SplunkHECLogsExportController) ExportLogs(ctx context.Context, logs plog.Logs) error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if !c.config.Enabled || c.exporter == nil || c.closed {
		return nil
	}
	return c.exporter.ExportLogs(ctx, logs)
}

func (c *SplunkHECLogsExportController) Shutdown(ctx context.Context) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return
	}
	c.closed = true
	c.retire(c.exporter, ctx)
	c.exporter = nil
}
