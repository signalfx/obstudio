package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

// This exporter captures actual SDK-ended spans. Expectations live in a separate
// fixture and are never derived from these spans or the workflow's pass status.
type correctnessSDKCapture struct {
	mu    sync.Mutex
	spans []sdktrace.ReadOnlySpan
}

func (e *correctnessSDKCapture) ExportSpans(_ context.Context, spans []sdktrace.ReadOnlySpan) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.spans = append(e.spans, spans...)
	return nil
}

func (e *correctnessSDKCapture) Shutdown(context.Context) error { return nil }

func TestCorrectnessIndependentAppSDKOTLPAndMCP(t *testing.T) {
	contract, err := os.ReadFile("testdata/skill-correctness-contract.json")
	if err != nil {
		t.Fatal(err)
	}
	for _, variant := range []struct {
		name            string
		instrumentation string
		audit           string
	}{
		{"correct", "pass", "fail"},
		{"wrong_route", "fail", "pass"},
		{"missing", "fail", "pass"},
		{"duplicate", "fail", "pass"},
		{"wrong_parent", "fail", "pass"},
		{"failure_path", "pass", "fail"},
		{"contract_only", "unknown", "unknown"},
	} {
		t.Run(variant.name, func(t *testing.T) {
			var args map[string]any
			selectedContract := contract
			if variant.name == "failure_path" {
				selectedContract, err = os.ReadFile("testdata/skill-correctness-error-contract.json")
				if err != nil {
					t.Fatal(err)
				}
			}
			if err := json.Unmarshal(selectedContract, &args); err != nil {
				t.Fatal(err)
			}
			s := store.New()
			d := NewDispatcher(s, testSkillCatalog())
			receiver, err := otlp.StartReceiver(context.Background(), s, "127.0.0.1:0", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = receiver.Shutdown(context.Background()) })
			mux := http.NewServeMux()
			mux.Handle("/v1/traces", receiver.HTTPHandler())
			Register(mux, s, testSkillCatalog())
			server := httptest.NewServer(mux)
			defer server.Close()
			// Independent scenario execution follows an already-passed skill run.
			run := completedWorkflow(d, t)
			exporter := &correctnessSDKCapture{}
			provider := sdktrace.NewTracerProvider(sdktrace.WithSyncer(exporter), sdktrace.WithResource(resource.NewSchemaless(attribute.String("service.name", "tasks"), attribute.String("service.version", "fixture-v1"))))
			defer provider.Shutdown(context.Background())
			proofMode := "app_test"
			if variant.name == "contract_only" {
				proofMode = "contract_only"
			}
			ctx, witness := provider.Tracer("obstudio.verification").Start(context.Background(), "scenario POST /tasks", trace.WithAttributes(
				attribute.String("verification.run_id", run.RunID), attribute.String("verification.scenario", "tasks.create"), attribute.String("verification.proof_mode", proofMode)))
			tracer := provider.Tracer("tasks.http")
			invocations := 0
			statusCode := http.StatusCreated
			if variant.name == "failure_path" {
				statusCode = http.StatusInternalServerError
			}
			handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				invocations++
				if variant.name != "missing" {
					parent := r.Context()
					if variant.name == "wrong_parent" {
						parent = trace.ContextWithSpanContext(context.Background(), trace.NewSpanContext(trace.SpanContextConfig{TraceID: witness.SpanContext().TraceID(), SpanID: trace.SpanID{9}, TraceFlags: trace.FlagsSampled}))
					}
					route := "/tasks"
					if variant.name == "wrong_route" {
						route = "/wrong"
					}
					_, span := tracer.Start(parent, "POST /tasks", trace.WithSpanKind(trace.SpanKindServer), trace.WithAttributes(attribute.String("http.route", route), attribute.Int("http.response.status_code", statusCode)))
					if variant.name == "failure_path" {
						span.SetStatus(codes.Error, "task creation failed")
						span.SetAttributes(attribute.String("error.type", "task_creation_failed"))
					}
					span.End()
					if variant.name == "duplicate" {
						_, duplicate := tracer.Start(parent, "POST /tasks", trace.WithSpanKind(trace.SpanKindServer))
						duplicate.End()
					}
				}
				w.WriteHeader(statusCode)
			})
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, httptest.NewRequest("POST", "/tasks", nil).WithContext(ctx))
			if response.Code != statusCode || invocations != 1 {
				t.Fatal("application scenario did not execute successfully")
			}
			ids := []string{}
			for _, span := range exporter.spans {
				ids = append(ids, span.SpanContext().SpanID().String())
			}
			witness.SetAttributes(attribute.Bool("verification.completed", true), attribute.StringSlice("verification.span_ids", ids))
			witness.SetStatus(codes.Ok, "scenario executed")
			witness.End()
			postCorrectnessJSON(t, server.URL+"/v1/traces", sdkCaptureOTLP(t, exporter.spans))
			args["runId"] = run.RunID
			scenario := toMapAny(toSliceAny(args["scenarios"])[0])
			scenario["traceId"] = witness.SpanContext().TraceID().String()
			scenario["witnessSpanId"] = witness.SpanContext().SpanID().String()
			rpc, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": map[string]any{"name": "observer_skill_correctness_evaluate", "arguments": args}})
			var envelope struct {
				Result toolResult `json:"result"`
				Error  any        `json:"error"`
			}
			if err := json.Unmarshal(postCorrectnessJSON(t, server.URL+"/mcp", rpc), &envelope); err != nil || envelope.Error != nil || envelope.Result.IsError {
				t.Fatalf("MCP failed: %+v, %v", envelope, err)
			}
			result := toMapAny(parseToolResult(t, envelope.Result))
			rows := toSliceAny(result["results"])
			for i, want := range []string{variant.instrumentation, variant.audit} {
				if toMapAny(rows[i])["outcome"] != want {
					t.Fatalf("independent expected %s; result: %+v", want, result)
				}
			}
			t.Logf("actual handler -> SDK -> OTLP/HTTP -> MCP: instrumentation=%s audit_gap=%s", variant.instrumentation, variant.audit)
		})
	}
}

func postCorrectnessJSON(t *testing.T, url string, data []byte) []byte {
	t.Helper()
	response, err := http.Post(url, "application/json", bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil || response.StatusCode != http.StatusOK {
		t.Fatalf("%s: HTTP %d, %s, %v", url, response.StatusCode, body, err)
	}
	return body
}

func sdkCaptureOTLP(t *testing.T, spans []sdktrace.ReadOnlySpan) []byte {
	t.Helper()
	data := ptrace.NewTraces()
	for _, observed := range spans {
		rs := data.ResourceSpans().AppendEmpty()
		for _, attr := range observed.Resource().Attributes() {
			putCorrectnessSDKAttribute(t, rs.Resource().Attributes(), attr)
		}
		scope := rs.ScopeSpans().AppendEmpty()
		scope.Scope().SetName(observed.InstrumentationScope().Name)
		span := scope.Spans().AppendEmpty()
		span.SetName(observed.Name())
		span.SetTraceID(pcommon.TraceID(observed.SpanContext().TraceID()))
		span.SetSpanID(pcommon.SpanID(observed.SpanContext().SpanID()))
		span.SetParentSpanID(pcommon.SpanID(observed.Parent().SpanID()))
		span.SetKind(ptrace.SpanKind(observed.SpanKind()))
		span.SetStartTimestamp(pcommon.NewTimestampFromTime(observed.StartTime()))
		span.SetEndTimestamp(pcommon.NewTimestampFromTime(observed.EndTime()))
		if observed.Status().Code == codes.Ok {
			span.Status().SetCode(ptrace.StatusCodeOk)
		} else if observed.Status().Code == codes.Error {
			span.Status().SetCode(ptrace.StatusCodeError)
		}
		for _, attr := range observed.Attributes() {
			putCorrectnessSDKAttribute(t, span.Attributes(), attr)
		}
	}
	body, err := (&ptrace.JSONMarshaler{}).MarshalTraces(data)
	if err != nil {
		t.Fatal(err)
	}
	return body
}

func putCorrectnessSDKAttribute(t *testing.T, attrs pcommon.Map, attr attribute.KeyValue) {
	t.Helper()
	data, err := json.Marshal(attr.Value.AsInterface())
	if err != nil {
		t.Fatal(err)
	}
	var raw any
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatal(err)
	}
	if err := attrs.PutEmpty(string(attr.Key)).FromRaw(raw); err != nil {
		t.Fatal(err)
	}
}
