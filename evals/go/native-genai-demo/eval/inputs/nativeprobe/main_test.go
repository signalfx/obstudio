package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestReadOnlyReceiptChecksActualWireAndCompleteSourceGraph(t *testing.T) {
	path := "../native-candidate-capture.json"
	if _, err := os.Stat(path); err != nil {
		t.Fatal("required candidate receipt missing")
	}
	failures, err := validateReceipt(path, "native")
	if err != nil || len(failures) != 0 {
		t.Fatalf("positive=%v %v", failures, err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	mutated := strings.Replace(string(data), `"body_sha256": "`, `"body_sha256": "corrupt-`, 1)
	dest := filepath.Join(t.TempDir(), "changed.json")
	if err = os.WriteFile(dest, []byte(mutated), 0600); err != nil {
		t.Fatal(err)
	}
	failures, err = validateReceipt(dest, "native")
	if err != nil || len(failures) == 0 {
		t.Fatalf("changed raw digest accepted %v %v", failures, err)
	}
}
func TestMissingToolMessagesRealNativeNegative(t *testing.T) {
	path := "../native-missing-tool-message-capture.json"
	if _, err := os.Stat(path); err != nil {
		t.Fatal("required negative receipt missing")
	}
	failures, err := validateReceipt(path, "native")
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, failure := range failures {
		if failure == "missing gen_ai.input.messages" {
			found = true
		}
	}
	if !found {
		t.Fatalf("missing tool input messages accepted %v", failures)
	}
}
func TestCleanEnvironmentRemovesEveryProxySpellingWithoutChangingCaller(t *testing.T) {
	t.Setenv("HtTp_PrOxY", "http://invalid.example")
	t.Setenv("NO_PROXY", "")
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "secret=hidden")
	env := cleanEnvironment("http://127.0.0.1:1234")
	for _, item := range env {
		upper := strings.ToUpper(item)
		if strings.HasPrefix(upper, "HTTP_PROXY=") || strings.HasPrefix(upper, "NO_PROXY=") || strings.Contains(item, "secret=hidden") {
			t.Fatal("ambient transport configuration inherited")
		}
	}
	if os.Getenv("HtTp_PrOxY") != "http://invalid.example" {
		t.Fatal("caller environment changed")
	}
}
func TestGraphRejectsOmittedSpanAndEmptyBaseline(t *testing.T) {
	if len(graph(nil)) == 0 {
		t.Fatal("empty trace accepted")
	}
}

func TestActualWireGraphRejectsCoverageAndTimingRegressions(t *testing.T) {
	data, err := os.ReadFile("../native-candidate-capture.json")
	if err != nil {
		t.Fatal(err)
	}
	var envelope struct {
		Runs []struct {
			Native []struct {
				Path string `json:"path"`
				Body string `json:"body_base64"`
			} `json:"native_requests"`
		} `json:"runs"`
	}
	if json.Unmarshal(data, &envelope) != nil || len(envelope.Runs) == 0 {
		t.Fatal("invalid required receipt")
	}
	original := []record{}
	for _, request := range envelope.Runs[0].Native {
		if request.Path == "/v1/traces" {
			body, err := base64.StdEncoding.DecodeString(request.Body)
			if err != nil {
				t.Fatal(err)
			}
			rows, err := decode(request.Path, body)
			if err != nil {
				t.Fatal(err)
			}
			original = append(original, rows...)
		}
	}
	if failures := graph(original); len(failures) > 0 {
		t.Fatal(failures)
	}
	cases := map[string]func([]record) []record{
		"omitted source child": func(rows []record) []record { return rows[1:] },
		"duplicate span":       func(rows []record) []record { return append(rows, rows[0]) },
		"orphan parent":        func(rows []record) []record { rows[0]["parent_span_id"] = "1234567890abcdef"; return rows },
		"split request":        func(rows []record) []record { rows[0]["trace_id"] = "1234567890abcdef1234567890abcdef"; return rows },
		"zero identity":        func(rows []record) []record { rows[0]["span_id"] = "0000000000000000"; return rows },
		"unclosed span":        func(rows []record) []record { rows[0]["end_time_unix_nano"] = "0"; return rows },
		"child outside parent": func(rows []record) []record { rows[0]["start_time_unix_nano"] = "1"; return rows },
		"wrong source operation": func(rows []record) []record {
			rows[0]["attributes"].(record)["gen_ai.operation.name"] = "invented_workflow"
			return rows
		},
		"wrong kind": func(rows []record) []record { rows[0]["kind"] = int32(2); return rows },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			data, _ := json.Marshal(original)
			var rows []record
			_ = json.Unmarshal(data, &rows)
			for _, row := range rows {
				row["kind"] = int32(row["kind"].(float64))
			}
			if len(graph(mutate(rows))) == 0 {
				t.Fatal("invalid whole trace accepted")
			}
		})
	}
}

func TestSourceBoundReceiptsMatchFrozenProvenance(t *testing.T) {
	data, err := os.ReadFile("../candidate-provenance.json")
	if err != nil {
		t.Fatal("required provenance missing")
	}
	var provenance struct {
		Files map[string]string `json:"files"`
	}
	if json.Unmarshal(data, &provenance) != nil || len(provenance.Files) < 8 {
		t.Fatal("invalid source provenance")
	}
	for path, want := range provenance.Files {
		data, err := os.ReadFile(filepath.Join("../../..", path))
		if err != nil {
			t.Fatal(err)
		}
		digest := sha256.Sum256(data)
		if hex.EncodeToString(digest[:]) != want {
			t.Fatalf("source/capture provenance changed: %s", path)
		}
	}
}

func currentNativeRunForReview(t *testing.T) (record, record, record) {
	t.Helper()
	data, err := os.ReadFile("../native-candidate-capture.json")
	if err != nil {
		t.Fatal(err)
	}
	var envelope struct {
		Project record `json:"resolved_project"`
		Stream  record `json:"resolved_agent_stream"`
		Runs    []struct {
			Business  []record          `json:"business_outcomes"`
			Models    []record          `json:"model_requests"`
			Resources []record          `json:"resource_requests"`
			IDs       map[string]string `json:"model_response_ids"`
			Native    []struct {
				Path    string `json:"path"`
				Status  int    `json:"status"`
				Headers record `json:"headers"`
				Body    []byte `json:"body_base64"`
			} `json:"native_requests"`
		} `json:"runs"`
	}
	if json.Unmarshal(data, &envelope) != nil || len(envelope.Runs) == 0 {
		t.Fatal("invalid real native receipt")
	}
	source := envelope.Runs[0]
	native := []record{}
	for _, request := range source.Native {
		rows, err := decode(request.Path, request.Body)
		if err != nil {
			t.Fatal(err)
		}
		native = append(native, record{"path": request.Path, "status": request.Status, "headers": request.Headers, "records": rows})
	}
	return record{"native_requests": native, "business_outcomes": source.Business, "model_requests": source.Models, "resource_requests": source.Resources, "model_response_ids": source.IDs}, envelope.Project, envelope.Stream
}
func TestMixedPublicAndStudioTraceBindingsRejected(t *testing.T) {
	run, project, stream := currentNativeRunForReview(t)
	if failures := validate(run, "native", project, stream); len(failures) > 0 {
		t.Fatal(failures)
	}
	for _, request := range run["native_requests"].([]record) {
		if request["path"] == "/v1/traces" {
			request["headers"].(record)["agentstreamid"] = "unexpected-public-binding"
			break
		}
	}
	if failures := validate(run, "native", project, stream); len(failures) == 0 {
		t.Fatal("accepted public agentstreamid alongside correct selected Studio projectid/logstreamid")
	}
}
func TestOtherApplicableMetricsRemainSeparateFromInferenceProfile(t *testing.T) {
	run, project, stream := currentNativeRunForReview(t)
	// A valid non-inference operation instrument must retain its actual operation,
	// rather than acquiring a nonexistent model request or chat classification.
	extra := record{"name": "gen_ai.client.operation.duration", "unit": "s", "type": "histogram", "count": uint64(4), "sum": 0.25, "attributes": record{"gen_ai.operation.name": "execute_tool", "gen_ai.provider.name": "fixture.http"}}
	for _, request := range run["native_requests"].([]record) {
		if request["path"] == "/v1/metrics" {
			request["records"] = append(request["records"].([]record), extra)
			break
		}
	}
	if failures := validate(run, "native", project, stream); len(failures) > 0 {
		t.Fatalf("valid additional source-applicable metric falsely classified as inference: %v", failures)
	}
}
func TestRequiredInferenceMetricsStillValidateTheirOwnDimensions(t *testing.T) {
	run, project, stream := currentNativeRunForReview(t)
	for _, request := range run["native_requests"].([]record) {
		if request["path"] == "/v1/metrics" {
			for _, point := range request["records"].([]record) {
				if point["name"] == "gen_ai.client.inference.usage.input_tokens" {
					point["attributes"].(record)["gen_ai.operation.name"] = "execute_tool"
					break
				}
			}
		}
	}
	if failures := validate(run, "native", project, stream); len(failures) == 0 {
		t.Fatal("required inference token counter lost its own chat/source dimension guard")
	}
}

func TestRejectedStudioTraceStillRejectsMixedPublicBinding(t *testing.T) {
	run, _, _ := currentNativeRunForReview(t)
	for _, request := range run["native_requests"].([]record) {
		if request["path"] == "/v1/traces" {
			request["status"] = 400
		}
	}
	if failures := failureEvidence(run, "existing", true); len(failures) > 0 {
		t.Fatal(failures)
	}
	for _, request := range run["native_requests"].([]record) {
		if request["path"] == "/v1/traces" {
			request["headers"].(record)["agentstreamid"] = "unexpected-public-binding"
			break
		}
	}
	if failures := failureEvidence(run, "existing", true); len(failures) == 0 {
		t.Fatal("trace rejection hid mixed public/Studio routing")
	}
}

func stageNativeCandidateForTest(t *testing.T) string {
	t.Helper()
	directory := t.TempDir()
	for _, name := range []string{"main.go", "go.mod", "go.sum"} {
		data, err := os.ReadFile(filepath.Join("../../..", name))
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(directory, name), data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	source, err := os.ReadFile("../nativecandidate/telemetry.go")
	if err != nil {
		t.Fatal(err)
	}
	prefix := []byte("//go:build ignore\n\n")
	if !bytes.HasPrefix(source, prefix) {
		t.Fatal("candidate build-tag transformation changed")
	}
	if err = os.WriteFile(filepath.Join(directory, "telemetry.go"), bytes.TrimPrefix(source, prefix), 0600); err != nil {
		t.Fatal(err)
	}
	executable := filepath.Join(directory, "agent")
	goName := "go"
	if runtime.GOOS == "windows" {
		goName += ".exe"
		executable += ".exe"
	}
	command := exec.Command(filepath.Join(runtime.GOROOT(), "bin", goName), "build", "-mod=readonly", "-o", executable, ".")
	command.Dir = directory
	command.Env = append(os.Environ(), "GOTOOLCHAIN=local")
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("compile exact candidate: %v\n%s", err, output)
	}
	return executable
}
func assertCandidateSourceMetadata(t *testing.T, run record) {
	t.Helper()
	roots := 0
	for _, span := range spansFrom(run) {
		a := span["attributes"].(record)
		if a["gen_ai.agent.name"] != "support_agent" {
			t.Errorf("%s missing source-affiliated owning agent", span["name"])
		}
		if a["gen_ai.operation.name"] == "invoke_agent" {
			roots++
			if a["gen_ai.request.model"] != "fixture-model-v1" {
				t.Errorf("agent missing source fixed model: %v", a["app.request_id"])
			}
		}
	}
	if roots != 4 {
		t.Fatalf("expected4agentroots got%d", roots)
	}
}
func TestNativeCandidateMetadataAndConflictRecovery(t *testing.T) {
	executable := stageNativeCandidateForTest(t)
	for _, scenario := range []string{"source_metadata", "project_conflict", "stream_conflict", "project_unresolved", "stream_wrong_parent", "project_relookup_forbidden"} {
		t.Run(scenario, func(t *testing.T) {
			state := &server{resources: "missing", responseIDs: map[string]string{}}
			if strings.HasPrefix(scenario, "stream_") {
				state.project = record{"id": uuid(), "name": "fixture-project", "type": "gen_ai"}
			}
			conflicted := false
			projectPosts, streamPosts, relookups := 0, 0, 0
			sink := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if strings.HasPrefix(r.URL.Path, "/ao/api/projects") {
					state.mu.Lock()
					target := false
					if r.Method == "POST" {
						if r.URL.Path == "/ao/api/projects" {
							projectPosts++
							target = strings.HasPrefix(scenario, "project_")
						} else if strings.HasSuffix(r.URL.Path, "/log_streams") {
							streamPosts++
							target = strings.HasPrefix(scenario, "stream_")
						}
					}
					if conflicted && r.Method == "GET" {
						relookups++
					}
					if target && !conflicted {
						conflicted = true
						var input any
						_ = json.NewDecoder(r.Body).Decode(&input)
						state.journal = append(state.journal, record{"method": r.Method, "path": r.URL.Path, "query": r.URL.RawQuery, "body": input, "status": 409})
						if r.Header.Get("X-SF-Token") != "local-gateway" {
							t.Error("resource public marker missing")
						}
						if scenario == "project_conflict" {
							state.project = record{"id": uuid(), "name": "fixture-project", "type": "gen_ai"}
						}
						if scenario == "stream_conflict" || scenario == "stream_wrong_parent" {
							parent := state.project["id"]
							if scenario == "stream_wrong_parent" {
								parent = uuid()
							}
							state.stream = record{"id": uuid(), "name": "fixture-agent", "project_id": parent}
						}
						state.mu.Unlock()
						write(w, 409, record{"error": "private-resource-detail"})
						return
					}
					if conflicted && scenario == "project_relookup_forbidden" && r.Method == "GET" {
						state.journal = append(state.journal, record{"method": r.Method, "path": r.URL.Path, "status": 403})
						state.mu.Unlock()
						write(w, 403, record{"error": "private-resource-detail"})
						return
					}
					state.mu.Unlock()
				}
				state.ServeHTTP(w, r)
			}))
			defer sink.Close()
			output := filepath.Join(t.TempDir(), "business.json")
			ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
			defer cancel()
			command := exec.CommandContext(ctx, executable, "--model-origin", sink.URL, "--scenario", "all", "--output", output)
			command.Env = cleanEnvironment(sink.URL)
			var diagnostics bytes.Buffer
			command.Stderr = &diagnostics
			if err := command.Run(); err != nil {
				t.Fatalf("actual candidate runtime failed: %v %s", err, diagnostics.String())
			}
			if strings.Contains(diagnostics.String(), "private-resource-detail") {
				t.Fatal("raw resource failure leaked into diagnostics")
			}
			data, err := os.ReadFile(output)
			if err != nil {
				t.Fatal(err)
			}
			var outcomes []record
			if json.Unmarshal(data, &outcomes) != nil {
				t.Fatal("invalid business output")
			}
			state.mu.Lock()
			defer state.mu.Unlock()
			run := record{"native_requests": state.native, "business_outcomes": outcomes, "model_requests": state.models, "resource_requests": state.journal, "model_response_ids": state.responseIDs}
			assertCandidateSourceMetadata(t, run)
			if failures := validate(run, "capture", state.project, state.stream); len(failures) > 0 {
				t.Fatal(failures)
			}
			if failures := graph(spansFrom(run)); len(failures) > 0 {
				t.Fatal(failures)
			}
			if scenario == "source_metadata" || scenario == "project_conflict" || scenario == "stream_conflict" {
				if failures := validate(run, "native", state.project, state.stream); len(failures) > 0 {
					t.Fatal(failures)
				}
			} else {
				for _, request := range state.native {
					headers := request["headers"].(record)
					if headers["projectid"] != nil || headers["logstreamid"] != nil || headers["agentstreamid"] != nil {
						t.Fatal("unresolved/invalid conflict retained bound headers")
					}
				}
			}
			metrics := map[string][]record{}
			for _, request := range state.native {
				if request["path"] == "/v1/metrics" {
					if request["status"] != 200 {
						t.Fatal("independent metric export rejected")
					}
					for _, point := range request["records"].([]record) {
						metrics[point["name"].(string)] = append(metrics[point["name"].(string)], point)
					}
				}
			}
			if failures := profile(run, metrics); len(failures) > 0 {
				t.Fatal(failures)
			}
			if scenario != "source_metadata" {
				if !conflicted || projectPosts > 1 || streamPosts > 1 {
					t.Fatalf("conflict retried creation: projectPOST=%d streamPOST=%d", projectPosts, streamPosts)
				}
				if scenario == "project_unresolved" {
					if relookups != 2 || streamPosts != 0 {
						t.Fatalf("unresolved project recovery not bounded: GET=%d streamPOST=%d", relookups, streamPosts)
					}
				} else if scenario == "stream_conflict" || scenario == "stream_wrong_parent" || scenario == "project_relookup_forbidden" {
					if relookups != 1 {
						t.Fatalf("unexpected exact relookup count %d", relookups)
					}
				}
			}
		})
	}
}

func TestStoredNativeCandidateSourceKnownMetadata(t *testing.T) {
	for _, name := range []string{"native-candidate-capture.json", "native-missing-tool-message-capture.json", "native-lookup-failure-capture.json", "native-rejected-traces-capture.json"} {
		t.Run(name, func(t *testing.T) {
			data, err := os.ReadFile(filepath.Join("..", name))
			if err != nil {
				t.Fatal(err)
			}
			var envelope struct {
				Runs []struct {
					Native []struct {
						Path string `json:"path"`
						Body []byte `json:"body_base64"`
					} `json:"native_requests"`
				} `json:"runs"`
			}
			if json.Unmarshal(data, &envelope) != nil || len(envelope.Runs) == 0 {
				t.Fatal("invalid required actual capture")
			}
			for _, run := range envelope.Runs {
				native := []record{}
				for _, request := range run.Native {
					if request.Path == "/v1/traces" {
						spans, err := decode(request.Path, request.Body)
						if err != nil {
							t.Fatal(err)
						}
						native = append(native, record{"path": request.Path, "records": spans})
					}
				}
				assertCandidateSourceMetadata(t, record{"native_requests": native})
			}
		})
	}
}
