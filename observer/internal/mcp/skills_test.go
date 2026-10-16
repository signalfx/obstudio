package mcp

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"testing/fstest"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

func testSkillCatalog() *SkillCatalog {
	return NewSkillCatalog(fstest.MapFS{
		"otel-audit/SKILL.md":                      {Data: []byte("---\nname: otel-audit\ndescription: Audit\nmetadata:\n  example: retained\n  path: ../references/unchanged\n---\nRead ../references/workflows.json\n")},
		"otel-audit/references/stages/discover.md": {Data: []byte("Discovery")},
		"references/workflows.json":                {Data: []byte(`{"skills":{"otel-audit":{"stages":[{"id":"discover","branches":["go"]},{"id":"assess","after":["discover"]},{"id":"report","after":["assess"]}]}}}`)},
		"broken/SKILL.md":                          {Data: []byte("not frontmatter")},
	})
}
func skillMeta() map[string]any {
	return map[string]any{"io.modelcontextprotocol/protocolVersion": modernProtocol,
		"io.modelcontextprotocol/clientInfo":         map[string]any{"name": "test-host", "version": "1"},
		"io.modelcontextprotocol/clientCapabilities": map[string]any{"extensions": map[string]any{skillsExtension: map[string]any{}}}}
}
func skillRPC(d *Dispatcher, method string, params map[string]any) jsonRPCResponse {
	if params == nil {
		params = map[string]any{}
	}
	params["_meta"] = skillMeta()
	response, _ := d.Dispatch(jsonRPCRequest{JSONRPC: "2.0", ID: "test", Method: method, Params: params})
	return response
}

func TestSkillsManifestAndDeliveryAreNotExecution(t *testing.T) {
	catalog := testSkillCatalog()
	if len(catalog.names) != 1 || len(catalog.unavailable) != 1 {
		t.Fatalf("catalog isolation: %+v", catalog)
	}
	s := store.New()
	d := NewDispatcher(s, catalog)
	response := skillRPC(d, "server/discover", nil)
	if response.Error != nil {
		t.Fatal(response.Error)
	}
	capabilities := toMapAny(toMapAny(response.Result)["capabilities"])
	if toMapAny(capabilities["extensions"])[skillsExtension] == nil {
		t.Fatal("missing extension capability")
	}
	entry := catalog.skills["otel-audit"].entry
	if toMapAny(entry.Frontmatter["metadata"])["example"] != "retained" || toMapAny(entry.Frontmatter["metadata"])["path"] != "../references/unchanged" {
		t.Fatal("frontmatter changed")
	}
	for _, resource := range entry.Resources {
		response := skillRPC(d, "resources/read", map[string]any{"uri": resource.URI})
		if response.Error != nil {
			t.Fatal(response.Error)
		}
		contents := toSliceAny(toMapAny(response.Result)["contents"])
		data := []byte(toMapAny(contents[0])["text"].(string))
		if resource.Digest != fmt.Sprintf("sha256:%x", sha256.Sum256(data)) || resource.Size != len(data) {
			t.Fatal("manifest does not cover served bytes")
		}
		if strings.HasSuffix(resource.URI, "SKILL.md") && !bytes.Contains(data, []byte("references/shared/workflows.json")) {
			t.Fatal("shared content is not self-contained")
		}
	}
	get := skillRPC(d, "skills/get", map[string]any{"uri": entry.URI})
	if get.Error != nil || toMapAny(get.Result)["skill"] == nil {
		t.Fatal("skill lookup failed")
	}
	list := skillRPC(d, "skills/list", nil)
	if list.Error != nil || len(toSliceAny(toMapAny(list.Result)["skills"])) != 1 {
		t.Fatal("list failed")
	}
	directory := skillRPC(d, "resources/directory/read", map[string]any{"uri": "skill://obstudio/otel-audit/references"})
	if directory.Error != nil || len(toSliceAny(toMapAny(directory.Result)["resources"])) != 2 {
		t.Fatalf("directory failed: %+v", directory)
	}
	for _, span := range s.SnapshotSpans() {
		if span.Attributes["skill.observation"] != "resource_read" {
			t.Fatal("resource delivery mislabeled as execution")
		}
	}
	runs := toMapAny(parseToolResult(t, d.skillWorkflows(nil)))["runs"]
	if len(toSliceAny(runs)) != 0 {
		t.Fatal("resource fetch created a skill invocation")
	}
	for _, uri := range []string{"skill://obstudio/otel-audit/../secrets", "skill://obstudio/otel-audit/%2e%2e/secrets", "file:///etc/passwd"} {
		if response := skillRPC(d, "resources/read", map[string]any{"uri": uri}); response.Error == nil {
			t.Fatalf("accepted %s", uri)
		}
	}
}

func TestSkillsMetadataAndLegacyCompatibility(t *testing.T) {
	d := NewDispatcher(store.New(), testSkillCatalog())
	req := jsonRPCRequest{JSONRPC: "2.0", ID: 1, Method: "skills/list"}
	response, _ := d.Dispatch(req)
	if response.Error == nil {
		t.Fatal("accepted missing metadata")
	}
	meta := skillMeta()
	delete(meta, "io.modelcontextprotocol/clientCapabilities")
	req.Params = map[string]any{"_meta": meta}
	response, _ = d.Dispatch(req)
	if response.Error == nil {
		t.Fatal("accepted missing client capabilities")
	}
	meta = skillMeta()
	meta["io.modelcontextprotocol/clientCapabilities"] = map[string]any{}
	req.Params = map[string]any{"_meta": meta}
	response, _ = d.Dispatch(req)
	if response.Error == nil || response.Error.Code != -32021 {
		t.Fatal("accepted undeclared extension or returned the wrong modern error")
	}
	meta = skillMeta()
	delete(meta, "io.modelcontextprotocol/clientInfo")
	req.Params = map[string]any{"_meta": meta}
	response, _ = d.Dispatch(req)
	if response.Error != nil {
		t.Fatal("optional client identity became required")
	}
	meta = skillMeta()
	meta["io.modelcontextprotocol/protocolVersion"] = "2099-01-01"
	req.Params = map[string]any{"_meta": meta}
	response, _ = d.Dispatch(req)
	if response.Error == nil || response.Error.Code != -32022 {
		t.Fatal("wrong unsupported protocol response")
	}
	response, _ = d.Dispatch(jsonRPCRequest{ID: 1, Method: "initialize", Params: map[string]any{"protocolVersion": "2025-06-18"}})
	if toMapAny(response.Result)["protocolVersion"] != "2025-06-18" {
		t.Fatal("legacy negotiation changed")
	}
	response, _ = d.Dispatch(jsonRPCRequest{ID: 1, Method: "tools/list"})
	if toMapAny(response.Result)["resultType"] != nil {
		t.Fatal("legacy tool envelope changed")
	}
	response = skillRPC(d, "tools/list", nil)
	if toMapAny(response.Result)["resultType"] != "complete" {
		t.Fatal("modern tool envelope missing")
	}
	empty := NewDispatcher(store.New(), NewSkillCatalog(fstest.MapFS{}))
	if response := skillRPC(empty, "skills/list", nil); response.Error == nil {
		t.Fatal("empty catalog advertised")
	}
	response, _ = empty.Dispatch(jsonRPCRequest{ID: 1, Method: "tools/call", Params: map[string]any{"name": "observer_skill_workflows"}})
	if response.Error == nil {
		t.Fatal("unavailable workflow tool exposed")
	}
	response, _ = empty.Dispatch(jsonRPCRequest{ID: 1, Method: "tools/call", Params: map[string]any{"name": "observer_status"}})
	if response.Error != nil {
		t.Fatal("catalog failure broke core tool")
	}
}

func TestSkillsHTTPAndStdioShareCatalog(t *testing.T) {
	catalog := testSkillCatalog()
	request := jsonRPCRequest{JSONRPC: "2.0", ID: "read", Method: "resources/read", Params: map[string]any{"uri": "skill://obstudio/otel-audit/SKILL.md", "_meta": skillMeta()}}
	data, _ := json.Marshal(request)
	mux := http.NewServeMux()
	Register(mux, store.New(), catalog)
	req := httptest.NewRequest("POST", "/mcp", bytes.NewReader(data))
	req.RemoteAddr = "127.0.0.1:54321"
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("MCP-Protocol-Version", modernProtocol)
	req.Header.Set("Mcp-Method", request.Method)
	req.Header.Set("Mcp-Name", "skill://obstudio/otel-audit/SKILL.md")
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, req)
	var httpResult jsonRPCResponse
	if err := json.Unmarshal(response.Body.Bytes(), &httpResult); err != nil || httpResult.Error != nil {
		t.Fatalf("HTTP: %s", response.Body.String())
	}
	var out bytes.Buffer
	RunStdio(store.New(), io.NopCloser(bytes.NewReader(append(data, '\n'))), &out, catalog)
	var stdioResult jsonRPCResponse
	if err := json.Unmarshal(out.Bytes(), &stdioResult); err != nil || stdioResult.Error != nil {
		t.Fatalf("stdio: %s", out.String())
	}
	a, _ := json.Marshal(httpResult.Result)
	b, _ := json.Marshal(stdioResult.Result)
	if !bytes.Equal(a, b) {
		t.Fatal("transport content differs")
	}
}

func TestSkillCatalogRejectsSymlinksAndOversizedSkillsIndependently(t *testing.T) {
	source := fstest.MapFS{
		"valid/SKILL.md":    {Data: []byte("---\nname: valid\ndescription: Valid\n---\n")},
		"invalid/SKILL.md":  {Data: []byte("---\nname: invalid\ndescription: Invalid\n---\n")},
		"invalid/link":      {Mode: 1 << 27, Data: []byte("secret")},
		"Bad_Name/SKILL.md": {Data: []byte("---\nname: Bad_Name\ndescription: Invalid name\n---\n")},
		"huge/SKILL.md":     {Data: []byte("---\nname: huge\ndescription: Huge\n---\n")},
		"huge/data":         {Data: make([]byte, maxSkillBytes+1)},
	}
	catalog := NewSkillCatalog(source)
	if len(catalog.names) != 1 || catalog.names[0] != "valid" {
		t.Fatalf("bad catalog failure isolation: %v", catalog.names)
	}
}

func testWorkflowRun() workflowRun {
	start := time.Now().UTC().Add(-time.Minute)
	return workflowRun{SchemaVersion: 1, RunID: strings.Repeat("a", 32), Skill: "otel-audit", StartedAt: start, Status: "running", Events: []workflowEvent{}}
}
func recordWorkflow(d *Dispatcher, run workflowRun) toolResult {
	raw, _ := json.Marshal(run)
	var value map[string]any
	_ = json.Unmarshal(raw, &value)
	return d.skillWorkflowRecord(map[string]any{"run": value})
}
func checkpoint(run workflowRun, stage string, attempt int) workflowEvent {
	return workflowEvent{Stage: stage, Attempt: attempt, Status: "passed", Source: "checkpoint", StartedAt: run.StartedAt.Add(time.Second), EndedAt: run.StartedAt.Add(time.Second), Evidence: []workflowEvidence{}}
}

func TestWorkflowReplayMetricsAndHonestIncompleteState(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s, testSkillCatalog())
	run := testWorkflowRun()
	if result := recordWorkflow(d, run); result.IsError {
		t.Fatal(result)
	}
	if len(s.SnapshotSpans()) != 1 {
		t.Fatal("start not retained")
	}
	rows := toMapAny(parseToolResult(t, d.skillWorkflows(nil)))
	row := toMapAny(toSliceAny(rows["runs"])[0])
	if row["status"] != "incomplete" || row["tokens"] != nil {
		t.Fatal("incomplete run or unknown tokens misrepresented")
	}
	run.Events = append(run.Events, checkpoint(run, "discover", 1), checkpoint(run, "assess", 1), checkpoint(run, "report", 1))
	finish := run.StartedAt.Add(5 * time.Second)
	run.FinishedAt = &finish
	run.Status = "passed"
	if result := recordWorkflow(d, run); result.IsError {
		t.Fatal(result)
	}
	if len(s.SnapshotSpans()) != 6 {
		t.Fatal("expected root, start, three stages, and evaluation receipt")
	}
	metricCount := len(s.SnapshotMetrics())
	if result := recordWorkflow(d, run); result.IsError {
		t.Fatal(result)
	}
	if len(s.SnapshotSpans()) != 6 || len(s.SnapshotMetrics()) != metricCount {
		t.Fatal("replay duplicated telemetry")
	}
	for _, metric := range s.SnapshotMetrics() {
		if metric.Attributes["skill.run_id"] != nil {
			t.Fatal("unbounded metric label")
		}
		if metric.Name == "obstudio.skill.stage.duration" {
			t.Fatal("checkpoint gained measured duration")
		}
	}
	run.Events[0].Status = "failed"
	if result := recordWorkflow(d, run); !result.IsError {
		t.Fatal("conflicting replay accepted")
	}
	if len(s.SnapshotSpans()) != 6 {
		t.Fatal("conflict partially committed")
	}
}

func TestWorkflowValidationIsAtomicAndMeasuredStagesStaySeparate(t *testing.T) {
	d := NewDispatcher(store.New(), testSkillCatalog())
	run := testWorkflowRun()
	run.Events = []workflowEvent{checkpoint(run, "discover", 1)}
	duration, code := 42.0, 3
	event := checkpoint(run, "assess", 1)
	event.Source = "executed"
	event.Status = "failed"
	event.DurationMs = &duration
	event.ExitCode = &code
	event.EndedAt = event.StartedAt.Add(42 * time.Millisecond)
	run.Events = append(run.Events, event)
	if result := recordWorkflow(d, run); result.IsError {
		t.Fatal(result)
	}
	if len(d.store.SnapshotMetrics()) != 3 {
		t.Fatal("missing count/duration for executed stage")
	}
	finish := run.StartedAt.Add(6 * time.Second)
	run.FinishedAt = &finish
	run.Status = "passed"
	count := len(d.store.SnapshotSpans())
	if result := recordWorkflow(d, run); !result.IsError {
		t.Fatal("missing/failed stages accepted as passed")
	}
	if len(d.store.SnapshotSpans()) != count {
		t.Fatal("invalid run partially committed")
	}
	run.Status = "partial"
	if result := recordWorkflow(d, run); result.IsError {
		t.Fatal(result)
	}
	result := toMapAny(parseToolResult(t, d.skillWorkflows(nil)))
	row := toMapAny(toSliceAny(result["runs"])[0])
	findings := toSliceAny(row["improvementCandidates"])
	if len(findings) != 2 {
		t.Fatalf("missing failed/unobserved diagnostics: %v", findings)
	}
	for _, mutate := range []func(*workflowRun){
		func(r *workflowRun) { r.RunID = "invalid" },
		func(r *workflowRun) { r.Events[0].Stage = "invented" },
		func(r *workflowRun) { r.Events[0].Branch = "invented" },
		func(r *workflowRun) { r.Events[0].Attempt = 2 },
		func(r *workflowRun) { r.Events[0].DurationMs = &duration },
		func(r *workflowRun) { r.Events[0].Status = "blocked" },
	} {
		candidate := testWorkflowRun()
		candidate.Events = []workflowEvent{checkpoint(candidate, "discover", 1)}
		mutate(&candidate)
		if result := recordWorkflow(d, candidate); !result.IsError {
			t.Fatal("invalid stage accepted")
		}
	}
}

func TestModernHTTPHeadersAreValidatedWithoutChangingLegacyRequests(t *testing.T) {
	mux := http.NewServeMux()
	Register(mux, store.New(), testSkillCatalog())
	for _, scenario := range []struct {
		name, method, version, headerMethod string
		want                                int
	}{
		{"valid", "skills/list", modernProtocol, "skills/list", 200},
		{"method mismatch", "skills/list", modernProtocol, "tools/list", 400},
		{"version mismatch", "skills/list", "2099-01-01", "skills/list", 400},
		{"unknown RPC", "unknown/method", modernProtocol, "unknown/method", 404},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			request := jsonRPCRequest{JSONRPC: "2.0", ID: "request", Method: scenario.method, Params: map[string]any{"_meta": skillMeta()}}
			data, _ := json.Marshal(request)
			req := httptest.NewRequest("POST", "/mcp", bytes.NewReader(data))
			req.RemoteAddr = "127.0.0.1:54321"
			req.Header.Set("MCP-Protocol-Version", scenario.version)
			req.Header.Set("Mcp-Method", scenario.headerMethod)
			req.Header.Set("Mcp-Session-Id", "stale-legacy-session")
			recorder := httptest.NewRecorder()
			mux.ServeHTTP(recorder, req)
			if recorder.Code != scenario.want {
				t.Fatalf("got %d: %s", recorder.Code, recorder.Body.String())
			}
			if recorder.Header().Get("Mcp-Session-Id") != "" {
				t.Fatal("modern response minted a legacy session")
			}
		})
	}
}

func TestCatalogPreservesFrontmatterDelimitersAndIsolatesInvalidMetadata(t *testing.T) {
	source := fstest.MapFS{
		"valid/SKILL.md":                         {Data: []byte("---\nname: valid\ndescription: 'Keep --- inside a value'\n---\nRead ../references/example.md\n")},
		"bad/SKILL.md":                           {Data: []byte("---\nname: bad\ndescription: Bad\nmetadata:\n  value: .nan\n---\n")},
		"collision/SKILL.md":                     {Data: []byte("---\nname: collision\ndescription: Collision\n---\n")},
		"collision/references/shared/example.md": {Data: []byte("owned content")},
		"references/example.md":                  {Data: []byte("shared content")},
	}
	catalog := NewSkillCatalog(source)
	if len(catalog.names) != 1 || catalog.names[0] != "valid" {
		t.Fatalf("bad catalog isolation: %v", catalog.names)
	}
	if catalog.skills["valid"].entry.Frontmatter["description"] != "Keep --- inside a value" {
		t.Fatal("frontmatter delimiter was parsed inside a value")
	}
}

func TestWorkflowConcurrentReplaysRemainIdempotent(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s, testSkillCatalog())
	run := testWorkflowRun()
	run.Events = []workflowEvent{checkpoint(run, "discover", 1), checkpoint(run, "assess", 1), checkpoint(run, "report", 1)}
	finish := run.StartedAt.Add(5 * time.Second)
	run.FinishedAt = &finish
	run.Status = "passed"
	errors := make(chan bool, 24)
	for i := 0; i < 24; i++ {
		go func() { errors <- recordWorkflow(d, run).IsError }()
	}
	for i := 0; i < 24; i++ {
		if <-errors {
			t.Fatal("concurrent replay failed")
		}
	}
	if len(s.SnapshotSpans()) != 6 || len(s.SnapshotMetrics()) != 5 {
		t.Fatal("concurrent replay duplicated spans or metrics")
	}
}

func TestProjectedSkillsRunSharedHelpersWithoutSiblingDependencies(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("Python unavailable for materialized helper smoke test")
	}
	catalog := NewSkillCatalog(os.DirFS("../../../skills"))
	t.Setenv("OBSTUDIO_SKILL_MCP_ENDPOINT", "none")
	for _, name := range []string{"otel-audit", "otel-instrument", "otel-verify"} {
		t.Run(name, func(t *testing.T) {
			skill, ok := catalog.skills[name]
			if !ok {
				t.Fatal("canonical skill could not be projected")
			}
			root := t.TempDir()
			directory := filepath.Join(root, name)
			for filename, data := range skill.files {
				target := filepath.Join(directory, filepath.FromSlash(filename))
				if err := os.MkdirAll(filepath.Dir(target), 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(target, data, 0600); err != nil {
					t.Fatal(err)
				}
			}
			command := exec.Command(python, filepath.Join(directory, "scripts", "observe_report.py"), "--help")
			if output, err := command.CombinedOutput(); err != nil {
				t.Fatalf("remote report helper: %v: %s", err, output)
			}
			if name != "otel-audit" {
				validator := "validate_gap_closure.py"
				if name == "otel-verify" {
					validator = "validate_reader_report.py"
				}
				command = exec.Command(python, "-c", `import runpy,sys; m=runpy.run_path(sys.argv[1]); m["load_shared_report_module"]()`, filepath.Join(directory, "scripts", validator))
				if output, err := command.CombinedOutput(); err != nil {
					t.Fatalf("remote validator dependency: %v: %s", err, output)
				}
			}
			command = exec.Command(python, filepath.Join(directory, "references", "shared", "scripts", "skill_workflow.py"), "start", "--skill", name, "--repo-root", root)
			output, err := command.Output()
			if err != nil {
				t.Fatalf("remote workflow helper: %v", err)
			}
			var started struct {
				Run string `json:"run"`
			}
			if err := json.Unmarshal(output, &started); err != nil {
				t.Fatal(err)
			}
			state, err := os.ReadFile(started.Run)
			if err != nil {
				t.Fatal(err)
			}
			var run workflowRun
			if err := json.Unmarshal(state, &run); err != nil {
				t.Fatal(err)
			}
			if run.SkillDigest == "" || run.ContractDigest == "" {
				t.Fatal("missing materialized source version")
			}
			if result := recordWorkflow(NewDispatcher(store.New(), catalog), run); result.IsError {
				t.Fatalf("materialized journal incompatible with MCP: %+v", result)
			}
		})
	}
}

func TestCatalogRejectsSymlinkedSharedRoot(t *testing.T) {
	root := t.TempDir()
	external := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "valid"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "valid", "SKILL.md"), []byte("---\nname: valid\ndescription: Valid\n---\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(external, "private.txt"), []byte("outside catalog"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(external, filepath.Join(root, "references")); err != nil {
		t.Skip("Symlinks unavailable:", err)
	}
	if catalog := NewSkillCatalog(os.DirFS(root)); len(catalog.names) != 0 {
		t.Fatal("symlinked shared root was served")
	}
}
func TestWorkflowQueryIgnoresMalformedUnrelatedTelemetry(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s, testSkillCatalog())
	s.AddSpansForConnection("external", []store.Span{{TraceID: "external", SpanID: "external", Scope: store.Scope{Name: "obstudio.skill-workflows"}, Attributes: map[string]any{"skill.name": true}}})
	result := toMapAny(parseToolResult(t, d.skillWorkflows(nil)))
	if len(toSliceAny(result["runs"])) != 0 {
		t.Fatal("malformed external telemetry exposed as workflow")
	}
}
