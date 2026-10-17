package mcp

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"

	"github.com/signalfx/obstudio/observer/internal/store"
)

var evaluationName = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$`)

type workflowEvaluationRule struct {
	Name     string   `json:"name"`
	Check    string   `json:"check"`
	Stage    string   `json:"stage,omitempty"`
	Expected string   `json:"expected,omitempty"`
	MaxMs    *float64 `json:"maxMs,omitempty"`
}

type workflowEvaluationResult struct {
	Name        string   `json:"name"`
	Check       string   `json:"check"`
	Stage       string   `json:"stage,omitempty"`
	Outcome     string   `json:"outcome"`
	Explanation string   `json:"explanation"`
	Score       *float64 `json:"score"`
}

func workflowEvaluationTool() toolDef {
	return toolDef{Name: "observer_skill_workflow_evaluate", Description: "Evaluate retained skill workflow telemetry using declarative rules. Defaults check stage coverage, order, terminal stage outcomes, and command errors. Custom rules support stage_present, stage_order, stage_outcome, stage_branch, stage_duration, workflow_duration, workflow_outcome, stage_coverage, stage_outcomes, and command_success. Durations use maxMs; outcome/branch checks use expected. Missing measurements or incomplete retained traces return unknown, never a passing score. Publishes determinate gen_ai.evaluation.result events linked to the workflow; does not grade report correctness or execute code.",
		InputSchema: jsonSchema{Type: "object", Required: []string{"runId"}, Properties: map[string]jsonSchema{
			"runId": {Type: "string"}, "rules": {Type: "array", Items: &jsonSchema{Type: "object", Required: []string{"name", "check"}, Properties: map[string]jsonSchema{
				"name": {Type: "string"}, "check": {Type: "string", Enum: []string{"stage_present", "stage_order", "stage_outcome", "stage_branch", "stage_duration", "workflow_duration", "workflow_outcome", "stage_coverage", "stage_outcomes", "command_success"}}, "stage": {Type: "string"}, "expected": {Type: "string"}, "maxMs": {Type: "number"},
			}}}}}, Annotations: toolAnnot{Title: "Evaluate skill telemetry", IdempotentHint: true}}
}

func (d *Dispatcher) skillWorkflowEvaluate(args map[string]any) toolResult {
	identity := strArg(args, "runId")
	if !workflowIdentifier.MatchString(identity) {
		return errorResult("Invalid workflow runId")
	}
	spans := []store.Span{}
	var root *store.Span
	skill := ""
	for _, span := range d.store.SnapshotSpansByTraceIDs([]string{identity})[identity] {
		if span.Scope.Name != "obstudio.skill-workflows" || span.Attributes["skill.observation"] == "telemetry_evaluation" {
			continue
		}
		spans = append(spans, span)
		skill, _ = span.Attributes["skill.name"].(string)
		if span.Attributes["skill.observation"] == "explicit_workflow_interval" {
			value := span
			root = &value
		}
	}
	if len(spans) == 0 {
		return errorResult("Workflow telemetry is not retained; replay its journal first")
	}
	stages, err := d.workflowStages(skill)
	if err != nil {
		return errorResult(err.Error())
	}
	rules := []workflowEvaluationRule{
		{Name: "workflow.telemetry.stage_coverage", Check: "stage_coverage"},
		{Name: "workflow.telemetry.stage_order", Check: "stage_order"},
		{Name: "workflow.telemetry.stage_outcomes", Check: "stage_outcomes"},
		{Name: "workflow.telemetry.command_success", Check: "command_success"},
	}
	if raw, ok := args["rules"]; ok {
		data, err := json.Marshal(raw)
		if err != nil || len(data) > 16384 {
			return errorResult("Invalid evaluation rules")
		}
		decoder := json.NewDecoder(bytes.NewReader(data))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&rules); err != nil || len(rules) == 0 || len(rules) > 32 {
			return errorResult("Expected 1–32 evaluation rules")
		}
	}
	definitions := map[string]workflowStage{}
	for _, stage := range stages {
		definitions[stage.ID] = stage
	}
	names := map[string]bool{}
	for _, rule := range rules {
		if !evaluationName.MatchString(rule.Name) || names[rule.Name] {
			return errorResult("Evaluation names must be unique bounded identifiers")
		}
		names[rule.Name] = true
		stage, hasStage := definitions[rule.Stage]
		switch rule.Check {
		case "stage_present", "stage_outcome", "stage_branch", "stage_duration":
			if !hasStage {
				return errorResult("Evaluation requires a known stage")
			}
		case "stage_coverage", "stage_order", "stage_outcomes", "command_success", "workflow_duration", "workflow_outcome":
			if rule.Stage != "" {
				return errorResult("Workflow rule cannot select a stage")
			}
		default:
			return errorResult("Unknown telemetry evaluation check")
		}
		switch rule.Check {
		case "stage_duration", "workflow_duration":
			if rule.MaxMs == nil || *rule.MaxMs < 0 || math.IsNaN(*rule.MaxMs) || math.IsInf(*rule.MaxMs, 0) || *rule.MaxMs > 1e9 {
				return errorResult("Duration rule requires finite maxMs between 0 and 1000000000")
			}
		default:
			if rule.MaxMs != nil {
				return errorResult("maxMs applies only to duration checks")
			}
		}
		switch rule.Check {
		case "stage_outcome":
			if rule.Expected != "passed" && rule.Expected != "failed" && rule.Expected != "skipped" && rule.Expected != "blocked" {
				return errorResult("Invalid expected stage outcome")
			}
		case "workflow_outcome":
			if rule.Expected != "passed" && rule.Expected != "failed" && rule.Expected != "partial" && rule.Expected != "cancelled" {
				return errorResult("Invalid expected workflow outcome")
			}
		case "stage_branch":
			found := false
			for _, branch := range stage.Branches {
				if branch == rule.Expected {
					found = true
				}
			}
			if !found {
				return errorResult("Invalid expected stage branch")
			}
		default:
			if rule.Expected != "" {
				return errorResult("expected applies only to outcome and branch checks")
			}
		}
	}
	sort.Slice(spans, func(i, j int) bool { return spans[i].SpanID < spans[j].SpanID })
	contract := d.skillCatalog.skills[skill].files["references/shared/workflows.json"]
	payload, _ := json.Marshal(struct {
		Version  int
		Spans    []store.Span
		Rules    []workflowEvaluationRule
		Contract string
	}{1, spans, rules, string(contract)})
	digest := sha256.Sum256(payload)
	receipt := hex.EncodeToString(digest[:])
	results := evaluateWorkflowSpans(root, spans, stages, rules)
	published := 0
	if root != nil {
		evaluation := skillSpan(identity, workflowSpanID(identity, "evaluation/"+receipt, 0), root.SpanID, "evaluate workflow_telemetry", root.EndTime, root.EndTime, map[string]any{
			"skill.name": skill, "skill.run_id": identity, "skill.observation": "telemetry_evaluation", "skill.evaluation.source": "retained_telemetry",
			"skill.evaluation.digest": "sha256:" + receipt, "skill.evaluation.scope": "workflow_conformance_only", "skill.evaluation.timing": "workflow_finish_reference",
		})
		for _, result := range results {
			if result.Outcome == "unknown" {
				continue
			}
			evaluation.Events = append(evaluation.Events, store.SpanEvent{Name: "gen_ai.evaluation.result", Timestamp: root.EndTime, Attributes: map[string]any{
				"gen_ai.evaluation.name": result.Name, "gen_ai.evaluation.score.value": *result.Score, "gen_ai.evaluation.score.label": result.Outcome,
				"gen_ai.evaluation.explanation": result.Explanation, "gen_ai.evaluation.passed": result.Outcome == "pass",
				"skill.evaluation.check": result.Check, "skill.evaluation.stage": result.Stage, "skill.evaluation.source": "retained_telemetry",
			}})
		}
		if len(evaluation.Events) > 0 {
			fresh, err := d.store.AddSkillWorkflowSpans([]store.Span{evaluation})
			if err != nil {
				return errorResult(err.Error())
			}
			published = len(fresh)
		}
	}
	return jsonToolResult(map[string]any{"runId": identity, "evaluationDigest": "sha256:" + receipt, "results": results, "newSpans": published,
		"limitations": "Checks describe retained recorder telemetry, including agent-reported checkpoints. They do not independently grade report correctness, application coverage, model behavior, or tokens. Unknown checks emit no passing evaluation event."})
}

func evaluateWorkflowSpans(root *store.Span, spans []store.Span, stages []workflowStage, rules []workflowEvaluationRule) []workflowEvaluationResult {
	latest := map[string]store.Span{}
	steps := []store.Span{}
	for _, span := range spans {
		stage, ok := span.Attributes["skill.stage"].(string)
		attempt, validAttempt := workflowInteger(span.Attributes["skill.stage.attempt"])
		sequence, validSequence := workflowInteger(span.Attributes["skill.stage.sequence"])
		if ok && (!validAttempt || !validSequence || attempt < 1 || sequence < 1) {
			return unknownWorkflowEvaluations(rules, "Retained stage telemetry has invalid attempt or sequence metadata")
		}
		if !ok {
			continue
		}
		steps = append(steps, span)
		prior, ok := latest[stage]
		if !ok || attempt > workflowIntegerValue(prior.Attributes["skill.stage.attempt"]) {
			latest[stage] = span
		}
	}
	sort.Slice(steps, func(i, j int) bool {
		return workflowIntegerValue(steps[i].Attributes["skill.stage.sequence"]) < workflowIntegerValue(steps[j].Attributes["skill.stage.sequence"])
	})
	complete := root != nil && root.Attributes["skill.workflow.recorded_events"] == len(steps)
	for index, step := range steps {
		if workflowIntegerValue(step.Attributes["skill.stage.sequence"]) != index+1 {
			complete = false
		}
	}
	results := []workflowEvaluationResult{}
	for _, rule := range rules {
		result := workflowEvaluationResult{Name: rule.Name, Check: rule.Check, Stage: rule.Stage, Outcome: "unknown", Explanation: "Workflow is unfinished or some recorded telemetry is no longer retained"}
		if !complete {
			results = append(results, result)
			continue
		}
		stage, present := latest[rule.Stage]
		passed := true
		known := true
		explanation := "Constraint satisfied by retained telemetry"
		switch rule.Check {
		case "stage_present":
			passed = present
			explanation = fmt.Sprintf("Stage %s observed: %t", rule.Stage, present)
		case "stage_coverage":
			missing := []string{}
			for _, definition := range stages {
				if _, ok := latest[definition.ID]; !ok {
					missing = append(missing, definition.ID)
				}
			}
			passed = len(missing) == 0
			explanation = fmt.Sprintf("Observed %d/%d declared stages; missing: %v", len(latest), len(stages), missing)
		case "stage_order":
			seen := map[string]bool{}
			definitions := map[string]workflowStage{}
			for _, definition := range stages {
				definitions[definition.ID] = definition
			}
			for _, step := range steps {
				name := step.Attributes["skill.stage"].(string)
				for _, parent := range definitions[name].After {
					if !seen[parent] {
						passed = false
					}
				}
				seen[name] = true
			}
			explanation = fmt.Sprintf("Declared predecessor constraints satisfied: %t", passed)
		case "stage_outcomes":
			for _, definition := range stages {
				step, ok := latest[definition.ID]
				if !ok {
					passed = false
					continue
				}
				status := step.Attributes["skill.stage.status"]
				if status != "passed" && status != "skipped" {
					passed = false
				}
			}
			explanation = fmt.Sprintf("Every declared stage ended passed or explicitly skipped: %t", passed)
		case "command_success":
			count := 0
			failed := 0
			validCommands := true
			for _, step := range steps {
				if step.Attributes["skill.observation"] == "executed" {
					count++
					code, valid := workflowInteger(step.Attributes["skill.stage.command_exit_code"])
					validCommands = validCommands && valid
					if code != 0 {
						failed++
					}
				}
			}
			known = count > 0 && validCommands
			passed = failed == 0
			explanation = fmt.Sprintf("%d measured commands, %d nonzero exits (including recovered attempts)", count, failed)
		case "stage_outcome":
			known = present
			passed = stage.Attributes["skill.stage.status"] == rule.Expected
			explanation = "Latest observed stage outcome must equal " + rule.Expected
		case "stage_branch":
			known = present
			passed = stage.Attributes["skill.stage.branch"] == rule.Expected
			explanation = "Latest observed branch must equal " + rule.Expected
		case "workflow_outcome":
			passed = root.Attributes["skill.workflow.status"] == rule.Expected
			explanation = "Recorder-reported workflow outcome must equal " + rule.Expected
		case "stage_duration":
			known = present && stage.Attributes["skill.observation"] == "executed"
			if known {
				duration, measured := firstNumericAttributeValueForWorkflow(stage.Attributes["skill.stage.command_duration_ms"])
				known = measured
				passed = duration <= *rule.MaxMs
				explanation = fmt.Sprintf("Measured command duration %.3f ms; maximum %.3f ms", duration, *rule.MaxMs)
			}
		case "workflow_duration":
			passed = root.DurationMs <= *rule.MaxMs
			explanation = fmt.Sprintf("Explicit workflow interval %.3f ms; maximum %.3f ms", root.DurationMs, *rule.MaxMs)
		}
		if known {
			result.Outcome = "pass"
			score := 1.0
			if !passed {
				result.Outcome = "fail"
				score = 0
			}
			result.Score = &score
			result.Explanation = explanation
		} else {
			result.Explanation = "Required stage or measured command evidence is unavailable; checkpoints have no measured duration"
		}
		results = append(results, result)
	}
	return results
}

func workflowInteger(value any) (int, bool) {
	switch number := value.(type) {
	case int:
		return number, true
	case float64:
		if math.IsNaN(number) || math.IsInf(number, 0) || number < 0 || number > 1000000 || math.Trunc(number) != number {
			return 0, false
		}
		return int(number), true
	case json.Number:
		parsed, err := strconv.Atoi(number.String())
		return parsed, err == nil
	default:
		return 0, false
	}
}
func workflowIntegerValue(value any) int { number, _ := workflowInteger(value); return number }
func unknownWorkflowEvaluations(rules []workflowEvaluationRule, reason string) []workflowEvaluationResult {
	results := []workflowEvaluationResult{}
	for _, rule := range rules {
		results = append(results, workflowEvaluationResult{Name: rule.Name, Check: rule.Check, Stage: rule.Stage, Outcome: "unknown", Explanation: reason})
	}
	return results
}

func firstNumericAttributeValueForWorkflow(value any) (float64, bool) {
	switch number := value.(type) {
	case float64:
		return number, !math.IsNaN(number) && !math.IsInf(number, 0) && number >= 0
	case int:
		return float64(number), number >= 0
	default:
		return 0, false
	}
}
