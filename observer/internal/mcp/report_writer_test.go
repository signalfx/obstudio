package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/store"
)

func reportTestDispatcher(t *testing.T) (*Dispatcher, *store.Store, string, map[string]any) {
	t.Helper()
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("Python 3 required for report integration")
	}
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, ".observe"), 0700); err != nil {
		t.Fatal(err)
	}
	var audit map[string]any
	for _, name := range []string{"otel-audit", "otel-selection", "otel-instrumentation", "otel-verify"} {
		data, err := os.ReadFile("../../../evals/go/chi-basic/eval/inputs/" + name + ".json")
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, ".observe", name+".json"), data, 0600); err != nil {
			t.Fatal(err)
		}
		if name == "otel-audit" {
			if err := json.Unmarshal(data, &audit); err != nil {
				t.Fatal(err)
			}
		}
	}
	s := store.New()
	return NewDispatcher(s, NewSkillCatalog(os.DirFS("../../../skills"))), s, root, audit
}

func TestReportWriterHTTPPublishesCompactReceiptsAndPreservesAudit(t *testing.T) {
	d, s, root, audit := reportTestDispatcher(t)
	mux := http.NewServeMux()
	Register(mux, s, d.skillCatalog)
	call := func(tool string, report map[string]any) map[string]any {
		t.Helper()
		data, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": map[string]any{"name": tool, "arguments": map[string]any{"repoRoot": root, "report": report, "serve": false}}})
		request := httptest.NewRequest("POST", "/mcp", bytes.NewReader(data))
		request.RemoteAddr = "127.0.0.1:12345"
		response := httptest.NewRecorder()
		mux.ServeHTTP(response, request)
		var envelope struct {
			Result toolResult `json:"result"`
		}
		if err := json.Unmarshal(response.Body.Bytes(), &envelope); err != nil || envelope.Result.IsError {
			t.Fatalf("%s: %s", tool, response.Body.String())
		}
		return toMapAny(parseToolResult(t, envelope.Result))
	}
	first := call("observer_audit_report_write", audit)
	if first["validated"] != true || first["operationTraceId"] == "" {
		t.Fatalf("missing receipt: %v", first)
	}
	oldHTML, _ := os.ReadFile(filepath.Join(root, ".observe", "otel.html"))
	for _, kind := range []string{"instrumentation", "verification"} {
		filename := "otel-instrumentation"
		if kind == "verification" {
			filename = "otel-verify"
		}
		data, _ := os.ReadFile(filepath.Join(root, ".observe", filename+".json"))
		var report map[string]any
		_ = json.Unmarshal(data, &report)
		first := call("observer_"+kind+"_report_write", report)
		second := call("observer_"+kind+"_report_write", report)
		if first["receipt"] != second["receipt"] || second["reused"] != true {
			t.Fatal("identical publication did not reuse receipt")
		}
		if len(mustJSON(t, second)) > 6000 {
			t.Fatal("report contents leaked into compact response")
		}
	}
	currentHTML, _ := os.ReadFile(filepath.Join(root, ".observe", "otel.html"))
	if !bytes.Equal(oldHTML, currentHTML) {
		t.Fatal("downstream report changed audit HTML")
	}
	spans := s.SnapshotSpans()
	if len(spans) != 5 {
		t.Fatalf("each server operation must be recorded, got %d", len(spans))
	}
	for _, span := range spans {
		if span.Status.Code != "OK" || span.Scope.Name != "obstudio.report-writer" || span.DurationMs <= 0 || span.Attributes["report.receipt"] == nil {
			t.Fatalf("unmeasured/unbound report operation: %+v", span)
		}
		if span.Attributes["skill.name"] != nil || span.Attributes["gen_ai.input.messages"] != nil {
			t.Fatal("report operation became a complete skill execution or captured report contents")
		}
	}
}

func mustJSON(t *testing.T, value any) []byte {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestReportWriterFailureIsolationAndUnavailableRuntime(t *testing.T) {
	d, s, root, audit := reportTestDispatcher(t)
	args := map[string]any{"repoRoot": root, "report": audit, "serve": false}
	args["unexpected"] = "ignored"
	if !d.writeReport(context.Background(), "observer_audit_report_write", args).IsError {
		t.Fatal("unknown argument accepted")
	}
	delete(args, "unexpected")
	t.Setenv("PATH", t.TempDir())
	if !d.writeReport(context.Background(), "observer_audit_report_write", args).IsError {
		t.Fatal("missing Python runtime accepted")
	}
	response, _ := d.Dispatch(jsonRPCRequest{ID: 2, Method: "tools/call", Params: map[string]any{"name": "observer_status"}})
	if response.Error != nil {
		t.Fatal("report runtime failure broke existing status tool")
	}
	for _, span := range s.SnapshotSpans() {
		if span.Status.Code != "ERROR" || span.Attributes["report.receipt"] != nil {
			t.Fatal("failed writer produced success receipt")
		}
	}
	if _, err := os.Stat(filepath.Join(root, ".observe", "otel.html")); !os.IsNotExist(err) {
		t.Fatal("unavailable writer changed artifacts")
	}
}

func TestReportWriterDiscoveryRequiresBundledEngine(t *testing.T) {
	d := NewDispatcher(store.New(), testSkillCatalog())
	for _, tool := range d.tools {
		if _, exists := reportKinds[tool.Name]; exists {
			t.Fatal("writer advertised without bundled engine")
		}
	}
	response, _ := d.Dispatch(jsonRPCRequest{ID: 1, Method: "tools/call", Params: map[string]any{"name": "observer_audit_report_write", "arguments": map[string]any{}}})
	if response.Error == nil {
		t.Fatal("unavailable writer accepted")
	}
}

func TestReportWriterStdioAndWorkflowLink(t *testing.T) {
	d, s, root, audit := reportTestDispatcher(t)
	run := testWorkflowRun()
	if result := recordWorkflow(d, run); result.IsError {
		t.Fatal(result)
	}
	args := map[string]any{"repoRoot": root, "report": audit, "serve": false, "runId": run.RunID}
	if result := d.writeReport(context.Background(), "observer_audit_report_write", args); result.IsError {
		t.Fatal(result)
	}
	for _, span := range s.SnapshotSpans() {
		if span.Scope.Name == "obstudio.report-writer" && (len(span.Links) != 1 || span.Links[0].TraceID != run.RunID) {
			t.Fatal("report operation lost its workflow link")
		}
	}
	delete(args, "runId")
	input := append(mustJSON(t, map[string]any{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": map[string]any{"name": "observer_audit_report_write", "arguments": args}}), '\n')
	inputReader, inputWriter := io.Pipe()
	outputReader, outputWriter := io.Pipe()
	t.Cleanup(func() { _ = inputWriter.Close(); _ = outputReader.Close() })
	done := make(chan struct{})
	go func() {
		RunStdio(store.New(), inputReader, outputWriter, d.skillCatalog)
		_ = outputWriter.Close()
		close(done)
	}()
	if _, err := inputWriter.Write(input); err != nil {
		t.Fatal(err)
	}
	var envelope struct {
		Result toolResult `json:"result"`
	}
	if err := json.NewDecoder(outputReader).Decode(&envelope); err != nil || envelope.Result.IsError {
		t.Fatalf("stdio publication failed: %v %+v", err, envelope.Result)
	}
	_ = inputWriter.Close()
	<-done
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if !d.writeReport(ctx, "observer_audit_report_write", args).IsError {
		t.Fatal("cancelled report publication succeeded")
	}
}

func TestReportWriterServedHTMLSurvivesWorkerCleanup(t *testing.T) {
	d, _, root, audit := reportTestDispatcher(t)
	result := d.writeReport(context.Background(), "observer_audit_report_write", map[string]any{"repoRoot": root, "report": audit})
	if result.IsError {
		t.Fatal(result)
	}
	response := toMapAny(parseToolResult(t, result))
	server := toMapAny(response["server"])
	pid, ok := server["pid"].(float64)
	if !ok {
		t.Fatalf("report server unavailable: %+v", server)
	}
	t.Cleanup(func() {
		if process, err := os.FindProcess(int(pid)); err == nil {
			_ = process.Kill()
		}
	})
	url, _ := server["url"].(string)
	page, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer page.Body.Close()
	data, _ := io.ReadAll(page.Body)
	if page.StatusCode != http.StatusOK || !bytes.Contains(data, []byte("Findings")) {
		t.Fatalf("served report lost after worker cleanup: %d", page.StatusCode)
	}
	privateURL := strings.TrimSuffix(url, "otel.html") + "otel-verify.json"
	private, err := http.Get(privateURL)
	if err != nil {
		t.Fatal(err)
	}
	defer private.Body.Close()
	if private.StatusCode != http.StatusNotFound {
		t.Fatal("private verification JSON exposed by report server")
	}
}
