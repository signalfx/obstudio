package mcp

import (
	"encoding/json"
	"math"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

const correctnessTraceID = "11111111111111111111111111111111"
const correctnessWitnessID = "1111111111111111"
const correctnessAppSpanID = "2222222222222222"

func correctnessFixture(t *testing.T) (*Dispatcher, map[string]any, store.TelemetrySnapshot) {
	t.Helper()
	d := NewDispatcher(store.New(), testSkillCatalog())
	run := completedWorkflow(d, t)
	start := run.StartedAt.Add(time.Second)
	resource := store.Resource{ServiceName: "tasks", Attributes: map[string]any{"service.name": "tasks", "service.version": "fixture-v1"}}
	witness := store.Span{TraceID: correctnessTraceID, SpanID: correctnessWitnessID, Name: "scenario POST /tasks", StartTime: start, EndTime: start.Add(time.Second), Status: store.SpanStatus{Code: "OK"}, Resource: resource, Scope: store.Scope{Name: "obstudio.verification"}, Attributes: map[string]any{
		"verification.run_id": run.RunID, "verification.scenario": "tasks.create", "verification.completed": true, "verification.proof_mode": "app_test",
		"verification.span_ids": []string{correctnessAppSpanID}, "verification.metric_count": 1, "verification.log_count": 1,
	}}
	app := store.Span{TraceID: correctnessTraceID, SpanID: correctnessAppSpanID, ParentSpanID: correctnessWitnessID, Name: "POST /tasks", Kind: "SERVER", Status: store.SpanStatus{Code: "UNSET"}, Resource: resource, Scope: store.Scope{Name: "app"}, StartTime: start.Add(time.Millisecond), EndTime: start.Add(2 * time.Millisecond), Attributes: map[string]any{"http.route": "/tasks", "http.response.status_code": int64(201)}}
	point := store.MetricDataPoint{Name: "tasks.created", Type: "sum", Unit: "{task}", Value: 1, Timestamp: app.EndTime, Resource: resource, Attributes: map[string]any{"verification.run_id": run.RunID, "verification.scenario": "tasks.create", "outcome": "success"}}
	record := store.LogRecord{ID: "test-log", TraceID: correctnessTraceID, SpanID: correctnessAppSpanID, SeverityText: "INFO", Timestamp: app.EndTime, Resource: resource, Body: "private body must not be copied into evaluation events", Attributes: map[string]any{"event.name": "task.created", "outcome": "success"}}
	args := map[string]any{"runId": run.RunID, "auditSha256": "sha256:" + strings.Repeat("a", 64), "sourceRevision": "fixture-v1", "scenarios": []any{map[string]any{
		"id": "tasks.create", "traceId": correctnessTraceID, "witnessSpanId": correctnessWitnessID, "serviceName": "tasks", "rules": []any{
			map[string]any{"name": "tasks.server", "findingId": "OTEL-001", "claim": "instrumentation", "signal": "span", "signalName": "POST /tasks", "count": 1, "kind": "SERVER", "status": "UNSET", "parentName": "scenario POST /tasks", "attributes": map[string]any{"http.route": "/tasks", "http.response.status_code": 201}},
			map[string]any{"name": "tasks.metric", "findingId": "OTEL-002", "claim": "instrumentation", "signal": "metric", "signalName": "tasks.created", "count": 1, "metricType": "sum", "unit": "{task}", "minValue": 1, "maxValue": 1, "attributes": map[string]any{"outcome": "success"}},
			map[string]any{"name": "tasks.log", "findingId": "OTEL-003", "claim": "instrumentation", "signal": "log", "signalName": "task.created", "count": 1, "severity": "INFO", "parentName": "POST /tasks", "attributes": map[string]any{"outcome": "success"}},
		},
	}}}
	return d, args, store.TelemetrySnapshot{Spans: []store.Span{witness, app}, Metrics: []store.MetricDataPoint{point}, Logs: []store.LogRecord{record}}
}

func retainCorrectnessFixture(d *Dispatcher, snapshot store.TelemetrySnapshot) {
	d.store.AddSpansForConnection("app-fixture", snapshot.Spans)
	d.store.AddMetricsForConnection("app-fixture", snapshot.Metrics)
	d.store.AddLogsForConnection("app-fixture", snapshot.Logs)
}

func correctnessResults(t *testing.T, d *Dispatcher, args map[string]any) map[string]any {
	t.Helper()
	result := d.skillCorrectnessEvaluate(args)
	if result.IsError {
		t.Fatal(result)
	}
	return toMapAny(parseToolResult(t, result))
}

func correctnessRules(args map[string]any) []any {
	return toMapAny(toSliceAny(args["scenarios"])[0])["rules"].([]any)
}

func TestCorrectnessChecksApplicationTelemetryDespiteReportedWorkflowSuccess(t *testing.T) {
	for _, test := range []struct {
		name   string
		change func(*store.TelemetrySnapshot)
		want   []string
	}{
		{"correct", func(*store.TelemetrySnapshot) {}, []string{"pass", "pass", "pass"}},
		{"wrong route", func(s *store.TelemetrySnapshot) { s.Spans[1].Attributes["http.route"] = "/wrong" }, []string{"fail", "pass", "pass"}},
		{"missing status attribute", func(s *store.TelemetrySnapshot) { delete(s.Spans[1].Attributes, "http.response.status_code") }, []string{"fail", "pass", "pass"}},
		{"wrong kind", func(s *store.TelemetrySnapshot) { s.Spans[1].Kind = "INTERNAL" }, []string{"fail", "pass", "pass"}},
		{"wrong status", func(s *store.TelemetrySnapshot) { s.Spans[1].Status.Code = "ERROR" }, []string{"fail", "pass", "pass"}},
		{"wrong parent", func(s *store.TelemetrySnapshot) { s.Spans[1].ParentSpanID = "" }, []string{"fail", "pass", "pass"}},
		{"missing span in complete capture", func(s *store.TelemetrySnapshot) {
			s.Spans = s.Spans[:1]
			s.Spans[0].Attributes["verification.span_ids"] = []string{}
		}, []string{"fail", "pass", "fail"}},
		{"wrong metric type", func(s *store.TelemetrySnapshot) { s.Metrics[0].Type = "gauge" }, []string{"pass", "fail", "pass"}},
		{"wrong metric unit", func(s *store.TelemetrySnapshot) { s.Metrics[0].Unit = "s" }, []string{"pass", "fail", "pass"}},
		{"wrong metric dimensions", func(s *store.TelemetrySnapshot) { s.Metrics[0].Attributes["outcome"] = "failed" }, []string{"pass", "fail", "pass"}},
		{"metric value outside range", func(s *store.TelemetrySnapshot) { s.Metrics[0].Value = 2 }, []string{"pass", "fail", "pass"}},
		{"no recorded metric value", func(s *store.TelemetrySnapshot) { s.Metrics[0].Flags = 1 }, []string{"pass", "fail", "pass"}},
		{"wrong log severity", func(s *store.TelemetrySnapshot) { s.Logs[0].SeverityText = "DEBUG" }, []string{"pass", "pass", "fail"}},
		{"uncorrelated log", func(s *store.TelemetrySnapshot) { s.Logs[0].SpanID = correctnessWitnessID }, []string{"pass", "pass", "fail"}},
		{"wrong log attributes", func(s *store.TelemetrySnapshot) { s.Logs[0].Attributes["outcome"] = "failure" }, []string{"pass", "pass", "fail"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			d, args, snapshot := correctnessFixture(t)
			test.change(&snapshot)
			retainCorrectnessFixture(d, snapshot)
			rows := toSliceAny(correctnessResults(t, d, args)["results"])
			for i, want := range test.want {
				if got := toMapAny(rows[i])["outcome"]; got != want {
					t.Fatalf("rule %d = %v, want %s: %+v", i, got, want, rows)
				}
			}
		})
	}
}

func TestCorrectnessRejectsUnfingerprintableEvidenceWithoutPublishing(t *testing.T) {
	d, args, snapshot := correctnessFixture(t)
	snapshot.Metrics[0].Value = math.NaN()
	retainCorrectnessFixture(d, snapshot)
	before := len(d.store.SnapshotSpans())
	if result := d.skillCorrectnessEvaluate(args); !result.IsError || len(d.store.SnapshotSpans()) != before {
		t.Fatal("nonfinite evidence created an invalid or reused receipt", result)
	}
}

func TestCorrectnessAuditGapCanBeSupportedOrRefuted(t *testing.T) {
	for _, missing := range []bool{false, true} {
		d, args, snapshot := correctnessFixture(t)
		toMapAny(correctnessRules(args)[0])["claim"] = "audit_gap"
		if missing {
			delete(snapshot.Spans[1].Attributes, "http.route")
		}
		retainCorrectnessFixture(d, snapshot)
		row := toMapAny(toSliceAny(correctnessResults(t, d, args)["results"])[0])
		want := "fail"
		if missing {
			want = "pass"
		}
		if row["outcome"] != want {
			t.Fatal(row)
		}
	}
}

func TestCorrectnessUnknownCannotBecomePassingEvidence(t *testing.T) {
	for _, test := range []struct {
		name   string
		change func(*store.TelemetrySnapshot)
	}{
		{"no witness", func(s *store.TelemetrySnapshot) { s.Spans = s.Spans[1:] }},
		{"stale revision", func(s *store.TelemetrySnapshot) { s.Spans[0].Resource.Attributes["service.version"] = "old" }},
		{"wrong run", func(s *store.TelemetrySnapshot) {
			s.Spans[0].Attributes["verification.run_id"] = strings.Repeat("f", 32)
		}},
		{"wrong scenario", func(s *store.TelemetrySnapshot) { s.Spans[0].Attributes["verification.scenario"] = "other" }},
		{"wrong service", func(s *store.TelemetrySnapshot) { s.Spans[0].Resource.ServiceName = "other" }},
		{"unfinished witness", func(s *store.TelemetrySnapshot) { s.Spans[0].Attributes["verification.completed"] = false }},
		{"failed trigger", func(s *store.TelemetrySnapshot) { s.Spans[0].Status.Code = "ERROR" }},
		{"synthetic contract", func(s *store.TelemetrySnapshot) { s.Spans[0].Attributes["verification.proof_mode"] = "contract_only" }},
		{"recorder as app", func(s *store.TelemetrySnapshot) { s.Spans[1].Scope.Name = "obstudio.skill-workflows" }},
		{"conflicting spans", func(s *store.TelemetrySnapshot) {
			copy := s.Spans[1]
			copy.Name = "conflict"
			s.Spans = append(s.Spans, copy)
		}},
	} {
		t.Run(test.name, func(t *testing.T) {
			d, args, snapshot := correctnessFixture(t)
			test.change(&snapshot)
			retainCorrectnessFixture(d, snapshot)
			before := len(d.store.SnapshotSpans())
			result := correctnessResults(t, d, args)
			for _, row := range toSliceAny(result["results"]) {
				if toMapAny(row)["outcome"] != "unknown" || toMapAny(row)["score"] != nil {
					t.Fatal(result)
				}
			}
			if len(d.store.SnapshotSpans()) != before {
				t.Fatal("unknown evaluations published passing/failed events")
			}
		})
	}
}

func TestCorrectnessCaptureCompletenessPerSignal(t *testing.T) {
	for _, key := range []string{"verification.span_ids", "verification.metric_count", "verification.log_count"} {
		d, args, snapshot := correctnessFixture(t)
		delete(snapshot.Spans[0].Attributes, key)
		retainCorrectnessFixture(d, snapshot)
		rows := toSliceAny(correctnessResults(t, d, args)["results"])
		for i, signal := range []string{"span_ids", "metric_count", "log_count"} {
			want := "pass"
			if key == "verification."+signal || (key == "verification.span_ids" && signal == "log_count") {
				want = "unknown"
			}
			if toMapAny(rows[i])["outcome"] != want {
				t.Fatal(rows)
			}
		}
	}
	for _, key := range []string{"span", "metric", "log"} {
		d, args, snapshot := correctnessFixture(t)
		switch key {
		case "span":
			snapshot.Spans = snapshot.Spans[:1]
		case "metric":
			snapshot.Metrics = nil
		case "log":
			snapshot.Logs = nil
		}
		retainCorrectnessFixture(d, snapshot)
		for _, value := range toSliceAny(correctnessResults(t, d, args)["results"]) {
			row := toMapAny(value)
			if (row["signal"] == key || (key == "span" && row["signal"] == "log")) && row["outcome"] != "unknown" {
				t.Fatal("evicted evidence became a failure or pass", row)
			}
		}
	}
}

func TestCorrectnessClosedCaptureDetectsMissingMetricsAndLogs(t *testing.T) {
	d, args, snapshot := correctnessFixture(t)
	snapshot.Metrics = nil
	snapshot.Logs = nil
	snapshot.Spans[0].Attributes["verification.metric_count"] = 0
	snapshot.Spans[0].Attributes["verification.log_count"] = 0
	retainCorrectnessFixture(d, snapshot)
	rows := toSliceAny(correctnessResults(t, d, args)["results"])
	if toMapAny(rows[0])["outcome"] != "pass" || toMapAny(rows[1])["outcome"] != "fail" || toMapAny(rows[2])["outcome"] != "fail" {
		t.Fatal(rows)
	}
}

func TestCorrectnessHistogramNeedsRealMeasurements(t *testing.T) {
	for _, count := range []uint64{0, 1} {
		d, args, snapshot := correctnessFixture(t)
		rule := toMapAny(correctnessRules(args)[1])
		rule["metricType"] = "histogram"
		delete(rule, "minValue")
		delete(rule, "maxValue")
		snapshot.Metrics[0].Type = "histogram"
		snapshot.Metrics[0].Count = count
		snapshot.Metrics[0].Sum = 0.4
		retainCorrectnessFixture(d, snapshot)
		row := toMapAny(toSliceAny(correctnessResults(t, d, args)["results"])[1])
		want := "fail"
		if count > 0 {
			want = "pass"
		}
		if row["outcome"] != want {
			t.Fatal(row)
		}
	}
}

func TestCorrectnessInvalidManifestAndRevisionNeverProveAbsence(t *testing.T) {
	for _, test := range []struct {
		name   string
		change func(*store.TelemetrySnapshot)
	}{
		{"duplicate ids", func(s *store.TelemetrySnapshot) {
			s.Spans[0].Attributes["verification.span_ids"] = []string{correctnessAppSpanID, correctnessAppSpanID}
			copy := s.Spans[1]
			copy.SpanID = "3333333333333333"
			s.Spans = append(s.Spans, copy)
		}},
		{"wrong ids", func(s *store.TelemetrySnapshot) {
			s.Spans[0].Attributes["verification.span_ids"] = []string{"3333333333333333"}
		}},
		{"invalid ids", func(s *store.TelemetrySnapshot) { s.Spans[0].Attributes["verification.span_ids"] = []string{"bad"} }},
		{"stale metric", func(s *store.TelemetrySnapshot) {
			s.Metrics[0].Resource = store.Resource{ServiceName: "tasks", Attributes: map[string]any{"service.version": "old"}}
		}},
		{"stale log", func(s *store.TelemetrySnapshot) {
			s.Logs[0].Resource = store.Resource{ServiceName: "tasks", Attributes: map[string]any{"service.version": "old"}}
		}},
	} {
		t.Run(test.name, func(t *testing.T) {
			d, args, snapshot := correctnessFixture(t)
			test.change(&snapshot)
			retainCorrectnessFixture(d, snapshot)
			row := toMapAny(toSliceAny(correctnessResults(t, d, args)["results"])[0])
			if row["outcome"] != "unknown" {
				t.Fatal(row)
			}
		})
	}
}

func TestCorrectnessMultipleScenariosIsolateUnavailableCapture(t *testing.T) {
	d, args, snapshot := correctnessFixture(t)
	retainCorrectnessFixture(d, snapshot)
	copy := map[string]any{"id": "tasks.other", "traceId": strings.Repeat("e", 32), "witnessSpanId": correctnessWitnessID, "serviceName": "tasks", "rules": []any{
		map[string]any{"name": "other.span", "findingId": "OTEL-004", "claim": "instrumentation", "signal": "span", "signalName": "GET /other", "count": 1},
	}}
	args["scenarios"] = append(toSliceAny(args["scenarios"]), copy)
	rows := toSliceAny(correctnessResults(t, d, args)["results"])
	for i, want := range []string{"pass", "pass", "pass", "unknown"} {
		if toMapAny(rows[i])["outcome"] != want {
			t.Fatal(rows)
		}
	}
}

func TestCorrectnessReceiptsAndEventsDoNotAffectWorkflowChecks(t *testing.T) {
	d, args, snapshot := correctnessFixture(t)
	retainCorrectnessFixture(d, snapshot)
	workflowBefore := toMapAny(parseToolResult(t, d.skillWorkflowEvaluate(map[string]any{"runId": args["runId"]})))
	first := correctnessResults(t, d, args)
	second := correctnessResults(t, d, args)
	if first["evaluationDigest"] != second["evaluationDigest"] || second["newSpans"] != float64(0) {
		t.Fatal("replay did not deduplicate", first, second)
	}
	workflowAfter := toMapAny(parseToolResult(t, d.skillWorkflowEvaluate(map[string]any{"runId": args["runId"]})))
	if workflowBefore["evaluationDigest"] != workflowAfter["evaluationDigest"] {
		t.Fatal("correctness results contaminated workflow execution evaluation")
	}
	found := false
	for _, span := range d.store.SnapshotSpans() {
		if span.Attributes["skill.evaluation.source"] != "retained_application_telemetry" {
			continue
		}
		found = true
		if len(span.Links) != 1 || span.Links[0].TraceID != correctnessTraceID || len(span.Events) != 3 || span.Attributes["skill.evaluation.audit_sha256"] != args["auditSha256"] {
			t.Fatal(span)
		}
		data, _ := json.Marshal(span)
		if strings.Contains(string(data), "private body") || strings.Contains(string(data), "http.response.status_code") {
			t.Fatal("raw application evidence was copied into evaluation events")
		}
	}
	if !found {
		t.Fatal("no trace-linked correctness events")
	}
	toMapAny(correctnessRules(args)[0])["kind"] = "CLIENT"
	changed := correctnessResults(t, d, args)
	if changed["evaluationDigest"] == first["evaluationDigest"] || toMapAny(toSliceAny(changed["results"])[0])["outcome"] != "fail" {
		t.Fatal("changed contract reused old receipt", changed)
	}
	row := toMapAny(toSliceAny(toMapAny(parseToolResult(t, d.skillWorkflows(map[string]any{"runId": args["runId"]})))["runs"])[0])
	if len(toSliceAny(row["evaluations"])) != 10 {
		t.Fatal("workflow query omitted correctness events", row)
	}
}

func TestCorrectnessRejectsInvalidContracts(t *testing.T) {
	for _, change := range []func(map[string]any){
		func(a map[string]any) { a["passed"] = true },
		func(a map[string]any) { a["auditSha256"] = "not-a-digest" },
		func(a map[string]any) { a["sourceRevision"] = "" },
		func(a map[string]any) { a["scenarios"] = []any{} },
		func(a map[string]any) { toMapAny(correctnessRules(a)[0])["count"] = 0 },
		func(a map[string]any) { toMapAny(correctnessRules(a)[0])["claim"] = "passed" },
		func(a map[string]any) { toMapAny(correctnessRules(a)[0])["signal"] = "token" },
		func(a map[string]any) { toMapAny(correctnessRules(a)[0])["kind"] = "UNKNOWN" },
		func(a map[string]any) {
			toMapAny(correctnessRules(a)[0])["attributes"] = map[string]any{"nested": map[string]any{}}
		},
		func(a map[string]any) { toMapAny(correctnessRules(a)[1])["unit"] = nil },
		func(a map[string]any) { toMapAny(correctnessRules(a)[1])["minValue"] = 5 },
		func(a map[string]any) { toMapAny(correctnessRules(a)[2])["severity"] = "VERBOSE" },
		func(a map[string]any) { toMapAny(correctnessRules(a)[2])["name"] = "tasks.server" },
		func(a map[string]any) { toMapAny(toSliceAny(a["scenarios"])[0])["traceId"] = a["runId"] },
	} {
		d, args, snapshot := correctnessFixture(t)
		retainCorrectnessFixture(d, snapshot)
		change(args)
		before := len(d.store.SnapshotSpans())
		if !d.skillCorrectnessEvaluate(args).IsError || len(d.store.SnapshotSpans()) != before {
			t.Fatal("invalid request accepted or partially published", args)
		}
	}
}

func TestCorrectnessReceiptIgnoresCaptureArrivalOrder(t *testing.T) {
	d, args, snapshot := correctnessFixture(t)
	workflowSpans := d.store.SnapshotSpans()
	secondPoint := snapshot.Metrics[0]
	secondPoint.Timestamp = secondPoint.Timestamp.Add(time.Nanosecond)
	snapshot.Metrics = append(snapshot.Metrics, secondPoint)
	secondLog := snapshot.Logs[0]
	secondLog.ID = "second-log"
	snapshot.Logs = append(snapshot.Logs, secondLog)
	snapshot.Spans[0].Attributes["verification.metric_count"] = 2
	snapshot.Spans[0].Attributes["verification.log_count"] = 2
	toMapAny(correctnessRules(args)[1])["count"] = 2
	toMapAny(correctnessRules(args)[2])["count"] = 2
	retainCorrectnessFixture(d, snapshot)
	first := correctnessResults(t, d, args)
	d.store.Clear()
	if _, err := d.store.AddSkillWorkflowSpans(workflowSpans); err != nil {
		t.Fatal(err)
	}
	snapshot.Metrics[0], snapshot.Metrics[1] = snapshot.Metrics[1], snapshot.Metrics[0]
	snapshot.Logs[0], snapshot.Logs[1] = snapshot.Logs[1], snapshot.Logs[0]
	retainCorrectnessFixture(d, snapshot)
	second := correctnessResults(t, d, args)
	if first["evaluationDigest"] != second["evaluationDigest"] {
		t.Fatal("unchanged captured evidence changed its receipt when arrival order changed", first, second)
	}
}

func TestCorrectnessUnavailableToolAndMissingWorkflowLeaveExistingToolsUsable(t *testing.T) {
	d := NewDispatcher(store.New())
	response, _ := d.Dispatch(jsonRPCRequest{JSONRPC: "2.0", ID: 1, Method: "tools/call", Params: map[string]any{"name": "observer_skill_correctness_evaluate", "arguments": map[string]any{}}})
	if response.Error == nil || response.Error.Code != -32602 {
		t.Fatal("catalog-free server advertised an unavailable tool", response)
	}
	response, _ = d.Dispatch(jsonRPCRequest{JSONRPC: "2.0", ID: 2, Method: "tools/call", Params: map[string]any{"name": "observer_status"}})
	if response.Error != nil {
		t.Fatal("unavailable correctness tool broke the existing status tool", response)
	}
	d, args, snapshot := correctnessFixture(t)
	d.store.Clear()
	retainCorrectnessFixture(d, snapshot)
	if !d.skillCorrectnessEvaluate(args).IsError {
		t.Fatal("application capture alone invented a completed skill workflow")
	}
}
