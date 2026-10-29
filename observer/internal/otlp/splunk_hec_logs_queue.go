package otlp

import (
	"context"
	"errors"
	"fmt"
	"go.opentelemetry.io/collector/config/configoptional"
	"go.opentelemetry.io/collector/config/configretry"
	"go.opentelemetry.io/collector/consumer/consumererror"
	"go.opentelemetry.io/collector/exporter"
	"go.opentelemetry.io/collector/exporter/exporterhelper"
	"go.opentelemetry.io/collector/pdata/plog"
	"strings"
	"sync"
	"time"
)

const (
	maxQueuedHECRecords = 10_000
	maxQueuedHECBytes   = 16 << 20
	maxQueuedHECBatches = 256
)

type hecQueueContextKey struct{}
type hecQueuedBatch struct {
	records, bytes int
	done           bool
	attempt        chan error
}

// The controller keeps the queue stable while connection edits replace the
// upstream HEC component. Collector exporterhelper owns storage and retries.
type SplunkHECLogsExportController struct {
	mu                                           sync.RWMutex
	exportMu                                     sync.RWMutex
	transitionMu                                 sync.Mutex
	config                                       SplunkHECLogsExporterConfig
	exporter                                     *SplunkHECLogsExporter
	pipeline                                     exporter.Logs
	version, configError                         string
	changed                                      chan struct{}
	transitioning, closed                        bool
	flushCancel                                  context.CancelFunc
	pendingRecords, pendingBytes, pendingBatches int
	droppedRecords                               uint64
}

func NewSplunkHECLogsExportController(config SplunkHECLogsExporterConfig) *SplunkHECLogsExportController {
	config = normalizeSplunkHECLogsExporterConfig(config)
	c := &SplunkHECLogsExportController{config: config, version: newRequestChannel(), changed: make(chan struct{})}
	if config.Enabled {
		c.exporter, _ = NewSplunkHECLogsExporter(config)
		if c.exporter == nil {
			c.configError = "Invalid HEC configuration."
		}
	}
	queue := exporterhelper.NewDefaultQueueConfig()
	queue.NumConsumers, queue.QueueSize = 1, maxQueuedHECBytes
	_ = queue.Sizer.UnmarshalText([]byte("bytes"))
	retry := configretry.NewDefaultBackOffConfig()
	retry.InitialInterval, retry.MaxInterval, retry.MaxElapsedTime = time.Second, 30*time.Second, 0
	pipeline, err := exporterhelper.NewLogs(context.Background(), hecExporterSettings(), &queue, c.exportQueuedLogs,
		exporterhelper.WithQueue(configoptional.Some(queue)), exporterhelper.WithRetry(retry), exporterhelper.WithTimeout(exporterhelper.TimeoutConfig{Timeout: 0}))
	if err == nil {
		err = pipeline.Start(context.Background(), minimalHost{})
	}
	if err != nil {
		if pipeline != nil {
			_ = pipeline.Shutdown(context.Background())
		}
		c.configError = "Could not start logs queue."
	} else {
		c.pipeline = pipeline
	}
	return c
}
func (c *SplunkHECLogsExportController) Config() SplunkHECLogsExporterConfig {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.config
}
func (c *SplunkHECLogsExportController) beginTransition() {
	c.transitionMu.Lock()
	c.mu.Lock()
	c.transitioning = true
	if c.flushCancel != nil {
		c.flushCancel()
	}
	c.mu.Unlock()
	c.exportMu.Lock()
}
func (c *SplunkHECLogsExportController) endTransition() {
	c.mu.Lock()
	c.transitioning = false
	close(c.changed)
	c.changed = make(chan struct{})
	c.mu.Unlock()
	c.exportMu.Unlock()
	c.transitionMu.Unlock()
}
func (c *SplunkHECLogsExportController) SetEnabled(enabled bool) error {
	c.beginTransition()
	defer c.endTransition()
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return fmt.Errorf("logs exporter is shutting down")
	}
	if enabled && c.exporter == nil {
		exp, err := NewSplunkHECLogsExporter(c.config)
		if err != nil {
			return err
		}
		c.exporter = exp
	}
	c.config.Enabled, c.version = enabled, newRequestChannel()
	return nil
}
func (c *SplunkHECLogsExportController) Apply(config SplunkHECLogsExporterConfig, exp *SplunkHECLogsExporter) {
	c.apply(config, exp, false)
}
func (c *SplunkHECLogsExportController) ApplyKeepingActivity(config SplunkHECLogsExporterConfig, exp *SplunkHECLogsExporter) {
	c.apply(config, exp, true)
}
func (c *SplunkHECLogsExportController) apply(config SplunkHECLogsExporterConfig, exp *SplunkHECLogsExporter, keep bool) {
	c.beginTransition()
	defer c.endTransition()
	c.mu.Lock()
	if c.closed {
		c.mu.Unlock()
		exp.Shutdown(context.Background())
		return
	}
	previous := c.exporter
	if keep && previous != nil && exp != nil && previous != exp {
		exp.carryActivity(previous)
	}
	c.config, c.exporter, c.configError, c.version = config, exp, "", newRequestChannel()
	c.mu.Unlock()
	if previous != exp {
		previous.Shutdown(context.Background())
	}
}
func (c *SplunkHECLogsExportController) Status() SplunkHECLogsExportStatus {
	c.mu.RLock()
	defer c.mu.RUnlock()
	status := c.exporter.Status()
	status.Version, status.Source, status.Sourcetype = c.version, c.config.Source, c.config.Sourcetype
	status.Endpoint, status.Index = c.config.Endpoint, c.config.Index
	status.SearchURL = splunkPlatformSearchURL(c.config.Endpoint, c.config.Index)
	status.Token, status.TokenConfigured = "", strings.TrimSpace(c.config.Token) != ""
	status.Configured = status.TokenConfigured && status.Endpoint != ""
	status.Connected = status.Configured && (c.config.ConnectionVerified || status.LastExportSuccess != "")
	status.InsecureSkipVerify = c.config.InsecureSkipVerify
	status.Enabled = c.config.Enabled && c.exporter != nil && !c.closed
	status.QueuedRecords, status.DroppedRecords = c.pendingRecords, c.droppedRecords
	if c.configError != "" {
		status.LastExportError = c.configError
	}
	return status
}
func (c *SplunkHECLogsExportController) ExportEnabled() bool { return c.Status().Enabled }
func (c *SplunkHECLogsExportController) QueueLogs(logs plog.Logs) {
	_, _ = c.enqueue(context.Background(), logs)
}
func (c *SplunkHECLogsExportController) ExportLogs(ctx context.Context, logs plog.Logs) error {
	batch, err := c.enqueue(ctx, logs)
	if err != nil || batch == nil || !c.ExportEnabled() {
		return err
	}
	select {
	case err := <-batch.attempt:
		return err
	case <-ctx.Done():
		return ctx.Err()
	}
}
func (c *SplunkHECLogsExportController) enqueue(ctx context.Context, logs plog.Logs) (*hecQueuedBatch, error) {
	if logs.LogRecordCount() == 0 {
		return nil, nil
	}
	queued := prepareHECLogs(logs)
	batch := &hecQueuedBatch{records: queued.LogRecordCount(), bytes: (&plog.ProtoMarshaler{}).LogsSize(queued), attempt: make(chan error, 1)}
	c.mu.Lock()
	// Reject new overflow rather than evicting data already owned by the Collector.
	if c.closed || c.pipeline == nil || c.pendingRecords+batch.records > maxQueuedHECRecords || c.pendingBytes+batch.bytes > maxQueuedHECBytes || c.pendingBatches >= maxQueuedHECBatches {
		c.droppedRecords += uint64(batch.records)
		c.mu.Unlock()
		return nil, exporterhelper.ErrQueueIsFull
	}
	c.pendingRecords += batch.records
	c.pendingBytes += batch.bytes
	c.pendingBatches++
	pipeline := c.pipeline
	c.mu.Unlock()
	err := pipeline.ConsumeLogs(context.WithValue(ctx, hecQueueContextKey{}, batch), queued)
	if err != nil {
		c.finishBatch(batch, true)
	}
	return batch, err
}
func (c *SplunkHECLogsExportController) finishBatch(batch *hecQueuedBatch, dropped bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if batch.done {
		return
	}
	batch.done = true
	c.pendingRecords -= batch.records
	c.pendingBytes -= batch.bytes
	c.pendingBatches--
	if dropped {
		c.droppedRecords += uint64(batch.records)
	}
}
func (c *SplunkHECLogsExportController) exportQueuedLogs(ctx context.Context, logs plog.Logs) error {
	batch := ctx.Value(hecQueueContextKey{}).(*hecQueuedBatch)
	for {
		c.exportMu.RLock()
		c.mu.Lock()
		if c.closed {
			c.mu.Unlock()
			c.exportMu.RUnlock()
			c.finishBatch(batch, true)
			return consumererror.NewPermanent(fmt.Errorf("logs exporter is shutting down"))
		}
		if c.transitioning || !c.config.Enabled || c.exporter == nil {
			changed := c.changed
			c.mu.Unlock()
			c.exportMu.RUnlock()
			select {
			case <-changed:
				continue
			case <-ctx.Done():
				return ctx.Err()
			}
		}
		exp := c.exporter
		sendCtx, cancel := context.WithCancel(ctx)
		c.flushCancel = cancel
		c.mu.Unlock()
		before := exp.Status().ExportedRecords
		err := exp.ExportLogs(sendCtx, logs)
		sent := int(exp.Status().ExportedRecords - before)
		intentionalCancel := err != nil && sendCtx.Err() == context.Canceled && ctx.Err() == nil
		cancel()
		c.mu.Lock()
		c.flushCancel = nil
		c.pendingRecords -= sent
		batch.records -= sent
		var partial consumererror.Logs
		if errors.As(err, &partial) {
			if dropped := batch.records - partial.Data().LogRecordCount(); dropped > 0 {
				c.pendingRecords -= dropped
				batch.records -= dropped
				c.droppedRecords += uint64(dropped)
			}
		}
		c.mu.Unlock()
		c.exportMu.RUnlock()
		if intentionalCancel {
			var partial consumererror.Logs
			if errors.As(err, &partial) {
				logs = partial.Data()
			}
			continue
		}
		if err == nil || consumererror.IsPermanent(err) {
			c.finishBatch(batch, err != nil)
		}
		select {
		case batch.attempt <- err:
		default:
		}
		return err
	}
}
func (c *SplunkHECLogsExportController) Shutdown(ctx context.Context) {
	c.mu.Lock()
	if c.closed {
		c.mu.Unlock()
		return
	}
	c.closed = true
	if c.flushCancel != nil {
		c.flushCancel()
	}
	close(c.changed)
	c.changed = make(chan struct{})
	pipeline := c.pipeline
	c.mu.Unlock()
	if pipeline != nil {
		_ = pipeline.Shutdown(ctx)
	}
	c.exportMu.Lock()
	c.mu.Lock()
	exp := c.exporter
	c.droppedRecords += uint64(c.pendingRecords)
	c.pendingRecords, c.pendingBytes, c.pendingBatches = 0, 0, 0
	c.mu.Unlock()
	c.exportMu.Unlock()
	exp.Shutdown(ctx)
}
func (e *SplunkHECLogsExporter) carryActivity(previous *SplunkHECLogsExporter) {
	previous.mu.Lock()
	defer previous.mu.Unlock()
	e.mu.Lock()
	defer e.mu.Unlock()
	e.exportedBatches += previous.exportedBatches
	e.exportedRecords += previous.exportedRecords
	e.failedBatches += previous.failedBatches
	if e.lastExportSuccess.IsZero() && e.config.Endpoint == previous.config.Endpoint &&
		e.config.Token == previous.config.Token && e.config.Index == previous.config.Index &&
		e.config.InsecureSkipVerify == previous.config.InsecureSkipVerify {
		e.lastExportSuccess, e.lastExportError = previous.lastExportSuccess, previous.lastExportError
		e.lastHTTPStatus, e.lastHECCode = previous.lastHTTPStatus, previous.lastHECCode
	}
}
