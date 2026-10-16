package mcp

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"sort"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

var workflowIdentifier = regexp.MustCompile("^[0-9a-f]{32}$")
var workflowDigest = regexp.MustCompile("^sha256:[0-9a-f]{64}$")
var workflowReason = regexp.MustCompile("^[a-zA-Z0-9._-]{0,160}$")

type workflowEvidence struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}
type workflowEvent struct {
	Stage      string             `json:"stage"`
	Attempt    int                `json:"attempt"`
	Status     string             `json:"status"`
	Source     string             `json:"source"`
	Branch     string             `json:"branch"`
	Reason     string             `json:"reason"`
	StartedAt  time.Time          `json:"startedAt"`
	EndedAt    time.Time          `json:"endedAt"`
	Evidence   []workflowEvidence `json:"evidence"`
	DurationMs *float64           `json:"durationMs,omitempty"`
	ExitCode   *int               `json:"exitCode,omitempty"`
}
type workflowRun struct {
	SchemaVersion  int             `json:"schemaVersion"`
	RunID          string          `json:"runId"`
	Skill          string          `json:"skill"`
	SkillDigest    string          `json:"skillDigest,omitempty"`
	ContractDigest string          `json:"contractDigest,omitempty"`
	StartedAt      time.Time       `json:"startedAt"`
	FinishedAt     *time.Time      `json:"finishedAt,omitempty"`
	Status         string          `json:"status"`
	Events         []workflowEvent `json:"events"`
}
type workflowStage struct {
	ID       string   `json:"id"`
	After    []string `json:"after"`
	Branches []string `json:"branches"`
}

func timeNow() time.Time { return time.Now().UTC() }

func workflowSpanID(runID, stage string, attempt int) string {
	value := sha256.Sum256([]byte(fmt.Sprintf("%s/%s/%d", runID, stage, attempt)))
	return hex.EncodeToString(value[:8])
}

func skillSpan(traceID, spanID, parent, name string, start, end time.Time, attrs map[string]any) store.Span {
	return store.Span{TraceID: traceID, SpanID: spanID, ParentSpanID: parent, Name: name,
		Kind: "INTERNAL", StartTime: start, EndTime: end, DurationMs: end.Sub(start).Seconds() * 1000,
		Status: store.SpanStatus{Code: "UNSET"}, Attributes: attrs,
		Resource: store.Resource{ServiceName: "obstudio.skills", Attributes: map[string]any{"service.name": "obstudio.skills"}},
		Scope:    store.Scope{Name: "obstudio.skill-workflows", Version: "1"}}
}

func (d *Dispatcher) recordSkillRead(uri string, started time.Time, success bool) {
	name, _, ok := d.skillCatalog.resolve(uri)
	if !ok {
		name = "unknown"
	}
	identity := make([]byte, 16)
	if _, err := rand.Read(identity); err != nil {
		return
	}
	traceID := hex.EncodeToString(identity)
	attrs := map[string]any{"skill.name": name, "skill.observation": "resource_read", "resource.read.success": success}
	span := skillSpan(traceID, traceID[:16], "", "skill.resource.read", started, timeNow(), attrs)
	if !success {
		span.Status.Code = "ERROR"
	}
	d.store.AddSpansForConnection("skill-delivery", []store.Span{span})
	d.store.AddMetricsForConnection("skill-delivery", []store.MetricDataPoint{{
		Name: "obstudio.skill.resource.read.count", Type: "sum", Value: 1, IsMonotonic: true, Temporality: "delta",
		Timestamp: span.EndTime, Attributes: attrs, Resource: span.Resource, Scope: span.Scope,
	}})
}

func (d *Dispatcher) workflowStages(skill string) ([]workflowStage, error) {
	if d.skillCatalog == nil {
		return nil, fmt.Errorf("skill catalog unavailable")
	}
	selected, ok := d.skillCatalog.skills[skill]
	if !ok {
		return nil, fmt.Errorf("unknown skill")
	}
	var definitions struct {
		Skills map[string]struct {
			Stages []workflowStage `json:"stages"`
		} `json:"skills"`
	}
	if err := json.Unmarshal(selected.files["references/shared/workflows.json"], &definitions); err != nil {
		return nil, fmt.Errorf("workflow contract unavailable")
	}
	stages := definitions.Skills[skill].Stages
	if len(stages) == 0 {
		return nil, fmt.Errorf("workflow contract unavailable")
	}
	return stages, nil
}

func (d *Dispatcher) skillWorkflowRecord(args map[string]any) toolResult {
	raw, err := json.Marshal(args["run"])
	if err != nil || len(raw) > 1024*1024 {
		return errorResult("Invalid workflow journal")
	}
	var run workflowRun
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&run); err != nil {
		return errorResult("Invalid workflow journal fields")
	}
	stages, err := d.workflowStages(run.Skill)
	if err != nil {
		return errorResult(err.Error())
	}
	if (run.SkillDigest != "" && !workflowDigest.MatchString(run.SkillDigest)) || (run.ContractDigest != "" && !workflowDigest.MatchString(run.ContractDigest)) || run.SchemaVersion != 1 || !workflowIdentifier.MatchString(run.RunID) || run.StartedAt.IsZero() || len(run.Events) > 256 {
		return errorResult("Invalid workflow identity or capacity")
	}
	switch run.Status {
	case "running":
		if run.FinishedAt != nil {
			return errorResult("Running workflow cannot have a finish time")
		}
	case "passed", "failed", "partial", "cancelled":
		if run.FinishedAt == nil || run.FinishedAt.Before(run.StartedAt) {
			return errorResult("Finished workflow requires an ordered finish time")
		}
	default:
		return errorResult("Invalid workflow outcome")
	}
	definitions := map[string]workflowStage{}
	for _, stage := range stages {
		definitions[stage.ID] = stage
	}
	seen := map[string]bool{}
	attempts := map[string]int{}
	latest := map[string]string{}
	var spans []store.Span
	rootID := workflowSpanID(run.RunID, "root", 0)
	spans = append(spans, skillSpan(run.RunID, workflowSpanID(run.RunID, "started", 0), rootID,
		"skill.workflow.started."+run.Skill, run.StartedAt, run.StartedAt, map[string]any{
			"skill.name": run.Skill, "skill.run_id": run.RunID, "skill.bundle_digest": run.SkillDigest, "skill.contract_digest": run.ContractDigest, "skill.observation": "explicit_start"}))
	for sequence, event := range run.Events {
		definition, ok := definitions[event.Stage]
		if !ok || event.Attempt != attempts[event.Stage]+1 {
			return errorResult("Unknown stage or nonsequential attempt")
		}
		attempts[event.Stage] = event.Attempt
		if event.Branch != "" {
			found := false
			for _, branch := range definition.Branches {
				if branch == event.Branch {
					found = true
				}
			}
			if !found {
				return errorResult("Unknown stage branch")
			}
		}
		if event.StartedAt.Before(run.StartedAt) || event.EndedAt.Before(event.StartedAt) ||
			(run.FinishedAt != nil && event.EndedAt.After(*run.FinishedAt)) || !workflowReason.MatchString(event.Reason) {
			return errorResult("Invalid stage timing or reason")
		}
		switch event.Status {
		case "passed", "failed":
		case "blocked", "skipped":
			if event.Reason == "" {
				return errorResult("Blocked/skipped stage requires a reason code")
			}
		default:
			return errorResult("Invalid stage outcome")
		}
		attrs := map[string]any{"skill.name": run.Skill, "skill.run_id": run.RunID, "skill.stage": event.Stage,
			"skill.stage.attempt": event.Attempt, "skill.stage.status": event.Status, "skill.stage.sequence": sequence + 1,
			"skill.stage.reason": event.Reason,
			"skill.stage.branch": event.Branch, "skill.observation": event.Source}
		for _, parent := range definition.After {
			if !seen[parent] {
				attrs["skill.stage.order_violation"] = true
			}
		}
		seen[event.Stage] = true
		latest[event.Stage] = event.Status
		started := event.StartedAt
		switch event.Source {
		case "executed":
			if event.DurationMs == nil || *event.DurationMs < 0 || math.IsNaN(*event.DurationMs) || math.IsInf(*event.DurationMs, 0) || event.ExitCode == nil ||
				(event.Status == "passed") != (*event.ExitCode == 0) {
				return errorResult("Executed stage requires consistent duration and exit status")
			}
			attrs["gen_ai.operation.name"] = "execute_tool"
			attrs["gen_ai.tool.name"] = run.Skill + "." + event.Stage
			attrs["gen_ai.tool.call.id"] = workflowSpanID(run.RunID, event.Stage, event.Attempt)
			attrs["skill.content.coverage"] = "metadata_only"
			attrs["skill.stage.command_exit_code"] = *event.ExitCode
			attrs["skill.stage.command_duration_ms"] = *event.DurationMs
		case "checkpoint":
			if event.DurationMs != nil || event.ExitCode != nil {
				return errorResult("Checkpoint cannot claim measured command timing")
			}
			attrs["skill.stage.timing"] = "unmeasured"
			started = event.EndedAt
		default:
			return errorResult("Invalid observation source")
		}
		// Evidence stays in the local journal; only bounded counts leave the workspace.
		if len(event.Evidence) > 32 {
			return errorResult("Evidence limit exceeded")
		}
		attrs["skill.stage.evidence_count"] = len(event.Evidence)
		span := skillSpan(run.RunID, workflowSpanID(run.RunID, event.Stage, event.Attempt), rootID,
			"skill."+event.Source+"."+event.Stage, started, event.EndedAt, attrs)
		if event.Source == "executed" {
			span.Name = "execute_tool " + run.Skill + "." + event.Stage
		}
		if event.Status == "failed" {
			span.Status.Code = "ERROR"
			span.Status.Message = "Recorded stage failed"
			span.Attributes["error.type"] = "skill_stage_failed"
		}
		spans = append(spans, span)
	}
	if run.FinishedAt != nil {
		missing := []string{}
		for _, stage := range stages {
			if !seen[stage.ID] {
				missing = append(missing, stage.ID)
			}
		}
		if run.Status == "passed" {
			if len(missing) > 0 {
				return errorResult("Passed workflow has unobserved stages")
			}
			for _, status := range latest {
				if status != "passed" && status != "skipped" {
					return errorResult("Passed workflow has unresolved stages")
				}
			}
			for _, span := range spans {
				if span.Attributes["skill.stage.order_violation"] == true {
					return errorResult("Passed workflow has an ordering violation")
				}
			}
		}
		attrs := map[string]any{"skill.name": run.Skill, "skill.run_id": run.RunID, "skill.workflow.status": run.Status,
			"skill.observation": "explicit_workflow_interval", "skill.workflow.unobserved_stages": missing,
			"gen_ai.operation.name": "invoke_workflow", "gen_ai.workflow.name": run.Skill,
			"skill.workflow.recorded_events": len(run.Events), "skill.content.coverage": "metadata_only",
			"skill.workflow.outcome_source": "recorder_reported", "skill.tokens.coverage": "unknown", "skill.bundle_digest": run.SkillDigest, "skill.contract_digest": run.ContractDigest}
		root := skillSpan(run.RunID, rootID, "", "invoke_workflow "+run.Skill, run.StartedAt, *run.FinishedAt, attrs)
		if run.Status == "failed" {
			root.Status.Code = "ERROR"
			root.Status.Message = "Recorded workflow failed"
			root.Attributes["error.type"] = "skill_workflow_failed"
		}
		spans = append(spans, root)
	}
	// Validate the entire journal before committing any of it.
	added, err := d.store.AddSkillWorkflowSpans(spans)
	if err != nil {
		return errorResult(err.Error())
	}
	d.recordWorkflowMetrics(added)
	if run.FinishedAt != nil {
		// Evaluate the retained telemetry, independently of journal parsing.
		_ = d.skillWorkflowEvaluate(map[string]any{"runId": run.RunID})
	}
	return jsonToolResult(map[string]any{"accepted": true, "newSpans": len(added), "traceId": run.RunID, "tokens": nil})
}

func (d *Dispatcher) skillWorkflows(args map[string]any) toolResult {
	byRun := map[string][]store.Span{}
	for _, span := range d.store.SnapshotSpans() {
		if name, valid := span.Attributes["skill.name"].(string); !valid || name == "" {
			continue
		}
		if span.Scope.Name != "obstudio.skill-workflows" || span.Attributes["skill.observation"] == "resource_read" {
			continue
		}
		if skill := strArg(args, "skillName"); skill != "" && span.Attributes["skill.name"] != skill {
			continue
		}
		if identity := strArg(args, "runId"); identity != "" && span.TraceID != identity {
			continue
		}
		byRun[span.TraceID] = append(byRun[span.TraceID], span)
	}
	rows := []map[string]any{}
	for identity, spans := range byRun {
		sort.Slice(spans, func(i, j int) bool { return spans[i].StartTime.Before(spans[j].StartTime) })
		row := map[string]any{"runId": identity, "status": "incomplete", "tokens": nil, "elapsedMs": nil,
			"coverage": "retained recorder observations; checkpoints are agent-reported", "startedAt": spans[0].StartTime}
		steps := []map[string]any{}
		evaluations := []map[string]any{}
		for _, span := range spans {
			row["skillName"] = span.Attributes["skill.name"]
			if span.Attributes["skill.observation"] == "telemetry_evaluation" {
				for _, event := range span.Events {
					evaluations = append(evaluations, event.Attributes)
				}
			}
			if span.ParentSpanID == "" {
				row["status"] = span.Attributes["skill.workflow.status"]
				row["elapsedMs"] = span.DurationMs
				row["bundleDigest"] = span.Attributes["skill.bundle_digest"]
			}
			if stage, ok := span.Attributes["skill.stage"].(string); ok {
				step := map[string]any{"stage": stage, "branch": span.Attributes["skill.stage.branch"],
					"attempt": span.Attributes["skill.stage.attempt"], "status": span.Attributes["skill.stage.status"],
					"observation": span.Attributes["skill.observation"], "durationMs": nil}
				if span.Attributes["skill.observation"] == "executed" {
					step["durationMs"] = span.Attributes["skill.stage.command_duration_ms"]
				}
				steps = append(steps, step)
			}
		}
		row["steps"] = steps
		row["evaluations"] = evaluations
		if include, _ := args["includeSpans"].(bool); include {
			row["spans"] = spans
		}
		row["improvementCandidates"] = d.workflowDiagnostics(row["skillName"].(string), spans)
		rows = append(rows, row)
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i]["startedAt"].(time.Time).After(rows[j]["startedAt"].(time.Time)) })
	limit := intArg(args, "limit", 100)
	if limit < 1 {
		limit = 1
	}
	if limit > 1000 {
		limit = 1000
	}
	if len(rows) > limit {
		rows = rows[:limit]
	}
	return jsonToolResult(map[string]any{"runs": rows, "retention": "bounded in-memory; replay local journals after eviction",
		"limitations": "Resource reads are not activation. Missing stages are unobserved. Recorded workflow outcomes are not independent skill-quality grades."})
}

func workflowTools() []toolDef {
	return append([]toolDef{
		{Name: "observer_skill_workflow_record", Description: "Ingest an explicit local skill workflow journal. Records measured helper stages and separately labeled agent checkpoints. Does not execute commands or infer token counts.",
			InputSchema: jsonSchema{Type: "object", Required: []string{"run"}, Properties: map[string]jsonSchema{"run": {Type: "object"}}},
			Annotations: toolAnnot{Title: "Record skill workflow", IdempotentHint: true}},
		{Name: "observer_skill_workflows", Description: "Inspect retained skill stage paths, branches, and explicitly completed workflow intervals. Incomplete and unobserved are distinct from success; tokens remain unknown.",
			InputSchema: jsonSchema{Type: "object", Properties: map[string]jsonSchema{"skillName": {Type: "string"}, "runId": {Type: "string"}, "limit": {Type: "integer"}, "includeSpans": {Type: "boolean"}}},
			Annotations: toolAnnot{Title: "Inspect skill workflows", ReadOnlyHint: true, IdempotentHint: true}},
	}, workflowEvaluationTool())
}

func (d *Dispatcher) recordWorkflowMetrics(spans []store.Span) {
	var metrics []store.MetricDataPoint
	for _, span := range spans {
		source, _ := span.Attributes["skill.observation"].(string)
		if source == "explicit_start" {
			continue
		}
		attrs := map[string]any{"skill.name": span.Attributes["skill.name"], "skill.observation": source}
		name := "obstudio.skill.stage"
		if span.ParentSpanID == "" {
			name = "obstudio.skill.workflow"
			attrs["skill.status"] = span.Attributes["skill.workflow.status"]
		} else {
			attrs["skill.stage"] = span.Attributes["skill.stage"]
			attrs["skill.branch"] = span.Attributes["skill.stage.branch"]
			attrs["skill.status"] = span.Attributes["skill.stage.status"]
		}
		metric := store.MetricDataPoint{Name: name + ".count", Type: "sum", Timestamp: span.EndTime,
			Value: 1, IsMonotonic: true, Temporality: "delta", Attributes: attrs, Resource: span.Resource, Scope: span.Scope}
		metrics = append(metrics, metric)
		if source == "executed" || source == "explicit_workflow_interval" {
			duration := span.DurationMs
			if source == "executed" {
				duration = span.Attributes["skill.stage.command_duration_ms"].(float64)
			}
			metric.Name = name + ".duration"
			metric.Type = "histogram"
			metric.Unit = "ms"
			metric.Value = 0
			metric.IsMonotonic = false
			metric.Count = 1
			metric.Sum = duration
			metric.Min = duration
			metric.Max = duration
			metric.BucketCounts = []uint64{1}
			metrics = append(metrics, metric)
		}
	}
	if len(metrics) > 0 {
		d.store.AddMetricsForConnection("skill-workflows", metrics)
	}
}

func (d *Dispatcher) workflowDiagnostics(skill string, spans []store.Span) []map[string]any {
	stages, _ := d.workflowStages(skill)
	latest := map[string]store.Span{}
	findings := []map[string]any{}
	for _, span := range spans {
		stage, _ := span.Attributes["skill.stage"].(string)
		if stage == "" {
			continue
		}
		prior, ok := latest[stage]
		if !ok || workflowIntegerValue(span.Attributes["skill.stage.attempt"]) > workflowIntegerValue(prior.Attributes["skill.stage.attempt"]) {
			latest[stage] = span
		}
		if span.Attributes["skill.stage.order_violation"] == true {
			findings = append(findings, map[string]any{"kind": "stage_order", "stage": stage})
		}
	}
	for _, stage := range stages {
		span, ok := latest[stage.ID]
		if !ok {
			findings = append(findings, map[string]any{"kind": "unobserved", "stage": stage.ID})
			continue
		}
		status := span.Attributes["skill.stage.status"]
		if status == "failed" || status == "blocked" {
			findings = append(findings, map[string]any{"kind": status, "stage": stage.ID})
		}
	}
	return findings
}
