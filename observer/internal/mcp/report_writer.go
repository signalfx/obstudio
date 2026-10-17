package mcp

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

var reportKinds = map[string]string{
	"observer_audit_report_write":           "audit",
	"observer_instrumentation_report_write": "instrumentation",
	"observer_verification_report_write":    "verification",
}

func reportTools() []toolDef {
	definitions := []toolDef{}
	for _, name := range []string{"observer_audit_report_write", "observer_instrumentation_report_write", "observer_verification_report_write"} {
		f := false
		definitions = append(definitions, toolDef{Name: name,
			Description: "Validate and publish a canonical " + reportKinds[name] + " report into an existing local repository's .observe directory. Submit structured canonical JSON once; the server generates JSON, Markdown where applicable, and existing HTML views. Binds existing audit/selection/implementation digests, preserves audit HTML during downstream writes, and automatically records this report operation. No application code edits, test execution, or independent correctness judgment. Returns a compact receipt, file paths/digests and a loopback HTML URL. Requires Python 3 on the server; if unavailable, use the bundled offline report writer. Read the report-writing reference for the canonical JSON contract.",
			InputSchema: jsonSchema{Type: "object", AdditionalProperties: &f, Required: []string{"repoRoot", "report"}, Properties: map[string]jsonSchema{
				"repoRoot": {Type: "string", Description: "Existing absolute service repository directory on the MCP server's filesystem."},
				"report":   {Type: "object", Description: "Canonical otel-audit (schema 2), otel-instrumentation or otel-verify (schema 1) JSON object. Existing bound prerequisites must be present in repoRoot/.observe."},
				"details":  {Type: "object", Description: "Optional structured reader context: summary, verificationHandoff, detectorHandoff, remainingGaps, supplementalEvidence are string lists. genaiClosure rows have 6 cells (surface, required signals, implemented/proven, tests, remaining signals, result); incidentRoles rows have 6 cells (surface, exact signal, role, detector use/reason, proof, remaining owner/prerequisite); validationGates rows have 3 cells; runtimeDependencies rows have 5 cells. GenAI/incident rows are required when their audited scope applies. No Markdown document is needed."},
				"runId":    {Type: "string", Description: "Optional retained recorder run ID for this skill; links the server operation to that workflow without inventing its start or completion."},
				"serve":    {Type: "boolean", Default: true, Description: "Serve the generated HTML using the existing restricted loopback report server. False writes offline artifacts only."},
			}}, Annotations: toolAnnot{Title: "Write " + reportKinds[name] + " report"}})
	}
	return definitions
}

func (d *Dispatcher) reportWriterAvailable() bool {
	if d.skillCatalog == nil {
		return false
	}
	for _, skill := range d.skillCatalog.skills {
		if len(skill.files["references/shared/scripts/report_writer.py"]) > 0 && len(skill.files["references/shared/scripts/observe_report.py"]) > 0 {
			return true
		}
	}
	return false
}

type boundedReportOutput struct{ bytes.Buffer }

func (b *boundedReportOutput) Write(p []byte) (int, error) {
	if b.Len()+len(p) > 64*1024 {
		return 0, fmt.Errorf("report writer output exceeds 64 KiB")
	}
	return b.Buffer.Write(p)
}

func (d *Dispatcher) writeReport(ctx context.Context, name string, args map[string]any) toolResult {
	started := timeNow()
	identity := make([]byte, 16)
	if _, err := rand.Read(identity); err != nil {
		return errorResult("Cannot create report operation identity")
	}
	traceID := hex.EncodeToString(identity)
	kind := reportKinds[name]
	attrs := map[string]any{"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name,
		"report.kind": kind, "report.operation_id": traceID, "report.observation": "server_executed_report_write", "report.proof_scope": "report_validation_only"}
	var workflowLink *store.SpanLink
	failed := true
	defer func() {
		span := skillSpan(traceID, traceID[:16], "", "execute_tool "+name, started, timeNow(), attrs)
		span.Scope.Name = "obstudio.report-writer"
		if workflowLink != nil {
			span.Links = []store.SpanLink{*workflowLink}
		}
		if failed {
			span.Status.Code = "ERROR"
			span.Attributes["error.type"] = "report_write_failed"
		} else {
			span.Status.Code = "OK"
		}
		d.store.AddSpansForConnection("report-writer", []store.Span{span})
	}()
	for key := range args {
		if key != "repoRoot" && key != "report" && key != "serve" && key != "runId" && key != "details" {
			return errorResult("Unknown report writer argument")
		}
	}
	root := strArg(args, "repoRoot")
	if !filepath.IsAbs(root) {
		return errorResult("repoRoot must be an existing absolute directory on the MCP server")
	}
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return errorResult("repoRoot must be an existing absolute directory on the MCP server")
	}
	if _, ok := args["report"].(map[string]any); !ok {
		return errorResult("report must be a structured canonical JSON object")
	}
	if value, exists := args["runId"]; exists {
		runID, ok := value.(string)
		if !ok || !workflowIdentifier.MatchString(runID) {
			return errorResult("Invalid runId")
		}
		for _, span := range d.store.SnapshotSpans() {
			if span.TraceID == runID && span.Attributes["skill.name"] == "otel-"+map[string]string{"audit": "audit", "instrumentation": "instrument", "verification": "verify"}[kind] && span.Scope.Name == "obstudio.skill-workflows" {
				workflowLink = &store.SpanLink{TraceID: runID, SpanID: span.SpanID}
				attrs["report.workflow_run_id"] = runID
				break
			}
		}
		if workflowLink == nil {
			return errorResult("runId does not identify a retained workflow for this report skill")
		}
	}
	request := map[string]any{"kind": kind, "repoRoot": root, "report": args["report"]}
	if details, exists := args["details"]; exists {
		request["details"] = details
	}
	if serve, exists := args["serve"]; exists {
		if _, ok := serve.(bool); !ok {
			return errorResult("serve must be a boolean")
		}
		request["serve"] = serve
	}
	data, err := json.Marshal(request)
	if err != nil || len(data) > 2*1024*1024 {
		return errorResult("Report request must be finite JSON no larger than 2 MiB")
	}
	python, err := exec.LookPath("python3")
	if err != nil {
		python, err = exec.LookPath("python")
	}
	if err != nil {
		return errorResult("Python 3 is unavailable on the MCP server; use the bundled offline report writer in a compatible runtime")
	}
	directory, err := os.MkdirTemp("", "obstudio-report-writer-*")
	if err != nil {
		return errorResult("Cannot prepare report writer")
	}
	defer os.RemoveAll(directory)
	for _, skill := range d.skillCatalog.skills {
		if len(skill.files["references/shared/scripts/report_writer.py"]) == 0 {
			continue
		}
		for _, filename := range []string{"report_writer.py", "observe_report.py"} {
			if err := os.WriteFile(filepath.Join(directory, filename), skill.files["references/shared/scripts/"+filename], 0600); err != nil {
				return errorResult("Cannot prepare report writer resources")
			}
		}
		break
	}
	ctx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, python, "-I", filepath.Join(directory, "report_writer.py"))
	command.Dir = directory
	command.Stdin = bytes.NewReader(data)
	var output, diagnostic boundedReportOutput
	command.Stdout, command.Stderr = &output, &diagnostic
	err = command.Run()
	if ctx.Err() != nil {
		return errorResult("Report writer interrupted; inspect canonical artifacts before retrying")
	}
	var result map[string]any
	if json.Unmarshal(output.Bytes(), &result) != nil {
		return errorResult("Report writer unavailable or returned invalid output; inspect canonical artifacts before retrying with a compatible Python 3 runtime")
	}
	if err != nil || result["error"] != nil {
		message, _ := result["error"].(string)
		if strings.TrimSpace(message) == "" {
			message = "Report writer failed"
		}
		return errorResult(message)
	}
	failed = false
	attrs["report.receipt"] = result["receipt"]
	attrs["report.result"] = result["reportResult"]
	attrs["report.reused"] = result["reused"]
	result["operationTraceId"] = traceID
	return jsonToolResult(result)
}
