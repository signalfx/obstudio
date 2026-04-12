package validator

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strconv"
	"sync/atomic"
	"testing"
	"time"

	telemetrystore "github.com/signalfx/obstudio/observer/internal/store"
)

func TestValidatorHealthTimeoutDefault(t *testing.T) {
	t.Setenv("OBSTUDIO_VALIDATOR_HEALTH_TIMEOUT", "")

	if got := validatorHealthTimeout(); got != defaultValidatorHealthTimeout {
		t.Fatalf("expected default timeout %s, got %s", defaultValidatorHealthTimeout, got)
	}
}

func TestValidatorHealthTimeoutParsesOverride(t *testing.T) {
	t.Setenv("OBSTUDIO_VALIDATOR_HEALTH_TIMEOUT", "2m15s")

	if got := validatorHealthTimeout(); got != 2*time.Minute+15*time.Second {
		t.Fatalf("expected parsed timeout 2m15s, got %s", got)
	}
}

func TestValidatorHealthTimeoutRejectsInvalidOverride(t *testing.T) {
	t.Setenv("OBSTUDIO_VALIDATOR_HEALTH_TIMEOUT", "not-a-duration")

	if got := validatorHealthTimeout(); got != defaultValidatorHealthTimeout {
		t.Fatalf("expected invalid override to fall back to %s, got %s", defaultValidatorHealthTimeout, got)
	}
}

func TestValidatorWorkingDirUsesBinaryDirectoryWhenAvailable(t *testing.T) {
	dir := t.TempDir()
	binary := dir + "/weaver"

	if got := validatorWorkingDir(binary); got != dir {
		t.Fatalf("expected working dir %q, got %q", dir, got)
	}
}

func TestValidatorWorkingDirFallsBackWhenBinaryDirectoryMissing(t *testing.T) {
	dir := t.TempDir()
	missingDir := dir + "/gone"
	binary := missingDir + "/weaver"

	if got := validatorWorkingDir(binary); got == missingDir {
		t.Fatalf("expected missing binary directory to be rejected, got %q", got)
	}
	if got := validatorWorkingDir(binary); got == "" {
		t.Fatal("expected non-empty fallback working directory")
	}
}

func TestWaitForHealthEventuallyReady(t *testing.T) {
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if attempts.Add(1) < 3 {
			http.Error(w, "starting", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	if err := waitForHealth(t.Context(), server.URL, time.Second); err != nil {
		t.Fatalf("expected waitForHealth to succeed, got %v", err)
	}
}

func TestWaitForHealthTimeout(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "not ready", http.StatusServiceUnavailable)
	}))
	defer server.Close()

	if err := waitForHealth(t.Context(), server.URL, 150*time.Millisecond); err == nil {
		t.Fatal("expected waitForHealth to time out")
	}
}

func TestValidatorStderrSummaryDropsNoiseAndAnsi(t *testing.T) {
	collector := newValidatorStderr()
	collector.add("Weaver Registry Live Check")
	collector.add("\u001b[31mDiagnostic report:\u001b[0m")
	collector.add("  × Git error occurred while cloning `https://github.com/open-telemetry/")
	collector.add("  │ semantic-conventions.git`: Could not obtain the current directory")

	if got := collector.summary(); got != "Git error occurred while cloning `https://github.com/open-telemetry/ semantic-conventions.git`: Could not obtain the current directory" {
		t.Fatalf("unexpected stderr summary: %q", got)
	}
}

func TestStopProcessReturnsGracefulFlagBeforeError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	cmd := exec.Command("sh", "-c", "exit 0")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start helper command: %v", err)
	}

	graceful, err := stopProcess(cmd, server.URL)
	if err != nil {
		t.Fatalf("stopProcess returned error: %v", err)
	}
	if !graceful {
		t.Fatal("expected stopProcess to report graceful stop after successful admin request")
	}
}

func TestExportKeysRemainNonEmpty(t *testing.T) {
	resource := telemetrystore.Resource{
		ServiceName: "checkout",
		Attributes: map[string]any{
			"deployment.environment": "test",
		},
		SchemaURL: "https://opentelemetry.io/schemas/1.0.0",
	}
	if got := resourceKey(resource); got == "" {
		t.Fatal("expected resourceKey to return a non-empty key")
	}

	point := telemetrystore.MetricDataPoint{
		Name:        "http.server.duration",
		Description: "Request duration",
		Unit:        "ms",
		Type:        "histogram",
		Temporality: "delta",
		IsMonotonic: false,
		Resource:    resource,
		Scope: telemetrystore.Scope{
			Name:      "otel",
			Version:   "1.0.0",
			SchemaURL: "https://opentelemetry.io/schemas/1.0.0",
		},
	}
	if got := metricKey(point); got == "" {
		t.Fatal("expected metricKey to return a non-empty key")
	}
}

func TestValidatorStartupErrorPrefersStderrSummary(t *testing.T) {
	err := validatorStartupError(
		errors.New("validator health check timed out"),
		runExitCodeHelper(t, "1"),
		false,
		"Git error occurred while cloning semantic-conventions.git: Could not obtain the current directory",
	)
	if err == nil {
		t.Fatal("expected startup error")
	}
	if got := err.Error(); got != "validator startup failed: Git error occurred while cloning semantic-conventions.git: Could not obtain the current directory" {
		t.Fatalf("unexpected startup error: %q", got)
	}
}

func TestValidatorStartupErrorPreservesCancellation(t *testing.T) {
	err := validatorStartupError(context.Canceled, nil, false, "some diagnostic")
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context cancellation, got %v", err)
	}
}

func TestIsExpectedExitAllowsExitStatusOneAfterGracefulStop(t *testing.T) {
	err := runExitCodeHelper(t, "1")
	if err == nil {
		t.Fatal("expected helper to exit non-zero")
	}
	if !isExpectedExit(err, true) {
		t.Fatal("expected graceful stop to treat exit status 1 as expected")
	}
	if isExpectedExit(err, false) {
		t.Fatal("expected exit status 1 without graceful stop to remain unexpected")
	}
}

func TestExitCodeHelper(t *testing.T) {
	if os.Getenv("GO_WANT_VALIDATOR_EXIT_HELPER") != "1" {
		return
	}
	code, err := strconv.Atoi(os.Getenv("VALIDATOR_HELPER_EXIT_CODE"))
	if err != nil {
		code = 1
	}
	os.Exit(code)
}

func runExitCodeHelper(t *testing.T, code string) error {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=TestExitCodeHelper")
	cmd.Env = append(os.Environ(),
		"GO_WANT_VALIDATOR_EXIT_HELPER=1",
		"VALIDATOR_HELPER_EXIT_CODE="+code,
	)
	return cmd.Run()
}

func TestEnrichValidationEntitiesInfersSpanServiceAndScopeFromSnapshotName(t *testing.T) {
	entities := map[string]Entity{
		"span::not_stable:send payment.processed": {
			Key:    "span::not_stable:send payment.processed",
			Signal: SignalRef{Type: "span", SpanName: "send payment.processed", MetricName: "send payment.processed"},
			Findings: []Finding{{
				EntityKey: "span::not_stable:send payment.processed",
				RuleID:    "not_stable",
				Severity:  SeverityViolation,
				Message:   "span is unstable",
				Signal:    SignalRef{Type: "span", SpanName: "send payment.processed", MetricName: "send payment.processed"},
			}},
		},
	}

	snapshot := telemetrystore.TelemetrySnapshot{
		Spans: []telemetrystore.Span{{
			TraceID:   "trace-1",
			SpanID:    "span-1",
			Name:      "send payment.processed",
			Resource:  telemetrystore.Resource{ServiceName: "notification-service"},
			Scope:     telemetrystore.Scope{Name: "orders.consumer"},
			StartTime: time.Unix(10, 0),
			EndTime:   time.Unix(10, int64(750*time.Microsecond)),
		}},
	}

	enrichValidationEntities(entities, snapshot)

	entity := entities["span::not_stable:send payment.processed"]
	if entity.Signal.ServiceName != "notification-service" {
		t.Fatalf("expected entity service name to be enriched, got %q", entity.Signal.ServiceName)
	}
	if entity.Signal.ScopeName != "orders.consumer" {
		t.Fatalf("expected entity scope name to be enriched, got %q", entity.Signal.ScopeName)
	}
	if entity.Signal.MetricName != "" {
		t.Fatalf("expected span metricName to be cleared, got %q", entity.Signal.MetricName)
	}
	if entity.Findings[0].Signal.ServiceName != "notification-service" {
		t.Fatalf("expected finding service name to be enriched, got %q", entity.Findings[0].Signal.ServiceName)
	}
	if entity.Findings[0].Signal.ScopeName != "orders.consumer" {
		t.Fatalf("expected finding scope name to be enriched, got %q", entity.Findings[0].Signal.ScopeName)
	}
	if entity.Findings[0].Signal.MetricName != "" {
		t.Fatalf("expected span finding metricName to be cleared, got %q", entity.Findings[0].Signal.MetricName)
	}
}

func TestEnrichValidationEntitiesLeavesAmbiguousSpanNamesUnset(t *testing.T) {
	entities := map[string]Entity{
		"span::not_stable:process": {
			Key:    "span::not_stable:process",
			Signal: SignalRef{Type: "span", SpanName: "process"},
			Findings: []Finding{{
				EntityKey: "span::not_stable:process",
				RuleID:    "not_stable",
				Severity:  SeverityViolation,
				Message:   "span is unstable",
				Signal:    SignalRef{Type: "span", SpanName: "process"},
			}},
		},
	}

	snapshot := telemetrystore.TelemetrySnapshot{
		Spans: []telemetrystore.Span{
			{
				TraceID:  "trace-1",
				SpanID:   "span-1",
				Name:     "process",
				Resource: telemetrystore.Resource{ServiceName: "orders"},
				Scope:    telemetrystore.Scope{Name: "orders.scope"},
			},
			{
				TraceID:  "trace-2",
				SpanID:   "span-2",
				Name:     "process",
				Resource: telemetrystore.Resource{ServiceName: "payments"},
				Scope:    telemetrystore.Scope{Name: "payments.scope"},
			},
		},
	}

	enrichValidationEntities(entities, snapshot)

	entity := entities["span::not_stable:process"]
	if entity.Signal.ServiceName != "" {
		t.Fatalf("expected ambiguous span service to remain unset, got %q", entity.Signal.ServiceName)
	}
	if entity.Signal.ScopeName != "" {
		t.Fatalf("expected ambiguous span scope to remain unset, got %q", entity.Signal.ScopeName)
	}
}
