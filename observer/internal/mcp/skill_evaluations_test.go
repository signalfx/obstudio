package mcp

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

func completedWorkflow(d *Dispatcher, t *testing.T) workflowRun {
	t.Helper()
	run := testWorkflowRun()
	run.Events = []workflowEvent{checkpoint(run, "discover", 1), checkpoint(run, "assess", 1), checkpoint(run, "report", 1)}
	duration, code := 42.0, 0
	run.Events[2].Source = "executed"
	run.Events[2].DurationMs = &duration
	run.Events[2].ExitCode = &code
	run.Events[2].EndedAt = run.Events[2].StartedAt.Add(42 * time.Millisecond)
	finish := run.StartedAt.Add(5 * time.Second)
	run.FinishedAt = &finish
	run.Status = "passed"
	if result := recordWorkflow(d, run); result.IsError {
		t.Fatal(result)
	}
	return run
}

func TestWorkflowGenAIProjectionUsesActualOperationBoundaries(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s, testSkillCatalog())
	run := completedWorkflow(d, t)
	trace := s.Trace(run.RunID, 100)
	if trace == nil || !trace.GenAI.IsGenAI || trace.GenAI.TokenUsageObserved || trace.GenAI.LLMCalls != 0 || trace.GenAI.ToolCalls != 1 {
		t.Fatalf("wrong GenAI projection: %+v", trace)
	}
	if len(trace.GenAI.ModelNames) != 0 {
		t.Fatal("invented model")
	}
	workflows, tools := 0, 0
	for _, span := range trace.Spans {
		if span.Attributes["gen_ai.usage.input_tokens"] != nil || span.Attributes["gen_ai.provider.name"] != nil {
			t.Fatal("invented provider accounting")
		}
		switch span.Attributes["gen_ai.operation.name"] {
		case "invoke_workflow":
			workflows++
			if span.Name != "invoke_workflow otel-audit" {
				t.Fatal(span.Name)
			}
		case "execute_tool":
			tools++
			if span.Attributes["skill.observation"] != "executed" || span.ParentSpanID == "" {
				t.Fatal("false tool boundary")
			}
		}
		if span.Attributes["skill.observation"] == "checkpoint" && span.Attributes["gen_ai.operation.name"] != nil {
			t.Fatal("checkpoint became a tool call")
		}
	}
	if workflows != 1 || tools != 1 {
		t.Fatalf("workflow=%d tool=%d", workflows, tools)
	}
	if len(trace.GenAI.FlowNodes) == 0 || trace.GenAI.FlowNodes[0].DescendantEvaluationCount != 4 {
		t.Fatalf("evaluation rollup missing: %+v", trace.GenAI.FlowNodes)
	}
}

func TestTelemetryEvaluationDefinitionsAndUnknownMeasurements(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s, testSkillCatalog())
	run := completedWorkflow(d, t)
	rules := []map[string]any{
		{"name": "report.latency", "check": "stage_duration", "stage": "report", "maxMs": 40},
		{"name": "discover.latency", "check": "stage_duration", "stage": "discover", "maxMs": 1000},
		{"name": "discover.branch", "check": "stage_branch", "stage": "discover", "expected": "go"},
		{"name": "workflow.budget", "check": "workflow_duration", "maxMs": 6000},
	}
	result := d.skillWorkflowEvaluate(map[string]any{"runId": run.RunID, "rules": rules})
	if result.IsError {
		t.Fatal(result)
	}
	parsed := toMapAny(parseToolResult(t, result))
	values := toSliceAny(parsed["results"])
	for index, want := range []string{"fail", "unknown", "fail", "pass"} {
		row := toMapAny(values[index])
		if row["outcome"] != want {
			t.Fatalf("rule %d: %v", index, row)
		}
		if want == "unknown" && row["score"] != nil {
			t.Fatal("unknown scored as success")
		}
	}
	before := len(s.SnapshotSpans())
	result = d.skillWorkflowEvaluate(map[string]any{"runId": run.RunID, "rules": rules})
	if result.IsError || len(s.SnapshotSpans()) != before {
		t.Fatal("evaluation replay not idempotent")
	}
	trace := s.Trace(run.RunID, 100)
	found := false
	for _, span := range trace.Spans {
		for _, event := range span.Events {
			if event.Attributes["gen_ai.evaluation.name"] == "report.latency" {
				found = true
				if event.Attributes["gen_ai.evaluation.score.label"] != "fail" {
					t.Fatal("threshold failure lost")
				}
			}
			if event.Attributes["gen_ai.evaluation.name"] == "discover.latency" {
				t.Fatal("unmeasured checkpoint published an evaluation")
			}
		}
	}
	if !found {
		t.Fatal("no trace-linked result")
	}
	for _, invalid := range []any{[]map[string]any{{"name": "bad", "check": "invented"}}, []map[string]any{{"name": "bad", "check": "stage_duration", "stage": "report", "maxMs": -1}}, []map[string]any{{"name": "bad", "check": "stage_branch", "stage": "report", "expected": "invented"}}, []map[string]any{{"name": "bad", "check": "stage_present", "stage": "report", "secret": "data"}}} {
		if !d.skillWorkflowEvaluate(map[string]any{"runId": run.RunID, "rules": invalid}).IsError {
			t.Fatal("invalid rule accepted")
		}
	}
}

func TestTelemetryEvaluationIncompleteRetentionAndMalformedMetadata(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s, testSkillCatalog())
	run := testWorkflowRun()
	if result := recordWorkflow(d, run); result.IsError {
		t.Fatal(result)
	}
	result := toMapAny(parseToolResult(t, d.skillWorkflowEvaluate(map[string]any{"runId": run.RunID})))
	for _, value := range toSliceAny(result["results"]) {
		if toMapAny(value)["outcome"] != "unknown" {
			t.Fatal("unfinished evaluated as complete")
		}
	}
	if len(s.SnapshotSpans()) != 1 {
		t.Fatal("unfinished generated passing telemetry")
	}
	s = store.New()
	d = NewDispatcher(s, testSkillCatalog())
	run = completedWorkflow(d, t)
	spans := s.SnapshotSpans()
	var root *store.Span
	var steps []store.Span
	for _, span := range spans {
		if span.Attributes["skill.observation"] == "explicit_workflow_interval" {
			copy := span
			root = &copy
		}
		if span.Attributes["skill.stage"] != nil {
			steps = append(steps, span)
		}
	}
	rules := []workflowEvaluationRule{{Name: "present", Check: "stage_coverage"}}
	results := evaluateWorkflowSpans(root, steps[:1], nil, rules)
	if results[0].Outcome != "unknown" {
		t.Fatal("evicted stages not unknown")
	}
	data, _ := json.Marshal(steps)
	var malformed []store.Span
	_ = json.Unmarshal(data, &malformed)
	malformed[0].Attributes["skill.stage.sequence"] = "invalid"
	results = evaluateWorkflowSpans(root, malformed, nil, rules)
	if results[0].Outcome != "unknown" {
		t.Fatal("malformed retained metadata not unknown")
	}
}

func TestPartialWorkflowEvaluationsIdentifyMissingStagesAndCommandErrors(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s, testSkillCatalog())
	run := testWorkflowRun()
	event := checkpoint(run, "assess", 1)
	event.Source = "executed"
	event.Status = "failed"
	duration, code := 12.0, 7
	event.DurationMs = &duration
	event.ExitCode = &code
	run.Events = []workflowEvent{event}
	finish := run.StartedAt.Add(5 * time.Second)
	run.FinishedAt = &finish
	run.Status = "partial"
	if result := recordWorkflow(d, run); result.IsError {
		t.Fatal(result)
	}
	result := toMapAny(parseToolResult(t, d.skillWorkflowEvaluate(map[string]any{"runId": run.RunID})))
	for _, value := range toSliceAny(result["results"]) {
		if toMapAny(value)["outcome"] != "fail" {
			t.Fatalf("partial path defect missed: %v", value)
		}
	}
	trace := s.Trace(run.RunID, 100)
	for _, span := range trace.Spans {
		if span.Attributes["skill.stage"] == "assess" && (span.Status.Code != "ERROR" || span.Attributes["error.type"] != "skill_stage_failed") {
			t.Fatal("error semantics missing")
		}
	}
}

func TestTelemetryStageAndWorkflowOutcomeRules(t *testing.T) {
	d := NewDispatcher(store.New(), testSkillCatalog())
	run := completedWorkflow(d, t)
	rules := []map[string]any{
		{"name": "present", "check": "stage_present", "stage": "report"},
		{"name": "outcome", "check": "stage_outcome", "stage": "report", "expected": "passed"},
		{"name": "terminal", "check": "workflow_outcome", "expected": "failed"},
	}
	result := toMapAny(parseToolResult(t, d.skillWorkflowEvaluate(map[string]any{"runId": run.RunID, "rules": rules})))
	for index, want := range []string{"pass", "pass", "fail"} {
		if toMapAny(toSliceAny(result["results"])[index])["outcome"] != want {
			t.Fatal(result)
		}
	}
}
