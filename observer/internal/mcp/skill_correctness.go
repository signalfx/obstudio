package mcp

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/store"
)

type correctnessRequest struct {
	RunID                 string                `json:"runId"`
	AuditSHA256           string                `json:"auditSha256"`
	InstrumentationSHA256 string                `json:"instrumentationSha256,omitempty"`
	SourceRevision        string                `json:"sourceRevision"`
	Scenarios             []correctnessScenario `json:"scenarios"`
}

type correctnessScenario struct {
	ID            string            `json:"id"`
	TraceID       string            `json:"traceId"`
	WitnessSpanID string            `json:"witnessSpanId"`
	ServiceName   string            `json:"serviceName"`
	Rules         []correctnessRule `json:"rules"`
}

type correctnessRule struct {
	Name       string         `json:"name"`
	FindingID  string         `json:"findingId"`
	Claim      string         `json:"claim"`
	Signal     string         `json:"signal"`
	SignalName string         `json:"signalName"`
	Count      int            `json:"count"`
	Attributes map[string]any `json:"attributes,omitempty"`
	Kind       string         `json:"kind,omitempty"`
	Status     string         `json:"status,omitempty"`
	ParentName string         `json:"parentName,omitempty"`
	MetricType string         `json:"metricType,omitempty"`
	Unit       *string        `json:"unit,omitempty"`
	MinValue   *float64       `json:"minValue,omitempty"`
	MaxValue   *float64       `json:"maxValue,omitempty"`
	Severity   string         `json:"severity,omitempty"`
}

type correctnessResult struct {
	Name          string   `json:"name"`
	FindingID     string   `json:"findingId"`
	ScenarioID    string   `json:"scenarioId"`
	Claim         string   `json:"claim"`
	Signal        string   `json:"signal"`
	Outcome       string   `json:"outcome"`
	Score         *float64 `json:"score"`
	ProofMode     string   `json:"proofMode"`
	ExpectedCount int      `json:"expectedCount"`
	ObservedCount *int     `json:"observedCount"`
	Violations    []string `json:"violations"`
	Explanation   string   `json:"explanation"`
}

type correctnessCapture struct {
	Witness *store.Span             `json:"witness"`
	Spans   []store.Span            `json:"spans"`
	Metrics []store.MetricDataPoint `json:"metrics"`
	Logs    []store.LogRecord       `json:"logs"`
	Problem string                  `json:"problem,omitempty"`
}

func correctnessTool() toolDef {
	rule := jsonSchema{Type: "object", Required: []string{"name", "findingId", "claim", "signal", "signalName", "count"}, Properties: map[string]jsonSchema{
		"name": {Type: "string"}, "findingId": {Type: "string"},
		"claim":      {Type: "string", Enum: []string{"instrumentation", "audit_gap"}},
		"signal":     {Type: "string", Enum: []string{"span", "metric", "log"}},
		"signalName": {Type: "string", Description: "Exact span/metric name, or log event.name attribute."}, "count": {Type: "integer"},
		"attributes": {Type: "object"}, "kind": {Type: "string"}, "status": {Type: "string"}, "parentName": {Type: "string"},
		"metricType": {Type: "string"}, "unit": {Type: "string"}, "minValue": {Type: "number"}, "maxValue": {Type: "number"}, "severity": {Type: "string"},
	}}
	return toolDef{Name: "observer_skill_correctness_evaluate", Description: "Check per-finding instrumentation or audit-gap claims against retained application telemetry and an independent harness capture manifest. Requires a completed skill run, report digests, source revision, and scenario witness from scope obstudio.verification. Never accepts a reported pass as proof. Exact contracts cover spans/parentage, metric datapoints and correlated logs. Missing, stale, incomplete, or contract-only captures are unknown. Results describe the supplied contract and producer-declared app proof mode, not general task correctness. Read skill://obstudio/otel-verify/references/correctness-evaluations.md for the capture contract.",
		InputSchema: jsonSchema{Type: "object", Required: []string{"runId", "auditSha256", "sourceRevision", "scenarios"}, Properties: map[string]jsonSchema{
			"runId": {Type: "string"}, "auditSha256": {Type: "string"}, "instrumentationSha256": {Type: "string"}, "sourceRevision": {Type: "string"},
			"scenarios": {Type: "array", Items: &jsonSchema{Type: "object", Required: []string{"id", "traceId", "witnessSpanId", "serviceName", "rules"}, Properties: map[string]jsonSchema{
				"id": {Type: "string"}, "traceId": {Type: "string"}, "witnessSpanId": {Type: "string"}, "serviceName": {Type: "string"}, "rules": {Type: "array", Items: &rule},
			}}},
		}}, Annotations: toolAnnot{Title: "Evaluate skill correctness evidence", IdempotentHint: true}}
}

func (d *Dispatcher) skillCorrectnessEvaluate(args map[string]any) toolResult {
	data, err := json.Marshal(args)
	if err != nil || len(data) > 128*1024 {
		return errorResult("Invalid correctness request capacity")
	}
	var request correctnessRequest
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		return errorResult("Invalid correctness request fields")
	}
	if err := request.validate(); err != nil {
		return errorResult(err.Error())
	}
	snapshot := d.store.SnapshotTelemetry()
	var root *store.Span
	for _, span := range snapshot.Spans {
		if span.TraceID == request.RunID && span.Scope.Name == "obstudio.skill-workflows" && span.Attributes["skill.observation"] == "explicit_workflow_interval" {
			copy := span
			root = &copy
		}
	}
	if root == nil {
		return errorResult("A completed retained skill workflow is required; replay its journal first")
	}
	results := []correctnessResult{}
	captures := []correctnessCapture{}
	for _, scenario := range request.Scenarios {
		capture := captureCorrectnessScenario(snapshot, request, scenario)
		captures = append(captures, capture)
		for _, rule := range scenario.Rules {
			results = append(results, evaluateCorrectnessRule(scenario.ID, rule, capture))
		}
	}
	payload, err := json.Marshal(struct {
		Version  int
		Request  correctnessRequest
		Captures []correctnessCapture
	}{1, request, captures})
	if err != nil {
		return errorResult("Application evidence contains values that cannot be fingerprinted as JSON; no results published")
	}
	digest := sha256.Sum256(payload)
	receipt := hex.EncodeToString(digest[:])
	evaluation := skillSpan(request.RunID, workflowSpanID(request.RunID, "correctness/"+receipt, 0), root.SpanID, "evaluate application_contracts", root.EndTime, root.EndTime, map[string]any{
		"skill.name": root.Attributes["skill.name"], "skill.run_id": request.RunID, "skill.observation": "telemetry_evaluation",
		"skill.evaluation.source": "retained_application_telemetry", "skill.evaluation.scope": "scenario_contract_only",
		"skill.evaluation.digest": "sha256:" + receipt, "skill.evaluation.timing": "workflow_finish_reference",
		"skill.evaluation.audit_sha256": request.AuditSHA256, "skill.evaluation.instrumentation_sha256": request.InstrumentationSHA256,
		"skill.evaluation.source_revision": request.SourceRevision, "skill.evaluation.trust": "caller_contract_and_producer_capture_manifest",
	})
	for _, capture := range captures {
		if capture.Witness != nil {
			evaluation.Links = append(evaluation.Links, store.SpanLink{TraceID: capture.Witness.TraceID, SpanID: capture.Witness.SpanID})
		}
	}
	for _, result := range results {
		if result.Score == nil {
			continue
		}
		evaluation.Events = append(evaluation.Events, store.SpanEvent{Name: "gen_ai.evaluation.result", Timestamp: root.EndTime, Attributes: map[string]any{
			"gen_ai.evaluation.name": result.Name, "gen_ai.evaluation.score.value": *result.Score,
			"gen_ai.evaluation.score.label": result.Outcome, "gen_ai.evaluation.passed": result.Outcome == "pass", "gen_ai.evaluation.explanation": result.Explanation,
			"skill.evaluation.source": "retained_application_telemetry", "skill.evaluation.finding_id": result.FindingID,
			"skill.evaluation.scenario_id": result.ScenarioID, "skill.evaluation.claim": result.Claim, "skill.evaluation.signal": result.Signal, "skill.evaluation.proof_mode": result.ProofMode,
			"skill.evaluation.expected_count": result.ExpectedCount, "skill.evaluation.observed_count": *result.ObservedCount, "skill.evaluation.violations": result.Violations,
		}})
	}
	added := 0
	if len(evaluation.Events) > 0 {
		fresh, err := d.store.AddSkillWorkflowSpans([]store.Span{evaluation})
		if err != nil {
			return errorResult(err.Error())
		}
		added = len(fresh)
	}
	return jsonToolResult(map[string]any{"runId": request.RunID, "evaluationDigest": "sha256:" + receipt, "results": results, "newSpans": added,
		"limitations": "Checks compare retained application telemetry with caller-supplied contracts. Report digests are bindings, not file validation. The harness declares source revision, execution mode and capture completeness; these are not authenticated. A pass proves only the tested scenario contract. It does not establish audit completeness, source correctness, cloud receipt, or independence of the contract author. Unknown results emit no numeric score or passing event."})
}

func (r correctnessRequest) validate() error {
	if !workflowIdentifier.MatchString(r.RunID) || !workflowDigest.MatchString(r.AuditSHA256) || (r.InstrumentationSHA256 != "" && !workflowDigest.MatchString(r.InstrumentationSHA256)) || !boundedCorrectnessText(r.SourceRevision, 128) || len(r.Scenarios) < 1 || len(r.Scenarios) > 8 {
		return fmt.Errorf("Invalid run, report digest, source revision or scenario capacity")
	}
	names, identities := map[string]bool{}, map[string]bool{}
	total := 0
	for _, scenario := range r.Scenarios {
		if !evaluationName.MatchString(scenario.ID) || identities[scenario.ID] || !workflowIdentifier.MatchString(scenario.TraceID) || scenario.TraceID == strings.Repeat("0", 32) || scenario.TraceID == r.RunID || !validCorrectnessSpanID(scenario.WitnessSpanID) || !boundedCorrectnessText(scenario.ServiceName, 128) || len(scenario.Rules) == 0 {
			return fmt.Errorf("Invalid scenario identity, application trace, service or rules")
		}
		identities[scenario.ID] = true
		for _, rule := range scenario.Rules {
			total++
			if total > 32 || !evaluationName.MatchString(rule.Name) || names[rule.Name] || !evaluationName.MatchString(rule.FindingID) || !boundedCorrectnessText(rule.SignalName, 256) || rule.Count < 1 || rule.Count > 128 || (rule.Claim != "instrumentation" && rule.Claim != "audit_gap") {
				return fmt.Errorf("Invalid rule identity, claim, expected count or rule capacity")
			}
			names[rule.Name] = true
			if len(rule.Attributes) > 16 {
				return fmt.Errorf("Too many expected attributes")
			}
			for key, value := range rule.Attributes {
				if !boundedCorrectnessText(key, 128) || !correctnessScalar(value) {
					return fmt.Errorf("Expected attributes must be bounded scalar values")
				}
			}
			switch rule.Signal {
			case "span":
				if !oneOfCorrectness(rule.Kind, "", "INTERNAL", "SERVER", "CLIENT", "PRODUCER", "CONSUMER") || !oneOfCorrectness(rule.Status, "", "UNSET", "OK", "ERROR") || (rule.ParentName != "" && !boundedCorrectnessText(rule.ParentName, 256)) || rule.MetricType != "" || rule.Unit != nil || rule.MinValue != nil || rule.MaxValue != nil || rule.Severity != "" {
					return fmt.Errorf("Invalid span contract fields")
				}
			case "metric":
				if !oneOfCorrectness(rule.MetricType, "gauge", "sum", "histogram", "exponential_histogram", "summary") || rule.Unit == nil || len(*rule.Unit) > 32 || rule.Kind != "" || rule.Status != "" || rule.ParentName != "" || rule.Severity != "" {
					return fmt.Errorf("Metric contracts require type/unit and metric-only fields")
				}
				for _, value := range []*float64{rule.MinValue, rule.MaxValue} {
					if value != nil && (math.IsNaN(*value) || math.IsInf(*value, 0)) {
						return fmt.Errorf("Metric bounds must be finite")
					}
				}
				if (rule.MinValue != nil || rule.MaxValue != nil) && rule.MetricType != "gauge" && rule.MetricType != "sum" {
					return fmt.Errorf("Value bounds apply only to gauge/sum datapoints")
				}
				if rule.MinValue != nil && rule.MaxValue != nil && *rule.MinValue > *rule.MaxValue {
					return fmt.Errorf("Metric minimum exceeds maximum")
				}
			case "log":
				if !oneOfCorrectness(rule.Severity, "TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL") || rule.Kind != "" || rule.Status != "" || rule.MetricType != "" || rule.Unit != nil || rule.MinValue != nil || rule.MaxValue != nil || (rule.ParentName != "" && !boundedCorrectnessText(rule.ParentName, 256)) {
					return fmt.Errorf("Invalid correlated log contract fields")
				}
			default:
				return fmt.Errorf("Unknown correctness signal")
			}
		}
	}
	return nil
}

func boundedCorrectnessText(value string, max int) bool {
	return strings.TrimSpace(value) != "" && len(value) <= max && !strings.ContainsAny(value, "\x00\r\n")
}

func validCorrectnessSpanID(value string) bool {
	_, err := hex.DecodeString(value)
	return len(value) == 16 && value != "0000000000000000" && value == strings.ToLower(value) && err == nil
}

func correctnessScalar(value any) bool {
	switch v := value.(type) {
	case string:
		return len(v) <= 512
	case bool:
		return true
	case float64:
		return !math.IsNaN(v) && !math.IsInf(v, 0)
	default:
		return false
	}
}

func oneOfCorrectness(value string, choices ...string) bool {
	for _, choice := range choices {
		if value == choice {
			return true
		}
	}
	return false
}

func captureCorrectnessScenario(snapshot store.TelemetrySnapshot, request correctnessRequest, scenario correctnessScenario) correctnessCapture {
	capture := correctnessCapture{Spans: []store.Span{}, Metrics: []store.MetricDataPoint{}, Logs: []store.LogRecord{}}
	ids := map[string]store.Span{}
	for _, span := range snapshot.Spans {
		if span.TraceID != scenario.TraceID {
			continue
		}
		if prior, exists := ids[span.SpanID]; exists {
			if !sameCorrectnessValue(prior, span) {
				capture.Problem = "Conflicting application span identities"
			}
			continue
		}
		if len(ids) >= 129 {
			capture.Problem = "Scenario span capture exceeds capacity"
			break
		}
		ids[span.SpanID] = span
		if span.SpanID == scenario.WitnessSpanID {
			copy := span
			capture.Witness = &copy
			continue
		}
		capture.Spans = append(capture.Spans, span)
	}
	witness := capture.Witness
	if witness == nil {
		capture.Problem = "Scenario capture witness is not retained"
		return capture
	}
	if witness.Scope.Name != "obstudio.verification" || witness.Resource.ServiceName != scenario.ServiceName || witness.Resource.Attributes["service.version"] != request.SourceRevision || witness.Attributes["verification.run_id"] != request.RunID || witness.Attributes["verification.scenario"] != scenario.ID || witness.Attributes["verification.completed"] != true || witness.Status.Code != "OK" || witness.StartTime.IsZero() || !witness.EndTime.After(witness.StartTime) {
		capture.Problem = "Scenario witness is unfinished or its run, scenario, service or source revision does not match"
	}
	if !oneOfCorrectness(stringAttr(witness.Attributes, "verification.proof_mode"), "app_test", "app_runtime") {
		capture.Problem = "Application execution is not declared; contract-only telemetry cannot prove application correctness"
	}
	for _, span := range capture.Spans {
		if !validCorrectnessSpanID(span.SpanID) || span.Scope.Name == "obstudio.skill-workflows" || span.Resource.ServiceName != scenario.ServiceName || span.Resource.Attributes["service.version"] != request.SourceRevision || span.StartTime.Before(witness.StartTime) || span.EndTime.After(witness.EndTime) || span.EndTime.Before(span.StartTime) {
			capture.Problem = "Application trace contains mismatched source/service, invalid timing or recorder evidence"
		}
	}
	for _, point := range snapshot.Metrics {
		if point.Resource.ServiceName == scenario.ServiceName && point.Attributes["verification.run_id"] == request.RunID && point.Attributes["verification.scenario"] == scenario.ID && !point.Timestamp.Before(witness.StartTime) && !point.Timestamp.After(witness.EndTime) {
			if len(capture.Metrics) >= 512 {
				capture.Problem = "Scenario metric capture exceeds capacity"
				break
			}
			capture.Metrics = append(capture.Metrics, point)
			if point.Resource.Attributes["service.version"] != request.SourceRevision {
				capture.Problem = "Metric source revision does not match"
			}
		}
	}
	for _, record := range snapshot.Logs {
		if record.TraceID == scenario.TraceID && record.Resource.ServiceName == scenario.ServiceName && !record.Timestamp.Before(witness.StartTime) && !record.Timestamp.After(witness.EndTime) {
			if len(capture.Logs) >= 512 {
				capture.Problem = "Scenario log capture exceeds capacity"
				break
			}
			capture.Logs = append(capture.Logs, record)
			if record.Resource.Attributes["service.version"] != request.SourceRevision {
				capture.Problem = "Log source revision does not match"
			}
		}
	}
	sort.Slice(capture.Spans, func(i, j int) bool { return capture.Spans[i].SpanID < capture.Spans[j].SpanID })
	sortCorrectnessJSON(capture.Metrics)
	sortCorrectnessJSON(capture.Logs)
	return capture
}

func stringAttr(attrs map[string]any, name string) string {
	value, _ := attrs[name].(string)
	return value
}

func sortCorrectnessJSON[T any](values []T) {
	sort.Slice(values, func(i, j int) bool {
		a, _ := json.Marshal(values[i])
		b, _ := json.Marshal(values[j])
		return bytes.Compare(a, b) < 0
	})
}

func sameCorrectnessValue(a, b any) bool {
	x, errX := json.Marshal(a)
	y, errY := json.Marshal(b)
	return errX == nil && errY == nil && bytes.Equal(x, y)
}

func correctnessManifestComplete(signal string, capture correctnessCapture) bool {
	if signal == "span" {
		data, _ := json.Marshal(capture.Witness.Attributes["verification.span_ids"])
		var manifest []string
		if err := json.Unmarshal(data, &manifest); err != nil || string(data) == "null" || len(manifest) > 128 || len(manifest) != len(capture.Spans) {
			return false
		}
		ids := map[string]bool{}
		for _, id := range manifest {
			if !validCorrectnessSpanID(id) || ids[id] {
				return false
			}
			ids[id] = true
		}
		for _, span := range capture.Spans {
			if !ids[span.SpanID] {
				return false
			}
		}
		return true
	}
	count, valid := workflowInteger(capture.Witness.Attributes["verification."+signal+"_count"])
	actual := len(capture.Metrics)
	if signal == "log" {
		actual = len(capture.Logs)
	}
	return valid && count <= 512 && actual == count
}

func evaluateCorrectnessRule(scenarioID string, rule correctnessRule, capture correctnessCapture) correctnessResult {
	result := correctnessResult{Name: rule.Name, FindingID: rule.FindingID, ScenarioID: scenarioID, Claim: rule.Claim, Signal: rule.Signal, Outcome: "unknown", ProofMode: "unknown", ExpectedCount: rule.Count, Violations: []string{}, Explanation: capture.Problem}
	if capture.Witness != nil {
		result.ProofMode = stringAttr(capture.Witness.Attributes, "verification.proof_mode")
	}
	if capture.Problem != "" {
		return result
	}
	if !correctnessManifestComplete(rule.Signal, capture) || (rule.Signal == "log" && !correctnessManifestComplete("span", capture)) {
		result.Explanation = "Capture manifest is missing or differs from retained telemetry; absence and exact counts are not proven"
		return result
	}
	count := 0
	violations := map[string]bool{}
	check := func(matches bool, field string) {
		if !matches {
			violations[rule.Signal+"."+field] = true
		}
	}
	checkAttributes := func(observed map[string]any) {
		for key, value := range rule.Attributes {
			actual, exists := observed[key]
			check(exists && sameCorrectnessValue(value, actual), "attribute."+key)
		}
	}
	byID := map[string]store.Span{}
	for _, span := range capture.Spans {
		byID[span.SpanID] = span
	}
	byID[capture.Witness.SpanID] = *capture.Witness
	switch rule.Signal {
	case "span":
		for _, span := range capture.Spans {
			if span.Name != rule.SignalName {
				continue
			}
			count++
			checkAttributes(span.Attributes)
			check(rule.Kind == "" || span.Kind == rule.Kind, "kind")
			check(rule.Status == "" || span.Status.Code == rule.Status, "status")
			if rule.ParentName != "" {
				parent, exists := byID[span.ParentSpanID]
				check(exists && parent.Name == rule.ParentName, "parentName")
			}
		}
	case "metric":
		for _, point := range capture.Metrics {
			if point.Name != rule.SignalName {
				continue
			}
			count++
			checkAttributes(point.Attributes)
			check(point.Type == rule.MetricType, "type")
			check(point.Unit == *rule.Unit, "unit")
			check(point.Flags&1 == 0, "recordedValue")
			if point.Type == "histogram" || point.Type == "exponential_histogram" || point.Type == "summary" {
				check(point.Count > 0 && !math.IsNaN(point.Sum) && !math.IsInf(point.Sum, 0), "measurement")
			} else {
				check(!math.IsNaN(point.Value) && !math.IsInf(point.Value, 0) && (rule.MinValue == nil || point.Value >= *rule.MinValue) && (rule.MaxValue == nil || point.Value <= *rule.MaxValue), "valueRange")
			}
		}
	case "log":
		for _, record := range capture.Logs {
			if record.Attributes["event.name"] != rule.SignalName {
				continue
			}
			count++
			owner, exists := byID[record.SpanID]
			checkAttributes(record.Attributes)
			check(exists && record.SpanID != capture.Witness.SpanID, "correlation")
			check(record.SeverityText == rule.Severity, "severity")
			check(rule.ParentName == "" || owner.Name == rule.ParentName, "parentName")
		}
	}
	check(count == rule.Count, "count")
	for field := range violations {
		result.Violations = append(result.Violations, field)
	}
	sort.Strings(result.Violations)
	result.ObservedCount = &count
	conforms := len(violations) == 0
	passed := conforms
	if rule.Claim == "audit_gap" {
		passed = !conforms
	}
	score := 0.0
	result.Outcome = "fail"
	if passed {
		score = 1
		result.Outcome = "pass"
	}
	result.Score = &score
	result.Explanation = fmt.Sprintf("%s contract conforms: %t; observed %d, expected %d in the declared complete scenario capture. Violations: %v. Claim: %s. Proof mode: producer-declared %s.", rule.Signal, conforms, count, rule.Count, result.Violations, rule.Claim, result.ProofMode)
	return result
}
