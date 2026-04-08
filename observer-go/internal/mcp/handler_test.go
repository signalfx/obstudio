package mcp

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer-go/internal/store"
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
		name     string
		clientVer string
		expected string
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

// Test 3: Dispatch tools/list - returns all 7 tools with names
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

	if len(toolsList) != 7 {
		t.Fatalf("expected 7 tools, got %d", len(toolsList))
	}

	expectedToolNames := map[string]bool{
		"observer_metrics_overview": false,
		"observer_metric_detail":    false,
		"observer_traces_overview":  false,
		"observer_trace_detail":     false,
		"observer_logs_overview":    false,
		"observer_clear":            false,
		"observer_status":           false,
	}

	for _, tool := range toolsList {
		name := tool.Name
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
			"name":        "observer_trace_detail",
			"arguments":   map[string]any{},
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
			"name":        "observer_metrics_overview",
			"arguments":   map[string]any{},
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
			"name":        "observer_metric_detail",
			"arguments":   map[string]any{},
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
			"name":        "observer_logs_overview",
			"arguments":   map[string]any{},
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
	if !contains(log2["body"].(string), "started") {
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
			"name":        "observer_clear",
			"arguments":   map[string]any{},
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
			"name":        "unknown_tool",
			"arguments":   map[string]any{},
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

// Helper function
func contains(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
