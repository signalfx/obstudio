package store

import (
	"testing"
	"time"
)

func TestSkillWorkflowIdleReplayAndEvaluationRetainSourceEvidence(t *testing.T) {
	s := New()
	now := time.Now()
	root := newTestSpan("workflow", "root", "workflow", now, 10)
	root.Scope.Name = "obstudio.skill-workflows"
	stage := root
	stage.SpanID, stage.ParentSpanID = "stage", "root"
	s.AddMetricsForConnection("app", []MetricDataPoint{{Name: "app.count", Value: 1}})
	if _, err := s.AddSkillWorkflowSpans([]Span{stage}); err != nil {
		t.Fatal(err)
	}
	changes, invalidations := 0, 0
	s.SetChangeCallback(func(time.Time) { changes++ })
	s.SetInvalidateCallback(func() { invalidations++ })
	s.mu.Lock()
	s.lastIngest = now.Add(-35 * time.Second)
	s.mu.Unlock()
	fresh, err := s.AddSkillWorkflowSpans([]Span{stage, root})
	if err != nil || len(fresh) != 1 || len(s.SnapshotSpans()) != 2 || len(s.SnapshotMetrics()) != 1 {
		t.Fatalf("idle replay lost evidence: %v, %+v", err, s.SnapshotTelemetry())
	}
	evaluation := root
	evaluation.SpanID, evaluation.ParentSpanID = "evaluation", "root"
	evaluation.Name = "evaluate application_contracts"
	s.mu.Lock()
	s.lastIngest = now.Add(-35 * time.Second)
	s.mu.Unlock()
	fresh, err = s.AddSkillWorkflowSpans([]Span{evaluation})
	if err != nil || len(fresh) != 1 || len(s.SnapshotSpans()) != 3 || len(s.SnapshotMetrics()) != 1 || changes != 2 || invalidations != 0 || s.LastIngest().Before(now) {
		t.Fatalf("evaluation reset source workflow: %v, %+v", err, s.SnapshotTelemetry())
	}
	for _, span := range s.SnapshotSpans() {
		if span.ingestRevision == 0 || span.ownerConnID != "skill-workflows" {
			t.Fatal("ingestion bookkeeping lost", span)
		}
	}
	// The ordinary application's session-reset contract is unchanged.
	s.mu.Lock()
	s.lastIngest = now.Add(-35 * time.Second)
	s.mu.Unlock()
	s.AddSpansForConnection("app", []Span{newTestSpan("app", "next", "request", now, 1)})
	if len(s.SnapshotSpans()) != 1 || invalidations != 1 {
		t.Fatal("ordinary application session reset changed")
	}
}

func TestSkillWorkflowBatchConflictIsAtomicAndClearAllowsReplay(t *testing.T) {
	s := New()
	span := newTestSpan("workflow", "stage", "first", time.Now(), 1)
	span.Scope.Name = "obstudio.skill-workflows"
	conflict := span
	conflict.Name = "conflict"
	if _, err := s.AddSkillWorkflowSpans([]Span{span, conflict}); err == nil || len(s.SnapshotSpans()) != 0 {
		t.Fatal("conflicting new batch partially committed")
	}
	if fresh, err := s.AddSkillWorkflowSpans([]Span{span, span}); err != nil || len(fresh) != 1 {
		t.Fatal("identical batch duplicate was not deduplicated", err, fresh)
	}
	s.Clear()
	evaluation := span
	evaluation.SpanID = "evaluation"
	evaluation.ParentSpanID = span.SpanID
	evaluation.Attributes = map[string]any{"skill.observation": "telemetry_evaluation"}
	if _, err := s.AddSkillWorkflowSpans([]Span{evaluation}); err == nil || len(s.SnapshotSpans()) != 0 {
		t.Fatal("an evaluation resurrected a workflow cleared after its snapshot")
	}
	if fresh, err := s.AddSkillWorkflowSpans([]Span{span}); err != nil || len(fresh) != 1 {
		t.Fatal("clear prevented journal replay", err, fresh)
	}
}
