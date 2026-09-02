package mcp

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
)

// Test helper to unmarshal JSON tool results
func parseToolResult(t *testing.T, result toolResult) any {
	if len(result.Content) == 0 {
		t.Fatalf("no content in tool result")
	}
	var data any
	if err := json.Unmarshal([]byte(result.Content[0].Text), &data); err != nil {
		t.Fatalf("failed to unmarshal tool result: %v", err)
	}
	return data
}

// Test helper to convert any to map
func toMapAny(v any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return make(map[string]any)
}

// Test helper to convert any to slice
func toSliceAny(v any) []any {
	if s, ok := v.([]any); ok {
		return s
	}
	return []any{}
}

func containsAll(text string, parts ...string) bool {
	for _, part := range parts {
		if !strings.Contains(text, part) {
			return false
		}
	}
	return true
}

type fakeValidationRunner struct {
	summary validator.Summary
	calls   int
	onRun   func(context.Context) validator.Summary
}

func (f *fakeValidationRunner) Run(ctx context.Context) validator.Summary {
	f.calls++
	if f.onRun != nil {
		return f.onRun(ctx)
	}
	return f.summary
}

func TestDispatchContextCancelsValidationTools(t *testing.T) {
	for _, toolName := range []string{
		"observer_validation_analyze",
		"observer_validation_refresh",
	} {
		t.Run(toolName, func(t *testing.T) {
			started := make(chan struct{})
			canceled := make(chan struct{})
			runner := &fakeValidationRunner{
				onRun: func(ctx context.Context) validator.Summary {
					close(started)
					<-ctx.Done()
					close(canceled)
					return validator.Summary{}
				},
			}
			d := NewDispatcher(store.New(), validator.NewStore(), runner)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()

			done := make(chan jsonRPCResponse, 1)
			go func() {
				resp, _ := d.DispatchContext(ctx, jsonRPCRequest{
					ID:      1,
					JSONRPC: "2.0",
					Method:  "tools/call",
					Params: map[string]any{
						"name": toolName,
						"arguments": map[string]any{
							"timeoutSeconds": 300,
						},
					},
				})
				done <- resp
			}()

			select {
			case <-started:
			case <-time.After(time.Second):
				t.Fatal("validation runner did not start")
			}
			cancel()
			select {
			case <-canceled:
			case <-time.After(time.Second):
				t.Fatal("validation runner did not receive request cancellation")
			}
			select {
			case resp := <-done:
				if resp.Error != nil {
					t.Fatalf("unexpected JSON-RPC error: %+v", resp.Error)
				}
				result, ok := resp.Result.(toolResult)
				if !ok || !result.IsError {
					t.Fatalf("canceled validation result = %#v, want tool error", resp.Result)
				}
			case <-time.After(time.Second):
				t.Fatal("validation dispatch did not return after cancellation")
			}
		})
	}
}

func TestDispatchContextCancelsSplunkMetricsExportTest(t *testing.T) {
	started := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		close(started)
		<-release
	}))

	controller, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Enabled:     true,
		Endpoint:    server.URL,
		AccessToken: "test-token",
	})
	if err != nil {
		close(release)
		server.Close()
		t.Fatalf("create metrics export controller: %v", err)
	}
	defer func() {
		close(release)
		controller.Shutdown(context.Background())
		server.Close()
	}()

	d := NewDispatcher(store.New(), controller)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan jsonRPCResponse, 1)
	go func() {
		resp, _ := d.DispatchContext(ctx, jsonRPCRequest{
			ID:      1,
			JSONRPC: "2.0",
			Method:  "tools/call",
			Params: map[string]any{
				"name":      "observer_splunk_metrics_export_test",
				"arguments": map[string]any{},
			},
		})
		done <- resp
	}()

	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("metrics export test request did not start")
	}
	cancel()
	select {
	case resp := <-done:
		if resp.Error != nil {
			t.Fatalf("unexpected JSON-RPC error: %+v", resp.Error)
		}
		result, ok := resp.Result.(toolResult)
		if !ok || !result.IsError {
			t.Fatalf("canceled metrics export result = %#v, want tool error", resp.Result)
		}
	case <-time.After(time.Second):
		t.Fatal("metrics export dispatch did not return after cancellation")
	}
}

func TestJSONRPCRequestUnmarshalPreservesOnlyProtocolIdentifiers(t *testing.T) {
	var request jsonRPCRequest
	if err := json.Unmarshal([]byte(`{"jsonrpc":"2.0","id":9007199254740993,"method":"tools/call","params":{"name":"observer_metrics_overview","arguments":{"limit":7}}}`), &request); err != nil {
		t.Fatalf("unmarshal request: %v", err)
	}
	if request.ID != json.Number("9007199254740993") {
		t.Fatalf("request ID = %#v, want exact json.Number", request.ID)
	}
	params := toMapAny(request.Params)
	arguments := toMapAny(params["arguments"])
	if limit, ok := arguments["limit"].(float64); !ok || limit != 7 {
		t.Fatalf("limit = %#v, want unchanged float64(7)", arguments["limit"])
	}

	if err := json.Unmarshal([]byte(`{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":9007199254740993}}`), &request); err != nil {
		t.Fatalf("unmarshal cancellation: %v", err)
	}
	cancellationParams := toMapAny(request.Params)
	if cancellationParams["requestId"] != json.Number("9007199254740993") {
		t.Fatalf("cancellation requestId = %#v, want exact json.Number", cancellationParams["requestId"])
	}
}

// Test 1: Dispatch Initialize - returns server info, negotiated protocol version, capabilities
func TestDispatchInitialize(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "initialize",
		Params: map[string]any{
			"protocolVersion": "2025-06-18",
		},
	}

	resp, handled := d.Dispatch(req)
	if !handled {
		t.Fatalf("expected handled=true")
	}
	if resp.Error != nil {
		t.Fatalf("unexpected error: %v", resp.Error)
	}

	result := toMapAny(resp.Result)
	if result["serverInfo"] == nil {
		t.Fatalf("missing serverInfo")
	}
	serverInfo := toMapAny(result["serverInfo"])
	if serverInfo["name"] != "obstudio" {
		t.Fatalf("expected server name obstudio, got %v", serverInfo["name"])
	}
	if serverInfo["version"] != "0.1.0" {
		t.Fatalf("expected server version 0.1.0, got %v", serverInfo["version"])
	}

	if result["capabilities"] == nil {
		t.Fatalf("missing capabilities")
	}

	protocolVersion := result["protocolVersion"]
	if protocolVersion != "2025-06-18" {
		t.Fatalf("expected negotiated version 2025-06-18, got %v", protocolVersion)
	}
}

// Test 2: Initialize version negotiation - known versions accepted, unknown falls back
func TestInitializeVersionNegotiation(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	tests := []struct {
		name      string
		clientVer string
		expected  string
	}{
		{"known version", "2025-06-18", "2025-06-18"},
		{"known version 2", "2025-03-26", "2025-03-26"},
		{"known version 3", "2024-11-05", "2024-11-05"},
		{"unknown version falls back", "1999-01-01", "2025-06-18"},
		{"empty version falls back", "", "2025-06-18"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := jsonRPCRequest{
				ID:      1,
				JSONRPC: "2.0",
				Method:  "initialize",
				Params: map[string]any{
					"protocolVersion": tt.clientVer,
				},
			}

			resp, _ := d.Dispatch(req)
			result := toMapAny(resp.Result)
			protocolVersion := result["protocolVersion"].(string)
			if protocolVersion != tt.expected {
				t.Fatalf("expected %s, got %s", tt.expected, protocolVersion)
			}
		})
	}
}

// Test 3: Dispatch tools/list - returns all observer tools with names
func TestDispatchToolsList(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/list",
	}

	resp, handled := d.Dispatch(req)
	if !handled {
		t.Fatalf("expected handled=true")
	}
	if resp.Error != nil {
		t.Fatalf("unexpected error: %v", resp.Error)
	}

	result := toMapAny(resp.Result)
	if len(result) == 0 {
		t.Fatalf("result map is empty")
	}

	// tools are stored as []toolDef directly (not yet JSON-encoded)
	toolsRaw := result["tools"]
	if toolsRaw == nil {
		t.Fatalf("tools key not found in result")
	}

	// Type assert to []toolDef
	toolsList, ok := toolsRaw.([]toolDef)
	if !ok {
		t.Fatalf("tools is not []toolDef: %T", toolsRaw)
	}

	if len(toolsList) != 11 {
		t.Fatalf("expected 11 tools, got %d", len(toolsList))
	}

	expectedToolNames := map[string]bool{
		"observer_metrics_overview":     false,
		"observer_metric_detail":        false,
		"observer_traces_overview":      false,
		"observer_trace_detail":         false,
		"observer_token_usage_overview": false,
		"observer_logs_overview":        false,
		"observer_validation_status":    false,
		"observer_validation_analyze":   false,
		"observer_validation_refresh":   false,
		"observer_clear":                false,
		"observer_status":               false,
	}

	for _, tool := range toolsList {
		name := tool.Name
		if name == "observer_token_usage_overview" {
			if tool.Meta[TokenAccountingProtocolMetaKey] != TokenAccountingProtocolVersion {
				t.Fatalf("token accounting protocol metadata = %+v", tool.Meta)
			}
		}
		if _, ok := expectedToolNames[name]; ok {
			expectedToolNames[name] = true
		} else {
			t.Fatalf("unexpected tool name: %s", name)
		}
	}

	for name, found := range expectedToolNames {
		if !found {
			t.Fatalf("tool not found: %s", name)
		}
	}
}

func TestToolsCallTokenUsageOverviewNormalizesCoverageAndDeduplicates(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)
	now := time.Now()
	span := func(traceID, spanID, parentID, name string, offset time.Duration, attrs map[string]any) store.Span {
		return store.Span{
			TraceID:      traceID,
			SpanID:       spanID,
			ParentSpanID: parentID,
			Name:         name,
			Kind:         "INTERNAL",
			StartTime:    now.Add(offset),
			EndTime:      now.Add(offset + time.Millisecond),
			Status:       store.SpanStatus{Code: "OK"},
			Attributes:   attrs,
			Resource:     store.Resource{ServiceName: "audit-agent"},
		}
	}

	s.AddSpansForConnection("", []store.Span{
		span("measured", "workflow", "", "audit", 0, map[string]any{
			"gen_ai.operation.name":      "workflow",
			"gen_ai.usage.input_tokens":  999,
			"gen_ai.usage.output_tokens": 1,
			"gen_ai.usage.total_tokens":  1000,
		}),
		span("measured", "llm-1", "workflow", "chat", time.Millisecond, map[string]any{
			"gen_ai.operation.name":                    "chat",
			"gen_ai.request.model":                     "claude-sonnet",
			"gen_ai.usage.input_tokens":                int64(100),
			"gen_ai.usage.cached_input_tokens":         int64(40),
			"gen_ai.usage.cache_creation_input_tokens": int64(5),
			"gen_ai.usage.output_tokens":               int64(20),
			"gen_ai.usage.reasoning_output_tokens":     int64(8),
			"gen_ai.usage.total_tokens":                int64(120),
		}),
		span("measured", "llm-2", "workflow", "chat", 2*time.Millisecond, map[string]any{
			"gen_ai.operation.name":      "chat",
			"gen_ai.request.model":       "claude-sonnet",
			"gen_ai.usage.input_tokens":  int64(0),
			"gen_ai.usage.output_tokens": int64(0),
		}),
		span("measured", "database", "workflow", "database query", 2500*time.Microsecond, map[string]any{
			"model":        "database-v2",
			"total_tokens": int64(999),
		}),
		span("measured", "evaluation", "workflow", "quality", 3*time.Millisecond, map[string]any{
			"gen_ai.evaluation.name": "rubric",
		}),
		span("measured", "judge", "evaluation", "judge", 4*time.Millisecond, map[string]any{
			"gen_ai.operation.name":      "chat",
			"gen_ai.request.model":       "judge-model",
			"gen_ai.usage.input_tokens":  int64(500),
			"gen_ai.usage.output_tokens": int64(50),
		}),
		span("zero", "zero-llm", "", "chat", 10*time.Millisecond, map[string]any{
			"gen_ai.operation.name":                    "chat",
			"gen_ai.request.model":                     "gpt-5",
			"gen_ai.usage.input_tokens":                int64(0),
			"gen_ai.usage.cached_input_tokens":         int64(0),
			"gen_ai.usage.cache_creation_input_tokens": int64(0),
			"gen_ai.usage.output_tokens":               int64(0),
			"gen_ai.usage.reasoning_output_tokens":     int64(0),
			"gen_ai.usage.total_tokens":                int64(0),
		}),
		span("absent", "absent-llm", "", "chat", 20*time.Millisecond, map[string]any{
			"gen_ai.operation.name": "chat",
			"gen_ai.request.model":  "gpt-5",
		}),
		span("malformed", "malformed-llm", "", "chat", 30*time.Millisecond, map[string]any{
			"gen_ai.operation.name":      "chat",
			"gen_ai.request.model":       "gpt-5",
			"gen_ai.usage.input_tokens":  "not-a-token-count",
			"gen_ai.usage.output_tokens": -1,
		}),
	})

	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_token_usage_overview",
			"arguments": map[string]any{
				"serviceName": "audit-agent",
			},
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}
	data := toMapAny(parseToolResult(t, resp.Result.(toolResult)))
	if data["scope"] != "agent_task" || data["status"] != "partial" {
		t.Fatalf("unexpected overview scope/status: %+v", data)
	}

	traces := toSliceAny(data["traces"])
	if len(traces) != 4 {
		t.Fatalf("expected four GenAI traces, got %d", len(traces))
	}
	byTraceID := make(map[string]map[string]any, len(traces))
	for _, value := range traces {
		trace := toMapAny(value)
		byTraceID[trace["traceId"].(string)] = trace
	}

	measured := byTraceID["measured"]
	if measured["status"] != "measured" || measured["measurementSource"] != "llm_spans" {
		t.Fatalf("unexpected measured trace metadata: %+v", measured)
	}
	usage := toMapAny(measured["usage"])
	if usage["inputTokens"] != float64(100) || usage["providerTotalTokens"] != float64(120) || usage["derivedTotalTokens"] != float64(120) {
		t.Fatalf("workflow or judge usage was double counted: %+v", usage)
	}
	coverage := toMapAny(measured["coverage"])
	if coverage["recordCount"] != float64(2) || coverage["effectiveTotalCount"] != float64(2) {
		t.Fatalf("unexpected record coverage: %+v", coverage)
	}
	fieldCounts := toMapAny(coverage["fieldCounts"])
	if fieldCounts["cachedInputTokens"] != float64(1) || fieldCounts["inputTokens"] != float64(2) {
		t.Fatalf("partial field coverage was lost: %+v", fieldCounts)
	}
	models := toSliceAny(measured["modelNames"])
	if len(models) != 1 || models[0] != "claude-sonnet" {
		t.Fatalf("judge model leaked into agent usage: %+v", models)
	}

	zeroUsage := toMapAny(byTraceID["zero"]["usage"])
	if byTraceID["zero"]["status"] != "measured" || zeroUsage["effectiveTotalTokens"] != float64(0) {
		t.Fatalf("explicit zero was not preserved: %+v", byTraceID["zero"])
	}
	absentUsage := toMapAny(byTraceID["absent"]["usage"])
	if byTraceID["absent"]["status"] != "absent" || absentUsage["effectiveTotalTokens"] != nil {
		t.Fatalf("absent usage was not rendered as unknown: %+v", byTraceID["absent"])
	}
	malformedUsage := toMapAny(byTraceID["malformed"]["usage"])
	if byTraceID["malformed"]["status"] != "unrecognized" || malformedUsage["effectiveTotalTokens"] != nil {
		t.Fatalf("malformed usage was not distinguished: %+v", byTraceID["malformed"])
	}
}

func TestToolsCallTokenUsageOverviewDeduplicatesGenericSpanRetransmissions(t *testing.T) {
	s := store.New()
	now := time.Now()
	span := store.Span{
		TraceID: "retransmitted-trace", SpanID: "llm", Name: "chat",
		StartTime: now, EndTime: now.Add(time.Millisecond),
		Attributes: map[string]any{
			"gen_ai.operation.name":      "chat",
			"gen_ai.provider.name":       "openai",
			"gen_ai.usage.input_tokens":  int64(10),
			"gen_ai.usage.output_tokens": int64(2),
		},
		Resource: store.Resource{ServiceName: "application"},
	}
	s.AddSpansForConnection("application", []store.Span{span})
	span.Attributes = map[string]any{
		"gen_ai.operation.name":      "chat",
		"gen_ai.provider.name":       "openai",
		"gen_ai.usage.input_tokens":  int64(11),
		"gen_ai.usage.output_tokens": int64(3),
	}
	s.AddSpansForConnection("application", []store.Span{span})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"traceId": "retransmitted-trace"})
	trace := toMapAny(toSliceAny(data["traces"])[0])
	usage := toMapAny(trace["usage"])
	if trace["llmCalls"] != float64(1) || usage["inputTokens"] != float64(11) ||
		usage["outputTokens"] != float64(3) || usage["effectiveTotalTokens"] != float64(14) {
		t.Fatalf("generic span retransmission was double counted or stale: %+v", trace)
	}
}

func TestToolsCallTokenUsageOverviewClampsGenericFallbackLimit(t *testing.T) {
	s := store.New()
	now := time.Now()
	spans := make([]store.Span, 101)
	for index := range spans {
		spans[index] = store.Span{
			TraceID: fmt.Sprintf("trace-%03d", index), SpanID: "llm", Name: "chat",
			StartTime: now.Add(time.Duration(index) * time.Millisecond), EndTime: now.Add(time.Duration(index+1) * time.Millisecond),
			Attributes: map[string]any{
				"gen_ai.operation.name":      "chat",
				"gen_ai.usage.input_tokens":  int64(1),
				"gen_ai.usage.output_tokens": int64(1),
			},
			Resource: store.Resource{ServiceName: "application"},
		}
	}
	s.AddSpansForConnection("application", spans)

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"limit": 10_000})
	if traces := toSliceAny(data["traces"]); len(traces) != 100 {
		t.Fatalf("generic token fallback returned %d traces, want schema maximum 100", len(traces))
	}
}

func TestToolsCallTokenUsageOverviewNormalizesCodexAndClaudeProviderLogs(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)
	now := time.Now()
	providerLog := func(id, service, body string, offset time.Duration, attrs map[string]any) store.LogRecord {
		return store.LogRecord{
			ID:         id,
			Timestamp:  now.Add(offset),
			Body:       body,
			Attributes: attrs,
			Resource:   store.Resource{ServiceName: service},
		}
	}

	s.AddLogsForConnection("", []store.LogRecord{
		providerLog("codex-1", "Codex Desktop", "", 0, map[string]any{
			"event.name":            "codex.sse_event",
			"event.kind":            "response.completed",
			"event.sequence":        int64(1),
			"conversation.id":       "codex-conversation",
			"model":                 "gpt-5.4",
			"input_token_count":     "10",
			"cached_token_count":    int64(4),
			"output_token_count":    int64(5),
			"reasoning_token_count": int64(2),
			"tool_token_count":      int64(15),
		}),
		providerLog("codex-duplicate", "Codex Desktop", "", time.Millisecond, map[string]any{
			"event.name":            "codex.sse_event",
			"event.kind":            "response.completed",
			"event.sequence":        int64(1),
			"conversation.id":       "codex-conversation",
			"model":                 "gpt-5.4",
			"input_token_count":     int64(10),
			"cached_token_count":    int64(4),
			"output_token_count":    int64(5),
			"reasoning_token_count": int64(2),
			"tool_token_count":      int64(15),
		}),
		providerLog("codex-2", "Codex Desktop", "", 2*time.Millisecond, map[string]any{
			"event.name":            "codex.sse_event",
			"event.kind":            "response.completed",
			"event.sequence":        int64(2),
			"conversation.id":       "codex-conversation",
			"model":                 "gpt-5.4",
			"input_token_count":     int64(20),
			"cached_token_count":    int64(8),
			"output_token_count":    int64(6),
			"reasoning_token_count": int64(3),
			"tool_token_count":      int64(26),
		}),
		providerLog("claude-1", "claude-code", "claude_code.api_request", 3*time.Millisecond, map[string]any{
			"event.name":            "api_request",
			"request_id":            "request-1",
			"prompt.id":             "claude-prompt",
			"session.id":            "claude-session",
			"model":                 "claude-sonnet-4-5",
			"input_tokens":          int64(5),
			"cache_read_tokens":     int64(10),
			"cache_creation_tokens": int64(2),
			"output_tokens":         int64(4),
		}),
		providerLog("claude-duplicate", "claude-code", "claude_code.api_request", 4*time.Millisecond, map[string]any{
			"event.name":            "api_request",
			"request_id":            "request-1",
			"prompt.id":             "claude-prompt",
			"session.id":            "claude-session",
			"model":                 "claude-sonnet-4-5",
			"input_tokens":          int64(5),
			"cache_read_tokens":     int64(10),
			"cache_creation_tokens": int64(2),
			"output_tokens":         int64(4),
		}),
		providerLog("claude-2", "claude-code", "claude_code.api_request", 5*time.Millisecond, map[string]any{
			"event.name":            "api_request",
			"request_id":            "request-2",
			"prompt.id":             "claude-prompt",
			"session.id":            "claude-session",
			"model":                 "claude-sonnet-4-5",
			"input_tokens":          int64(1),
			"cache_read_tokens":     int64(0),
			"cache_creation_tokens": int64(0),
			"output_tokens":         int64(2),
		}),
	})

	data := callTokenUsageOverview(t, d, map[string]any{"limit": 10})
	if data["measurementSource"] != "provider_logs" || data["status"] != "measured" || data["accountingStatus"] != "uncorrelated" {
		t.Fatalf("unexpected provider overview: %+v", data)
	}
	if traces := toSliceAny(data["traces"]); len(traces) != 0 {
		t.Fatalf("provider logs should not be combined with trace usage: %+v", traces)
	}
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 2 {
		t.Fatalf("expected Codex and Claude tasks, got %+v", tasks)
	}
	byProvider := make(map[string]map[string]any, len(tasks))
	for _, value := range tasks {
		task := toMapAny(value)
		byProvider[task["provider"].(string)] = task
	}

	codex := byProvider["codex"]
	if codex["taskId"] != "codex-conversation" || codex["requestCount"] != float64(2) {
		t.Fatalf("Codex records were not grouped and deduplicated: %+v", codex)
	}
	codexUsage := toMapAny(codex["usage"])
	for field, want := range map[string]float64{
		"inputTokens":           30,
		"cachedInputTokens":     12,
		"outputTokens":          11,
		"reasoningOutputTokens": 5,
		"providerTotalTokens":   41,
		"derivedTotalTokens":    41,
	} {
		if got := codexUsage[field]; got != want {
			t.Fatalf("Codex %s = %#v, want %v: %+v", field, got, want, codexUsage)
		}
	}

	claude := byProvider["claude"]
	if claude["taskId"] != "claude-prompt" || claude["taskKind"] != "prompt" || claude["requestCount"] != float64(2) {
		t.Fatalf("Claude records were not grouped and deduplicated: %+v", claude)
	}
	claudeUsage := toMapAny(claude["usage"])
	for field, want := range map[string]float64{
		"inputTokens":              18,
		"cachedInputTokens":        10,
		"cacheCreationInputTokens": 2,
		"outputTokens":             6,
		"derivedTotalTokens":       24,
	} {
		if got := claudeUsage[field]; got != want {
			t.Fatalf("Claude %s = %#v, want %v: %+v", field, got, want, claudeUsage)
		}
	}
	if claudeUsage["providerTotalTokens"] != nil || claudeUsage["reasoningOutputTokens"] != nil {
		t.Fatalf("Claude unsupported fields should remain unknown: %+v", claudeUsage)
	}
}

func TestToolsCallTokenUsageOverviewRejectsConflictingProviderLogRetransmission(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("claude", []store.Span{{
		TraceID: "claude-conflicting-log", SpanID: "interaction", Name: "claude_code.interaction",
		StartTime: now, EndTime: now.Add(3 * time.Millisecond),
		Attributes: map[string]any{"prompt.id": "conflicting-prompt", "session.id": "conflicting-log-session"},
		Resource:   store.Resource{ServiceName: "claude-code"},
	}})
	request := func(id string, input int64, offset time.Duration) store.LogRecord {
		return store.LogRecord{
			ID: id, Timestamp: now.Add(offset), TraceID: "claude-conflicting-log", Body: "claude_code.api_request",
			Attributes: map[string]any{
				"event.name": "api_request", "request_id": "same-request", "prompt.id": "conflicting-prompt", "session.id": "conflicting-log-session",
				"input_tokens": input, "cache_read_tokens": int64(0), "cache_creation_tokens": int64(0), "output_tokens": int64(2),
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddLogsForConnection("claude", []store.LogRecord{
		request("first", 5, time.Millisecond),
		request("conflicting-retransmission", 9, 2*time.Millisecond),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "conflicting-log-session"})
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["correlationStatus"] != "trace_usage_mismatch" || task["accountingStatus"] != "uncorrelated" {
		t.Fatalf("conflicting provider-log retransmission was presented as exact: %+v", task)
	}
	if task["requestCount"] != float64(1) || !strings.Contains(task["normalization"].(string), "conflicting retransmissions") {
		t.Fatalf("conflicting provider-log retransmission diagnostics are wrong: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewKeepsIdentifierlessProviderRequestsDistinct(t *testing.T) {
	s := store.New()
	now := time.Now()
	logs := make([]store.LogRecord, 2)
	for index := range logs {
		logs[index] = store.LogRecord{
			Timestamp: now,
			Body:      "claude_code.api_request",
			Attributes: map[string]any{
				"event.name":            "api_request",
				"session.id":            "identifierless-session",
				"input_tokens":          int64(2),
				"cache_read_tokens":     int64(0),
				"cache_creation_tokens": int64(0),
				"output_tokens":         int64(1),
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddLogsForConnection("claude", logs)

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "identifierless-session"})
	task := toMapAny(toSliceAny(data["tasks"])[0])
	usage := toMapAny(task["usage"])
	if task["requestCount"] != float64(2) || task["providerEventCount"] != float64(2) ||
		usage["inputTokens"] != float64(4) || usage["outputTokens"] != float64(2) ||
		usage["effectiveTotalTokens"] != float64(6) {
		t.Fatalf("identifier-less provider requests were collapsed: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewDoesNotCallIdentifierlessRetransmissionsExact(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("claude", []store.Span{{
		TraceID: "claude-identifierless-retransmission", SpanID: "interaction", Name: "claude_code.interaction",
		StartTime: now, EndTime: now.Add(3 * time.Millisecond),
		Attributes: map[string]any{"prompt.id": "identifierless-prompt", "session.id": "identifierless-session"},
		Resource:   store.Resource{ServiceName: "claude-code"},
	}})
	logs := make([]store.LogRecord, 2)
	for index := range logs {
		logs[index] = store.LogRecord{
			Timestamp: now.Add(time.Millisecond), TraceID: "claude-identifierless-retransmission", Body: "claude_code.api_request",
			Attributes: map[string]any{
				"event.name": "api_request", "prompt.id": "identifierless-prompt", "session.id": "identifierless-session",
				"input_tokens": int64(2), "cache_read_tokens": int64(0), "cache_creation_tokens": int64(0), "output_tokens": int64(1),
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddLogsForConnection("claude", logs)

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "identifierless-session"})
	task := toMapAny(toSliceAny(data["tasks"])[0])
	usage := toMapAny(task["usage"])
	if task["accountingStatus"] == "exact" || task["correlationStatus"] == "trace_correlated" {
		t.Fatalf("identifier-less retransmissions were presented as exact: %+v", task)
	}
	if task["requestCount"] != float64(2) || usage["effectiveTotalTokens"] != float64(6) {
		t.Fatalf("identifier-less provider events were not preserved: %+v", task)
	}
}

func TestBuildProviderLogTasksDoesNotCorrelateOutOfWindowTraceLog(t *testing.T) {
	t.Parallel()

	now := time.Now().UTC()
	spans := map[string][]store.Span{
		"out-of-window-trace": {{
			TraceID: "out-of-window-trace", SpanID: "interaction", Name: "claude_code.interaction",
			StartTime: now, EndTime: now.Add(time.Second),
			Attributes: map[string]any{
				"prompt.id": "bounded-prompt", "session.id": "bounded-session",
				"skill.name": "bounded-skill", "model": "bounded-model",
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}},
	}
	logs := []store.LogRecord{{
		ID: "later-request", Timestamp: now.Add(2 * time.Second), TraceID: "out-of-window-trace", Body: "claude_code.api_request",
		Attributes: map[string]any{
			"event.name": "api_request", "request_id": "later-request", "session.id": "bounded-session",
			"input_tokens": int64(5), "cache_read_tokens": int64(0), "cache_creation_tokens": int64(0), "output_tokens": int64(2),
		},
		Resource: store.Resource{ServiceName: "claude-code"},
	}}

	built := buildProviderLogTasks(logs, spans, map[string]any{}, time.Time{})
	if len(built) != 1 {
		t.Fatalf("built provider log tasks = %d, want 1: %+v", len(built), built)
	}
	task := built[0].task
	if task.TaskID != "bounded-session" || task.AccountingStatus == "exact" || task.CorrelationStatus == "trace_correlated" ||
		len(task.SkillNames) != 0 || len(task.ModelNames) != 0 {
		t.Fatalf("out-of-window log inherited completed task metadata: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewCorrelatesDedicatedCodexAndClaudeTraces(t *testing.T) {
	s := store.New()
	now := time.Now()
	span := func(traceID, spanID, parentID, name, service string, offset time.Duration, attrs map[string]any) store.Span {
		return store.Span{
			TraceID:      traceID,
			SpanID:       spanID,
			ParentSpanID: parentID,
			Name:         name,
			StartTime:    now.Add(offset),
			EndTime:      now.Add(offset + time.Millisecond),
			Attributes:   attrs,
			Resource:     store.Resource{ServiceName: service},
		}
	}
	s.AddSpansForConnection("provider", []store.Span{
		span("codex-trace-1", "codex-root-1", "", "session_task.turn", "codex", 0, map[string]any{
			"thread.id":                           "shared-thread",
			"turn.id":                             "codex-turn-1",
			"codex.turn.token_usage.total_tokens": int64(15),
		}),
		span("codex-trace-2", "codex-root-2", "", "session_task.turn", "codex", 10*time.Millisecond, map[string]any{
			"thread.id":                           "shared-thread",
			"turn.id":                             "codex-turn-2",
			"codex.turn.token_usage.total_tokens": int64(0),
		}),
		span("claude-trace", "claude-root", "", "claude_code.interaction", "claude-code", 20*time.Millisecond, map[string]any{
			"prompt.id":  "claude-prompt",
			"session.id": "claude-session",
			"skill.name": "otel-audit",
		}),
		span("claude-trace", "claude-llm-1", "claude-root", "claude_code.llm_request", "claude-code", 21*time.Millisecond, map[string]any{}),
		span("claude-trace", "claude-llm-2", "claude-root", "claude_code.llm_request", "claude-code", 22*time.Millisecond, map[string]any{}),
		span("claude-trace", "evaluation", "claude-root", "quality", "claude-code", 23*time.Millisecond, map[string]any{
			"gen_ai.evaluation.name": "rubric",
		}),
		span("claude-trace", "judge", "evaluation", "claude_code.llm_request", "claude-code", 24*time.Millisecond, map[string]any{}),
	})
	providerLog := func(id, traceID, spanID, service, body string, offset time.Duration, attrs map[string]any) store.LogRecord {
		return store.LogRecord{
			ID:         id,
			Timestamp:  now.Add(offset),
			TraceID:    traceID,
			SpanID:     spanID,
			Body:       body,
			Attributes: attrs,
			Resource:   store.Resource{ServiceName: service},
		}
	}
	s.AddLogsForConnection("provider", []store.LogRecord{
		providerLog("codex-1", "", "codex-root-1", "codex", "codex.sse_event", time.Millisecond, map[string]any{
			"event.name":         "codex.sse_event",
			"event.kind":         "response.completed",
			"response.id":        "response-1",
			"conversation.id":    "shared-thread",
			"turn.id":            "codex-turn-1",
			"input_token_count":  int64(10),
			"output_token_count": int64(5),
			"tool_token_count":   int64(15),
		}),
		providerLog("codex-2", "", "codex-root-2", "codex", "codex.sse_event", 11*time.Millisecond, map[string]any{
			"event.name":            "codex.sse_event",
			"event.kind":            "response.completed",
			"response.id":           "response-2",
			"conversation.id":       "shared-thread",
			"turn.id":               "codex-turn-2",
			"input_token_count":     int64(0),
			"cached_token_count":    int64(0),
			"output_token_count":    int64(0),
			"reasoning_token_count": int64(0),
			"tool_token_count":      int64(0),
		}),
		providerLog("claude-1", "", "claude-llm-1", "claude-code", "claude_code.api_request", 24*time.Millisecond, map[string]any{
			"event.name":              "api_request",
			"request_id":              "claude-request-1",
			"prompt.id":               "claude-prompt",
			"skill.name":              "otel-audit",
			"input_tokens":            int64(5),
			"cache_read_tokens":       int64(10),
			"cache_creation_tokens":   int64(2),
			"output_tokens":           int64(4),
			"reasoning_output_tokens": int64(1),
			"total_tokens":            int64(21),
		}),
		providerLog("claude-2", "", "claude-llm-2", "claude-code", "claude_code.api_request", 25*time.Millisecond, map[string]any{
			"event.name":              "api_request",
			"request_id":              "claude-request-2",
			"prompt.id":               "claude-prompt",
			"input_tokens":            int64(1),
			"cache_read_tokens":       int64(0),
			"cache_creation_tokens":   int64(0),
			"output_tokens":           int64(2),
			"reasoning_output_tokens": int64(0),
			"total_tokens":            int64(3),
		}),
		providerLog("judge", "", "judge", "claude-code", "claude_code.api_request", 26*time.Millisecond, map[string]any{
			"event.name":    "api_request",
			"request_id":    "judge-request",
			"prompt.id":     "claude-prompt",
			"input_tokens":  int64(500),
			"output_tokens": int64(50),
		}),
	})

	all := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"limit": 10})
	if all["accountingStatus"] != "exact" {
		t.Fatalf("trace-correlated provider tasks should be exact: %+v", all)
	}
	tasks := toSliceAny(all["tasks"])
	if len(tasks) != 3 {
		t.Fatalf("Codex turns sharing a conversation were combined: %+v", tasks)
	}

	claude := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"traceId": "claude-trace"})
	claudeTasks := toSliceAny(claude["tasks"])
	if len(claudeTasks) != 1 {
		t.Fatalf("exact trace filter returned %+v", claudeTasks)
	}
	claudeTask := toMapAny(claudeTasks[0])
	if claudeTask["accountingStatus"] != "exact" || claudeTask["correlationStatus"] != "trace_correlated" || claudeTask["rootSpanName"] != "claude_code.interaction" {
		t.Fatalf("Claude trace correlation metadata is wrong: %+v", claudeTask)
	}
	if claudeTask["requestCount"] != float64(2) || toMapAny(claudeTask["usage"])["effectiveTotalTokens"] != float64(24) {
		t.Fatalf("Claude judge usage was included or requests were lost: %+v", claudeTask)
	}
	claudeUsage := toMapAny(claudeTask["usage"])
	if claudeUsage["providerTotalTokens"] != float64(24) || claudeUsage["reasoningOutputTokens"] != float64(1) {
		t.Fatalf("Claude provider total or reasoning breakdown was lost: %+v", claudeUsage)
	}
	if skills := toSliceAny(claudeTask["skillNames"]); len(skills) != 1 || skills[0] != "otel-audit" {
		t.Fatalf("Claude skill marker was not retained: %+v", skills)
	}

	zero := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"taskId": "codex-turn-2"})
	zeroTask := toMapAny(toSliceAny(zero["tasks"])[0])
	if zeroTask["status"] != "measured" || zeroTask["accountingStatus"] != "exact" || toMapAny(zeroTask["usage"])["effectiveTotalTokens"] != float64(0) {
		t.Fatalf("trace-correlated explicit zero was not exact: %+v", zeroTask)
	}

	conversation := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "shared-thread"})
	conversationTasks := toSliceAny(conversation["tasks"])
	if len(conversationTasks) != 2 || conversation["accountingStatus"] != "exact" || toMapAny(conversation["usage"])["effectiveTotalTokens"] != float64(15) {
		t.Fatalf("Codex conversation filter returned the wrong exact task total: %+v", conversation)
	}
	threadAlias := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"threadId": "shared-thread"})
	threadAliasTasks := toSliceAny(threadAlias["tasks"])
	if len(threadAliasTasks) != 2 || threadAlias["accountingStatus"] != "exact" || toMapAny(threadAlias["usage"])["effectiveTotalTokens"] != float64(15) {
		t.Fatalf("Codex threadId alias returned the wrong exact task total: %+v", threadAlias)
	}
	missingConversation := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "missing"})
	if missingConversation["measurementSource"] != "none" || len(toSliceAny(missingConversation["tasks"])) != 0 || len(toSliceAny(missingConversation["traces"])) != 0 {
		t.Fatalf("missing conversation filter fell back to unrelated spans: %+v", missingConversation)
	}
	missingThreadAlias := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"threadId": "missing"})
	if missingThreadAlias["measurementSource"] != "none" || len(toSliceAny(missingThreadAlias["tasks"])) != 0 || len(toSliceAny(missingThreadAlias["traces"])) != 0 {
		t.Fatalf("missing threadId alias fell back to unrelated spans: %+v", missingThreadAlias)
	}

	bySkill := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"skillName": "otel-audit"})
	if skillTasks := toSliceAny(bySkill["tasks"]); len(skillTasks) != 1 || toMapAny(skillTasks[0])["traceId"] != "claude-trace" {
		t.Fatalf("skill filter returned the wrong tasks: %+v", skillTasks)
	}
}

func TestToolsCallTokenUsageOverviewAggregatesAllMatchingTasksBeforeLimitingRows(t *testing.T) {
	for _, test := range []struct {
		name string
		args map[string]any
	}{
		{name: "conversation", args: map[string]any{"conversationId": "limit-thread"}},
		{name: "repository", args: map[string]any{"repositoryName": "limit-repo"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			s := store.New()
			now := time.Now().UTC()
			spans := make([]store.Span, 21)
			for index := range spans {
				spans[index] = store.Span{
					TraceID:   fmt.Sprintf("limit-trace-%02d", index),
					SpanID:    fmt.Sprintf("limit-turn-%02d", index),
					Name:      "session_task.turn",
					StartTime: now.Add(time.Duration(index) * time.Millisecond),
					EndTime:   now.Add(time.Duration(index+1) * time.Millisecond),
					Attributes: map[string]any{
						"thread.id":                           "limit-thread",
						"turn.id":                             fmt.Sprintf("limit-turn-%02d", index),
						"cwd":                                 "/work/limit-repo",
						"codex.turn.token_usage.total_tokens": int64(1),
					},
					Resource: store.Resource{ServiceName: "codex-app-server"},
				}
			}
			s.AddSpansForConnection("codex", spans)

			data := callTokenUsageOverview(t, NewDispatcher(s), test.args)
			if tasks := toSliceAny(data["tasks"]); len(tasks) != 20 {
				t.Fatalf("default returned task limit = %d, want 20: %+v", len(tasks), data)
			}
			if total := toMapAny(data["usage"])["effectiveTotalTokens"]; total != float64(21) {
				t.Fatalf("aggregate total was limited with returned rows: %+v", data)
			}
			if taskCount := toMapAny(data["coverage"])["taskCount"]; taskCount != float64(21) {
				t.Fatalf("aggregate coverage omitted matching tasks: %+v", data)
			}
		})
	}
}

func TestToolsCallTokenUsageOverviewReportsHighestUsageAcrossAllRetainedMatches(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	spans := make([]store.Span, 101)
	for index := range spans {
		total := int64(1)
		if index == 0 {
			total = 1000
		}
		spans[index] = store.Span{
			TraceID:   fmt.Sprintf("highest-usage-trace-%03d", index),
			SpanID:    fmt.Sprintf("highest-usage-turn-%03d", index),
			Name:      "session_task.turn",
			StartTime: now.Add(time.Duration(index) * time.Millisecond),
			EndTime:   now.Add(time.Duration(index+1) * time.Millisecond),
			Attributes: map[string]any{
				"thread.id":                           "highest-usage-thread",
				"turn.id":                             fmt.Sprintf("highest-usage-turn-%03d", index),
				"codex.turn.token_usage.total_tokens": total,
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		}
	}
	s.AddSpansForConnection("codex", spans)

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{
		"conversationId": "highest-usage-thread",
		"limit":          100,
	})
	if tasks := toSliceAny(data["tasks"]); len(tasks) != 100 {
		t.Fatalf("returned task count = %d, want 100: %+v", len(tasks), data)
	}
	highest := toMapAny(data["highestUsageTask"])
	if highest["taskId"] != "highest-usage-turn-000" ||
		toMapAny(highest["usage"])["effectiveTotalTokens"] != float64(1000) {
		t.Fatalf("highest retained task was omitted by the row limit: %+v", data)
	}
}

func TestToolsCallTokenUsageOverviewDoesNotRankUnknownUsageAsZero(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	s.AddSpansForConnection("codex", []store.Span{
		{
			TraceID: "known-ranking-trace", SpanID: "known-ranking-turn", Name: "session_task.turn",
			StartTime: now, EndTime: now.Add(time.Millisecond),
			Attributes: map[string]any{
				"thread.id": "ranking-thread", "turn.id": "known-ranking-turn",
				"codex.turn.token_usage.total_tokens": int64(10),
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		},
		{
			TraceID: "unknown-ranking-trace", SpanID: "unknown-ranking-turn", Name: "session_task.turn",
			StartTime: now.Add(time.Millisecond), EndTime: now.Add(2 * time.Millisecond),
			Attributes: map[string]any{
				"thread.id": "ranking-thread", "turn.id": "unknown-ranking-turn",
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		},
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{
		"conversationId": "ranking-thread",
	})
	if data["highestUsageTask"] != nil {
		t.Fatalf("unknown task was ranked as zero: %+v", data)
	}
}

func TestToolsCallTokenUsageOverviewMarksProviderTaskRingEvictionPartial(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	spans := make([]store.Span, store.DefaultProviderTaskCap+1)
	for index := range spans {
		spans[index] = store.Span{
			TraceID:   fmt.Sprintf("evicted-task-trace-%04d", index),
			SpanID:    fmt.Sprintf("evicted-task-turn-%04d", index),
			Name:      "session_task.turn",
			StartTime: now.Add(time.Duration(index) * time.Millisecond),
			EndTime:   now.Add(time.Duration(index+1) * time.Millisecond),
			Attributes: map[string]any{
				"thread.id":                           "evicted-task-thread",
				"turn.id":                             fmt.Sprintf("evicted-task-turn-%04d", index),
				"codex.turn.token_usage.total_tokens": int64(1),
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		}
	}
	s.AddSpansForConnection("codex", spans)
	noise := make([]store.Span, store.DefaultSpanCap+1)
	for index := range noise {
		noise[index] = store.Span{
			TraceID:    "evicted-task-noise",
			SpanID:     fmt.Sprintf("noise-%05d", index),
			Name:       "noise",
			StartTime:  now.Add(time.Minute),
			EndTime:    now.Add(time.Minute + time.Millisecond),
			Attributes: map[string]any{},
			Resource:   store.Resource{ServiceName: "noise"},
		}
	}
	s.AddSpansForConnection("noise", noise)

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{
		"conversationId": "evicted-task-thread",
		"limit":          100,
	})
	if data["accountingStatus"] != "partial" {
		t.Fatalf("evicted completed task history was presented as exact: %+v", data)
	}
	if total := toMapAny(data["usage"])["effectiveTotalTokens"]; total != float64(store.DefaultProviderTaskCap) {
		t.Fatalf("retained partial total = %v, want %d: %+v", total, store.DefaultProviderTaskCap, data)
	}
	if taskCount := toMapAny(data["coverage"])["taskCount"]; taskCount != float64(store.DefaultProviderTaskCap) {
		t.Fatalf("retained task coverage = %v, want %d: %+v", taskCount, store.DefaultProviderTaskCap, data)
	}
}

func TestToolsCallTokenUsageOverviewDoesNotCallBareTraceIDExact(t *testing.T) {
	s := store.New()
	s.AddLogsForConnection("provider", []store.LogRecord{{
		ID:        "codex-orphan",
		Timestamp: time.Now(),
		TraceID:   "missing-trace",
		Body:      "codex.sse_event",
		Attributes: map[string]any{
			"event.name":         "codex.sse_event",
			"event.kind":         "response.completed",
			"response.id":        "response-orphan",
			"turn.id":            "turn-orphan",
			"input_token_count":  int64(10),
			"output_token_count": int64(5),
			"tool_token_count":   int64(15),
		},
		Resource: store.Resource{ServiceName: "codex"},
	}})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"traceId": "missing-trace"})
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if data["accountingStatus"] != "uncorrelated" || task["accountingStatus"] != "uncorrelated" || task["correlationStatus"] != "trace_id" {
		t.Fatalf("bare trace ID was overstated as exact: %+v", data)
	}
}

func TestToolsCallTokenUsageOverviewDoesNotCorrelateGenericProviderTraceByConversation(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("application", []store.Span{{
		TraceID:   "generic-trace",
		SpanID:    "generic-root",
		Name:      "gen_ai.chat",
		StartTime: now,
		EndTime:   now.Add(10 * time.Millisecond),
		Attributes: map[string]any{
			"conversation.id":      "shared-conversation",
			"gen_ai.provider.name": "openai",
		},
		Resource: store.Resource{ServiceName: "openai-client"},
	}})
	s.AddLogsForConnection("provider", []store.LogRecord{{
		ID:        "codex-generic",
		Timestamp: now.Add(5 * time.Millisecond),
		Body:      "codex.sse_event",
		Attributes: map[string]any{
			"event.name":         "codex.sse_event",
			"event.kind":         "response.completed",
			"conversation.id":    "shared-conversation",
			"input_token_count":  int64(10),
			"output_token_count": int64(5),
		},
		Resource: store.Resource{ServiceName: "codex"},
	}})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"provider": "codex"})
	task := toMapAny(toSliceAny(data["tasks"])[0])
	_, hasTraceID := task["traceId"]
	if hasTraceID || task["correlationStatus"] != "provider_task" || task["accountingStatus"] != "uncorrelated" {
		t.Fatalf("generic provider trace was treated as an exact correlation: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewRequiresCompletedMatchingProviderTrace(t *testing.T) {
	t.Run("incomplete trace", func(t *testing.T) {
		s := store.New()
		now := time.Now()
		s.AddSpansForConnection("provider", []store.Span{{
			TraceID:      "claude-live",
			SpanID:       "llm-request",
			ParentSpanID: "pending-root",
			Name:         "claude_code.llm_request",
			StartTime:    now,
			EndTime:      now.Add(time.Millisecond),
			Attributes: map[string]any{
				"prompt.id": "prompt-live",
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}})
		s.AddLogsForConnection("provider", []store.LogRecord{{
			ID:        "claude-live-request",
			Timestamp: now.Add(time.Millisecond),
			TraceID:   "claude-live",
			Body:      "claude_code.api_request",
			Attributes: map[string]any{
				"event.name":            "api_request",
				"request_id":            "request-live",
				"prompt.id":             "prompt-live",
				"input_tokens":          int64(5),
				"cache_read_tokens":     int64(0),
				"cache_creation_tokens": int64(0),
				"output_tokens":         int64(2),
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}})

		data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"provider": "claude"})
		task := toMapAny(toSliceAny(data["tasks"])[0])
		if task["traceId"] != "claude-live" || task["traceComplete"] != false || task["correlationStatus"] != "trace_incomplete" || task["accountingStatus"] != "uncorrelated" {
			t.Fatalf("in-progress prompt was overstated as exact: %+v", task)
		}
	})

	t.Run("Claude completed trace with a missing request log", func(t *testing.T) {
		s := store.New()
		now := time.Now()
		span := func(spanID, parentID, name string, offset time.Duration) store.Span {
			return store.Span{
				TraceID: "claude-partial", SpanID: spanID, ParentSpanID: parentID, Name: name,
				StartTime: now.Add(offset), EndTime: now.Add(offset + time.Millisecond),
				Attributes: map[string]any{"prompt.id": "prompt-partial", "session.id": "session-partial"},
				Resource:   store.Resource{ServiceName: "claude-code"},
			}
		}
		s.AddSpansForConnection("provider", []store.Span{
			span("interaction", "", "claude_code.interaction", 0),
			span("request-1", "interaction", "claude_code.llm_request", time.Millisecond),
			span("request-2", "interaction", "claude_code.llm_request", 2*time.Millisecond),
		})
		s.AddLogsForConnection("provider", []store.LogRecord{{
			ID:        "claude-partial-request",
			Timestamp: now.Add(time.Millisecond),
			TraceID:   "claude-partial",
			SpanID:    "request-1",
			Body:      "claude_code.api_request",
			Attributes: map[string]any{
				"event.name":            "api_request",
				"request_id":            "request-partial",
				"prompt.id":             "prompt-partial",
				"session.id":            "session-partial",
				"input_tokens":          int64(5),
				"cache_read_tokens":     int64(0),
				"cache_creation_tokens": int64(0),
				"output_tokens":         int64(2),
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}})

		data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"provider": "claude"})
		task := toMapAny(toSliceAny(data["tasks"])[0])
		if task["traceComplete"] != true || task["correlationStatus"] != "trace_usage_mismatch" || task["accountingStatus"] != "uncorrelated" {
			t.Fatalf("partial retained Claude logs were overstated as exact: %+v", task)
		}
	})

	t.Run("Codex trace without a turn total", func(t *testing.T) {
		s := store.New()
		now := time.Now()
		s.AddSpansForConnection("provider", []store.Span{{
			TraceID:    "codex-no-total",
			SpanID:     "task-boundary",
			Name:       "session_task.turn",
			StartTime:  now,
			EndTime:    now.Add(time.Millisecond),
			Attributes: map[string]any{"turn.id": "turn-no-total"},
			Resource:   store.Resource{ServiceName: "codex"},
		}})
		s.AddLogsForConnection("provider", []store.LogRecord{{
			ID:        "codex-no-total-event",
			Timestamp: now.Add(time.Millisecond),
			TraceID:   "codex-no-total",
			Body:      "codex.sse_event",
			Attributes: map[string]any{
				"event.name":         "codex.sse_event",
				"event.kind":         "response.completed",
				"turn.id":            "turn-no-total",
				"input_token_count":  int64(10),
				"output_token_count": int64(5),
				"tool_token_count":   int64(15),
			},
			Resource: store.Resource{ServiceName: "codex"},
		}})

		data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"provider": "codex"})
		task := toMapAny(toSliceAny(data["tasks"])[0])
		if task["traceComplete"] != true || task["correlationStatus"] != "trace_usage_mismatch" || task["accountingStatus"] != "uncorrelated" {
			t.Fatalf("Codex usage without a turn total was overstated as exact: %+v", task)
		}
	})

	t.Run("provider mismatch", func(t *testing.T) {
		s := store.New()
		now := time.Now()
		s.AddSpansForConnection("provider", []store.Span{{
			TraceID:    "claude-trace",
			SpanID:     "claude-root",
			Name:       "claude_code.interaction",
			StartTime:  now,
			EndTime:    now.Add(time.Millisecond),
			Attributes: map[string]any{"prompt.id": "claude-prompt"},
			Resource:   store.Resource{ServiceName: "claude-code"},
		}})
		s.AddLogsForConnection("provider", []store.LogRecord{{
			ID:        "codex-mismatch",
			Timestamp: now.Add(time.Millisecond),
			TraceID:   "claude-trace",
			Body:      "codex.sse_event",
			Attributes: map[string]any{
				"event.name":         "codex.sse_event",
				"event.kind":         "response.completed",
				"turn.id":            "codex-turn",
				"input_token_count":  int64(10),
				"output_token_count": int64(5),
			},
			Resource: store.Resource{ServiceName: "codex"},
		}})

		data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"provider": "codex"})
		task := toMapAny(toSliceAny(data["tasks"])[0])
		if task["traceComplete"] != true || task["correlationStatus"] != "trace_provider_mismatch" || task["accountingStatus"] != "uncorrelated" {
			t.Fatalf("mismatched provider trace was overstated as exact: %+v", task)
		}
	})
}

func TestToolsCallTokenUsageOverviewCorrelatesRealCodexTraceShapeAndCumulativeEvents(t *testing.T) {
	s := store.New()
	now := time.Date(2026, time.August, 25, 12, 0, 0, 0, time.UTC)
	turnID := "01a03bfa-6ee9-7f53-af1e-6e18393ad488"
	conversationID := "01a03bfa-6daa-7310-9644-76207e3dd6cb"
	s.AddSpansForConnection("codex", []store.Span{
		{
			TraceID:    "main-trace",
			SpanID:     "rpc-root",
			Name:       "turn/start",
			StartTime:  now,
			EndTime:    now.Add(time.Millisecond),
			Attributes: map[string]any{"turn.id": turnID},
			Resource:   store.Resource{ServiceName: "Codex Desktop"},
		},
		{
			TraceID:      "main-trace",
			SpanID:       "task-boundary",
			ParentSpanID: "rpc-root",
			Name:         "session_task.turn",
			StartTime:    now,
			EndTime:      now.Add(5 * time.Second),
			Attributes: map[string]any{
				"thread.id":                            conversationID,
				"turn.id":                              turnID,
				"codex.turn.token_usage.input_tokens":  int64(20005),
				"codex.turn.token_usage.output_tokens": int64(16),
				"codex.turn.token_usage.total_tokens":  int64(20021),
			},
			Resource: store.Resource{ServiceName: "Codex Desktop"},
		},
		{
			TraceID:    "wrapper-trace",
			SpanID:     "wrapper-root",
			Name:       "codex.exec",
			StartTime:  now,
			EndTime:    now.Add(6 * time.Second),
			Attributes: map[string]any{"thread.id": conversationID, "turn.id": turnID},
			Resource:   store.Resource{ServiceName: "Codex Desktop"},
		},
	})
	providerLog := func(id string, offset time.Duration, input, cached, output, reasoning, total int64) store.LogRecord {
		return store.LogRecord{
			ID:        id,
			Timestamp: time.Unix(0, 0),
			Attributes: map[string]any{
				"event.name":            "codex.sse_event",
				"event.kind":            "response.completed",
				"event.timestamp":       now.Add(offset).Format(time.RFC3339Nano),
				"conversation.id":       conversationID,
				"model":                 "gpt-5.4-mini",
				"input_token_count":     input,
				"cached_token_count":    cached,
				"output_token_count":    output,
				"reasoning_token_count": reasoning,
				"tool_token_count":      total,
			},
			Resource: store.Resource{ServiceName: "Codex Desktop"},
		}
	}
	s.AddLogsForConnection("codex", []store.LogRecord{
		providerLog("startup", 3*time.Second, 8991, 0, 0, 0, 8991),
		providerLog("turn-total", 4*time.Second, 20005, 3456, 16, 9, 20021),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"provider": "codex"})
	if data["accountingStatus"] != "exact" || data["status"] != "measured" {
		t.Fatalf("real Codex trace shape was not exact: %+v", data)
	}
	task := toMapAny(toSliceAny(data["tasks"])[0])
	usage := toMapAny(task["usage"])
	if task["taskId"] != turnID || task["traceId"] != "main-trace" || task["rootSpanName"] != "session_task.turn" || task["requestCount"] != float64(1) || task["providerEventCount"] != float64(2) || task["traceComplete"] != true {
		t.Fatalf("real Codex trace identity or event reconciliation was lost: %+v", task)
	}
	if usage["inputTokens"] != float64(20005) || usage["providerTotalTokens"] != float64(20021) || usage["effectiveTotalTokens"] != float64(20021) {
		t.Fatalf("Codex cumulative/startup events were double counted: %+v", usage)
	}
}

func TestToolsCallTokenUsageOverviewKeepsCodexTurnsInOneTraceSeparate(t *testing.T) {
	s := store.New()
	now := time.Date(2026, time.August, 26, 12, 0, 0, 0, time.UTC)
	conversationID := "shared-codex-thread"
	span := func(spanID, parentID, name string, start, end time.Duration, attrs map[string]any) store.Span {
		return store.Span{
			TraceID:      "shared-codex-trace",
			SpanID:       spanID,
			ParentSpanID: parentID,
			Name:         name,
			StartTime:    now.Add(start),
			EndTime:      now.Add(end),
			Attributes:   attrs,
			Resource:     store.Resource{ServiceName: "codex-app-server"},
		}
	}
	s.AddSpansForConnection("codex", []store.Span{
		span("session", "", "session_loop", 0, 12*time.Second, map[string]any{"thread.id": conversationID}),
		span("turn-1-boundary", "session", "session_task.turn", time.Second, 5*time.Second, map[string]any{
			"thread.id":                            conversationID,
			"turn.id":                              "turn-1",
			"codex.turn.token_usage.input_tokens":  int64(90),
			"codex.turn.token_usage.output_tokens": int64(10),
			"codex.turn.token_usage.total_tokens":  int64(100),
		}),
		span("request-1", "turn-1-boundary", "codex.response", 2*time.Second, 4*time.Second, nil),
		span("turn-2-boundary", "session", "session_task.turn", 6*time.Second, 10*time.Second, map[string]any{
			"thread.id":                            conversationID,
			"turn.id":                              "turn-2",
			"codex.turn.token_usage.input_tokens":  int64(180),
			"codex.turn.token_usage.output_tokens": int64(20),
			"codex.turn.token_usage.total_tokens":  int64(200),
		}),
		span("request-2", "turn-2-boundary", "codex.response", 7*time.Second, 9*time.Second, nil),
	})
	providerLog := func(id, spanID string, timestamp time.Duration, input, output, total int64) store.LogRecord {
		return store.LogRecord{
			ID:        id,
			Timestamp: now.Add(timestamp),
			TraceID:   "shared-codex-trace",
			SpanID:    spanID,
			Attributes: map[string]any{
				"event.name":         "codex.sse_event",
				"event.kind":         "response.completed",
				"conversation.id":    conversationID,
				"input_token_count":  input,
				"output_token_count": output,
				"tool_token_count":   total,
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		}
	}
	s.AddLogsForConnection("codex", []store.LogRecord{
		providerLog("turn-1-usage", "request-1", 3*time.Second, 90, 10, 100),
		providerLog("turn-2-usage", "request-2", 8*time.Second, 180, 20, 200),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{
		"provider":       "codex",
		"conversationId": conversationID,
	})
	if data["accountingStatus"] != "exact" || toMapAny(data["usage"])["effectiveTotalTokens"] != float64(300) {
		t.Fatalf("same-trace Codex turns were not accounted independently: %+v", data)
	}
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 2 {
		t.Fatalf("same-trace Codex turns were merged or duplicated: %+v", tasks)
	}
	for index, want := range []struct {
		turnID string
		total  float64
	}{{turnID: "turn-2", total: 200}, {turnID: "turn-1", total: 100}} {
		task := toMapAny(tasks[index])
		if task["taskId"] != want.turnID || task["turnId"] != want.turnID || task["traceId"] != "shared-codex-trace" ||
			task["providerEventCount"] != float64(1) || task["requestCount"] != float64(1) || task["accountingStatus"] != "exact" {
			t.Fatalf("Codex turn %d identity or coverage is wrong: %+v", index, task)
		}
		if got := toMapAny(task["usage"])["effectiveTotalTokens"]; got != want.total {
			t.Fatalf("Codex turn %s total = %#v, want %v", want.turnID, got, want.total)
		}
	}
}

func TestToolsCallTokenUsageOverviewUsesCodexTaskSpanWhenRetainedLogsDoNotReconcile(t *testing.T) {
	s := store.New()
	now := time.Date(2026, time.August, 26, 10, 0, 0, 0, time.UTC)
	s.AddSpansForConnection("codex", []store.Span{{
		TraceID:   "codex-mismatch-trace",
		SpanID:    "task-boundary",
		Name:      "session_task.turn",
		StartTime: now,
		EndTime:   now.Add(5 * time.Second),
		Attributes: map[string]any{
			"thread.id":                           "codex-mismatch-thread",
			"turn.id":                             "codex-mismatch-turn",
			"model":                               "gpt-5.6",
			"codex.turn.token_usage.input_tokens": int64(100),
			"codex.turn.token_usage.cached_input_tokens":      int64(80),
			"codex.turn.token_usage.cache_write_input_tokens": int64(5),
			"codex.turn.token_usage.output_tokens":            int64(20),
			"codex.turn.token_usage.reasoning_output_tokens":  int64(7),
			"codex.turn.token_usage.total_tokens":             int64(120),
		},
		Resource: store.Resource{ServiceName: "codex-app-server"},
	}})
	providerLog := func(id string, offset time.Duration, attrs map[string]any) store.LogRecord {
		attrs["event.name"] = "codex.sse_event"
		attrs["event.kind"] = "response.completed"
		attrs["conversation.id"] = "codex-mismatch-thread"
		return store.LogRecord{
			ID:         id,
			Timestamp:  now.Add(offset),
			Attributes: attrs,
			Resource:   store.Resource{ServiceName: "codex-app-server"},
		}
	}
	s.AddLogsForConnection("codex", []store.LogRecord{
		providerLog("request-1", time.Second, map[string]any{
			"response.id":        "response-1",
			"input_token_count":  int64(10),
			"output_token_count": int64(2),
			"tool_token_count":   int64(12),
		}),
		providerLog("metadata-companion", 2*time.Second, map[string]any{}),
		providerLog("request-2", 2*time.Second, map[string]any{
			"response.id":        "response-2",
			"input_token_count":  int64(20),
			"output_token_count": int64(3),
			"tool_token_count":   int64(23),
		}),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{
		"threadId": "codex-mismatch-thread",
		"provider": "codex",
	})
	if data["measurementSource"] != "provider_telemetry" || data["status"] != "measured" || data["accountingStatus"] != "exact" {
		t.Fatalf("Codex task-span reconciliation was not exact: %+v", data)
	}
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["measurementSource"] != "codex_task_span" || task["requestCount"] != float64(1) || task["providerEventCount"] != float64(3) || task["correlationStatus"] != "trace_correlated" {
		t.Fatalf("Codex reconciliation diagnostics are wrong: %+v", task)
	}
	usage := toMapAny(task["usage"])
	for field, want := range map[string]float64{
		"inputTokens":              100,
		"cachedInputTokens":        80,
		"cacheCreationInputTokens": 5,
		"outputTokens":             20,
		"reasoningOutputTokens":    7,
		"providerTotalTokens":      120,
		"derivedTotalTokens":       120,
		"effectiveTotalTokens":     120,
	} {
		if got := usage[field]; got != want {
			t.Fatalf("Codex %s = %#v, want %v: %+v", field, got, want, usage)
		}
	}
}

func TestToolsCallTokenUsageOverviewUsesRetainedCodexTaskAfterGenericSpanEviction(t *testing.T) {
	s := store.New()
	now := time.Date(2026, time.August, 26, 11, 0, 0, 0, time.UTC)
	s.AddSpansForConnection("codex", []store.Span{{
		TraceID:   "retained-codex-trace",
		SpanID:    "retained-boundary",
		Name:      "session_task.turn",
		StartTime: now,
		EndTime:   now.Add(time.Second),
		Attributes: map[string]any{
			"thread.id":                           "retained-codex-thread",
			"turn.id":                             "retained-codex-turn",
			"codex.turn.token_usage.input_tokens": int64(40),
			"codex.turn.token_usage.cached_input_tokens":         int64(30),
			"codex.turn.token_usage.cache_creation_input_tokens": int64(2),
			"codex.turn.token_usage.output_tokens":               int64(6),
			"codex.turn.token_usage.reasoning_output_tokens":     int64(1),
			"codex.turn.token_usage.total_tokens":                int64(46),
		},
		Resource: store.Resource{ServiceName: "codex-app-server"},
	}})
	noise := make([]store.Span, store.DefaultSpanCap+1)
	for index := range noise {
		noise[index] = store.Span{
			TraceID:   "noise-trace",
			SpanID:    fmt.Sprintf("noise-%d", index),
			Name:      "noise",
			StartTime: now.Add(2 * time.Second),
			EndTime:   now.Add(3 * time.Second),
		}
	}
	s.AddSpansForConnection("noise", noise)
	if detail := s.Trace("retained-codex-trace", 1); detail != nil {
		t.Fatal("fixture did not evict the completed task from the generic span ring")
	}

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"threadId": "retained-codex-thread"})
	if data["measurementSource"] != "provider_spans" || data["accountingStatus"] != "exact" {
		t.Fatalf("retained provider task was not queryable after raw span eviction: %+v", data)
	}
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["taskId"] != "retained-codex-turn" || task["providerEventCount"] != float64(0) || task["traceComplete"] != true {
		t.Fatalf("retained provider task identity is wrong: %+v", task)
	}
	if got := toMapAny(task["usage"])["effectiveTotalTokens"]; got != float64(46) {
		t.Fatalf("retained provider task total = %#v, want 46", got)
	}
}

func TestToolsCallTokenUsageOverviewUsesLateClaudeRequestAfterGenericSpanEviction(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	s.AddSpansForConnection("claude", []store.Span{{
		TraceID: "late-claude-trace", SpanID: "interaction", Name: "claude_code.interaction",
		StartTime: now, EndTime: now.Add(10 * time.Millisecond),
		Attributes: map[string]any{"prompt.id": "late-claude-prompt", "session.id": "late-claude-session"},
		Resource:   store.Resource{ServiceName: "claude-code"},
	}})
	s.AddSpansForConnection("claude", []store.Span{{
		TraceID: "late-claude-trace", SpanID: "request", ParentSpanID: "interaction", Name: "claude_code.llm_request",
		StartTime: now.Add(time.Millisecond), EndTime: now.Add(2 * time.Millisecond),
		Attributes: map[string]any{
			"gen_ai.provider.name":        "anthropic",
			"input_tokens":                int64(5),
			"cache_read_input_tokens":     int64(0),
			"cache_creation_input_tokens": int64(0),
			"output_tokens":               int64(2),
		},
		Resource: store.Resource{ServiceName: "claude-code"},
	}})
	noise := make([]store.Span, store.DefaultSpanCap+1)
	for index := range noise {
		noise[index] = store.Span{
			TraceID: "late-claude-noise", SpanID: fmt.Sprintf("noise-%05d", index), Name: "noise",
			StartTime: now.Add(time.Second), EndTime: now.Add(time.Second + time.Millisecond),
		}
	}
	s.AddSpansForConnection("noise", noise)

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "late-claude-session"})
	if data["accountingStatus"] != "partial" {
		t.Fatalf("late Claude request subtotal was not retained as partial after generic span eviction: %+v", data)
	}
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["measurementSource"] != "claude_request_spans" || task["correlationStatus"] != "trace_request_window_incomplete" || toMapAny(task["usage"])["effectiveTotalTokens"] != float64(7) {
		t.Fatalf("late Claude request was not retained in the completed task snapshot: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewKeepsClaudeRequestSpanSubtotalPartial(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	interaction := store.Span{
		TraceID: "out-of-order-claude-trace", SpanID: "interaction", Name: "claude_code.interaction",
		StartTime: now, EndTime: now.Add(10 * time.Millisecond),
		Attributes: map[string]any{"prompt.id": "out-of-order-prompt", "session.id": "out-of-order-session"},
		Resource:   store.Resource{ServiceName: "claude-code"},
	}
	request := func(spanID string, offset time.Duration, input, output int64) store.Span {
		return store.Span{
			TraceID: "out-of-order-claude-trace", SpanID: spanID, ParentSpanID: "interaction", Name: "claude_code.llm_request",
			StartTime: now.Add(offset), EndTime: now.Add(offset + time.Millisecond),
			Attributes: map[string]any{
				"gen_ai.provider.name":        "anthropic",
				"input_tokens":                input,
				"cache_read_input_tokens":     int64(0),
				"cache_creation_input_tokens": int64(0),
				"output_tokens":               output,
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}
	}

	s.AddSpansForConnection("claude", []store.Span{interaction, request("request-1", time.Millisecond, 5, 2)})
	first := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "out-of-order-session"})
	firstTask := toMapAny(toSliceAny(first["tasks"])[0])
	if first["accountingStatus"] != "partial" || firstTask["accountingStatus"] != "partial" {
		t.Fatalf("completed boundary treated the currently retained child subtotal as exact: %+v", first)
	}
	if firstTask["status"] != "measured" || toMapAny(firstTask["usage"])["effectiveTotalTokens"] != float64(7) {
		t.Fatalf("known first-request subtotal was not retained as measured evidence: %+v", firstTask)
	}

	s.AddSpansForConnection("claude", []store.Span{request("request-2", 3*time.Millisecond, 3, 1)})
	second := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "out-of-order-session"})
	secondTask := toMapAny(toSliceAny(second["tasks"])[0])
	if second["accountingStatus"] != "partial" || secondTask["requestCount"] != float64(2) || toMapAny(secondTask["usage"])["effectiveTotalTokens"] != float64(11) {
		t.Fatalf("late child request was not added as a still-partial subtotal: %+v", second)
	}

	metric := func(tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", IsMonotonic: true,
			StartTime: now, Timestamp: now.Add(20 * time.Millisecond), Value: value,
			Attributes: map[string]any{"session.id": "out-of-order-session", "type": tokenType},
			Resource:   store.Resource{ServiceName: "claude-code"},
			Scope:      store.Scope{Name: "com.anthropic.claude_code"},
		}
	}
	s.AddMetricsForConnection("claude", []store.MetricDataPoint{
		metric("input", 8),
		metric("cacheRead", 0),
		metric("cacheCreation", 0),
		metric("output", 3),
	})
	exact := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "out-of-order-session"})
	exactTask := toMapAny(toSliceAny(exact["tasks"])[0])
	if exact["accountingStatus"] != "exact" || exact["measurementSource"] != "provider_metrics" || exactTask["providerMetricCount"] != float64(4) || toMapAny(exactTask["usage"])["effectiveTotalTokens"] != float64(11) {
		t.Fatalf("exact cumulative metrics did not replace the partial child-span subtotal: %+v", exact)
	}
}

func TestToolsCallTokenUsageOverviewUsesLatestReexportedProviderSpanOnce(t *testing.T) {
	s := store.New()
	now := time.Now()
	boundary := func(total int64, timestamp time.Time) store.Span {
		return store.Span{
			TraceID: "reexported-codex-trace", SpanID: "reexported-boundary", Name: "session_task.turn",
			StartTime: timestamp, EndTime: timestamp.Add(time.Millisecond),
			Attributes: map[string]any{
				"thread.id":                           "reexported-thread",
				"turn.id":                             "reexported-turn",
				"codex.turn.token_usage.total_tokens": total,
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		}
	}
	s.AddSpansForConnection("codex", []store.Span{boundary(10, now)})
	s.AddSpansForConnection("codex", []store.Span{boundary(30, now.Add(time.Second))})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"threadId": "reexported-thread"})
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 1 {
		t.Fatalf("re-exported provider boundary produced %d tasks: %+v", len(tasks), data)
	}
	task := toMapAny(tasks[0])
	if got := toMapAny(task["usage"])["effectiveTotalTokens"]; got != float64(30) {
		t.Fatalf("re-exported provider boundary total = %#v, want 30: %+v", got, task)
	}
}

func TestToolsCallTokenUsageOverviewDistinguishesZeroMissingAndMalformedTaskSpans(t *testing.T) {
	s := store.New()
	now := time.Now()
	span := func(traceID, turnID string, offset time.Duration, usage map[string]any) store.Span {
		attrs := map[string]any{"thread.id": "coverage-thread", "turn.id": turnID}
		for key, value := range usage {
			attrs[key] = value
		}
		return store.Span{
			TraceID: traceID, SpanID: traceID + "-boundary", Name: "session_task.turn",
			StartTime: now.Add(offset), EndTime: now.Add(offset + time.Millisecond),
			Attributes: attrs, Resource: store.Resource{ServiceName: "codex-app-server"},
		}
	}
	s.AddSpansForConnection("codex", []store.Span{
		span("zero-trace", "zero-turn", 0, map[string]any{
			"codex.turn.token_usage.input_tokens":  int64(0),
			"codex.turn.token_usage.output_tokens": int64(0),
			"codex.turn.token_usage.total_tokens":  int64(0),
		}),
		span("missing-trace", "missing-turn", time.Second, nil),
		span("malformed-trace", "malformed-turn", 2*time.Second, map[string]any{
			"codex.turn.token_usage.total_tokens": "not-a-count",
		}),
	})

	for _, test := range []struct {
		turnID string
		status string
		total  any
	}{
		{turnID: "zero-turn", status: "measured", total: float64(0)},
		{turnID: "missing-turn", status: "absent", total: nil},
		{turnID: "malformed-turn", status: "unrecognized", total: nil},
	} {
		t.Run(test.turnID, func(t *testing.T) {
			data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"taskId": test.turnID})
			task := toMapAny(toSliceAny(data["tasks"])[0])
			if task["status"] != test.status || toMapAny(task["usage"])["effectiveTotalTokens"] != test.total {
				t.Fatalf("unexpected task-span coverage: %+v", task)
			}
			wantAccounting := "unknown"
			if test.status == "measured" {
				wantAccounting = "exact"
			}
			if task["accountingStatus"] != wantAccounting {
				t.Fatalf("accountingStatus = %#v, want %q: %+v", task["accountingStatus"], wantAccounting, task)
			}
		})
	}
}

func TestToolsCallTokenUsageOverviewUsesClaudeRequestSpansAndExcludesJudgeUsage(t *testing.T) {
	s := store.New()
	now := time.Now()
	span := func(spanID, parentID, name string, offset time.Duration, attrs map[string]any) store.Span {
		return store.Span{
			TraceID: "claude-span-trace", SpanID: spanID, ParentSpanID: parentID, Name: name,
			StartTime: now.Add(offset), EndTime: now.Add(offset + time.Millisecond),
			Attributes: attrs, Resource: store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddSpansForConnection("claude", []store.Span{
		span("interaction", "", "claude_code.interaction", 0, map[string]any{
			"prompt.id": "claude-span-prompt", "session.id": "claude-span-session", "skill.name": "otel-audit",
		}),
		span("request", "interaction", "claude_code.llm_request", time.Millisecond, map[string]any{
			"gen_ai.provider.name": "anthropic", "model": "claude-sonnet-4-6",
			"input_tokens": int64(5), "cache_read_input_tokens": int64(10), "cache_creation_input_tokens": int64(2),
			"output_tokens": int64(4), "thinking_tokens": int64(1),
		}),
		span("evaluation", "interaction", "rubric", 2*time.Millisecond, map[string]any{"gen_ai.evaluation.name": "rubric"}),
		span("judge", "evaluation", "claude_code.llm_request", 3*time.Millisecond, map[string]any{
			"gen_ai.provider.name": "anthropic", "model": "judge-model", "skill.name": "rubric-grader", "input_tokens": int64(500), "output_tokens": int64(50),
		}),
	})
	for _, tokenType := range []string{"input", "cacheRead", "cacheCreation", "output"} {
		s.AddMetricsForConnection("claude", []store.MetricDataPoint{{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "delta", Value: 100,
			IsMonotonic: true, Timestamp: now.Add(4 * time.Millisecond), StartTime: now,
			Attributes: map[string]any{
				"session.id": "claude-span-session", "model": "claude-sonnet-4-6", "query_source": "main", "type": tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"}, Scope: store.Scope{Name: "com.anthropic.claude_code"},
		}})
	}

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{
		"conversationId": "claude-span-session",
		"provider":       "claude",
	})
	if data["measurementSource"] != "provider_spans" || data["accountingStatus"] != "partial" {
		t.Fatalf("Claude request-span subtotal did not remain partial: %+v", data)
	}
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["measurementSource"] != "claude_request_spans" || task["requestCount"] != float64(1) || task["correlationStatus"] != "trace_request_window_incomplete" {
		t.Fatalf("Claude request-span metadata is wrong: %+v", task)
	}
	if task["providerMetricCount"] != float64(0) {
		t.Fatalf("Claude metrics were added to richer span accounting: %+v", task)
	}
	usage := toMapAny(task["usage"])
	if usage["inputTokens"] != float64(17) || usage["cachedInputTokens"] != float64(10) || usage["cacheCreationInputTokens"] != float64(2) || usage["outputTokens"] != float64(4) || usage["reasoningOutputTokens"] != float64(1) || usage["effectiveTotalTokens"] != float64(21) {
		t.Fatalf("Claude cache/reasoning normalization or judge exclusion is wrong: %+v", usage)
	}
	if models := toSliceAny(task["modelNames"]); len(models) != 1 || models[0] != "claude-sonnet-4-6" {
		t.Fatalf("judge model leaked into agent task metadata: %+v", models)
	}
	if skills := toSliceAny(task["skillNames"]); len(skills) != 1 || skills[0] != "otel-audit" {
		t.Fatalf("judge skill leaked into agent task metadata: %+v", skills)
	}
}

func TestToolsCallTokenUsageOverviewExcludesNestedEvaluationTaskBoundariesAndMetadata(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	span := func(spanID, parentID, name string, offset time.Duration, attrs map[string]any) store.Span {
		return store.Span{
			TraceID:      "nested-evaluation-trace",
			SpanID:       spanID,
			ParentSpanID: parentID,
			Name:         name,
			StartTime:    now.Add(offset),
			EndTime:      now.Add(offset + time.Millisecond),
			Attributes:   attrs,
			Resource:     store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddSpansForConnection("claude", []store.Span{
		span("agent", "", "claude_code.interaction", 0, map[string]any{
			"gen_ai.provider.name": "anthropic",
			"prompt.id":            "agent-prompt",
			"input_tokens":         int64(2),
			"output_tokens":        int64(1),
			"total_tokens":         int64(3),
		}),
		span("evaluation-task", "agent", "evaluation", time.Millisecond, map[string]any{
			"gen_ai.evaluation.name": "rubric",
		}),
		span("judge-boundary", "evaluation-task", "claude_code.interaction", 2*time.Millisecond, map[string]any{
			"gen_ai.provider.name": "anthropic",
			"prompt.id":            "judge-prompt",
			"session.id":           "judge-session",
			"input_tokens":         int64(50),
			"output_tokens":        int64(5),
			"total_tokens":         int64(55),
		}),
		span("evaluation-metadata", "agent", "evaluation", 3*time.Millisecond, map[string]any{
			"gen_ai.evaluation.name": "rubric",
		}),
		span("judge-request", "evaluation-metadata", "claude_code.llm_request", 4*time.Millisecond, map[string]any{
			"gen_ai.provider.name": "anthropic",
			"session.id":           "judge-metadata-session",
			"input_tokens":         int64(500),
			"output_tokens":        int64(50),
		}),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"traceId": "nested-evaluation-trace"})
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 1 {
		t.Fatalf("evaluation-only native task boundary leaked into agent accounting: %+v", tasks)
	}
	task := toMapAny(tasks[0])
	if task["taskId"] != "agent-prompt" || task["conversationId"] != nil {
		t.Fatalf("evaluation-only identity leaked into agent task metadata: %+v", task)
	}
	if usage := toMapAny(task["usage"]); usage["effectiveTotalTokens"] != float64(3) {
		t.Fatalf("evaluation-only usage leaked into agent task accounting: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewExcludesSpanlessLogWithEvaluationPromptIdentity(t *testing.T) {
	s := store.New()
	now := s.ProviderUsageLogUnavailableThrough().Add(time.Second)
	span := func(spanID, parentID, name string, offset, duration time.Duration, attrs map[string]any) store.Span {
		return store.Span{
			TraceID:      "spanless-evaluation-log-trace",
			SpanID:       spanID,
			ParentSpanID: parentID,
			Name:         name,
			StartTime:    now.Add(offset),
			EndTime:      now.Add(offset + duration),
			Attributes:   attrs,
			Resource:     store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddSpansForConnection("claude", []store.Span{
		span("agent", "", "claude_code.interaction", 0, 10*time.Millisecond, map[string]any{
			"gen_ai.provider.name": "anthropic",
			"prompt.id":            "agent-prompt",
			"session.id":           "agent-session",
		}),
		span("evaluation", "agent", "evaluation", time.Millisecond, 8*time.Millisecond, map[string]any{
			"gen_ai.evaluation.name": "rubric",
		}),
		span("judge", "evaluation", "claude_code.interaction", 2*time.Millisecond, 6*time.Millisecond, map[string]any{
			"gen_ai.provider.name": "anthropic",
			"prompt.id":            "judge-prompt",
			"session.id":           "agent-session",
		}),
	})
	s.AddLogsForConnection("claude", []store.LogRecord{
		{
			ID:        "spanless-agent-request",
			Timestamp: now.Add(2 * time.Millisecond),
			TraceID:   "spanless-evaluation-log-trace",
			Body:      "claude_code.api_request",
			Attributes: map[string]any{
				"event.name":            "api_request",
				"request_id":            "spanless-agent-request",
				"prompt.id":             "agent-prompt",
				"session.id":            "agent-session",
				"input_tokens":          int64(2),
				"cache_read_tokens":     int64(0),
				"cache_creation_tokens": int64(0),
				"output_tokens":         int64(1),
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		},
		{
			ID:        "spanless-judge-request",
			Timestamp: now.Add(3 * time.Millisecond),
			TraceID:   "spanless-evaluation-log-trace",
			Body:      "claude_code.api_request",
			Attributes: map[string]any{
				"event.name":            "api_request",
				"request_id":            "spanless-judge-request",
				"prompt.id":             "judge-prompt",
				"session.id":            "agent-session",
				"input_tokens":          int64(50),
				"cache_read_tokens":     int64(0),
				"cache_creation_tokens": int64(0),
				"output_tokens":         int64(5),
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		},
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"traceId": "spanless-evaluation-log-trace"})
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 1 {
		t.Fatalf("unexpected agent tasks after excluding spanless judge log: %+v", data)
	}
	task := toMapAny(tasks[0])
	if usage := toMapAny(task["usage"]); usage["effectiveTotalTokens"] != float64(3) {
		t.Fatalf("agent usage was lost or spanless judge usage leaked into agent accounting: %+v", task)
	}
	if task["accountingStatus"] != "exact" {
		t.Fatalf("complete agent usage should remain exact: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewNormalizesNativeClaudeBoundaryUsageWithoutProviderAttribute(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("claude", []store.Span{{
		TraceID: "claude-boundary-trace", SpanID: "interaction", Name: "claude_code.interaction",
		StartTime: now, EndTime: now.Add(time.Millisecond),
		Attributes: map[string]any{
			"prompt.id": "claude-boundary-prompt", "session.id": "claude-boundary-session",
			"input_tokens": int64(5), "cache_read_input_tokens": int64(10),
			"cache_creation_input_tokens": int64(2), "output_tokens": int64(4),
		},
		Resource: store.Resource{ServiceName: "claude-code"},
	}})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "claude-boundary-session"})
	task := toMapAny(toSliceAny(data["tasks"])[0])
	usage := toMapAny(task["usage"])
	if task["accountingStatus"] != "exact" || task["measurementSource"] != "claude_interaction_span" {
		t.Fatalf("native Claude boundary was not exact provider accounting: %+v", task)
	}
	if usage["inputTokens"] != float64(17) || usage["cachedInputTokens"] != float64(10) ||
		usage["cacheCreationInputTokens"] != float64(2) || usage["effectiveTotalTokens"] != float64(21) {
		t.Fatalf("native Claude boundary cache semantics were not normalized: %+v", usage)
	}
}

func TestToolsCallTokenUsageOverviewRejectsGenericProviderBoundaryName(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("application", []store.Span{{
		TraceID: "application-trace", SpanID: "generic-boundary", Name: "session_task.turn",
		StartTime: now, EndTime: now.Add(time.Millisecond),
		Attributes: map[string]any{
			"turn.id":                             "application-turn",
			"codex.turn.token_usage.input_tokens": int64(100),
			"codex.turn.token_usage.total_tokens": int64(100),
		},
		Resource: store.Resource{ServiceName: "order-service"},
	}})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"provider": "codex"})
	if data["status"] != "absent" || len(toSliceAny(data["tasks"])) != 0 {
		t.Fatalf("generic application span was accepted as an exact Codex boundary: %+v", data)
	}
}

func TestToolsCallTokenUsageOverviewNormalizesClaudeDeltaMetricsAndDeduplicates(t *testing.T) {
	s := store.New()
	now := s.ProviderUsageMetricUnavailableThrough().Add(time.Second)
	metric := func(tokenType string, value float64, timestamp time.Time) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "delta", Value: value,
			IsMonotonic: true, Timestamp: timestamp, StartTime: now,
			Attributes: map[string]any{
				"session.id": "claude-metric-session", "model": "claude-haiku-4-5", "query_source": "main", "type": tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"}, Scope: store.Scope{Name: "com.anthropic.claude_code"},
		}
	}
	firstExport := []store.MetricDataPoint{
		metric("input", 5, now.Add(time.Second)),
		metric("cacheRead", 10, now.Add(time.Second)),
		metric("cacheCreation", 2, now.Add(time.Second)),
		metric("output", 4, now.Add(time.Second)),
	}
	secondExport := []store.MetricDataPoint{
		metric("input", 1, now.Add(2*time.Second)),
		metric("cacheRead", 0, now.Add(2*time.Second)),
		metric("cacheCreation", 3, now.Add(2*time.Second)),
		metric("output", 2, now.Add(2*time.Second)),
	}
	points := append(append([]store.MetricDataPoint{}, firstExport...), firstExport...)
	points = append(points, secondExport...)
	s.AddMetricsForConnection("claude", points)

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "claude-metric-session"})
	if data["measurementSource"] != "provider_metrics" || data["status"] != "measured" || data["accountingStatus"] != "partial" {
		t.Fatalf("Claude delta metric accounting was not retained-window partial: %+v", data)
	}
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["measurementSource"] != "claude_token_metrics" || task["providerMetricCount"] != float64(12) || task["requestCount"] != float64(0) {
		t.Fatalf("Claude metric diagnostics are wrong: %+v", task)
	}
	usage := toMapAny(task["usage"])
	if usage["inputTokens"] != float64(21) || usage["cachedInputTokens"] != float64(10) || usage["cacheCreationInputTokens"] != float64(5) || usage["outputTokens"] != float64(6) || usage["derivedTotalTokens"] != float64(27) || usage["effectiveTotalTokens"] != float64(27) {
		t.Fatalf("Claude delta/cache normalization is wrong: %+v", usage)
	}
	if usage["reasoningOutputTokens"] != nil || usage["providerTotalTokens"] != nil {
		t.Fatalf("Claude metric-only unknown fields were reported as zero: %+v", usage)
	}
}

func TestToolsCallTokenUsageOverviewRejectsConflictingClaudeDeltaRetransmission(t *testing.T) {
	t.Parallel()

	s := store.New()
	now := time.Now()
	metric := func(tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name:        "claude_code.token.usage",
			Type:        "sum",
			Temporality: "delta",
			IsMonotonic: true,
			StartTime:   now,
			Timestamp:   now,
			Value:       value,
			Attributes: map[string]any{
				"session.id": "conflicting-session",
				"type":       tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddMetricsForConnection("claude", []store.MetricDataPoint{
		metric("input", 10),
		metric("input", 20),
		metric("cacheRead", 0),
		metric("cacheCreation", 0),
		metric("output", 2),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "conflicting-session"})
	task := toMapAny(toSliceAny(data["tasks"])[0])
	usage := toMapAny(task["usage"])
	if task["status"] != "partial" || task["accountingStatus"] != "partial" {
		t.Fatalf("conflicting delta retransmission was presented as exact: %+v", task)
	}
	if usage["inputTokens"] != nil || usage["effectiveTotalTokens"] != nil || usage["outputTokens"] != float64(2) {
		t.Fatalf("conflicting delta interval was added into normalized usage: %+v", usage)
	}
}

func TestBuildClaudeMetricTaskMarksEvictedDeltaHistoryPartial(t *testing.T) {
	t.Parallel()

	now := time.Now()
	metric := func(tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name:        "claude_code.token.usage",
			Type:        "sum",
			Temporality: "delta",
			IsMonotonic: true,
			StartTime:   now.Add(-time.Hour),
			Timestamp:   now,
			Value:       value,
			Attributes: map[string]any{
				"session.id": "truncated-session",
				"type":       tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}
	}
	built := buildClaudeMetricTask([]store.MetricDataPoint{
		metric("input", 10),
		metric("cacheRead", 1),
		metric("cacheCreation", 2),
		metric("output", 3),
	}, now.Add(-30*time.Minute))
	if built.task.Status != "partial" || built.task.AccountingStatus != "partial" {
		t.Fatalf("evicted delta history was presented as exact: %+v", built.task)
	}
	if built.task.Usage.EffectiveTotalTokens == nil || *built.task.Usage.EffectiveTotalTokens != 16 {
		t.Fatalf("retained partial delta values were not preserved: %+v", built.task.Usage)
	}
}

func TestBuildClaudeMetricTaskMarksEvictedCumulativeSeriesPartial(t *testing.T) {
	t.Parallel()

	now := time.Now().UTC()
	metric := func(tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", Value: value,
			IsMonotonic: true, StartTime: now.Add(-time.Hour), Timestamp: now,
			Attributes: map[string]any{
				"session.id": "truncated-cumulative-session", "model": "claude-sonnet-4-6", "query_source": "main", "type": tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"}, Scope: store.Scope{Name: "com.anthropic.claude_code"},
		}
	}
	built := buildClaudeMetricTask([]store.MetricDataPoint{
		metric("input", 10),
		metric("cacheRead", 1),
		metric("cacheCreation", 2),
		metric("output", 3),
	}, now.Add(-30*time.Minute))
	if built.task.Status != "partial" || built.task.AccountingStatus != "partial" {
		t.Fatalf("cumulative session after series eviction was presented as exact: %+v", built.task)
	}
	if built.task.Usage.EffectiveTotalTokens == nil || *built.task.Usage.EffectiveTotalTokens != 16 {
		t.Fatalf("retained partial cumulative values were not preserved: %+v", built.task.Usage)
	}
}

func TestToolsCallTokenUsageOverviewUsesLatestClaudeCumulativeMetrics(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	for index, values := range []map[string]float64{
		{"input": 5, "cacheRead": 10, "cacheCreation": 2, "output": 4},
		{"input": 6, "cacheRead": 10, "cacheCreation": 5, "output": 6},
	} {
		points := make([]store.MetricDataPoint, 0, len(values))
		for tokenType, value := range values {
			points = append(points, store.MetricDataPoint{
				Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", Value: value,
				IsMonotonic: true, Timestamp: now.Add(time.Duration(index+1) * time.Second), StartTime: now,
				Attributes: map[string]any{
					"session.id": "claude-cumulative-session", "model": "claude-sonnet-4-6", "query_source": "main", "type": tokenType,
				},
				Resource: store.Resource{ServiceName: "claude-code"}, Scope: store.Scope{Name: "com.anthropic.claude_code"},
			})
		}
		s.AddMetricsForConnection("claude", points)
	}

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"taskId": "claude-cumulative-session"})
	task := toMapAny(toSliceAny(data["tasks"])[0])
	usage := toMapAny(task["usage"])
	if task["accountingStatus"] != "exact" || usage["inputTokens"] != float64(21) || usage["outputTokens"] != float64(6) || usage["effectiveTotalTokens"] != float64(27) {
		t.Fatalf("cumulative Claude metrics were added instead of selecting the latest values: %+v", task)
	}
}

func TestBuildClaudeMetricTaskRejectsDecreasingCumulativeSeries(t *testing.T) {
	t.Parallel()

	now := time.Now().UTC()
	metric := func(tokenType string, value float64, offset time.Duration) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", Value: value,
			IsMonotonic: true, Timestamp: now.Add(offset), StartTime: now,
			Attributes: map[string]any{
				"session.id": "decreasing-cumulative-session", "model": "claude-sonnet-4-6", "query_source": "main", "type": tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"}, Scope: store.Scope{Name: "com.anthropic.claude_code"},
		}
	}
	points := []store.MetricDataPoint{
		metric("input", 10, time.Second),
		metric("input", 9, 2*time.Second),
		metric("cacheRead", 1, time.Second),
		metric("cacheRead", 1, 2*time.Second),
		metric("cacheCreation", 2, time.Second),
		metric("cacheCreation", 2, 2*time.Second),
		metric("output", 3, time.Second),
		metric("output", 4, 2*time.Second),
	}

	built := buildClaudeMetricTask(points, time.Time{})
	if built.task.Status != "partial" || built.task.AccountingStatus != "partial" {
		t.Fatalf("decreasing cumulative series was presented as exact: %+v", built.task)
	}
}

func TestBuildClaudeMetricTaskCountsCumulativeResetAsSeparateSeries(t *testing.T) {
	t.Parallel()

	now := time.Now().UTC()
	metric := func(start time.Time, tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", Value: value,
			IsMonotonic: true, Timestamp: start.Add(time.Second), StartTime: start,
			Attributes: map[string]any{
				"session.id": "reset-cumulative-session", "model": "claude-sonnet-4-6", "query_source": "main", "type": tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"}, Scope: store.Scope{Name: "com.anthropic.claude_code"},
		}
	}
	points := make([]store.MetricDataPoint, 0, 8)
	for _, series := range []struct {
		start  time.Time
		values map[string]float64
	}{
		{start: now, values: map[string]float64{"input": 10, "cacheRead": 1, "cacheCreation": 2, "output": 3}},
		{start: now.Add(2 * time.Second), values: map[string]float64{"input": 1, "cacheRead": 0, "cacheCreation": 0, "output": 1}},
	} {
		for tokenType, value := range series.values {
			points = append(points, metric(series.start, tokenType, value))
		}
	}

	built := buildClaudeMetricTask(points, time.Time{})
	if built.task.Status != "measured" || built.task.AccountingStatus != "exact" {
		t.Fatalf("cumulative reset was not treated as a separate exact series: %+v", built.task)
	}
	usage := built.task.Usage
	if usage.InputTokens == nil || *usage.InputTokens != 14 || usage.OutputTokens == nil || *usage.OutputTokens != 4 ||
		usage.EffectiveTotalTokens == nil || *usage.EffectiveTotalTokens != 18 {
		t.Fatalf("cumulative reset series were not aggregated independently: %+v", usage)
	}
}

func TestBuildClaudeMetricTaskKeepsResourceAndScopeSeriesDistinct(t *testing.T) {
	t.Parallel()

	for _, test := range []struct {
		name     string
		resource func(int) store.Resource
		scope    func(int) store.Scope
	}{
		{
			name: "resource attributes",
			resource: func(index int) store.Resource {
				return store.Resource{
					ServiceName: "claude-code",
					Attributes:  map[string]any{"service.instance.id": fmt.Sprintf("instance-%d", index)},
				}
			},
			scope: func(int) store.Scope {
				return store.Scope{Name: "com.anthropic.claude_code", Version: "1.0.0"}
			},
		},
		{
			name: "resource schema",
			resource: func(index int) store.Resource {
				return store.Resource{
					ServiceName: "claude-code",
					SchemaURL:   fmt.Sprintf("https://opentelemetry.io/schemas/1.2.%d", index),
				}
			},
			scope: func(int) store.Scope {
				return store.Scope{Name: "com.anthropic.claude_code", Version: "1.0.0"}
			},
		},
		{
			name: "scope version",
			resource: func(int) store.Resource {
				return store.Resource{ServiceName: "claude-code"}
			},
			scope: func(index int) store.Scope {
				return store.Scope{
					Name:    "com.anthropic.claude_code",
					Version: fmt.Sprintf("1.0.%d", index),
				}
			},
		},
		{
			name: "scope schema",
			resource: func(int) store.Resource {
				return store.Resource{ServiceName: "claude-code"}
			},
			scope: func(index int) store.Scope {
				return store.Scope{
					Name:      "com.anthropic.claude_code",
					Version:   "1.0.0",
					SchemaURL: fmt.Sprintf("https://opentelemetry.io/schemas/1.2.%d", index),
				}
			},
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()

			now := time.Now().UTC()
			points := make([]store.MetricDataPoint, 0, 8)
			for stream := 1; stream <= 2; stream++ {
				for tokenType, value := range map[string]float64{
					"input": 10, "cacheRead": 1, "cacheCreation": 2, "output": 3,
				} {
					points = append(points, store.MetricDataPoint{
						Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", Value: value,
						IsMonotonic: true, Timestamp: now.Add(time.Second), StartTime: now,
						Attributes: map[string]any{
							"session.id": "distinct-stream-session", "model": "claude-sonnet-4-6", "query_source": "main", "type": tokenType,
						},
						Resource: test.resource(stream),
						Scope:    test.scope(stream),
					})
				}
			}

			built := buildClaudeMetricTask(points, time.Time{})
			if built.task.Status != "measured" || built.task.AccountingStatus != "exact" {
				t.Fatalf("complete distinct streams were not measured exactly: %+v", built.task)
			}
			usage := built.task.Usage
			if usage.InputTokens == nil || *usage.InputTokens != 26 || usage.OutputTokens == nil || *usage.OutputTokens != 6 ||
				usage.EffectiveTotalTokens == nil || *usage.EffectiveTotalTokens != 32 {
				t.Fatalf("distinct metric streams were merged: %+v", usage)
			}
		})
	}
}

func TestToolsCallTokenUsageOverviewMarksPreObserverClaudeCumulativeMetricsPartial(t *testing.T) {
	for _, test := range []struct {
		name  string
		clear bool
	}{
		{name: "startup"},
		{name: "clear", clear: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			s := store.New()
			if test.clear {
				s.Clear()
			}
			now := time.Now().UTC()
			points := make([]store.MetricDataPoint, 0, len(requiredClaudeMetricTokenTypes))
			for _, tokenType := range requiredClaudeMetricTokenTypes {
				points = append(points, store.MetricDataPoint{
					Name:        "claude_code.token.usage",
					Type:        "sum",
					Temporality: "cumulative",
					IsMonotonic: true,
					Value:       1,
					StartTime:   now.Add(-time.Hour),
					Timestamp:   now,
					Attributes: map[string]any{
						"session.id":   "pre-observer-session",
						"model":        "claude-sonnet-4-6",
						"query_source": "main",
						"type":         tokenType,
					},
					Resource: store.Resource{ServiceName: "claude-code"},
				})
			}
			s.AddMetricsForConnection("claude", points)

			data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "pre-observer-session"})
			if data["accountingStatus"] != "partial" {
				t.Fatalf("pre-%s cumulative metric history was presented as exact: %+v", test.name, data)
			}
		})
	}
}

func TestBuildClaudeMetricTaskMarksIncompleteCumulativeDimensionPartial(t *testing.T) {
	t.Parallel()

	now := time.Now().UTC()
	metric := func(model, querySource, tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", Value: value,
			IsMonotonic: true, Timestamp: now.Add(time.Second), StartTime: now,
			Attributes: map[string]any{
				"session.id": "multi-dimension-session", "model": model, "query_source": querySource, "type": tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"}, Scope: store.Scope{Name: "com.anthropic.claude_code"},
		}
	}
	points := []store.MetricDataPoint{
		metric("claude-sonnet-4-6", "main", "input", 10),
		metric("claude-sonnet-4-6", "main", "cacheRead", 2),
		metric("claude-sonnet-4-6", "main", "cacheCreation", 3),
		metric("claude-sonnet-4-6", "main", "output", 4),
		metric("claude-haiku-4-5", "subagent", "output", 7),
	}

	built := buildClaudeMetricTask(points, time.Time{})
	if built.task.Status != "partial" || built.task.AccountingStatus != "partial" {
		t.Fatalf("incomplete cumulative metric dimension was presented as exact: %+v", built.task)
	}
	if built.task.Usage.InputTokens == nil || *built.task.Usage.InputTokens != 15 ||
		built.task.Usage.OutputTokens == nil || *built.task.Usage.OutputTokens != 11 {
		t.Fatalf("recognized values from incomplete cumulative dimensions were not preserved: %+v", built.task.Usage)
	}
}

func TestBuildClaudeMetricTaskRejectsNonMonotonicSum(t *testing.T) {
	t.Parallel()

	now := time.Now().UTC()
	metric := func(tokenType string, monotonic bool) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", Value: 1,
			IsMonotonic: monotonic, Timestamp: now.Add(time.Second), StartTime: now,
			Attributes: map[string]any{
				"session.id": "non-monotonic-session", "model": "claude-sonnet-4-6", "query_source": "main", "type": tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"}, Scope: store.Scope{Name: "com.anthropic.claude_code"},
		}
	}
	points := []store.MetricDataPoint{
		metric("input", false),
		metric("cacheRead", true),
		metric("cacheCreation", true),
		metric("output", true),
	}

	built := buildClaudeMetricTask(points, time.Time{})
	if built.task.Status != "partial" || built.task.AccountingStatus != "partial" {
		t.Fatalf("non-monotonic Claude sum was presented as exact: %+v", built.task)
	}
	if built.task.Usage.InputTokens != nil || built.task.Usage.EffectiveTotalTokens != nil {
		t.Fatalf("non-monotonic Claude input was counted as consumption: %+v", built.task.Usage)
	}
}

func TestToolsCallTokenUsageOverviewFiltersCodexTasksByNativeRepositoryPath(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	repositoryPath := filepath.Join(t.TempDir(), "entity-model-service")
	workspacePath := filepath.Join(repositoryPath, "internal", "entity")
	judgeWorkspacePath := filepath.Join(t.TempDir(), "rubric-grader")
	if err := os.MkdirAll(filepath.Join(repositoryPath, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(workspacePath, 0o755); err != nil {
		t.Fatal(err)
	}
	s.AddSpansForConnection("codex", []store.Span{
		{
			TraceID: "repository-codex-trace", SpanID: "turn-boundary", Name: "session_task.turn",
			StartTime: now, EndTime: now.Add(time.Second),
			Attributes: map[string]any{
				"conversation.id":                      "repository-codex-conversation",
				"turn.id":                              "repository-codex-turn",
				"codex.turn.token_usage.input_tokens":  int64(12),
				"codex.turn.token_usage.output_tokens": int64(3),
				"codex.turn.token_usage.total_tokens":  int64(15),
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		},
		{
			TraceID: "repository-codex-trace", SpanID: "sampling", ParentSpanID: "turn-boundary", Name: "run_sampling_request",
			StartTime: now.Add(time.Millisecond), EndTime: now.Add(2 * time.Millisecond),
			Attributes: map[string]any{"cwd": workspacePath, "turn_id": "repository-codex-turn"},
			Resource:   store.Resource{ServiceName: "codex-app-server"},
		},
		{
			TraceID: "repository-codex-trace", SpanID: "workspace-root", ParentSpanID: "turn-boundary", Name: "workspace_context",
			StartTime: now.Add(2 * time.Millisecond), EndTime: now.Add(3 * time.Millisecond),
			Attributes: map[string]any{"cwd": repositoryPath},
			Resource:   store.Resource{ServiceName: "codex-app-server"},
		},
		{
			TraceID: "repository-codex-trace", SpanID: "evaluation", ParentSpanID: "turn-boundary", Name: "evaluation",
			StartTime: now.Add(3 * time.Millisecond), EndTime: now.Add(5 * time.Millisecond),
			Attributes: map[string]any{"gen_ai.evaluation.name": "rubric"},
			Resource:   store.Resource{ServiceName: "codex-app-server"},
		},
		{
			TraceID: "repository-codex-trace", SpanID: "judge", ParentSpanID: "evaluation", Name: "judge",
			StartTime: now.Add(4 * time.Millisecond), EndTime: now.Add(5 * time.Millisecond),
			Attributes: map[string]any{"cwd": judgeWorkspacePath},
			Resource:   store.Resource{ServiceName: "codex-app-server"},
		},
	})

	d := NewDispatcher(s, RepositoryCorrelationModeResolver(func(string) string { return "path" }))
	data := callTokenUsageOverview(t, d, map[string]any{
		"repositoryPath": repositoryPath,
		"provider":       "codex",
	})
	repositoryPath = cleanRepositoryPath(repositoryPath)
	if data["status"] != "measured" || data["accountingStatus"] != "exact" || data["repositoryCorrelationStatus"] != "correlated" {
		t.Fatalf("Codex repository accounting status is wrong: %+v", data)
	}
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 1 {
		t.Fatalf("Codex repository query returned %d tasks: %+v", len(tasks), data)
	}
	task := toMapAny(tasks[0])
	if task["repositoryName"] != "entity-model-service" || task["repositoryPath"] != repositoryPath ||
		task["workspacePath"] != repositoryPath || task["repositoryCorrelationStatus"] != "task_correlated" ||
		task["repositoryCorrelationSource"] != "provider_task_span" {
		t.Fatalf("Codex native cwd was not normalized to repository identity: %+v", task)
	}
	usage := toMapAny(task["usage"])
	if usage["effectiveTotalTokens"] != float64(15) {
		t.Fatalf("repository enrichment changed Codex token accounting: %+v", usage)
	}
	coverage := toMapAny(data["repositoryCoverage"])
	if coverage["candidateTaskCount"] != float64(1) || coverage["taskCorrelatedCount"] != float64(1) || coverage["matchedTaskCount"] != float64(1) {
		t.Fatalf("Codex repository coverage is wrong: %+v", coverage)
	}

	absent := callTokenUsageOverview(t, d, map[string]any{"repositoryName": "does-not-exist"})
	if absent["status"] != "absent" || absent["accountingStatus"] != "unknown" || len(toSliceAny(absent["tasks"])) != 0 {
		t.Fatalf("unmatched repository was not absent: %+v", absent)
	}
	if effective := toMapAny(absent["usage"])["effectiveTotalTokens"]; effective != nil {
		t.Fatalf("unmatched repository was reported as zero instead of unknown: %+v", absent["usage"])
	}
	absentCoverage := toMapAny(absent["repositoryCoverage"])
	if absentCoverage["candidateTaskCount"] != float64(1) || absentCoverage["matchedTaskCount"] != float64(0) {
		t.Fatalf("unmatched repository coverage hid candidate tasks: %+v", absentCoverage)
	}
}

func TestToolsCallTokenUsageOverviewNameModeRedactsNativeCodexPaths(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	repositoryPath := filepath.Join(t.TempDir(), "kvstore")
	if err := os.MkdirAll(filepath.Join(repositoryPath, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	s.AddSpansForConnection("codex", []store.Span{
		{
			TraceID: "name-mode-codex-trace", SpanID: "turn-boundary", Name: "session_task.turn",
			StartTime: now, EndTime: now.Add(time.Second),
			Attributes: map[string]any{
				"conversation.id":                      "name-mode-codex-conversation",
				"turn.id":                              "name-mode-codex-turn",
				"codex.turn.token_usage.input_tokens":  int64(12),
				"codex.turn.token_usage.output_tokens": int64(3),
				"codex.turn.token_usage.total_tokens":  int64(15),
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		},
		{
			TraceID: "name-mode-codex-trace", SpanID: "sampling", ParentSpanID: "turn-boundary", Name: "run_sampling_request",
			StartTime: now.Add(time.Millisecond), EndTime: now.Add(2 * time.Millisecond),
			Attributes: map[string]any{"cwd": repositoryPath, "turn_id": "name-mode-codex-turn"},
			Resource:   store.Resource{ServiceName: "codex-app-server"},
		},
	})
	s.AddLogsForConnection("codex", []store.LogRecord{{
		Timestamp: now,
		Body:      "obstudio.repository_correlation",
		Attributes: map[string]any{
			"event.name":                           "obstudio.repository_correlation",
			"gen_ai.provider.name":                 "codex",
			"turn.id":                              "name-mode-codex-turn",
			"repository.name":                      "kvstore",
			"repository.path":                      repositoryPath,
			"workspace.path":                       repositoryPath,
			"obstudio.repository_correlation.mode": "path",
		},
		Resource: store.Resource{ServiceName: "obstudio-agent-correlation"},
	}})

	resolverCalls := 0
	d := NewDispatcher(s, RepositoryCorrelationModeResolver(func(provider string) string {
		resolverCalls++
		if provider != "codex" {
			t.Fatalf("repository mode requested for provider %q", provider)
		}
		return "name"
	}))
	data := callTokenUsageOverview(t, d, map[string]any{
		"repositoryName": "kvstore",
		"provider":       "codex",
	})
	if resolverCalls != 1 {
		t.Fatalf("repository mode resolver called %d times, want 1", resolverCalls)
	}
	if data["accountingStatus"] != "exact" || data["repositoryCorrelationStatus"] != "correlated" {
		t.Fatalf("name-mode Codex accounting status is wrong: %+v", data)
	}
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["repositoryName"] != "kvstore" || task["repositoryCorrelationStatus"] != "task_correlated" ||
		task["repositoryCorrelationSource"] != "provider_task_span" {
		t.Fatalf("name-mode Codex repository identity changed: %+v", task)
	}
	if _, ok := task["repositoryPath"]; ok {
		t.Fatalf("name mode exposed repositoryPath: %+v", task)
	}
	if _, ok := task["workspacePath"]; ok {
		t.Fatalf("name mode exposed workspacePath: %+v", task)
	}
	rawSpans := s.SnapshotSpans()
	if len(rawSpans) != 2 || rawSpans[1].Attributes["cwd"] != repositoryPath {
		t.Fatalf("name-mode normalization changed raw provider spans: %+v", rawSpans)
	}

	offDispatcher := NewDispatcher(s, RepositoryCorrelationModeResolver(func(string) string { return "off" }))
	offData := callTokenUsageOverview(t, offDispatcher, map[string]any{"provider": "codex"})
	offTask := toMapAny(toSliceAny(offData["tasks"])[0])
	for _, field := range []string{"repositoryName", "repositoryPath", "workspacePath", "repositoryCorrelationSource"} {
		if _, ok := offTask[field]; ok {
			t.Fatalf("off mode exposed %s: %+v", field, offTask)
		}
	}
	if offTask["repositoryCorrelationStatus"] != "unknown" {
		t.Fatalf("off mode repository status = %#v, want unknown", offTask["repositoryCorrelationStatus"])
	}
	offFiltered := callTokenUsageOverview(t, offDispatcher, map[string]any{
		"repositoryName": "kvstore",
		"provider":       "codex",
	})
	if offFiltered["status"] != "absent" || len(toSliceAny(offFiltered["tasks"])) != 0 {
		t.Fatalf("off mode matched a repository filter: %+v", offFiltered)
	}
}

func TestToolsCallTokenUsageOverviewCorrelatesClaudeMetricsBySessionRepository(t *testing.T) {
	s := store.New()
	now := time.Now().UTC()
	repositoryPath := filepath.Join(t.TempDir(), "entity-model-service")
	if err := os.MkdirAll(filepath.Join(repositoryPath, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	s.AddLogsForConnection("claude", []store.LogRecord{{
		Timestamp: now.Add(time.Second),
		Body:      "obstudio.repository_correlation",
		Attributes: map[string]any{
			"event.name":                             "obstudio.repository_correlation",
			"gen_ai.provider.name":                   "claude",
			"session.id":                             "repository-claude-session",
			"repository.name":                        "entity-model-service",
			"repository.path":                        repositoryPath,
			"workspace.path":                         repositoryPath,
			"obstudio.repository_correlation.mode":   "path",
			"obstudio.repository_correlation.source": "SessionStart",
		},
		Resource: store.Resource{ServiceName: "obstudio-agent-correlation"},
	}})
	for tokenType, value := range map[string]float64{"input": 10, "cacheRead": 2, "cacheCreation": 3, "output": 4} {
		s.AddMetricsForConnection("claude", []store.MetricDataPoint{{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", Value: value,
			IsMonotonic: true, StartTime: now, Timestamp: now.Add(2 * time.Second),
			Attributes: map[string]any{"session.id": "repository-claude-session", "type": tokenType},
			Resource:   store.Resource{ServiceName: "claude-code"},
		}})
	}

	data := callTokenUsageOverview(t, NewDispatcher(s, RepositoryCorrelationModeResolver(func(string) string { return "path" })), map[string]any{
		"repositoryName": "entity-model-service",
		"provider":       "claude",
	})
	if data["accountingStatus"] != "exact" || data["repositoryCorrelationStatus"] != "correlated" {
		t.Fatalf("Claude accounting and repository statuses were conflated: %+v", data)
	}
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["repositoryCorrelationStatus"] != "session_correlated" || task["repositoryCorrelationSource"] != "SessionStart" ||
		task["repositoryPath"] != repositoryPath {
		t.Fatalf("Claude session repository correlation is wrong: %+v", task)
	}
	usage := toMapAny(task["usage"])
	if usage["inputTokens"] != float64(15) || usage["effectiveTotalTokens"] != float64(19) ||
		usage["reasoningOutputTokens"] != nil || usage["providerTotalTokens"] != nil {
		t.Fatalf("Claude repository enrichment changed cache or unknown semantics: %+v", usage)
	}

	nameData := callTokenUsageOverview(t, NewDispatcher(s, RepositoryCorrelationModeResolver(func(string) string { return "name" })), map[string]any{
		"repositoryName": "entity-model-service",
		"provider":       "claude",
	})
	nameTask := toMapAny(toSliceAny(nameData["tasks"])[0])
	if nameTask["repositoryName"] != "entity-model-service" {
		t.Fatalf("current name mode lost retained Claude repository identity: %+v", nameTask)
	}
	for _, field := range []string{"repositoryPath", "workspacePath"} {
		if _, ok := nameTask[field]; ok {
			t.Fatalf("current name mode exposed retained Claude %s: %+v", field, nameTask)
		}
	}

	offData := callTokenUsageOverview(t, NewDispatcher(s, RepositoryCorrelationModeResolver(func(string) string { return "off" })), map[string]any{
		"provider": "claude",
	})
	offTask := toMapAny(toSliceAny(offData["tasks"])[0])
	for _, field := range []string{"repositoryName", "repositoryPath", "workspacePath", "repositoryCorrelationSource"} {
		if _, ok := offTask[field]; ok {
			t.Fatalf("current off mode exposed retained Claude %s: %+v", field, offTask)
		}
	}
	if offTask["repositoryCorrelationStatus"] != "unknown" {
		t.Fatalf("current off mode repository status = %#v, want unknown", offTask["repositoryCorrelationStatus"])
	}

	invalidData := callTokenUsageOverview(t, NewDispatcher(s, RepositoryCorrelationModeResolver(func(string) string { return "invalid" })), map[string]any{
		"provider": "claude",
	})
	invalidTask := toMapAny(toSliceAny(invalidData["tasks"])[0])
	if _, ok := invalidTask["repositoryName"]; ok || invalidTask["repositoryCorrelationStatus"] != "unknown" {
		t.Fatalf("invalid current mode did not fail closed: %+v", invalidTask)
	}

	s.AddLogsForConnection("claude", []store.LogRecord{{
		Timestamp: now.Add(1500 * time.Millisecond),
		Body:      "obstudio.repository_correlation",
		Attributes: map[string]any{
			"event.name":                           "obstudio.repository_correlation",
			"gen_ai.provider.name":                 "claude",
			"session.id":                           "repository-claude-session",
			"repository.name":                      "other-service",
			"obstudio.repository_correlation.mode": "name",
		},
	}})
	ambiguous := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{
		"repositoryName": "entity-model-service",
		"provider":       "claude",
	})
	ambiguousCoverage := toMapAny(ambiguous["repositoryCoverage"])
	if len(toSliceAny(ambiguous["tasks"])) != 0 || ambiguousCoverage["ambiguousTaskCount"] != float64(1) {
		t.Fatalf("multi-repository Claude session was attributed to one repository: %+v", ambiguous)
	}
}

func TestToolsCallTokenUsageOverviewFailsClosedAfterRepositoryCorrelationEviction(t *testing.T) {
	s := store.New()
	now := time.Now().UTC().Add(time.Second)
	correlations := make([]store.LogRecord, store.DefaultProviderRepositoryCorrelationCap+1)
	for index := range correlations {
		repositoryName := "new-service"
		if index == 0 {
			repositoryName = "old-service"
		}
		correlations[index] = store.LogRecord{
			Timestamp: now.Add(time.Duration(index) * time.Microsecond),
			Body:      "obstudio.repository_correlation",
			Attributes: map[string]any{
				"event.name":                           "obstudio.repository_correlation",
				"gen_ai.provider.name":                 "claude",
				"session.id":                           "evicted-correlation-session",
				"repository.name":                      repositoryName,
				"obstudio.repository_correlation.mode": "name",
			},
			Resource: store.Resource{ServiceName: "obstudio-agent-correlation"},
		}
	}
	s.AddLogsForConnection("claude", correlations)

	metric := func(tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", Value: value,
			IsMonotonic: true, StartTime: now, Timestamp: now.Add(2 * time.Second),
			Attributes: map[string]any{"session.id": "evicted-correlation-session", "type": tokenType},
			Resource:   store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddMetricsForConnection("claude", []store.MetricDataPoint{
		metric("input", 10),
		metric("cacheRead", 2),
		metric("cacheCreation", 3),
		metric("output", 4),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s, RepositoryCorrelationModeResolver(func(string) string { return "name" })), map[string]any{
		"repositoryName": "new-service",
		"provider":       "claude",
	})
	coverage := toMapAny(data["repositoryCoverage"])
	if len(toSliceAny(data["tasks"])) != 0 || data["repositoryCorrelationStatus"] != "unknown" ||
		coverage["candidateTaskCount"] != float64(1) || coverage["unattributedTaskCount"] != float64(1) ||
		coverage["matchedTaskCount"] != float64(0) {
		t.Fatalf("evicted correlation history attributed a cumulative Claude session: %+v", data)
	}
}

func TestRepositoryCorrelationReportsAmbiguousSessionWithoutAttributingTokens(t *testing.T) {
	task := providerLogTaskBuild{task: tokenUsageTask{
		TaskID: "prompt-1", ConversationID: "session-1", Provider: "claude",
		StartTime: formatTokenUsageTime(time.Unix(100, 0)),
	}}
	observedAt := time.Unix(90, 0)
	correlations := []store.ProviderRepositoryCorrelation{
		{Provider: "claude", ConversationID: "session-1", RepositoryName: "one", Mode: "name", Source: "SessionStart", ObservedAt: observedAt},
		{Provider: "claude", ConversationID: "session-1", RepositoryName: "two", Mode: "name", Source: "SessionStart", ObservedAt: observedAt},
	}
	filtered, coverage := correlateAndFilterProviderTasks([]providerLogTaskBuild{task}, correlations, &tokenUsageRepositoryFilter{RepositoryName: "one"})
	if len(filtered) != 0 || coverage.AmbiguousTaskCount != 1 || coverage.MatchedTaskCount != 0 {
		t.Fatalf("ambiguous repository attribution was included: tasks=%+v coverage=%+v", filtered, coverage)
	}
}

func TestRepositoryCorrelationPreservesNativeProviderAmbiguity(t *testing.T) {
	task := providerLogTaskBuild{task: tokenUsageTask{
		TaskID: "prompt-1", ConversationID: "session-1", Provider: "claude",
		StartTime:                   formatTokenUsageTime(time.Unix(100, 0)),
		RepositoryCorrelationStatus: "ambiguous",
	}}
	correlation := store.ProviderRepositoryCorrelation{
		Provider: "claude", ConversationID: "session-1", TaskID: "prompt-1",
		RepositoryName: "one", RepositoryPath: "/repositories/one", WorkspacePath: "/repositories/one",
		Mode: "path", Source: "SessionStart", ObservedAt: time.Unix(90, 0),
	}

	for _, test := range []struct {
		name         string
		correlations []store.ProviderRepositoryCorrelation
	}{
		{name: "matching lifecycle correlation", correlations: []store.ProviderRepositoryCorrelation{correlation}},
		{name: "no lifecycle correlation"},
	} {
		t.Run(test.name, func(t *testing.T) {
			filtered, coverage := correlateAndFilterProviderTasksWithResolver(
				[]providerLogTaskBuild{task},
				test.correlations,
				&tokenUsageRepositoryFilter{RepositoryName: "one"},
				RepositoryCorrelationModeResolver(func(string) string { return "path" }),
			)
			if len(filtered) != 0 || coverage.AmbiguousTaskCount != 1 || coverage.MatchedTaskCount != 0 {
				t.Fatalf("native provider ambiguity was overwritten: tasks=%+v coverage=%+v", filtered, coverage)
			}
		})
	}
}

func TestRepositoryCorrelationNameModeIgnoresHistoricalPathDifferences(t *testing.T) {
	task := providerLogTaskBuild{task: tokenUsageTask{
		TaskID: "session-1", ConversationID: "session-1", Provider: "claude", TaskKind: "session",
		StartTime: formatTokenUsageTime(time.Unix(100, 0)),
		EndTime:   formatTokenUsageTime(time.Unix(120, 0)),
	}}
	correlations := []store.ProviderRepositoryCorrelation{
		{
			Provider: "claude", ConversationID: "session-1", RepositoryName: "service",
			RepositoryPath: "/worktree/one", WorkspacePath: "/worktree/one", Mode: "path",
			ObservedAt: time.Unix(90, 0),
		},
		{
			Provider: "claude", ConversationID: "session-1", RepositoryName: "service",
			RepositoryPath: "/worktree/two", WorkspacePath: "/worktree/two", Mode: "path",
			ObservedAt: time.Unix(110, 0),
		},
	}

	nameTasks, nameCoverage := correlateAndFilterProviderTasksWithResolver(
		[]providerLogTaskBuild{task}, correlations, nil,
		RepositoryCorrelationModeResolver(func(string) string { return "name" }),
	)
	if len(nameTasks) != 1 || nameCoverage.SessionCorrelatedCount != 1 {
		t.Fatalf("name mode treated historical paths for one repository as ambiguous: tasks=%+v coverage=%+v", nameTasks, nameCoverage)
	}
	nameTask := nameTasks[0].task
	if nameTask.RepositoryName != "service" || nameTask.RepositoryPath != "" || nameTask.WorkspacePath != "" {
		t.Fatalf("name mode did not redact historical path identity: %+v", nameTask)
	}

	pathTasks, pathCoverage := correlateAndFilterProviderTasksWithResolver(
		[]providerLogTaskBuild{task}, correlations, nil,
		RepositoryCorrelationModeResolver(func(string) string { return "path" }),
	)
	if len(pathTasks) != 1 || pathCoverage.AmbiguousTaskCount != 1 || pathTasks[0].task.RepositoryCorrelationStatus != "ambiguous" {
		t.Fatalf("path mode did not preserve distinct historical worktrees: tasks=%+v coverage=%+v", pathTasks, pathCoverage)
	}
}

func TestRepositoryPathComparisonPreservesCaseSensitiveFilesystemIdentity(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows path identity is case-insensitive")
	}
	root := t.TempDir()
	if sameRepositoryPath(filepath.Join(root, "Repo"), filepath.Join(root, "repo")) {
		t.Fatal("case-distinct nonexistent repository paths were treated as identical")
	}
}

func TestRepositoryPathFilterDistinguishesLinkedWorktrees(t *testing.T) {
	root := t.TempDir()
	repositoryPath := filepath.Join(root, "repository")
	worktreeA := filepath.Join(root, "worktree-a")
	worktreeB := filepath.Join(root, "worktree-b")
	gitDirectory := filepath.Join(repositoryPath, ".git")
	for _, workspace := range []string{worktreeA, worktreeB} {
		name := filepath.Base(workspace)
		worktreeGitDirectory := filepath.Join(gitDirectory, "worktrees", name)
		if err := os.MkdirAll(worktreeGitDirectory, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(workspace, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(worktreeGitDirectory, "commondir"), []byte("../..\n"), 0o644); err != nil {
			t.Fatal(err)
		}
		marker := "gitdir: " + worktreeGitDirectory + "\n"
		if err := os.WriteFile(filepath.Join(workspace, ".git"), []byte(marker), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	filter := repositoryFilterFromArgs(map[string]any{"repositoryPath": worktreeA})
	if filter == nil || !sameRepositoryPath(filter.RepositoryPath, repositoryPath) || !sameRepositoryPath(filter.workspacePath, worktreeA) {
		t.Fatalf("worktree filter lost repository identity: %+v", filter)
	}
	taskA := tokenUsageTask{
		RepositoryPath:              repositoryPath,
		WorkspacePath:               worktreeA,
		RepositoryCorrelationStatus: "task_correlated",
	}
	taskB := taskA
	taskB.WorkspacePath = worktreeB
	if !taskMatchesRepositoryFilter(taskA, filter) {
		t.Fatal("selected worktree did not match its repository filter")
	}
	if taskMatchesRepositoryFilter(taskB, filter) {
		t.Fatal("sibling worktree matched a worktree-specific repository filter")
	}

	repositoryFilter := repositoryFilterFromArgs(map[string]any{"repositoryPath": repositoryPath})
	if !taskMatchesRepositoryFilter(taskA, repositoryFilter) || !taskMatchesRepositoryFilter(taskB, repositoryFilter) {
		t.Fatal("canonical repository filter did not include linked worktrees")
	}
}

func TestToolsCallTokenUsageOverviewUsesExactClaudeMetricsOverMalformedLogs(t *testing.T) {
	t.Parallel()

	s := store.New()
	now := time.Now()
	s.AddLogsForConnection("claude", []store.LogRecord{{
		Timestamp: now,
		Body:      "claude_code.api_request",
		Attributes: map[string]any{
			"event.name":   "api_request",
			"session.id":   "metric-fallback-session",
			"input_tokens": "malformed",
		},
		Resource: store.Resource{ServiceName: "claude-code"},
	}})
	metric := func(tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name:        "claude_code.token.usage",
			Type:        "sum",
			Temporality: "cumulative",
			IsMonotonic: true,
			StartTime:   now,
			Timestamp:   now.Add(time.Second),
			Value:       value,
			Attributes: map[string]any{
				"session.id": "metric-fallback-session",
				"type":       tokenType,
			},
			Resource: store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddMetricsForConnection("claude", []store.MetricDataPoint{
		metric("input", 10),
		metric("cacheRead", 2),
		metric("cacheCreation", 3),
		metric("output", 4),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "metric-fallback-session"})
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 1 || data["measurementSource"] != "provider_metrics" || data["accountingStatus"] != "exact" {
		t.Fatalf("exact Claude metric fallback was suppressed or double counted: %+v", data)
	}
	task := toMapAny(tasks[0])
	if task["providerMetricCount"] != float64(4) || task["providerEventCount"] != float64(0) {
		t.Fatalf("weaker malformed log was retained beside exact metrics: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewUsesExactClaudeMetricsForMixedQualitySession(t *testing.T) {
	t.Parallel()

	s := store.New()
	now := time.Now()
	span := func(traceID, spanID, parentID, name string, offset time.Duration, attrs map[string]any) store.Span {
		return store.Span{
			TraceID: traceID, SpanID: spanID, ParentSpanID: parentID, Name: name,
			StartTime: now.Add(offset), EndTime: now.Add(offset + time.Millisecond), Attributes: attrs,
			Resource: store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddSpansForConnection("claude", []store.Span{
		span("exact-trace", "exact-interaction", "", "claude_code.interaction", 0, map[string]any{
			"prompt.id": "exact-prompt", "session.id": "mixed-quality-session",
		}),
		span("exact-trace", "exact-request", "exact-interaction", "claude_code.llm_request", time.Millisecond, nil),
		span("partial-trace", "partial-interaction", "", "claude_code.interaction", 2*time.Millisecond, map[string]any{
			"prompt.id": "partial-prompt", "session.id": "mixed-quality-session",
		}),
		span("partial-trace", "partial-request", "partial-interaction", "claude_code.llm_request", 3*time.Millisecond, nil),
	})
	s.AddLogsForConnection("claude", []store.LogRecord{
		{
			ID: "exact-log", Timestamp: now.Add(time.Millisecond), TraceID: "exact-trace", SpanID: "exact-request",
			Body: "claude_code.api_request", Resource: store.Resource{ServiceName: "claude-code"},
			Attributes: map[string]any{
				"event.name": "api_request", "request_id": "exact-request", "prompt.id": "exact-prompt",
				"session.id": "mixed-quality-session", "input_tokens": int64(10), "cache_read_tokens": int64(0),
				"cache_creation_tokens": int64(0), "output_tokens": int64(2),
			},
		},
		{
			ID: "partial-log", Timestamp: now.Add(3 * time.Millisecond), TraceID: "partial-trace", SpanID: "partial-request",
			Body: "claude_code.api_request", Resource: store.Resource{ServiceName: "claude-code"},
			Attributes: map[string]any{
				"event.name": "api_request", "request_id": "partial-request", "prompt.id": "partial-prompt",
				"session.id": "mixed-quality-session", "input_tokens": "malformed", "output_tokens": int64(1),
			},
		},
	})
	metric := func(tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", IsMonotonic: true,
			StartTime: now, Timestamp: now.Add(4 * time.Millisecond), Value: value,
			Attributes: map[string]any{"session.id": "mixed-quality-session", "type": tokenType},
			Resource:   store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddMetricsForConnection("claude", []store.MetricDataPoint{
		metric("input", 100),
		metric("cacheRead", 0),
		metric("cacheCreation", 0),
		metric("output", 20),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "mixed-quality-session"})
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 1 || data["measurementSource"] != "provider_metrics" || data["accountingStatus"] != "exact" {
		t.Fatalf("exact session metric did not replace all mixed-quality richer tasks: %+v", data)
	}
	task := toMapAny(tasks[0])
	usage := toMapAny(task["usage"])
	if task["providerMetricCount"] != float64(4) || task["providerEventCount"] != float64(0) || usage["effectiveTotalTokens"] != float64(120) {
		t.Fatalf("mixed-quality richer tasks were retained or the exact session total was lost: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewKeepsPostStartClaudeSubtotalPartialWhenSessionPredatesObserver(t *testing.T) {
	t.Parallel()

	s := store.New()
	now := time.Now().UTC().Add(time.Second)
	s.AddSpansForConnection("claude", []store.Span{
		{
			TraceID: "preexisting-session-trace", SpanID: "interaction", Name: "claude_code.interaction",
			StartTime: now, EndTime: now.Add(3 * time.Millisecond),
			Attributes: map[string]any{"prompt.id": "post-start-prompt", "session.id": "preexisting-session"},
			Resource:   store.Resource{ServiceName: "claude-code"},
		},
		{
			TraceID: "preexisting-session-trace", SpanID: "request", ParentSpanID: "interaction", Name: "claude_code.llm_request",
			StartTime: now.Add(time.Millisecond), EndTime: now.Add(2 * time.Millisecond),
			Resource: store.Resource{ServiceName: "claude-code"},
		},
	})
	s.AddLogsForConnection("claude", []store.LogRecord{{
		ID: "post-start-request", Timestamp: now.Add(time.Millisecond), TraceID: "preexisting-session-trace", SpanID: "request",
		Body: "claude_code.api_request", Resource: store.Resource{ServiceName: "claude-code"},
		Attributes: map[string]any{
			"event.name": "api_request", "request_id": "post-start-request", "prompt.id": "post-start-prompt",
			"session.id": "preexisting-session", "input_tokens": int64(10), "cache_read_tokens": int64(0),
			"cache_creation_tokens": int64(0), "output_tokens": int64(2),
		},
	}})
	metric := func(tokenType string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: "cumulative", IsMonotonic: true,
			StartTime: s.ProviderUsageMetricUnavailableThrough().Add(-time.Hour), Timestamp: now.Add(4 * time.Millisecond), Value: value,
			Attributes: map[string]any{"session.id": "preexisting-session", "type": tokenType},
			Resource:   store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddMetricsForConnection("claude", []store.MetricDataPoint{
		metric("input", 100),
		metric("cacheRead", 0),
		metric("cacheCreation", 0),
		metric("output", 20),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "preexisting-session"})
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 1 || data["accountingStatus"] != "partial" {
		t.Fatalf("post-start Claude subtotal hid incomplete pre-Observer session history: %+v", data)
	}
	task := toMapAny(tasks[0])
	usage := toMapAny(task["usage"])
	if task["status"] != "measured" || task["accountingStatus"] != "partial" || task["providerEventCount"] != float64(1) || task["providerMetricCount"] != float64(0) {
		t.Fatalf("known post-start Claude subtotal or source precedence is wrong: %+v", task)
	}
	if normalization, _ := task["normalization"].(string); !strings.Contains(normalization, "session predates retained Observer history") {
		t.Fatalf("session-history limitation is not explained: %+v", task)
	}
	if usage["effectiveTotalTokens"] != float64(12) {
		t.Fatalf("overlapping cumulative metric was added to the post-start subtotal: %+v", usage)
	}

	prompt := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"taskId": "post-start-prompt"})
	if prompt["accountingStatus"] != "exact" {
		t.Fatalf("session-level history evidence degraded the exact post-start prompt query: %+v", prompt)
	}
}

func TestSelectClaudeMetricFallbacksCarriesIncompleteSessionHistoryToLogsAndSpans(t *testing.T) {
	t.Parallel()

	richer := func(source string) providerLogTaskBuild {
		return providerLogTaskBuild{task: tokenUsageTask{
			Provider: "claude", ConversationID: "preexisting-session", MeasurementSource: source,
			Status: "measured", AccountingStatus: "exact", Normalization: "normalized provider usage",
		}}
	}
	metric := providerLogTaskBuild{
		task: tokenUsageTask{
			Provider: "claude", ConversationID: "preexisting-session", MeasurementSource: "claude_token_metrics",
			Status: "partial", AccountingStatus: "partial",
		},
		sessionHistoryIncomplete: true,
	}

	for _, test := range []struct {
		name      string
		logTasks  []providerLogTaskBuild
		spanTasks []providerLogTaskBuild
	}{
		{name: "logs", logTasks: []providerLogTaskBuild{richer("claude_api_request_logs")}},
		{name: "spans", spanTasks: []providerLogTaskBuild{richer("claude_interaction_span")}},
	} {
		t.Run(test.name, func(t *testing.T) {
			logs, spans, metrics := selectClaudeMetricFallbacks(test.logTasks, test.spanTasks, []providerLogTaskBuild{metric})
			selected := append(logs, spans...)
			if len(selected) != 1 || len(metrics) != 0 || selected[0].task.AccountingStatus != "partial" {
				t.Fatalf("incomplete session-history evidence was not carried to %s: logs=%+v spans=%+v metrics=%+v", test.name, logs, spans, metrics)
			}
			if !strings.Contains(selected[0].task.Normalization, "session predates retained Observer history") {
				t.Fatalf("%s history limitation is not explained: %+v", test.name, selected[0].task)
			}
		})
	}
}

func TestToolsCallTokenUsageOverviewDistinguishesClaudeMetricZeroMissingAndMalformed(t *testing.T) {
	now := time.Now().UTC()
	metric := func(sessionID, tokenType, temporality string, value float64) store.MetricDataPoint {
		return store.MetricDataPoint{
			Name: "claude_code.token.usage", Type: "sum", Temporality: temporality, Value: value,
			IsMonotonic: true, Timestamp: now.Add(time.Second), StartTime: now,
			Attributes: map[string]any{"session.id": sessionID, "model": "claude-haiku-4-5", "query_source": "main", "type": tokenType},
			Resource:   store.Resource{ServiceName: "claude-code"}, Scope: store.Scope{Name: "com.anthropic.claude_code"},
		}
	}

	t.Run("explicit zero", func(t *testing.T) {
		s := store.New()
		postStart := time.Now().UTC()
		for _, tokenType := range []string{"input", "cacheRead", "cacheCreation", "output"} {
			point := metric("zero-session", tokenType, "cumulative", 0)
			point.StartTime = postStart
			s.AddMetricsForConnection("claude", []store.MetricDataPoint{point})
		}
		data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "zero-session"})
		task := toMapAny(toSliceAny(data["tasks"])[0])
		usage := toMapAny(task["usage"])
		if task["status"] != "measured" || task["accountingStatus"] != "exact" || usage["inputTokens"] != float64(0) || usage["effectiveTotalTokens"] != float64(0) {
			t.Fatalf("explicit Claude metric zero was not measured: %+v", task)
		}
	})

	t.Run("absent", func(t *testing.T) {
		data := callTokenUsageOverview(t, NewDispatcher(store.New()), map[string]any{"provider": "claude"})
		if data["status"] != "absent" || data["accountingStatus"] != "unknown" || len(toSliceAny(data["tasks"])) != 0 {
			t.Fatalf("missing Claude metric usage was not absent: %+v", data)
		}
	})

	t.Run("missing components", func(t *testing.T) {
		s := store.New()
		s.AddMetricsForConnection("claude", []store.MetricDataPoint{metric("missing-components", "output", "delta", 2)})
		data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "missing-components"})
		task := toMapAny(toSliceAny(data["tasks"])[0])
		usage := toMapAny(task["usage"])
		if task["status"] != "partial" || task["accountingStatus"] != "partial" || usage["inputTokens"] != nil || usage["outputTokens"] != float64(2) || usage["effectiveTotalTokens"] != nil {
			t.Fatalf("missing Claude metric components were presented as exact: %+v", task)
		}
	})

	t.Run("unrecognized temporality and type", func(t *testing.T) {
		s := store.New()
		s.AddMetricsForConnection("claude", []store.MetricDataPoint{metric("unknown-session", "futureCache", "", 0)})
		data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "unknown-session"})
		task := toMapAny(toSliceAny(data["tasks"])[0])
		if task["status"] != "unrecognized" || task["accountingStatus"] != "unknown" || toMapAny(task["usage"])["effectiveTotalTokens"] != nil {
			t.Fatalf("unknown Claude metric semantics were guessed: %+v", task)
		}
	})

	t.Run("malformed and partial", func(t *testing.T) {
		s := store.New()
		points := []store.MetricDataPoint{
			metric("partial-session", "input", "delta", -1),
			metric("partial-session", "cacheRead", "delta", 0),
			metric("partial-session", "cacheCreation", "delta", 0),
			metric("partial-session", "output", "delta", 0),
		}
		s.AddMetricsForConnection("claude", points)
		data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "partial-session"})
		task := toMapAny(toSliceAny(data["tasks"])[0])
		usage := toMapAny(task["usage"])
		if task["status"] != "partial" || task["accountingStatus"] != "partial" || usage["inputTokens"] != nil || usage["cachedInputTokens"] != float64(0) || usage["outputTokens"] != float64(0) || usage["effectiveTotalTokens"] != nil {
			t.Fatalf("malformed/partial Claude metrics were not reported distinctly: %+v", task)
		}
	})
}

func TestToolsCallTokenUsageOverviewRetainsClaudeLogsAfterGenericLogEviction(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("claude", []store.Span{{
		TraceID: "claude-retained-log", SpanID: "interaction", Name: "claude_code.interaction",
		StartTime: now, EndTime: now.Add(3 * time.Millisecond),
		Attributes: map[string]any{"prompt.id": "retained-log-prompt", "session.id": "retained-log-session"},
		Resource:   store.Resource{ServiceName: "claude-code"},
	}})
	s.AddLogsForConnection("claude", []store.LogRecord{{
		ID: "claude-usage", Timestamp: now.Add(time.Millisecond), TraceID: "claude-retained-log", Body: "claude_code.api_request",
		Attributes: map[string]any{
			"event.name": "api_request", "request_id": "request-1", "prompt.id": "retained-log-prompt", "session.id": "retained-log-session",
			"input_tokens": int64(5), "cache_read_tokens": int64(10), "cache_creation_tokens": int64(2), "output_tokens": int64(4),
		},
		Resource: store.Resource{ServiceName: "claude-code"},
	}})
	noise := make([]store.LogRecord, store.DefaultLogCap+1)
	for index := range noise {
		noise[index] = store.LogRecord{ID: fmt.Sprintf("noise-%d", index), Timestamp: now.Add(time.Second), Body: "noise"}
	}
	s.AddLogsForConnection("noise", noise)
	for _, record := range s.SnapshotLogs() {
		if store.ClassifyProviderUsageLog(record) != store.ProviderUsageLogUnknown {
			t.Fatal("fixture did not evict the Claude usage event from the generic log ring")
		}
	}

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"conversationId": "retained-log-session"})
	if data["measurementSource"] != "provider_logs" || data["accountingStatus"] != "exact" {
		t.Fatalf("dedicated Claude log retention was not used: %+v", data)
	}
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["providerEventCount"] != float64(1) || task["traceComplete"] != true {
		t.Fatalf("retained Claude task diagnostics are wrong: %+v", task)
	}
	usage := toMapAny(task["usage"])
	if usage["inputTokens"] != float64(17) || usage["effectiveTotalTokens"] != float64(21) {
		t.Fatalf("retained Claude usage was normalized incorrectly: %+v", usage)
	}
}

func TestToolsCallTokenUsageOverviewReportsPartialClaudeRequestCoverage(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("claude", []store.Span{{
		TraceID: "claude-partial", SpanID: "interaction", Name: "claude_code.interaction",
		StartTime: now, EndTime: now.Add(3 * time.Millisecond),
		Attributes: map[string]any{"prompt.id": "partial-prompt", "session.id": "partial-session"},
		Resource:   store.Resource{ServiceName: "claude-code"},
	}})
	requestLog := func(id string, offset time.Duration, attrs map[string]any) store.LogRecord {
		attrs["event.name"] = "api_request"
		attrs["request_id"] = id
		attrs["prompt.id"] = "partial-prompt"
		attrs["session.id"] = "partial-session"
		return store.LogRecord{
			ID: id, Timestamp: now.Add(offset), TraceID: "claude-partial", Body: "claude_code.api_request",
			Attributes: attrs, Resource: store.Resource{ServiceName: "claude-code"},
		}
	}
	s.AddLogsForConnection("claude", []store.LogRecord{
		requestLog("measured", time.Millisecond, map[string]any{
			"input_tokens": int64(5), "cache_read_tokens": int64(0), "cache_creation_tokens": int64(0), "output_tokens": int64(2),
		}),
		requestLog("missing", 2*time.Millisecond, map[string]any{"model": "claude-sonnet-4-6"}),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"taskId": "partial-prompt"})
	task := toMapAny(toSliceAny(data["tasks"])[0])
	if task["status"] != "partial" || task["accountingStatus"] != "partial" || task["requestCount"] != float64(2) {
		t.Fatalf("partial Claude request coverage was not preserved: %+v", task)
	}
	coverage := toMapAny(task["coverage"])
	if coverage["recordCount"] != float64(2) || coverage["effectiveTotalCount"] != float64(1) {
		t.Fatalf("partial Claude coverage counts are wrong: %+v", coverage)
	}
}

func TestToolsCallTokenUsageOverviewOmitsInProgressTurnFromExplicitCompletedConversation(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("codex", []store.Span{{
		TraceID: "completed-trace", SpanID: "completed-boundary", Name: "session_task.turn",
		StartTime: now, EndTime: now.Add(5 * time.Second),
		Attributes: map[string]any{
			"thread.id": "completed-thread", "turn.id": "audit-turn",
			"codex.turn.token_usage.input_tokens": int64(100), "codex.turn.token_usage.output_tokens": int64(20),
			"codex.turn.token_usage.total_tokens": int64(120),
		},
		Resource: store.Resource{ServiceName: "codex-app-server"},
	}})
	providerLog := func(id string, timestamp time.Time, input, output, total int64) store.LogRecord {
		return store.LogRecord{
			ID: id, Timestamp: timestamp,
			Attributes: map[string]any{
				"event.name": "codex.sse_event", "event.kind": "response.completed", "conversation.id": "completed-thread",
				"response.id": id, "input_token_count": input, "output_token_count": output, "tool_token_count": total,
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		}
	}
	s.AddLogsForConnection("codex", []store.LogRecord{
		providerLog("audit-response", now.Add(4*time.Second), 100, 20, 120),
		providerLog("query-turn-response", now.Add(10*time.Second), 10, 2, 12),
	})

	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"threadId": "completed-thread"})
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 1 || data["accountingStatus"] != "exact" || toMapAny(data["usage"])["effectiveTotalTokens"] != float64(120) {
		t.Fatalf("in-progress query-turn usage contaminated the completed audit: %+v", data)
	}
	if task := toMapAny(tasks[0]); task["taskId"] != "audit-turn" || task["traceComplete"] != true {
		t.Fatalf("wrong completed task selected: %+v", task)
	}
}

func TestToolsCallTokenUsageOverviewConsumesCodexAndClaudeOTLPLogs(t *testing.T) {
	logs := plog.NewLogs()
	appendLog := func(serviceName, scopeName, body string, timestamp time.Time, attrs map[string]any) {
		resourceLogs := logs.ResourceLogs().AppendEmpty()
		resourceLogs.Resource().Attributes().PutStr("service.name", serviceName)
		scopeLogs := resourceLogs.ScopeLogs().AppendEmpty()
		scopeLogs.Scope().SetName(scopeName)
		record := scopeLogs.LogRecords().AppendEmpty()
		if !timestamp.IsZero() {
			record.SetTimestamp(pcommon.NewTimestampFromTime(timestamp))
		}
		record.Body().SetStr(body)
		for key, value := range attrs {
			switch typed := value.(type) {
			case string:
				record.Attributes().PutStr(key, typed)
			case int64:
				record.Attributes().PutInt(key, typed)
			default:
				t.Fatalf("unsupported OTLP fixture attribute %s=%T", key, value)
			}
		}
	}
	appendLog("Codex Desktop", "codex_otel", "", time.Time{}, map[string]any{
		"event.name":            "codex.sse_event",
		"event.kind":            "response.completed",
		"event.sequence":        int64(7),
		"conversation.id":       "codex-otlp",
		"input_token_count":     int64(100),
		"cached_token_count":    int64(40),
		"output_token_count":    int64(20),
		"reasoning_token_count": int64(5),
		"tool_token_count":      int64(120),
	})
	appendLog("claude-code", "com.anthropic.claude_code.events", "claude_code.api_request", time.Now(), map[string]any{
		"event.name":            "api_request",
		"request_id":            "claude-request",
		"prompt.id":             "claude-otlp",
		"input_tokens":          int64(10),
		"cache_read_tokens":     int64(20),
		"cache_creation_tokens": int64(30),
		"output_tokens":         int64(5),
	})

	s := store.New()
	s.AddLogsForConnection("", otlp.ConvertLogs(logs))
	data := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{})
	tasks := toSliceAny(data["tasks"])
	if len(tasks) != 2 {
		t.Fatalf("expected both OTLP provider tasks, got %+v", tasks)
	}
	byProvider := make(map[string]map[string]any, len(tasks))
	for _, value := range tasks {
		task := toMapAny(value)
		byProvider[task["provider"].(string)] = task
	}
	if byProvider["codex"]["startTime"] != "" || byProvider["codex"]["endTime"] != "" {
		t.Fatalf("missing Codex OTLP timestamp should remain unknown: %+v", byProvider["codex"])
	}
	if got := toMapAny(byProvider["codex"]["usage"])["effectiveTotalTokens"]; got != float64(120) {
		t.Fatalf("Codex OTLP total = %#v, want 120", got)
	}
	claudeUsage := toMapAny(byProvider["claude"]["usage"])
	if claudeUsage["inputTokens"] != float64(60) || claudeUsage["derivedTotalTokens"] != float64(65) {
		t.Fatalf("Claude OTLP cache normalization is wrong: %+v", claudeUsage)
	}
}

func TestToolsCallTokenUsageOverviewProviderLogCoverageAndSourcePrecedence(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)
	now := time.Now()
	logRecord := func(id, conversation string, offset time.Duration, attrs map[string]any) store.LogRecord {
		attrs["event.name"] = "codex.sse_event"
		attrs["event.kind"] = "response.completed"
		attrs["conversation.id"] = conversation
		return store.LogRecord{
			ID:         id,
			Timestamp:  now.Add(offset),
			Attributes: attrs,
			Resource:   store.Resource{ServiceName: "Codex Desktop"},
		}
	}
	s.AddLogsForConnection("", []store.LogRecord{
		logRecord("zero", "zero", 0, map[string]any{
			"input_token_count":     int64(0),
			"cached_token_count":    int64(0),
			"output_token_count":    int64(0),
			"reasoning_token_count": int64(0),
			"tool_token_count":      int64(0),
		}),
		logRecord("absent", "absent", time.Millisecond, map[string]any{"model": "gpt-5.4"}),
		logRecord("malformed", "malformed", 2*time.Millisecond, map[string]any{
			"input_token_count":  "not-a-count",
			"output_token_count": int64(-1),
		}),
		logRecord("unrecognized", "unrecognized", 3*time.Millisecond, map[string]any{
			"mystery_token_count": int64(12),
		}),
	})
	s.AddSpansForConnection("", []store.Span{{
		TraceID:   "would-double-count",
		SpanID:    "llm",
		Name:      "chat",
		StartTime: now,
		EndTime:   now.Add(time.Millisecond),
		Attributes: map[string]any{
			"gen_ai.operation.name":      "chat",
			"gen_ai.provider.name":       "openai",
			"gen_ai.usage.input_tokens":  int64(999),
			"gen_ai.usage.output_tokens": int64(1),
		},
		Resource: store.Resource{ServiceName: "Codex Desktop"},
	}})

	data := callTokenUsageOverview(t, d, map[string]any{"serviceName": "Codex Desktop"})
	if data["measurementSource"] != "provider_logs" || len(toSliceAny(data["traces"])) != 0 {
		t.Fatalf("span usage was combined with provider logs: %+v", data)
	}
	if got := toMapAny(data["usage"])["effectiveTotalTokens"]; got != float64(0) {
		t.Fatalf("explicit zero should be the only measured total, got %#v", got)
	}
	byID := make(map[string]map[string]any)
	for _, value := range toSliceAny(data["tasks"]) {
		task := toMapAny(value)
		byID[task["taskId"].(string)] = task
	}
	if byID["zero"]["status"] != "measured" || toMapAny(byID["zero"]["usage"])["effectiveTotalTokens"] != float64(0) {
		t.Fatalf("explicit zero was not preserved: %+v", byID["zero"])
	}
	if byID["absent"]["status"] != "absent" || toMapAny(byID["absent"]["usage"])["effectiveTotalTokens"] != nil {
		t.Fatalf("absent provider usage was not kept unknown: %+v", byID["absent"])
	}
	for _, taskID := range []string{"malformed", "unrecognized"} {
		if byID[taskID]["status"] != "unrecognized" || toMapAny(byID[taskID]["usage"])["effectiveTotalTokens"] != nil {
			t.Fatalf("%s usage was not marked unrecognized: %+v", taskID, byID[taskID])
		}
	}
}

func TestToolsCallTokenUsageOverviewIgnoresNonUsageTokenMetadata(t *testing.T) {
	t.Parallel()

	providerLog := func(conversationID string, attrs map[string]any) store.LogRecord {
		attrs["event.name"] = "codex.sse_event"
		attrs["event.kind"] = "response.completed"
		attrs["conversation.id"] = conversationID
		return store.LogRecord{
			Timestamp:  time.Now(),
			Attributes: attrs,
			Resource:   store.Resource{ServiceName: "codex-app-server"},
		}
	}

	absentStore := store.New()
	absentStore.AddLogsForConnection("codex", []store.LogRecord{
		providerLog("metadata-only", map[string]any{"max_tokens": int64(4096)}),
	})
	absent := callTokenUsageOverview(t, NewDispatcher(absentStore), map[string]any{"conversationId": "metadata-only"})
	if absent["status"] != "absent" || absent["accountingStatus"] != "unknown" {
		t.Fatalf("non-usage token metadata was treated as observed usage: %+v", absent)
	}

	unrecognizedStore := store.New()
	unrecognizedStore.AddLogsForConnection("codex", []store.LogRecord{
		providerLog("malformed-usage", map[string]any{"input_token_count": "not-a-number"}),
	})
	unrecognized := callTokenUsageOverview(t, NewDispatcher(unrecognizedStore), map[string]any{"conversationId": "malformed-usage"})
	if unrecognized["status"] != "unrecognized" || unrecognized["accountingStatus"] != "unknown" {
		t.Fatalf("malformed known usage was not distinguished from absence: %+v", unrecognized)
	}
}

func TestToolsCallTokenUsageOverviewIgnoresMalformedProviderEventsAndFallsBackToSpans(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)
	now := time.Now()
	s.AddLogsForConnection("", []store.LogRecord{{
		ID:        "wrong-kind",
		Timestamp: now,
		Attributes: map[string]any{
			"event.name":        "codex.sse_event",
			"event.kind":        "response.failed",
			"conversation.id":   "ignored",
			"input_token_count": int64(500),
		},
		Resource: store.Resource{ServiceName: "Codex Desktop"},
	}})
	s.AddSpansForConnection("", []store.Span{{
		TraceID:   "span-fallback",
		SpanID:    "llm",
		Name:      "chat",
		StartTime: now,
		EndTime:   now.Add(time.Millisecond),
		Attributes: map[string]any{
			"gen_ai.operation.name":      "chat",
			"gen_ai.usage.input_tokens":  int64(9),
			"gen_ai.usage.output_tokens": int64(1),
		},
		Resource: store.Resource{ServiceName: "Codex Desktop"},
	}})

	data := callTokenUsageOverview(t, d, map[string]any{})
	if data["measurementSource"] != "gen_ai_spans" || len(toSliceAny(data["tasks"])) != 0 || len(toSliceAny(data["traces"])) != 1 {
		t.Fatalf("malformed provider event blocked span fallback: %+v", data)
	}
	if got := toMapAny(data["usage"])["effectiveTotalTokens"]; got != float64(10) {
		t.Fatalf("unexpected span fallback total: %#v", got)
	}
	if len(s.SnapshotLogs()) != 1 {
		t.Fatal("raw malformed provider event was not retained")
	}
}

func TestFormatTokenUsageTimeTreatsMissingOTLPTimestampsAsUnknown(t *testing.T) {
	if got := formatTokenUsageTime(time.Unix(0, 0)); got != "" {
		t.Fatalf("Unix epoch timestamp = %q, want unknown", got)
	}
	want := "2026-08-25T12:34:56.000000007Z"
	if got := formatTokenUsageTime(time.Date(2026, 8, 25, 12, 34, 56, 7, time.UTC)); got != want {
		t.Fatalf("valid provider timestamp = %q, want %q", got, want)
	}
}

func TestProviderLogWindowCompletenessUsesAvailabilityWatermark(t *testing.T) {
	start := time.Date(2026, time.August, 26, 12, 0, 0, 0, time.UTC)
	metadata := providerTraceMetadata{startTime: start}
	if !providerLogWindowComplete(metadata, time.Time{}) {
		t.Fatal("a provider log window with no unavailable-history boundary was treated as truncated")
	}
	if !providerLogWindowComplete(metadata, start.Add(-time.Nanosecond)) {
		t.Fatal("an unavailable-history boundary before the task start was treated as task truncation")
	}
	if providerLogWindowComplete(metadata, start) {
		t.Fatal("an unavailable-history boundary at the task start did not invalidate log completeness")
	}
}

func TestReconcileClaudeTaskEventsRequiresCompleteWindowWithoutRequestSpans(t *testing.T) {
	events := []providerLogTokenEvent{{provider: "claude", stableIdentity: true}}
	metadata := providerTraceMetadata{provider: "claude", taskComplete: true}

	if _, reconciled := reconcileClaudeTaskEvents(events, metadata, false); reconciled {
		t.Fatal("a truncated Claude provider-log window was reconciled without request-span evidence")
	}
	if _, reconciled := reconcileClaudeTaskEvents(events, metadata, true); !reconciled {
		t.Fatal("a complete Claude provider-log window was not accepted")
	}
	events[0].stableIdentity = false
	if _, reconciled := reconcileClaudeTaskEvents(events, metadata, true); reconciled {
		t.Fatal("identifier-less Claude records were accepted as exact without request-span evidence")
	}
}

func callTokenUsageOverview(t *testing.T, dispatcher *Dispatcher, args map[string]any) map[string]any {
	t.Helper()
	resp, handled := dispatcher.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_token_usage_overview",
			"arguments": args,
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected token usage response: %+v", resp)
	}
	return toMapAny(parseToolResult(t, resp.Result.(toolResult)))
}

func TestTokenUsageToolDescriptionGuidesNaturalQuestions(t *testing.T) {
	tools := buildToolDefs(false)
	for _, tool := range tools {
		if tool.Name != "observer_token_usage_overview" {
			continue
		}
		if !containsAll(tool.Description, "recent task or audit", "Codex thread or Claude session ID", "completed native task/request spans", "incomplete or evicted", "cached input", "reasoning output", "repository name or absolute path", "accountingStatus=exact describes token accounting only", "Null means unknown", "evaluation-only judge branches are excluded") {
			t.Fatalf("token usage description lost natural-language guidance: %q", tool.Description)
		}
		if _, ok := tool.InputSchema.Properties["conversationId"]; !ok {
			t.Fatal("token usage schema lost the Codex thread / Claude session filter")
		}
		if _, ok := tool.InputSchema.Properties["threadId"]; !ok {
			t.Fatal("token usage schema lost the observed Codex threadId alias")
		}
		if _, ok := tool.InputSchema.Properties["repositoryName"]; !ok {
			t.Fatal("token usage schema lost the repository name filter")
		}
		if _, ok := tool.InputSchema.Properties["repositoryPath"]; !ok {
			t.Fatal("token usage schema lost the repository path filter")
		}
		return
	}
	t.Fatal("observer_token_usage_overview tool not found")
}

func TestTokenUsageFromSpanPreservesProviderCacheAndReasoningSemantics(t *testing.T) {
	claude := tokenUsageFromSpan(store.Span{Attributes: map[string]any{
		"gen_ai.provider.name":        "anthropic",
		"input_tokens":                int64(5),
		"cache_read_input_tokens":     int64(10),
		"cache_creation_input_tokens": int64(20),
		"output_tokens":               int64(8),
		"thinking_tokens":             int64(3),
	}})
	if claude.provider != "claude" || claude.usage.InputTokens == nil || *claude.usage.InputTokens != 35 {
		t.Fatalf("Claude cache components were not added to normalized input: %+v", claude)
	}
	if claude.usage.DerivedTotalTokens == nil || *claude.usage.DerivedTotalTokens != 43 {
		t.Fatalf("Claude derived total is wrong: %+v", claude.usage)
	}
	if claude.usage.ReasoningOutputTokens == nil || *claude.usage.ReasoningOutputTokens != 3 {
		t.Fatalf("Claude thinking breakdown was lost: %+v", claude.usage)
	}

	codex := tokenUsageFromSpan(store.Span{Attributes: map[string]any{
		"gen_ai.provider.name":             "openai",
		"gen_ai.usage.input_tokens":        int64(35),
		"gen_ai.usage.cached_input_tokens": int64(10),
		"gen_ai.usage.output_tokens":       int64(8),
		"gen_ai.usage.reasoning_tokens":    int64(3),
	}})
	if codex.provider != "codex" || codex.usage.InputTokens == nil || *codex.usage.InputTokens != 35 {
		t.Fatalf("Codex cached input was incorrectly subtracted or added: %+v", codex)
	}
	if codex.usage.OutputTokens == nil || *codex.usage.OutputTokens != 8 {
		t.Fatalf("Codex output was incorrectly adjusted for reasoning: %+v", codex)
	}
	if _, valid := nonNegativeInt64(float64(math.MaxInt64)); valid {
		t.Fatal("out-of-range float token count was accepted")
	}
}

func TestTokenUsageSpanSelectionScalesToRetentionCap(t *testing.T) {
	spans := make([]store.Span, store.DefaultSpanCap)
	for index := range spans {
		spanID := fmt.Sprintf("span-%05d", index)
		parentID := ""
		if index > 0 {
			parentID = fmt.Sprintf("span-%05d", index-1)
		}
		spans[index] = store.Span{
			SpanID:       spanID,
			ParentSpanID: parentID,
			Name:         "chat",
			Attributes: map[string]any{
				"gen_ai.operation.name":     "chat",
				"gen_ai.usage.input_tokens": int64(1),
			},
		}
	}

	filtered := filterAgentTaskSpans(spans)
	if len(filtered) != len(spans) {
		t.Fatalf("retention-cap agent filter kept %d spans, want %d", len(filtered), len(spans))
	}
	selected, source := selectTokenUsageSpans(filtered)
	if source != "llm_spans" || len(selected) != 1 || selected[0].SpanID != spans[len(spans)-1].SpanID {
		t.Fatalf("retention-cap span selection = %q %+v, want deepest LLM span", source, selected)
	}
	if count := providerClaudeRequestSpanCount(spans); count != 1 {
		t.Fatalf("retention-cap Claude request count = %d, want 1", count)
	}
}

func TestProviderTaskSpanIndexScalesToRetentionCap(t *testing.T) {
	spans := make([]store.Span, store.DefaultSpanCap)
	for index := range spans {
		spanID := fmt.Sprintf("span-%05d", index)
		parentID := ""
		if index > 0 {
			parentID = fmt.Sprintf("span-%05d", index-1)
		}
		spans[index] = store.Span{
			TraceID: "retention-cap-trace", SpanID: spanID, ParentSpanID: parentID, Name: "chat",
			Attributes: map[string]any{"gen_ai.operation.name": "chat"},
			Resource:   store.Resource{ServiceName: "codex-app-server"},
		}
	}
	spans[0].Name = "session_task.turn"
	spans[0].Attributes = map[string]any{"turn.id": "retention-cap-turn"}

	groups, boundaryOrder, assignments := providerTaskSpanGroups(spans)
	if len(boundaryOrder) != 1 || boundaryOrder[0] != spans[0].SpanID || len(assignments) != len(spans) {
		t.Fatalf("retention-cap provider task index = boundaries %+v, assignments %d", boundaryOrder, len(assignments))
	}
	group := groups[spans[0].SpanID]
	if len(group) != len(spans) {
		t.Fatalf("retention-cap provider task group kept %d spans, want %d", len(group), len(spans))
	}
	metadata := buildProviderTraceMetadata(spans[0].TraceID, group)
	if metadata.spanCount != len(spans) || len(metadata.evaluationSpanIDs) != 0 {
		t.Fatalf("retention-cap provider metadata = %+v", metadata)
	}
}

func TestProviderTraceIndexScalesAcrossRetentionCapBoundaries(t *testing.T) {
	spans := make([]store.Span, store.DefaultSpanCap)
	for index := range spans {
		spanID := fmt.Sprintf("turn-%05d", index)
		spans[index] = store.Span{
			TraceID: "many-turns-trace",
			SpanID:  spanID,
			Name:    "session_task.turn",
			Attributes: map[string]any{
				"turn.id": spanID,
			},
			Resource: store.Resource{ServiceName: "codex-app-server"},
		}
	}

	index := buildProviderTraceIndex(map[string][]store.Span{"many-turns-trace": spans})
	if len(index.tasks) != len(spans) || len(index.taskBySpan) != len(spans) {
		t.Fatalf("many-boundary provider index = %d tasks, %d assigned spans", len(index.tasks), len(index.taskBySpan))
	}
}

func TestSpanAncestryIndexPreservesCycleSemantics(t *testing.T) {
	index := newSpanAncestryIndex(map[string]string{
		"cycle-a": "cycle-b",
		"cycle-b": "cycle-a",
		"child":   "cycle-a",
	})

	singleCandidate := index.candidatesWithDescendants(map[string]struct{}{"cycle-a": {}})
	if _, selfDescendant := singleCandidate["cycle-a"]; selfDescendant {
		t.Fatal("a candidate was treated as its own descendant through a parent cycle")
	}
	multipleCandidates := index.candidatesWithDescendants(map[string]struct{}{"cycle-a": {}, "cycle-b": {}})
	if _, found := multipleCandidates["cycle-a"]; !found {
		t.Fatal("cycle-a did not recognize cycle-b as a descendant")
	}
	if _, found := multipleCandidates["cycle-b"]; !found {
		t.Fatal("cycle-b did not recognize cycle-a as a descendant")
	}

	withAncestor := index.idsWithAncestor(map[string]struct{}{"cycle-a": {}})
	for _, spanID := range []string{"cycle-a", "cycle-b", "child"} {
		if _, found := withAncestor[spanID]; !found {
			t.Fatalf("%s did not recognize cycle-a as an ancestor: %+v", spanID, withAncestor)
		}
	}
}

func TestSpanAncestryIndexMatchesReferenceAncestry(t *testing.T) {
	spanIDs := []string{"a", "b", "c", "d"}
	parentChoices := []string{"", "a", "b", "c", "d", "missing"}
	graphCount := 1
	for range spanIDs {
		graphCount *= len(parentChoices)
	}

	for graph := 0; graph < graphCount; graph++ {
		encoded := graph
		parentByID := make(map[string]string, len(spanIDs))
		for _, spanID := range spanIDs {
			parentByID[spanID] = parentChoices[encoded%len(parentChoices)]
			encoded /= len(parentChoices)
		}
		index := newSpanAncestryIndex(parentByID)

		for mask := 0; mask < 1<<len(spanIDs); mask++ {
			candidates := make(map[string]struct{})
			for candidateIndex, spanID := range spanIDs {
				if mask&(1<<candidateIndex) != 0 {
					candidates[spanID] = struct{}{}
				}
			}

			withDescendants := index.candidatesWithDescendants(candidates)
			withAncestor := index.idsWithAncestor(candidates)
			inBranches := index.idsInBranches(candidates)
			nearest := index.nearestAncestorOrSelf(candidates)
			for _, spanID := range spanIDs {
				if _, candidate := candidates[spanID]; candidate {
					_, gotDescendant := withDescendants[spanID]
					wantDescendant := referenceHasDescendantInSet(spanID, parentByID, candidates)
					if gotDescendant != wantDescendant {
						t.Fatalf("descendant mismatch for parents=%+v candidates=%+v span=%q: got %t, want %t", parentByID, candidates, spanID, gotDescendant, wantDescendant)
					}
				}
				_, gotAncestor := withAncestor[spanID]
				wantAncestor := referenceHasAncestorInSet(spanID, parentByID, candidates)
				if gotAncestor != wantAncestor {
					t.Fatalf("ancestor mismatch for parents=%+v candidates=%+v span=%q: got %t, want %t", parentByID, candidates, spanID, gotAncestor, wantAncestor)
				}
				_, gotInBranch := inBranches[spanID]
				wantNearest := referenceNearestAncestorOrSelf(spanID, parentByID, candidates)
				if wantInBranch := wantNearest != ""; gotInBranch != wantInBranch {
					t.Fatalf("branch mismatch for parents=%+v roots=%+v span=%q: got %t, want %t", parentByID, candidates, spanID, gotInBranch, wantInBranch)
				}
				if gotNearest := nearest[spanID]; gotNearest != wantNearest {
					t.Fatalf("nearest mismatch for parents=%+v roots=%+v span=%q: got %q, want %q", parentByID, candidates, spanID, gotNearest, wantNearest)
				}
			}
		}
	}
}

func referenceHasDescendantInSet(spanID string, parentByID map[string]string, ids map[string]struct{}) bool {
	for candidateID := range ids {
		if candidateID != spanID && referenceHasAncestorID(candidateID, spanID, parentByID) {
			return true
		}
	}
	return false
}

func referenceHasAncestorID(spanID, ancestorID string, parentByID map[string]string) bool {
	seen := make(map[string]struct{})
	for parentID := parentByID[spanID]; parentID != ""; parentID = parentByID[parentID] {
		if parentID == ancestorID {
			return true
		}
		if _, visited := seen[parentID]; visited {
			return false
		}
		seen[parentID] = struct{}{}
	}
	return false
}

func referenceNearestAncestorOrSelf(spanID string, parentByID map[string]string, ids map[string]struct{}) string {
	seen := make(map[string]struct{})
	for spanID != "" {
		if _, found := ids[spanID]; found {
			return spanID
		}
		if _, duplicate := seen[spanID]; duplicate {
			return ""
		}
		seen[spanID] = struct{}{}
		parentID, retained := parentByID[spanID]
		if !retained {
			return ""
		}
		spanID = parentID
	}
	return ""
}

func referenceHasAncestorInSet(spanID string, parentByID map[string]string, ids map[string]struct{}) bool {
	seen := make(map[string]struct{})
	for parentID := parentByID[spanID]; parentID != ""; parentID = parentByID[parentID] {
		if _, candidate := ids[parentID]; candidate {
			return true
		}
		if _, visited := seen[parentID]; visited {
			return false
		}
		seen[parentID] = struct{}{}
	}
	return false
}

func TestTokenUsageAccumulatorOverflowIsUnknownAndPartial(t *testing.T) {
	maximum := int64(math.MaxInt64)
	one := int64(1)
	zero := int64(0)
	records := []tokenUsageRecord{
		{
			observed:   true,
			recognized: true,
			usage: tokenUsageValues{
				InputTokens:          &maximum,
				CachedInputTokens:    &zero,
				EffectiveTotalTokens: &maximum,
			},
		},
		{
			observed:   true,
			recognized: true,
			usage: tokenUsageValues{
				InputTokens:          &one,
				CachedInputTokens:    &zero,
				EffectiveTotalTokens: &one,
			},
		},
	}

	var aggregate tokenUsageAccumulator
	aggregate.addTask(records)
	usage := aggregate.values()
	if usage.InputTokens != nil || usage.EffectiveTotalTokens != nil {
		t.Fatalf("overflowed token totals must be unknown: %+v", usage)
	}
	if usage.CachedInputTokens == nil || *usage.CachedInputTokens != 0 {
		t.Fatalf("explicit zero was lost while handling overflow: %+v", usage)
	}
	if aggregate.coverage.FieldCounts.InputTokens != 2 || aggregate.coverage.EffectiveTotalCount != 2 {
		t.Fatalf("overflow discarded measurement coverage: %+v", aggregate.coverage)
	}
	if aggregate.status() != "partial" {
		t.Fatalf("overflow status = %q, want partial", aggregate.status())
	}
	tasks := []tokenUsageTask{{AccountingStatus: "exact"}}
	if status := providerTasksAggregateAccountingStatus(tasks, aggregate); status != "partial" {
		t.Fatalf("overflow accounting status = %q, want partial", status)
	}
}

func TestValidationToolDescriptionsGuideNaturalUsage(t *testing.T) {
	tools := buildToolDefs(false)
	index := make(map[string]toolDef, len(tools))
	for _, tool := range tools {
		index[tool.Name] = tool
	}

	if got := index["observer_validation_status"].Description; !containsAll(got, "whether validation has run", "run is currently in progress") {
		t.Fatalf("status description lost guidance: %q", got)
	}
	if got := index["observer_validation_analyze"].Description; !containsAll(got, "Primary validation tool", "automatically runs validation", "based on the prior run time") {
		t.Fatalf("analyze description lost guidance: %q", got)
	}
	if got := index["observer_validation_refresh"].Description; !containsAll(got, "Explicitly run validation", "explicitly asks to run, re-run, refresh") {
		t.Fatalf("refresh description lost guidance: %q", got)
	}
}

func TestToolsCallValidationRefresh(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	runner := &fakeValidationRunner{
		onRun: func(context.Context) validator.Summary {
			summary := v.StartRun("run-1", time.Unix(10, 0))
			go func() {
				time.Sleep(20 * time.Millisecond)
				v.CompleteRun("run-1", map[string]validator.Entity{
					"metric:checkout::http.server.duration": {
						Key:             "metric:checkout::http.server.duration",
						HighestSeverity: validator.SeverityImprovement,
						Signal:          validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
						UpdatedAt:       time.Unix(20, 0),
						Findings: []validator.Finding{{
							EntityKey: "metric:checkout::http.server.duration",
							Source:    "weaver",
							RuleID:    "deprecated",
							Severity:  validator.SeverityImprovement,
							Message:   "deprecated metric",
							Signal:    validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
							UpdatedAt: time.Unix(20, 0),
						}},
					},
				}, validator.RunStats{}, time.Unix(20, 0))
			}()
			return summary
		},
	}
	d := NewDispatcher(s, v, runner)

	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_validation_refresh",
			"arguments": map[string]any{
				"timeoutSeconds": 5,
			},
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}
	if runner.calls != 1 {
		t.Fatalf("expected runner to be called once, got %d", runner.calls)
	}
	data := parseToolResult(t, resp.Result.(toolResult))
	analysis := toMapAny(data)
	if analysis["analysisBasis"] != "fresh_run" {
		t.Fatalf("unexpected refresh analysis: %+v", analysis)
	}
}

func TestToolsCallValidationAnalyzeAutoRunsWhenNoResult(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
	runner := &fakeValidationRunner{
		onRun: func(context.Context) validator.Summary {
			summary := v.StartRun("run-2", time.Unix(10, 0))
			go func() {
				time.Sleep(20 * time.Millisecond)
				v.CompleteRun("run-2", map[string]validator.Entity{
					"span:trace-1:span-1": {
						Key:             "span:trace-1:span-1",
						HighestSeverity: validator.SeverityViolation,
						Signal:          validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
						UpdatedAt:       time.Unix(20, 0),
						Findings: []validator.Finding{{
							EntityKey: "span:trace-1:span-1",
							Source:    "weaver",
							RuleID:    "missing_attribute",
							Severity:  validator.SeverityViolation,
							Message:   "missing attribute",
							Signal:    validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
							UpdatedAt: time.Unix(20, 0),
						}},
					},
				}, validator.RunStats{}, time.Unix(20, 0))
			}()
			return summary
		},
	}

	d := NewDispatcher(s, v, runner)
	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_validation_analyze",
			"arguments": map[string]any{
				"timeoutSeconds": 5,
			},
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}
	if runner.calls != 1 {
		t.Fatalf("expected analyze to run validation once, got %d", runner.calls)
	}

	analysis := toMapAny(parseToolResult(t, resp.Result.(toolResult)))
	if analysis["analysisBasis"] != "fresh_run" {
		t.Fatalf("expected fresh run analysis, got %+v", analysis)
	}
}

func TestToolsCallValidationAnalyzeReturnsStoredStaleResult(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	startedAt := time.Unix(10, 0)
	completedAt := time.Unix(20, 0)
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
	v.StartRun("run-1", startedAt)
	v.CompleteRun("run-1", map[string]validator.Entity{
		"span:trace-1:span-1": {
			Key:             "span:trace-1:span-1",
			HighestSeverity: validator.SeverityViolation,
			Signal:          validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
			UpdatedAt:       completedAt,
			Findings: []validator.Finding{{
				EntityKey: "span:trace-1:span-1",
				Source:    "weaver",
				RuleID:    "missing_attribute",
				Severity:  validator.SeverityViolation,
				Message:   "missing attribute",
				Signal:    validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
				UpdatedAt: completedAt,
			}},
		},
	}, validator.RunStats{}, completedAt)
	v.MarkTelemetryChanged(time.Unix(30, 0))

	d := NewDispatcher(s, v)
	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_validation_analyze",
			"arguments": map[string]any{
				"serviceName": "checkout",
			},
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}

	data := parseToolResult(t, resp.Result.(toolResult))
	snapshot := toMapAny(data)
	summary := toMapAny(snapshot["summary"])
	if stale, _ := summary["stale"].(bool); !stale {
		t.Fatalf("expected stale summary, got %+v", summary)
	}
	if snapshot["analysisBasis"] != "stale_result" {
		t.Fatalf("expected stale analysis basis, got %+v", snapshot)
	}
	message, _ := snapshot["analysisMessage"].(string)
	if !strings.Contains(message, "based on run run-1 completed at") {
		t.Fatalf("expected stale analysis message, got %+v", snapshot)
	}
	findings := toSliceAny(snapshot["findings"])
	if len(findings) != 1 {
		t.Fatalf("expected one stale finding, got %+v", snapshot)
	}
}

func TestToolsCallValidationAnalyzeReturnsCachedResultWithoutRerun(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	startedAt := time.Unix(10, 0)
	completedAt := time.Unix(20, 0)
	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
	v.StartRun("run-4", startedAt)
	v.CompleteRun("run-4", map[string]validator.Entity{
		"span:trace-1:span-1": {
			Key:             "span:trace-1:span-1",
			HighestSeverity: validator.SeverityViolation,
			Signal:          validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
			UpdatedAt:       completedAt,
			Findings: []validator.Finding{{
				EntityKey: "span:trace-1:span-1",
				Source:    "weaver",
				RuleID:    "missing_attribute",
				Severity:  validator.SeverityViolation,
				Message:   "missing attribute",
				Signal:    validator.SignalRef{Type: "span", ServiceName: "checkout", TraceID: "trace-1", SpanID: "span-1", SpanName: "GET /orders"},
				UpdatedAt: completedAt,
			}},
		},
	}, validator.RunStats{}, completedAt)
	v.MarkTelemetryChanged(time.Unix(30, 0))
	runner := &fakeValidationRunner{}

	d := NewDispatcher(s, v, runner)
	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_validation_analyze",
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}
	if runner.calls != 0 {
		t.Fatalf("expected cached analysis path to avoid rerun, got %d calls", runner.calls)
	}

	snapshot := toMapAny(parseToolResult(t, resp.Result.(toolResult)))
	summary := toMapAny(snapshot["summary"])
	if stale, _ := summary["stale"].(bool); !stale {
		t.Fatalf("expected cached stale analysis, got %+v", summary)
	}
}

// Test 4: tools/call observer_status - returns endpoints + stats
func TestToolsCallObserverStatus(t *testing.T) {
	s := store.New()
	s.SetEndpoints(store.Endpoints{
		OTLPHTTP: "http://localhost:4318",
		OTLPgRPC: "localhost:4317",
		REST:     "http://localhost:8080",
	})

	d := NewDispatcher(s)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_status",
		},
	}

	resp, handled := d.Dispatch(req)
	if !handled {
		t.Fatalf("expected handled=true")
	}
	if resp.Error != nil {
		t.Fatalf("unexpected error: %v", resp.Error)
	}

	toolRes := resp.Result.(toolResult)
	data := parseToolResult(t, toolRes)
	statusMap := toMapAny(data)

	if statusMap["endpoints"] == nil {
		t.Fatalf("missing endpoints")
	}
	endpoints := toMapAny(statusMap["endpoints"])
	if endpoints["otlpHttp"] != "http://localhost:4318" {
		t.Fatalf("incorrect otlpHttp")
	}

	if statusMap["stats"] == nil {
		t.Fatalf("missing stats")
	}
	stats := toMapAny(statusMap["stats"])
	if stats["spanCount"] == nil {
		t.Fatalf("missing spanCount in stats")
	}
}

func TestToolsCallSplunkExportRejectedWhenUnconfigured(t *testing.T) {
	// The Splunk export tools are only advertised in tools/list when a
	// controller is configured. A crafted call by name when no controller is
	// present must return an "Unknown tool" error, not panic on a nil
	// controller.
	s := store.New()
	d := NewDispatcher(s)

	for _, name := range []string{
		"observer_splunk_connection_realm",
		"observer_splunk_metrics_export_status",
		"observer_splunk_metrics_export_configure",
		"observer_splunk_metrics_export_test",
	} {
		resp, handled := d.Dispatch(jsonRPCRequest{
			ID:      1,
			JSONRPC: "2.0",
			Method:  "tools/call",
			Params: map[string]any{
				"name":      name,
				"arguments": map[string]any{"enabled": true},
			},
		})
		if !handled {
			t.Fatalf("%s: expected handled=true", name)
		}
		if resp.Error == nil {
			t.Fatalf("%s: expected error for unconfigured Splunk tool, got result", name)
		}
		if resp.Error.Code != -32602 {
			t.Fatalf("%s: error code = %d, want -32602", name, resp.Error.Code)
		}
	}
}

func TestToolsCallSplunkConnectionRealmReturnsOnlyRealm(t *testing.T) {
	s := store.New()
	metricsController, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Realm:       "us0",
		AccessToken: "not-returned-by-realm-tool",
	})
	if err != nil {
		t.Fatalf("create metrics export controller: %v", err)
	}
	tracesController, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Realm:       "us0",
		AccessToken: "not-returned-by-realm-tool",
	})
	if err != nil {
		t.Fatalf("create traces export controller: %v", err)
	}
	d := NewDispatcher(s, metricsController, tracesController)

	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_splunk_connection_realm",
			"arguments": map[string]any{},
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}

	result := toMapAny(parseToolResult(t, resp.Result.(toolResult)))
	if len(result) != 1 {
		t.Fatalf("realm response contains unexpected fields: %#v", result)
	}
	if result["realm"] != "us0" {
		t.Fatalf("realm = %v, want us0", result["realm"])
	}
}

func TestToolsCallSplunkConnectionRealmOmitsRealmWithoutToken(t *testing.T) {
	s := store.New()
	metricsController, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Realm: "us0",
	})
	if err != nil {
		t.Fatalf("create metrics export controller: %v", err)
	}
	tracesController, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Realm: "us0",
	})
	if err != nil {
		t.Fatalf("create traces export controller: %v", err)
	}
	d := NewDispatcher(s, metricsController, tracesController)

	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_splunk_connection_realm",
			"arguments": map[string]any{},
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}

	result := toMapAny(parseToolResult(t, resp.Result.(toolResult)))
	if len(result) != 0 {
		t.Fatalf("realm response = %#v, want empty response without token", result)
	}
}

func TestToolsCallSplunkConnectionRealmOmitsRealmForMismatchedTokens(t *testing.T) {
	s := store.New()
	metricsController, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Realm:       "us0",
		AccessToken: "metrics-token-not-returned",
	})
	if err != nil {
		t.Fatalf("create metrics export controller: %v", err)
	}
	tracesController, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Realm:       "us0",
		AccessToken: "traces-token-not-returned",
	})
	if err != nil {
		t.Fatalf("create traces export controller: %v", err)
	}
	d := NewDispatcher(s, metricsController, tracesController)

	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_splunk_connection_realm",
			"arguments": map[string]any{},
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}

	result := toMapAny(parseToolResult(t, resp.Result.(toolResult)))
	if len(result) != 0 {
		t.Fatalf("realm response = %#v, want empty response with mismatched tokens", result)
	}
}

func TestToolsCallSplunkConnectionRealmOmitsRealmForEndpointOverride(t *testing.T) {
	s := store.New()
	metricsController, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Realm:       "us0",
		Endpoint:    "https://metrics.example.com/v2/datapoint/otlp",
		AccessToken: "not-returned-by-realm-tool",
	})
	if err != nil {
		t.Fatalf("create metrics export controller: %v", err)
	}
	tracesController, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Realm:       "us0",
		AccessToken: "not-returned-by-realm-tool",
	})
	if err != nil {
		t.Fatalf("create traces export controller: %v", err)
	}
	d := NewDispatcher(s, metricsController, tracesController)

	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_splunk_connection_realm",
			"arguments": map[string]any{},
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}

	result := toMapAny(parseToolResult(t, resp.Result.(toolResult)))
	if len(result) != 0 {
		t.Fatalf("realm response = %#v, want empty response with endpoint override", result)
	}
}

func TestToolsCallValidationStatus(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	v.SetRuntimeStatus(validator.StatusReady, "ready")
	v.UpsertEntity(validator.Entity{
		Key:             "metric:checkout::http.server.duration",
		HighestSeverity: validator.SeverityImprovement,
		Signal:          validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
		UpdatedAt:       time.Now(),
		Findings: []validator.Finding{
			{
				EntityKey: "metric:checkout::http.server.duration",
				Source:    "weaver",
				RuleID:    "deprecated",
				Severity:  validator.SeverityImprovement,
				Message:   "deprecated metric",
				Signal:    validator.SignalRef{Type: "metric", ServiceName: "checkout", MetricName: "http.server.duration"},
				UpdatedAt: time.Now(),
			},
		},
	})

	d := NewDispatcher(s, v)
	resp, handled := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_validation_status",
		},
	})
	if !handled || resp.Error != nil {
		t.Fatalf("unexpected response: %+v", resp)
	}

	data := parseToolResult(t, resp.Result.(toolResult))
	summary := toMapAny(data)
	if summary["status"] != "ready" {
		t.Fatalf("unexpected status: %v", summary["status"])
	}
	if summary["totalAdvisories"] != float64(1) {
		t.Fatalf("unexpected advisory count: %v", summary["totalAdvisories"])
	}
}

// Test 5: tools/call observer_traces_overview - ingest spans first, call tool, verify trace summaries
func TestToolsCallTracesOverview(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	// Ingest sample spans
	now := time.Now()
	spans := []store.Span{
		{
			TraceID:   "trace1",
			SpanID:    "span1",
			Name:      "root",
			Kind:      "INTERNAL",
			StartTime: now,
			EndTime:   now.Add(100 * time.Millisecond),
			Status: store.SpanStatus{
				Code: "OK",
			},
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
		{
			TraceID:      "trace1",
			SpanID:       "span2",
			ParentSpanID: "span1",
			Name:         "child",
			Kind:         "INTERNAL",
			StartTime:    now.Add(10 * time.Millisecond),
			EndTime:      now.Add(90 * time.Millisecond),
			Status: store.SpanStatus{
				Code: "OK",
			},
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddSpansForConnection("", spans)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_traces_overview",
			"arguments": map[string]any{},
		},
	}

	resp, handled := d.Dispatch(req)
	if !handled {
		t.Fatalf("expected handled=true")
	}
	if resp.Error != nil {
		t.Fatalf("unexpected error: %v", resp.Error)
	}

	toolRes := resp.Result.(toolResult)
	data := parseToolResult(t, toolRes)
	tracesList := toSliceAny(data)

	if len(tracesList) != 1 {
		t.Fatalf("expected 1 trace, got %d", len(tracesList))
	}

	traceMap := toMapAny(tracesList[0])
	if traceMap["traceId"] != "trace1" {
		t.Fatalf("expected traceId trace1, got %v", traceMap["traceId"])
	}
	if traceMap["serviceName"] != "service-a" {
		t.Fatalf("expected serviceName service-a, got %v", traceMap["serviceName"])
	}
	if traceMap["status"] != "ok" {
		t.Fatalf("expected status ok, got %v", traceMap["status"])
	}
	if traceMap["spanCount"] != float64(2) {
		t.Fatalf("expected spanCount 2, got %v", traceMap["spanCount"])
	}
}

// Test 6: tools/call observer_traces_overview with filters - serviceName, status filter
func TestToolsCallTracesOverviewWithFilters(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	now := time.Now()
	spans := []store.Span{
		{
			TraceID:   "trace1",
			SpanID:    "span1",
			Name:      "root",
			Kind:      "INTERNAL",
			StartTime: now,
			EndTime:   now.Add(100 * time.Millisecond),
			Status: store.SpanStatus{
				Code: "OK",
			},
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
		{
			TraceID:   "trace2",
			SpanID:    "span3",
			Name:      "root",
			Kind:      "INTERNAL",
			StartTime: now.Add(50 * time.Millisecond),
			EndTime:   now.Add(150 * time.Millisecond),
			Status: store.SpanStatus{
				Code: "ERROR",
			},
			Resource: store.Resource{
				ServiceName: "service-b",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddSpansForConnection("", spans)

	// Filter by service-a, should get 1 trace
	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_traces_overview",
			"arguments": map[string]any{
				"serviceName": "service-a",
			},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)
	data := parseToolResult(t, toolRes)
	tracesList := toSliceAny(data)

	if len(tracesList) != 1 {
		t.Fatalf("expected 1 trace for service-a, got %d", len(tracesList))
	}

	// Filter by status=error, should get 1 trace
	req2 := jsonRPCRequest{
		ID:      2,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_traces_overview",
			"arguments": map[string]any{
				"status": "error",
			},
		},
	}

	resp2, _ := d.Dispatch(req2)
	toolRes2 := resp2.Result.(toolResult)
	data2 := parseToolResult(t, toolRes2)
	tracesList2 := toSliceAny(data2)

	if len(tracesList2) != 1 {
		t.Fatalf("expected 1 trace with error status, got %d", len(tracesList2))
	}
	trace := toMapAny(tracesList2[0])
	if trace["status"] != "error" {
		t.Fatalf("expected status error, got %v", trace["status"])
	}
}

// Test 7: tools/call observer_trace_detail - ingest spans, call with traceId, verify spans returned
func TestToolsCallTraceDetail(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	now := time.Now()
	spans := []store.Span{
		{
			TraceID:   "trace1",
			SpanID:    "span1",
			Name:      "root",
			Kind:      "INTERNAL",
			StartTime: now,
			EndTime:   now.Add(100 * time.Millisecond),
			Status: store.SpanStatus{
				Code: "OK",
			},
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
		{
			TraceID:      "trace1",
			SpanID:       "span2",
			ParentSpanID: "span1",
			Name:         "child",
			Kind:         "INTERNAL",
			StartTime:    now.Add(10 * time.Millisecond),
			EndTime:      now.Add(90 * time.Millisecond),
			Status: store.SpanStatus{
				Code: "OK",
			},
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddSpansForConnection("", spans)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_trace_detail",
			"arguments": map[string]any{
				"traceId": "trace1",
			},
		},
	}

	resp, handled := d.Dispatch(req)
	if !handled {
		t.Fatalf("expected handled=true")
	}
	if resp.Error != nil {
		t.Fatalf("unexpected error: %v", resp.Error)
	}

	toolRes := resp.Result.(toolResult)
	data := parseToolResult(t, toolRes)
	traceDetail := toMapAny(data)

	if traceDetail["traceId"] != "trace1" {
		t.Fatalf("expected traceId trace1, got %v", traceDetail["traceId"])
	}
	if traceDetail["spanCount"] != float64(2) {
		t.Fatalf("expected spanCount 2, got %v", traceDetail["spanCount"])
	}

	spansList := toSliceAny(traceDetail["spans"])
	if len(spansList) != 2 {
		t.Fatalf("expected 2 spans in detail, got %d", len(spansList))
	}
}

// Test 8: tools/call observer_trace_detail missing traceId - error
func TestToolsCallTraceDetailMissingTraceId(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_trace_detail",
			"arguments": map[string]any{},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)

	if !toolRes.IsError {
		t.Fatalf("expected IsError=true for missing traceId")
	}
	if len(toolRes.Content) == 0 {
		t.Fatalf("expected error message")
	}
	if toolRes.Content[0].Text != "traceId is required" {
		t.Fatalf("expected error message 'traceId is required', got %s", toolRes.Content[0].Text)
	}
}

// Test 9: tools/call observer_trace_detail with non-existent traceId - error
func TestToolsCallTraceDetailNonExistent(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_trace_detail",
			"arguments": map[string]any{
				"traceId": "nonexistent",
			},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)

	if !toolRes.IsError {
		t.Fatalf("expected IsError=true for non-existent trace")
	}
	if len(toolRes.Content) == 0 {
		t.Fatalf("expected error message")
	}
}

// Test 10: tools/call observer_metrics_overview - ingest metrics, call tool, verify groups
func TestToolsCallMetricsOverview(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	now := time.Now()
	metrics := []store.MetricDataPoint{
		{
			Name:      "http.request.count",
			Type:      "sum",
			Timestamp: now,
			Value:     42,
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
		{
			Name:      "http.request.duration",
			Type:      "histogram",
			Timestamp: now,
			Sum:       1000,
			Count:     100,
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddMetricsForConnection("", metrics)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_metrics_overview",
			"arguments": map[string]any{},
		},
	}

	resp, handled := d.Dispatch(req)
	if !handled {
		t.Fatalf("expected handled=true")
	}
	if resp.Error != nil {
		t.Fatalf("unexpected error: %v", resp.Error)
	}

	toolRes := resp.Result.(toolResult)
	data := parseToolResult(t, toolRes)
	groupsList := toSliceAny(data)

	if len(groupsList) < 2 {
		t.Fatalf("expected at least 2 metric groups, got %d", len(groupsList))
	}

	names := make(map[string]bool)
	for _, g := range groupsList {
		group := toMapAny(g)
		names[group["name"].(string)] = true
	}

	if !names["http.request.count"] {
		t.Fatalf("missing metric http.request.count")
	}
	if !names["http.request.duration"] {
		t.Fatalf("missing metric http.request.duration")
	}
}

// Test 11: tools/call observer_metrics_overview with filters - metricName, serviceName
func TestToolsCallMetricsOverviewWithFilters(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	now := time.Now()
	metrics := []store.MetricDataPoint{
		{
			Name:      "http.request.count",
			Type:      "sum",
			Timestamp: now,
			Value:     42,
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
		{
			Name:      "database.query.duration",
			Type:      "histogram",
			Timestamp: now,
			Sum:       1000,
			Count:     100,
			Resource: store.Resource{
				ServiceName: "service-b",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddMetricsForConnection("", metrics)

	// Filter by metricName
	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_metrics_overview",
			"arguments": map[string]any{
				"metricName": "http.request.count",
			},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)
	data := parseToolResult(t, toolRes)
	groupsList := toSliceAny(data)

	if len(groupsList) != 1 {
		t.Fatalf("expected 1 metric group after filter, got %d", len(groupsList))
	}
	group := toMapAny(groupsList[0])
	if group["name"] != "http.request.count" {
		t.Fatalf("expected metric name http.request.count, got %v", group["name"])
	}

	// Filter by serviceName
	req2 := jsonRPCRequest{
		ID:      2,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_metrics_overview",
			"arguments": map[string]any{
				"serviceName": "service-b",
			},
		},
	}

	resp2, _ := d.Dispatch(req2)
	toolRes2 := resp2.Result.(toolResult)
	data2 := parseToolResult(t, toolRes2)
	groupsList2 := toSliceAny(data2)

	found := false
	for _, g := range groupsList2 {
		group := toMapAny(g)
		if group["serviceName"] == "service-b" {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("expected to find metric for service-b")
	}
}

// Test 12: tools/call observer_metric_detail - call with metricName, verify data
func TestToolsCallMetricDetail(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	now := time.Now()
	metrics := []store.MetricDataPoint{
		{
			Name:      "http.request.count",
			Type:      "sum",
			Timestamp: now,
			Value:     42,
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddMetricsForConnection("", metrics)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_metric_detail",
			"arguments": map[string]any{
				"metricName": "http.request.count",
			},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)
	data := parseToolResult(t, toolRes)
	detail := toMapAny(data)

	if detail["name"] != "http.request.count" {
		t.Fatalf("expected metric name http.request.count, got %v", detail["name"])
	}
	if detail["type"] != "sum" {
		t.Fatalf("expected metric type sum, got %v", detail["type"])
	}
}

// Test 13: tools/call observer_metric_detail missing name - error
func TestToolsCallMetricDetailMissingName(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_metric_detail",
			"arguments": map[string]any{},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)

	if !toolRes.IsError {
		t.Fatalf("expected IsError=true for missing metricName")
	}
	if toolRes.Content[0].Text != "metricName is required" {
		t.Fatalf("expected error message 'metricName is required', got %s", toolRes.Content[0].Text)
	}
}

// Test 14: tools/call observer_metric_detail with non-existent metric - error
func TestToolsCallMetricDetailNonExistent(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_metric_detail",
			"arguments": map[string]any{
				"metricName": "nonexistent.metric",
			},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)

	if !toolRes.IsError {
		t.Fatalf("expected IsError=true for non-existent metric")
	}
}

// Test 15: tools/call observer_logs_overview - ingest logs, call tool, verify
func TestToolsCallLogsOverview(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	now := time.Now()
	logs := []store.LogRecord{
		{
			Timestamp:    now,
			SeverityText: "INFO",
			Body:         "application started",
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
		{
			Timestamp:    now.Add(10 * time.Millisecond),
			SeverityText: "ERROR",
			Body:         "connection failed",
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddLogsForConnection("", logs)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_logs_overview",
			"arguments": map[string]any{},
		},
	}

	resp, handled := d.Dispatch(req)
	if !handled {
		t.Fatalf("expected handled=true")
	}
	if resp.Error != nil {
		t.Fatalf("unexpected error: %v", resp.Error)
	}

	toolRes := resp.Result.(toolResult)
	data := parseToolResult(t, toolRes)
	logsList := toSliceAny(data)

	if len(logsList) != 2 {
		t.Fatalf("expected 2 logs, got %d", len(logsList))
	}
}

// Test 16: tools/call observer_logs_overview with filters - severityText, body
func TestToolsCallLogsOverviewWithFilters(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	now := time.Now()
	logs := []store.LogRecord{
		{
			Timestamp:    now,
			SeverityText: "INFO",
			Body:         "application started",
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
		{
			Timestamp:    now.Add(10 * time.Millisecond),
			SeverityText: "ERROR",
			Body:         "connection failed",
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddLogsForConnection("", logs)

	// Filter by severityText
	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_logs_overview",
			"arguments": map[string]any{
				"severityText": "ERROR",
			},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)
	data := parseToolResult(t, toolRes)
	logsList := toSliceAny(data)

	if len(logsList) != 1 {
		t.Fatalf("expected 1 error log, got %d", len(logsList))
	}
	log := toMapAny(logsList[0])
	if log["severityText"] != "ERROR" {
		t.Fatalf("expected ERROR severity, got %v", log["severityText"])
	}

	// Filter by body substring
	req2 := jsonRPCRequest{
		ID:      2,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_logs_overview",
			"arguments": map[string]any{
				"body": "started",
			},
		},
	}

	resp2, _ := d.Dispatch(req2)
	toolRes2 := resp2.Result.(toolResult)
	data2 := parseToolResult(t, toolRes2)
	logsList2 := toSliceAny(data2)

	if len(logsList2) != 1 {
		t.Fatalf("expected 1 log with 'started', got %d", len(logsList2))
	}
	log2 := toMapAny(logsList2[0])
	if !strings.Contains(log2["body"].(string), "started") {
		t.Fatalf("expected 'started' in body")
	}
}

// Test 17: tools/call observer_clear - clear store, verify stats 0
func TestToolsCallClear(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	now := time.Now()
	spans := []store.Span{
		{
			TraceID:   "trace1",
			SpanID:    "span1",
			Name:      "root",
			Kind:      "INTERNAL",
			StartTime: now,
			EndTime:   now.Add(100 * time.Millisecond),
			Status: store.SpanStatus{
				Code: "OK",
			},
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddSpansForConnection("", spans)

	// Verify data was added
	stats1 := s.Stats()
	if stats1.SpanCount != 1 {
		t.Fatalf("expected 1 span before clear")
	}

	// Clear the store
	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "observer_clear",
			"arguments": map[string]any{},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)

	if toolRes.IsError {
		t.Fatalf("expected no error for clear")
	}

	// Verify store is empty
	stats2 := s.Stats()
	if stats2.SpanCount != 0 {
		t.Fatalf("expected 0 spans after clear, got %d", stats2.SpanCount)
	}
}

// Test 18: tools/call unknown tool - error
func TestToolsCallUnknownTool(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name":      "unknown_tool",
			"arguments": map[string]any{},
		},
	}

	resp, handled := d.Dispatch(req)
	if !handled {
		t.Fatalf("expected handled=true")
	}
	if resp.Error == nil {
		t.Fatalf("expected error for unknown tool")
	}
	if resp.Error.Code != -32602 {
		t.Fatalf("expected error code -32602, got %d", resp.Error.Code)
	}
}

// Test 19: Unknown JSON-RPC method - handled=false for notifications, error for others
func TestUnknownMethod(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "unknown_method",
	}

	resp, handled := d.Dispatch(req)
	if !handled {
		t.Fatalf("expected handled=true for unknown method")
	}
	if resp.Error == nil {
		t.Fatalf("expected error for unknown method")
	}
	if resp.Error.Code != -32601 {
		t.Fatalf("expected error code -32601, got %d", resp.Error.Code)
	}
}

// Test 20: notifications/initialized - no response, handled=false
func TestNotificationInitialized(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	req := jsonRPCRequest{
		JSONRPC: "2.0",
		Method:  "notifications/initialized",
	}

	resp, handled := d.Dispatch(req)
	if handled {
		t.Fatalf("expected handled=false for notification")
	}
	if resp.Result != nil || resp.Error != nil {
		t.Fatalf("expected empty response for notification")
	}
}

// Test 21: intArg defaults and clamping
func TestIntArgDefaultsAndClamping(t *testing.T) {
	tests := []struct {
		name     string
		args     map[string]any
		key      string
		def      int
		expected int
	}{
		{"missing key uses default", map[string]any{}, "limit", 20, 20},
		{"float64 value", map[string]any{"limit": 42.0}, "limit", 20, 42},
		{"int value", map[string]any{"limit": 42}, "limit", 20, 42},
		{"negative value uses default", map[string]any{"limit": -5.0}, "limit", 20, 20},
		{"zero value", map[string]any{"limit": 0.0}, "limit", 20, 0},
		{"clamped to max", map[string]any{"limit": 50000.0}, "limit", 20, maxIntArg},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := intArg(tt.args, tt.key, tt.def)
			if result != tt.expected {
				t.Fatalf("expected %d, got %d", tt.expected, result)
			}
		})
	}
}

// Test 22: Verify tool response data correctness - JSON content matches expected structure
func TestToolResponseDataCorrectness(t *testing.T) {
	s := store.New()
	d := NewDispatcher(s)

	now := time.Now()
	spans := []store.Span{
		{
			TraceID:   "trace1",
			SpanID:    "span1",
			Name:      "root",
			Kind:      "INTERNAL",
			StartTime: now,
			EndTime:   now.Add(100 * time.Millisecond),
			Status: store.SpanStatus{
				Code: "OK",
			},
			Resource: store.Resource{
				ServiceName: "service-a",
			},
			Scope: store.Scope{Name: "test"},
		},
	}
	s.AddSpansForConnection("", spans)

	req := jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params: map[string]any{
			"name": "observer_traces_overview",
			"arguments": map[string]any{
				"limit": 10,
			},
		},
	}

	resp, _ := d.Dispatch(req)
	toolRes := resp.Result.(toolResult)

	// Verify toolResult structure
	if toolRes.IsError {
		t.Fatalf("expected IsError=false")
	}
	if len(toolRes.Content) != 1 {
		t.Fatalf("expected 1 content item")
	}
	if toolRes.Content[0].Type != "text" {
		t.Fatalf("expected type 'text'")
	}

	// Verify JSON is valid and contains expected fields
	data := parseToolResult(t, toolRes)
	traces := toSliceAny(data)
	if len(traces) == 0 {
		t.Fatalf("expected non-empty traces result after ingesting a span")
	}
	trace := toMapAny(traces[0])
	// Check all required fields are present
	requiredFields := []string{"traceId", "rootSpanName", "serviceName", "spanCount", "status"}
	for _, field := range requiredFields {
		if trace[field] == nil {
			t.Fatalf("missing required field: %s", field)
		}
	}
}
