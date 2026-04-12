package validator

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	telemetrystore "github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/plog/plogotlp"
	"go.opentelemetry.io/collector/pdata/pmetric/pmetricotlp"
	"go.opentelemetry.io/collector/pdata/ptrace/ptraceotlp"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

const defaultValidatorHealthTimeout = 90 * time.Second

var ansiEscapePattern = regexp.MustCompile(`\x1b\[[0-9;]*m`)

type Manager struct {
	store     *Store
	telemetry *telemetrystore.Store

	mu           sync.Mutex
	activeRunID  string
	activeCancel context.CancelFunc
	runSeq       atomic.Uint64
}

func NewManager(store *Store, telemetry *telemetrystore.Store) *Manager {
	return &Manager{store: store, telemetry: telemetry}
}

func (m *Manager) Start(context.Context) error {
	if _, err := resolveWeaverPath(); err != nil {
		m.store.SetRuntimeStatus(StatusDisabled, "Weaver runtime not found beside obstudio or on PATH")
		return nil
	}
	m.store.SetRuntimeStatus(StatusIdle, "Validation has not been run yet")
	return nil
}

func (m *Manager) Shutdown(context.Context) error {
	m.cancelActiveRun()
	return nil
}

func (m *Manager) Reset() {
	m.cancelActiveRun()
	m.store.Clear()
}

func (m *Manager) MarkTelemetryChanged(changedAt time.Time) {
	m.store.MarkTelemetryChanged(changedAt)
}

func (m *Manager) Run(context.Context) Summary {
	if _, err := resolveWeaverPath(); err != nil {
		m.cancelActiveRun()
		m.store.SetRuntimeStatus(StatusDisabled, "Weaver runtime not found beside obstudio or on PATH")
		return m.store.Summary()
	}

	summary := m.store.Summary()
	if summary.Status == StatusDisabled {
		m.store.SetRuntimeStatus(StatusIdle, "Validation has not been run yet")
	}

	runID := fmt.Sprintf("run-%d", m.runSeq.Add(1))
	startedAt := time.Now()
	summary = m.store.StartRun(runID, startedAt)
	if summary.ActiveRunID != runID || summary.Status != StatusRunning {
		return summary
	}

	snapshot := m.telemetry.SnapshotTelemetry()
	runCtx, cancel := context.WithCancel(context.Background())
	m.setActiveRun(runID, cancel)

	go m.executeRun(runCtx, runID, snapshot)

	return m.store.Summary()
}

func (m *Manager) executeRun(ctx context.Context, runID string, snapshot telemetrystore.TelemetrySnapshot) {
	defer m.clearActiveRun(runID)

	if len(snapshot.Spans) == 0 && len(snapshot.Metrics) == 0 && len(snapshot.Logs) == 0 {
		m.store.CompleteRun(runID, map[string]Entity{}, weaverStats{}, time.Now())
		return
	}

	path, err := resolveWeaverPath()
	if err != nil {
		m.store.FailRun(runID, "Weaver runtime not found beside obstudio or on PATH", time.Now())
		return
	}

	signals, err := buildSnapshotSignals(snapshot)
	if err != nil {
		m.store.FailRun(runID, fmt.Sprintf("build validation snapshot: %v", err), time.Now())
		return
	}

	result, err := runWeaverSnapshot(ctx, path, signals)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return
		}
		m.store.FailRun(runID, fmt.Sprintf("validation failed: %v", err), time.Now())
		return
	}

	enrichValidationEntities(result.entities, snapshot)
	m.store.CompleteRun(runID, result.entities, result.stats, time.Now())
}

func (m *Manager) setActiveRun(runID string, cancel context.CancelFunc) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.activeRunID = runID
	m.activeCancel = cancel
}

func (m *Manager) clearActiveRun(runID string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.activeRunID != runID {
		return
	}
	m.activeRunID = ""
	m.activeCancel = nil
}

func (m *Manager) cancelActiveRun() {
	m.mu.Lock()
	cancel := m.activeCancel
	m.activeRunID = ""
	m.activeCancel = nil
	m.mu.Unlock()
	if cancel != nil {
		cancel()
	}
}

type runResult struct {
	entities map[string]Entity
	stats    weaverStats
}

type runCollector struct {
	mu       sync.Mutex
	entities map[string]Entity
	stats    weaverStats
}

func newRunCollector() *runCollector {
	return &runCollector{entities: make(map[string]Entity)}
}

func (c *runCollector) readStdout(stdout io.Reader) {
	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 0, 64*1024), 2*1024*1024)
	for scanner.Scan() {
		line := scanner.Bytes()
		normalized, ok, err := normalizeLine(line, time.Now())
		if err != nil {
			log.Printf("[validator] parse error: %v", err)
			continue
		}
		if !ok {
			continue
		}
		c.mu.Lock()
		if normalized.Entity != nil {
			c.entities[normalized.Entity.Key] = *normalized.Entity
		}
		if normalized.Stats != nil {
			c.stats = *normalized.Stats
		}
		c.mu.Unlock()
	}
}

func (c *runCollector) snapshot() runResult {
	c.mu.Lock()
	defer c.mu.Unlock()
	entities := make(map[string]Entity, len(c.entities))
	for key, entity := range c.entities {
		entities[key] = entity
	}
	return runResult{entities: entities, stats: c.stats}
}

func runWeaverSnapshot(ctx context.Context, binaryPath string, signals snapshotSignals) (runResult, error) {
	otlpPort, err := pickFreePort()
	if err != nil {
		return runResult{}, fmt.Errorf("pick validator OTLP port: %w", err)
	}
	adminPort, err := pickFreePort()
	if err != nil {
		return runResult{}, fmt.Errorf("pick validator admin port: %w", err)
	}

	cmd := exec.CommandContext(ctx, binaryPath,
		"registry", "live-check",
		"--format", "jsonl",
		"--otlp-grpc-port", otlpPort,
		"--admin-port", adminPort,
		"--inactivity-timeout", "0",
	)
	cmd.Dir = validatorWorkingDir(binaryPath)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return runResult{}, fmt.Errorf("weaver stdout pipe: %w", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return runResult{}, fmt.Errorf("weaver stderr pipe: %w", err)
	}
	if err := cmd.Start(); err != nil {
		return runResult{}, fmt.Errorf("start weaver: %w", err)
	}

	adminURL := "http://127.0.0.1:" + adminPort
	collector := newRunCollector()
	stderrCollector := newValidatorStderr()
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		collector.readStdout(stdout)
	}()
	go func() {
		defer wg.Done()
		readStderr(stderr, stderrCollector)
	}()

	if err := waitForHealth(ctx, adminURL+"/health", validatorHealthTimeout()); err != nil {
		gracefulStop, processErr := stopProcess(cmd, adminURL)
		wg.Wait()
		return runResult{}, validatorStartupError(err, processErr, gracefulStop, stderrCollector.summary())
	}

	conn, err := grpc.NewClient("127.0.0.1:"+otlpPort, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		stopProcess(cmd, adminURL)
		wg.Wait()
		return runResult{}, fmt.Errorf("connect to weaver: %w", err)
	}
	defer conn.Close()

	if err := exportSnapshot(ctx, conn, signals); err != nil {
		stopProcess(cmd, adminURL)
		wg.Wait()
		return runResult{}, err
	}

	gracefulStop, processErr := stopProcess(cmd, adminURL)
	wg.Wait()
	if processErr != nil && !isExpectedExit(processErr, gracefulStop) && !errors.Is(processErr, context.Canceled) {
		return runResult{}, fmt.Errorf("weaver exit: %w", processErr)
	}

	return collector.snapshot(), nil
}

func exportSnapshot(ctx context.Context, conn *grpc.ClientConn, signals snapshotSignals) error {
	traceClient := ptraceotlp.NewGRPCClient(conn)
	metricClient := pmetricotlp.NewGRPCClient(conn)
	logClient := plogotlp.NewGRPCClient(conn)

	if signals.traces.ResourceSpans().Len() > 0 {
		exportCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		if _, err := traceClient.Export(exportCtx, ptraceotlp.NewExportRequestFromTraces(signals.traces)); err != nil {
			return fmt.Errorf("export traces: %w", err)
		}
	}
	if signals.metrics.ResourceMetrics().Len() > 0 {
		exportCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		if _, err := metricClient.Export(exportCtx, pmetricotlp.NewExportRequestFromMetrics(signals.metrics)); err != nil {
			return fmt.Errorf("export metrics: %w", err)
		}
	}
	if signals.logs.ResourceLogs().Len() > 0 {
		exportCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		if _, err := logClient.Export(exportCtx, plogotlp.NewExportRequestFromLogs(signals.logs)); err != nil {
			return fmt.Errorf("export logs: %w", err)
		}
	}
	return nil
}

func readStderr(stderr io.Reader, collector *validatorStderr) {
	scanner := bufio.NewScanner(stderr)
	scanner.Buffer(make([]byte, 0, 16*1024), 512*1024)
	for scanner.Scan() {
		line := scanner.Text()
		log.Printf("[validator] %s", line)
		if collector != nil {
			collector.add(line)
		}
	}
}

func enrichValidationEntities(entities map[string]Entity, snapshot telemetrystore.TelemetrySnapshot) {
	spanByID := make(map[string]telemetrystore.Span, len(snapshot.Spans))
	spanByName := make(map[string]signalMetadata)
	metricByName := make(map[string]signalMetadata)
	logByBody := make(map[string]signalMetadata)

	for _, span := range snapshot.Spans {
		if span.TraceID != "" && span.SpanID != "" {
			spanByID[span.TraceID+":"+span.SpanID] = span
		}
		addSignalMetadata(spanByName, span.Name, span.Resource.ServiceName, span.Scope.Name)
	}
	for _, metric := range snapshot.Metrics {
		addSignalMetadata(metricByName, metric.Name, metric.Resource.ServiceName, metric.Scope.Name)
	}
	for _, record := range snapshot.Logs {
		addSignalMetadata(logByBody, record.Body, record.Resource.ServiceName, record.Scope.Name)
	}

	for key, entity := range entities {
		entity.Signal = enrichSignalRef(entity.Signal, spanByID, spanByName, metricByName, logByBody)
		for i := range entity.Findings {
			entity.Findings[i].Signal = enrichSignalRef(entity.Findings[i].Signal, spanByID, spanByName, metricByName, logByBody)
		}
		entities[key] = entity
	}
}

type signalMetadata struct {
	serviceName string
	scopeName   string
	ambiguous   bool
}

func addSignalMetadata(index map[string]signalMetadata, key, serviceName, scopeName string) {
	if key == "" {
		return
	}
	if current, ok := index[key]; ok {
		if current.serviceName != serviceName || current.scopeName != scopeName {
			current.ambiguous = true
			index[key] = current
		}
		return
	}
	index[key] = signalMetadata{
		serviceName: serviceName,
		scopeName:   scopeName,
	}
}

func enrichSignalRef(
	signal SignalRef,
	spanByID map[string]telemetrystore.Span,
	spanByName map[string]signalMetadata,
	metricByName map[string]signalMetadata,
	logByBody map[string]signalMetadata,
) SignalRef {
	switch normalizeSignalType(signal.Type) {
	case "span":
		signal.MetricName = ""
		if signal.TraceID != "" && signal.SpanID != "" {
			if span, ok := spanByID[signal.TraceID+":"+signal.SpanID]; ok {
				if signal.ServiceName == "" {
					signal.ServiceName = span.Resource.ServiceName
				}
				if signal.ScopeName == "" {
					signal.ScopeName = span.Scope.Name
				}
				if signal.SpanName == "" {
					signal.SpanName = span.Name
				}
				return signal
			}
		}
		if meta, ok := spanByName[signal.SpanName]; ok && !meta.ambiguous {
			if signal.ServiceName == "" {
				signal.ServiceName = meta.serviceName
			}
			if signal.ScopeName == "" {
				signal.ScopeName = meta.scopeName
			}
		}
	case "metric":
		if meta, ok := metricByName[signal.MetricName]; ok && !meta.ambiguous {
			if signal.ServiceName == "" {
				signal.ServiceName = meta.serviceName
			}
			if signal.ScopeName == "" {
				signal.ScopeName = meta.scopeName
			}
		}
	case "log":
		if meta, ok := logByBody[signal.LogBody]; ok && !meta.ambiguous {
			if signal.ServiceName == "" {
				signal.ServiceName = meta.serviceName
			}
			if signal.ScopeName == "" {
				signal.ScopeName = meta.scopeName
			}
		}
	}

	return signal
}

type validatorStderr struct {
	mu    sync.Mutex
	lines []string
}

func newValidatorStderr() *validatorStderr {
	return &validatorStderr{lines: make([]string, 0, 8)}
}

func (c *validatorStderr) add(line string) {
	cleaned := strings.TrimSpace(ansiEscapePattern.ReplaceAllString(line, ""))
	if cleaned == "" {
		return
	}
	if isValidatorNoise(cleaned) {
		return
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.lines) == cap(c.lines) {
		copy(c.lines, c.lines[1:])
		c.lines = c.lines[:len(c.lines)-1]
	}
	c.lines = append(c.lines, cleaned)
}

func (c *validatorStderr) summary() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.lines) == 0 {
		return ""
	}
	parts := make([]string, 0, len(c.lines))
	for _, line := range c.lines {
		trimmed := strings.TrimSpace(strings.TrimLeft(line, "×│• "))
		if trimmed == "" {
			continue
		}
		parts = append(parts, trimmed)
	}
	return strings.Join(parts, " ")
}

func isValidatorNoise(line string) bool {
	switch {
	case strings.HasPrefix(line, "Weaver Registry Live Check"):
		return true
	case strings.HasPrefix(line, "Resolving registry "):
		return true
	case strings.HasPrefix(line, "Diagnostic report"):
		return true
	case strings.HasPrefix(line, "Total execution time:"):
		return true
	case strings.HasPrefix(line, "ℹ To stop the OTLP receiver:"):
		return true
	case strings.HasPrefix(line, "The OTLP receiver will run indefinitely"):
		return true
	case strings.HasPrefix(line, "✔ "):
		return true
	default:
		return false
	}
}

func validatorStartupError(waitErr error, processErr error, gracefulStop bool, stderrSummary string) error {
	if errors.Is(waitErr, context.Canceled) {
		return waitErr
	}
	if stderrSummary != "" {
		return fmt.Errorf("validator startup failed: %s", stderrSummary)
	}
	if processErr != nil && !isExpectedExit(processErr, gracefulStop) && !errors.Is(processErr, context.Canceled) {
		return fmt.Errorf("validator startup failed: %w", processErr)
	}
	return waitErr
}

func resolveWeaverPath() (string, error) {
	if custom := os.Getenv("WEAVER_PATH"); custom != "" {
		return custom, nil
	}

	exe, err := os.Executable()
	if err == nil {
		candidates := []string{filepath.Join(filepath.Dir(exe), "weaver")}
		if runtime.GOOS == "windows" {
			candidates = append(candidates, filepath.Join(filepath.Dir(exe), "weaver.exe"))
		}
		for _, candidate := range candidates {
			if _, statErr := os.Stat(candidate); statErr == nil {
				return candidate, nil
			}
		}
	}

	return exec.LookPath("weaver")
}

func validatorWorkingDir(binaryPath string) string {
	if dir := filepath.Dir(binaryPath); dir != "." && dir != "" {
		if info, err := os.Stat(dir); err == nil && info.IsDir() {
			return dir
		}
	}
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		if info, statErr := os.Stat(home); statErr == nil && info.IsDir() {
			return home
		}
	}
	return os.TempDir()
}

func pickFreePort() (string, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", err
	}
	defer ln.Close()
	return fmt.Sprintf("%d", ln.Addr().(*net.TCPAddr).Port), nil
}

func validatorHealthTimeout() time.Duration {
	raw := os.Getenv("OBSTUDIO_VALIDATOR_HEALTH_TIMEOUT")
	if raw == "" {
		return defaultValidatorHealthTimeout
	}

	parsed, err := time.ParseDuration(raw)
	if err != nil || parsed <= 0 {
		return defaultValidatorHealthTimeout
	}
	return parsed
}

func waitForHealth(ctx context.Context, url string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for {
		if time.Now().After(deadline) {
			return fmt.Errorf("validator health check timed out")
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err != nil {
			return err
		}
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return nil
			}
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(100 * time.Millisecond):
		}
	}
}

func stopProcess(cmd *exec.Cmd, adminURL string) (bool, error) {
	gracefulStop := false
	stopCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	req, err := http.NewRequestWithContext(stopCtx, http.MethodPost, adminURL+"/stop", nil)
	if err == nil {
		resp, reqErr := http.DefaultClient.Do(req)
		if reqErr == nil {
			gracefulStop = resp.StatusCode >= 200 && resp.StatusCode < 300
			resp.Body.Close()
		}
	}
	cancel()

	done := make(chan error, 1)
	go func() {
		done <- cmd.Wait()
	}()

	select {
	case err := <-done:
		return gracefulStop, err
	case <-time.After(2 * time.Second):
		if cmd.Process != nil {
			_ = cmd.Process.Kill()
		}
		return gracefulStop, <-done
	}
}

func isExpectedExit(err error, gracefulStop bool) bool {
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		return false
	}
	if status, ok := exitErr.Sys().(syscall.WaitStatus); ok {
		if status.Signaled() {
			return true
		}
		if gracefulStop && status.ExitStatus() == 1 {
			return true
		}
	}
	return false
}
