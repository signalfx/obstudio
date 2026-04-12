package validator

import (
	"testing"
	"time"
)

func TestStoreSummaryAndQuery(t *testing.T) {
	store := NewStore()
	store.SetRuntimeStatus(StatusReady, "ready")
	store.UpsertEntity(Entity{
		Key:             "span:trace-1:span-1",
		HighestSeverity: SeverityViolation,
		Signal:          SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
		UpdatedAt:       time.Unix(10, 0),
		Findings: []Finding{
			{
				EntityKey: "span:trace-1:span-1",
				Source:    "weaver",
				RuleID:    "missing_attribute",
				Severity:  SeverityViolation,
				Message:   "missing attribute",
				Signal:    SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
				UpdatedAt: time.Unix(10, 0),
			},
		},
	})

	summary := store.Summary()
	if !summary.Ready {
		t.Fatalf("expected store to be ready")
	}
	if summary.TotalEntities != 1 {
		t.Fatalf("expected 1 entity, got %d", summary.TotalEntities)
	}
	if summary.SeverityCounts["violation"] != 1 {
		t.Fatalf("expected violation count 1, got %d", summary.SeverityCounts["violation"])
	}

	findings := store.QueryFindings(Query{ServiceName: "checkout"})
	if len(findings) != 1 {
		t.Fatalf("expected 1 finding, got %d", len(findings))
	}
	if findings[0].RuleID != "missing_attribute" {
		t.Fatalf("unexpected rule id: %s", findings[0].RuleID)
	}
}

func TestStoreMarksResultsStaleAfterTelemetryChange(t *testing.T) {
	store := NewStore()
	store.SetRuntimeStatus(StatusIdle, "Validation has not been run yet")

	store.StartRun("run-1", time.Unix(10, 0))
	ok := store.CompleteRun("run-1", map[string]Entity{
		"metric:checkout::http.server.duration": {
			Key:             "metric:checkout::http.server.duration",
			HighestSeverity: SeverityImprovement,
			Signal:          SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
			UpdatedAt:       time.Unix(11, 0),
			Findings: []Finding{{
				EntityKey: "metric:checkout::http.server.duration",
				Source:    "weaver",
				RuleID:    "deprecated",
				Severity:  SeverityImprovement,
				Message:   "deprecated metric",
				Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
				UpdatedAt: time.Unix(11, 0),
			}},
		},
	}, weaverStats{}, time.Unix(11, 0))
	if !ok {
		t.Fatal("expected run completion to be accepted")
	}

	store.MarkTelemetryChanged(time.Unix(12, 0))
	summary := store.Summary()
	if !summary.HasResult {
		t.Fatal("expected stored result to remain available")
	}
	if !summary.Stale {
		t.Fatal("expected result to be marked stale")
	}
	if !summary.NeedsRun {
		t.Fatal("expected stale result to require rerun")
	}
	if summary.Ready {
		t.Fatal("expected stale result to report ready=false")
	}
}

func TestStoreFailedRerunPreservesPreviousResult(t *testing.T) {
	store := NewStore()
	store.SetRuntimeStatus(StatusIdle, "Validation has not been run yet")
	store.StartRun("run-1", time.Unix(10, 0))
	store.CompleteRun("run-1", map[string]Entity{
		"span:trace-1:span-1": {
			Key:             "span:trace-1:span-1",
			HighestSeverity: SeverityViolation,
			Signal:          SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
			UpdatedAt:       time.Unix(11, 0),
			Findings: []Finding{{
				EntityKey: "span:trace-1:span-1",
				Source:    "weaver",
				RuleID:    "missing_attribute",
				Severity:  SeverityViolation,
				Message:   "missing attribute",
				Signal:    SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
				UpdatedAt: time.Unix(11, 0),
			}},
		},
	}, weaverStats{}, time.Unix(11, 0))

	store.StartRun("run-2", time.Unix(12, 0))
	if !store.FailRun("run-2", "validation failed", time.Unix(13, 0)) {
		t.Fatal("expected rerun failure to be recorded")
	}

	summary := store.Summary()
	if summary.Status != StatusError {
		t.Fatalf("expected error status, got %s", summary.Status)
	}
	if !summary.HasResult {
		t.Fatal("expected previous successful result to remain available")
	}
	if summary.TotalAdvisories != 1 {
		t.Fatalf("expected previous advisory count to remain, got %d", summary.TotalAdvisories)
	}
	if summary.LastError != "validation failed" {
		t.Fatalf("expected last error to be preserved, got %q", summary.LastError)
	}
}

func TestStoreSnapshotWithoutLimitReturnsAllFindings(t *testing.T) {
	store := NewStore()
	store.SetRuntimeStatus(StatusReady, "ready")

	findings := make([]Finding, 0, 3)
	for i := 0; i < 3; i++ {
		findings = append(findings, Finding{
			EntityKey: "metric:checkout::jvm.thread.count",
			Source:    "weaver",
			RuleID:    "rule-" + string(rune('a'+i)),
			Severity:  SeverityViolation,
			Message:   "finding",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "jvm.thread.count"},
			UpdatedAt: time.Unix(int64(10+i), 0),
		})
	}

	store.UpsertEntity(Entity{
		Key:             "metric:checkout::jvm.thread.count",
		HighestSeverity: SeverityViolation,
		Signal:          SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "jvm.thread.count"},
		UpdatedAt:       time.Unix(12, 0),
		Findings:        findings,
	})

	full := store.Snapshot(0)
	if len(full.Findings) != 3 {
		t.Fatalf("expected all findings in unlimited snapshot, got %d", len(full.Findings))
	}

	limited := store.Snapshot(2)
	if len(limited.Findings) != 2 {
		t.Fatalf("expected limited snapshot to respect limit, got %d", len(limited.Findings))
	}
}

func TestBuildIssuesIncludesSeverityBreakdownAndSortsBySeverityCounts(t *testing.T) {
	issues := buildIssues([]Finding{
		{
			EntityKey: "metric:checkout::metric-a",
			RuleID:    "rule-a",
			Severity:  SeverityViolation,
			Message:   "violation",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "metric-a"},
			UpdatedAt: time.Unix(10, 0),
		},
		{
			EntityKey: "metric:checkout::metric-a",
			RuleID:    "rule-a-info-1",
			Severity:  SeverityInformation,
			Message:   "information",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "metric-a"},
			UpdatedAt: time.Unix(11, 0),
		},
		{
			EntityKey: "metric:checkout::metric-a",
			RuleID:    "rule-a-info-2",
			Severity:  SeverityInformation,
			Message:   "information",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "metric-a"},
			UpdatedAt: time.Unix(12, 0),
		},
		{
			EntityKey: "metric:checkout::metric-b",
			RuleID:    "rule-b-1",
			Severity:  SeverityViolation,
			Message:   "violation",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "metric-b"},
			UpdatedAt: time.Unix(10, 0),
		},
		{
			EntityKey: "metric:checkout::metric-b",
			RuleID:    "rule-b-2",
			Severity:  SeverityViolation,
			Message:   "violation",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "metric-b"},
			UpdatedAt: time.Unix(11, 0),
		},
		{
			EntityKey: "metric:checkout::metric-b",
			RuleID:    "rule-b-3",
			Severity:  SeverityInformation,
			Message:   "information",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "metric-b"},
			UpdatedAt: time.Unix(12, 0),
		},
		{
			EntityKey: "metric:checkout::metric-c",
			RuleID:    "rule-c-1",
			Severity:  SeverityViolation,
			Message:   "violation",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "metric-c"},
			UpdatedAt: time.Unix(10, 0),
		},
		{
			EntityKey: "metric:checkout::metric-c",
			RuleID:    "rule-c-2",
			Severity:  SeverityViolation,
			Message:   "violation",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "metric-c"},
			UpdatedAt: time.Unix(11, 0),
		},
		{
			EntityKey: "metric:checkout::metric-c",
			RuleID:    "rule-c-3",
			Severity:  SeverityImprovement,
			Message:   "improvement",
			Signal:    SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "metric-c"},
			UpdatedAt: time.Unix(12, 0),
		},
	})

	if len(issues) != 3 {
		t.Fatalf("expected 3 issues, got %d", len(issues))
	}
	if issues[0].TargetLabel != "metric-c" {
		t.Fatalf("expected metric-c first by violation and improvement tie-breakers, got %s", issues[0].TargetLabel)
	}
	if issues[0].ViolationCount != 2 || issues[0].ImprovementCount != 1 || issues[0].InformationCount != 0 {
		t.Fatalf("unexpected severity counts for metric-c: %+v", issues[0])
	}
	if issues[1].TargetLabel != "metric-b" {
		t.Fatalf("expected metric-b second by information tie-breaker, got %s", issues[1].TargetLabel)
	}
	if issues[2].TargetLabel != "metric-a" {
		t.Fatalf("expected metric-a last because it has fewer violations, got %s", issues[2].TargetLabel)
	}
}

func TestBuildIssuesCountsDistinctCorrectiveVariants(t *testing.T) {
	issues := buildIssues([]Finding{
		{
			EntityKey: "metric:orders::http.server.request.count",
			RuleID:    "missing_metric",
			Severity:  SeverityViolation,
			Message:   "Metric does not exist in the registry.",
			Signal:    SignalRef{Type: "metric", MetricName: "http.server.request.count"},
			UpdatedAt: time.Unix(10, 0),
		},
		{
			EntityKey: "metric:payments::http.server.request.count",
			RuleID:    "missing_metric",
			Severity:  SeverityViolation,
			Message:   "Metric does not exist in the registry.",
			Signal:    SignalRef{Type: "metric", MetricName: "http.server.request.count"},
			UpdatedAt: time.Unix(11, 0),
		},
		{
			EntityKey: "metric:payments::http.server.request.count",
			RuleID:    "missing_description",
			Severity:  SeverityImprovement,
			Message:   "Metric should include a description.",
			Signal:    SignalRef{Type: "metric", MetricName: "http.server.request.count"},
			UpdatedAt: time.Unix(12, 0),
		},
	})

	if len(issues) != 1 {
		t.Fatalf("expected 1 grouped issue, got %d", len(issues))
	}
	if issues[0].Count != 2 {
		t.Fatalf("expected 2 distinct corrective variants, got %d", issues[0].Count)
	}
	if issues[0].ViolationCount != 1 {
		t.Fatalf("expected 1 distinct violation, got %d", issues[0].ViolationCount)
	}
	if issues[0].ImprovementCount != 1 {
		t.Fatalf("expected 1 distinct improvement, got %d", issues[0].ImprovementCount)
	}
	if issues[0].AffectedEntityCount != 2 {
		t.Fatalf("expected 2 affected entities, got %d", issues[0].AffectedEntityCount)
	}
}

func TestBuildIssuesUsesResourceAttributeNameWhenUnique(t *testing.T) {
	issues := buildIssues([]Finding{{
		EntityKey: "resource:",
		RuleID:    "not_stable",
		Severity:  SeverityViolation,
		Message:   "Attribute 'deployment.environment.name' is not stable; stability = development.",
		Context: map[string]any{
			"attribute_name": "deployment.environment.name",
			"stability":      "development",
		},
		Signal:    SignalRef{Type: "resource"},
		UpdatedAt: time.Unix(10, 0),
	}})

	if len(issues) != 1 {
		t.Fatalf("expected 1 issue, got %d", len(issues))
	}
	if issues[0].TargetLabel != "deployment.environment.name" {
		t.Fatalf("expected resource target label to use unique attribute name, got %s", issues[0].TargetLabel)
	}
}
