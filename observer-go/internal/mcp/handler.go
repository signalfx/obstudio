package mcp

import (
	"encoding/json"
	"fmt"

	"github.com/signalfx/obstudio/observer-go/internal/store"
)

var supportedVersions = []string{"2025-06-18", "2025-03-26", "2024-11-05"}

type jsonRPCRequest struct {
	ID      any    `json:"id,omitempty"`
	JSONRPC string `json:"jsonrpc"`
	Method  string `json:"method"`
	Params  any    `json:"params,omitempty"`
}

type jsonRPCResponse struct {
	ID      any           `json:"id"`
	JSONRPC string        `json:"jsonrpc"`
	Result  any           `json:"result,omitempty"`
	Error   *jsonRPCError `json:"error,omitempty"`
}

type jsonRPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

type toolDef struct {
	Name        string     `json:"name"`
	Description string     `json:"description"`
	InputSchema jsonSchema `json:"inputSchema"`
	Annotations toolAnnot  `json:"annotations"`
}

type jsonSchema struct {
	Type                 string                `json:"type"`
	AdditionalProperties *bool                 `json:"additionalProperties,omitempty"`
	Required             []string              `json:"required,omitempty"`
	Properties           map[string]jsonSchema `json:"properties,omitempty"`
	Description          string                `json:"description,omitempty"`
	Enum                 []string              `json:"enum,omitempty"`
	Minimum              *int                  `json:"minimum,omitempty"`
	Maximum              *int                  `json:"maximum,omitempty"`
	Default              any                   `json:"default,omitempty"`
}

type toolAnnot struct {
	Title           string `json:"title"`
	ReadOnlyHint    bool   `json:"readOnlyHint"`
	DestructiveHint bool   `json:"destructiveHint"`
	IdempotentHint  bool   `json:"idempotentHint"`
	OpenWorldHint   bool   `json:"openWorldHint"`
}

type toolResult struct {
	Content []toolContent `json:"content"`
	IsError bool          `json:"isError,omitempty"`
}

type toolContent struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// Dispatcher handles MCP JSON-RPC method dispatch independent of transport.
type Dispatcher struct {
	store *store.Store
	tools []toolDef
}

// NewDispatcher creates a transport-agnostic MCP dispatcher.
func NewDispatcher(s *store.Store) *Dispatcher {
	return &Dispatcher{store: s, tools: buildToolDefs()}
}

// Dispatch processes a single JSON-RPC request and returns a response.
// Returns (response, handled). When handled is false the caller should
// send an HTTP 202 or similar acknowledgement (e.g. notifications).
func (d *Dispatcher) Dispatch(req jsonRPCRequest) (jsonRPCResponse, bool) {
	switch req.Method {
	case "initialize":
		return d.handleInitialize(req), true
	case "notifications/initialized":
		return jsonRPCResponse{}, false
	case "tools/list":
		return d.handleToolsList(req), true
	case "tools/call":
		return d.handleToolsCall(req), true
	default:
		return rpcError(req.ID, -32601, fmt.Sprintf("Method not found: %s", req.Method)), true
	}
}

func (d *Dispatcher) handleInitialize(req jsonRPCRequest) jsonRPCResponse {
	params, _ := toMap(req.Params)
	clientVersion, _ := params["protocolVersion"].(string)
	negotiated := negotiateVersion(clientVersion)

	return rpcResult(req.ID, map[string]any{
		"protocolVersion": negotiated,
		"capabilities":    map[string]any{"tools": map[string]any{"listChanged": false}},
		"serverInfo":      map[string]any{"name": "obstudio", "version": "0.1.0"},
	})
}

func (d *Dispatcher) handleToolsList(req jsonRPCRequest) jsonRPCResponse {
	return rpcResult(req.ID, map[string]any{"tools": d.tools})
}

func (d *Dispatcher) handleToolsCall(req jsonRPCRequest) jsonRPCResponse {
	params, _ := toMap(req.Params)
	toolName, _ := params["name"].(string)
	args, _ := toMap(params["arguments"])

	var result toolResult
	switch toolName {
	case "observer_metrics_overview":
		result = d.metricsOverview(args)
	case "observer_metric_detail":
		result = d.metricDetail(args)
	case "observer_traces_overview":
		result = d.tracesOverview(args)
	case "observer_trace_detail":
		result = d.traceDetail(args)
	case "observer_clear":
		result = d.clearStore()
	case "observer_status":
		result = d.status()
	default:
		return rpcError(req.ID, -32602, fmt.Sprintf("Unknown tool: %s", toolName))
	}

	return rpcResult(req.ID, result)
}

func (d *Dispatcher) metricsOverview(args map[string]any) toolResult {
	f := store.MetricFilter{
		MetricName:        strArg(args, "metricName"),
		ServiceName:       strArg(args, "serviceName"),
		ScopeName:         strArg(args, "scopeName"),
		Type:              strArg(args, "type"),
		ResourceAttribute: strArg(args, "resourceAttribute"),
		Limit:             intArg(args, "limit", 20),
		DataPointLimit:    intArg(args, "dataPointLimit", 3),
	}
	groups := d.store.QueryMetrics(f)
	return jsonToolResult(groups)
}

func (d *Dispatcher) metricDetail(args map[string]any) toolResult {
	name := strArg(args, "metricName")
	if name == "" {
		return errorResult("metricName is required")
	}
	f := store.MetricFilter{
		MetricName:     name,
		ServiceName:    strArg(args, "serviceName"),
		ScopeName:      strArg(args, "scopeName"),
		Limit:          1,
		DataPointLimit: intArg(args, "dataPointLimit", 50),
	}
	groups := d.store.QueryMetrics(f)
	if len(groups) == 0 {
		return errorResult(fmt.Sprintf("No metric found with name %q", name))
	}
	return jsonToolResult(groups[0])
}

func (d *Dispatcher) tracesOverview(args map[string]any) toolResult {
	f := store.TraceFilter{
		ServiceName:      strArg(args, "serviceName"),
		SpanName:         strArg(args, "spanName"),
		Status:           strArg(args, "status"),
		TraceIDPrefix:    strArg(args, "traceIdPrefix"),
		Limit:            intArg(args, "limit", 20),
		SpanPreviewCount: intArg(args, "spanPreviewCount", 5),
	}
	traces := d.store.QueryTraces(f)
	return jsonToolResult(traces)
}

func (d *Dispatcher) traceDetail(args map[string]any) toolResult {
	traceID := strArg(args, "traceId")
	if traceID == "" {
		return errorResult("traceId is required")
	}
	detail := d.store.GetTrace(traceID, intArg(args, "eventLimit", 12))
	if detail == nil {
		return errorResult(fmt.Sprintf("No trace found with id %q", traceID))
	}
	return jsonToolResult(detail)
}

func (d *Dispatcher) clearStore() toolResult {
	d.store.Clear()
	return toolResult{Content: []toolContent{{Type: "text", Text: "All telemetry data cleared."}}}
}

func (d *Dispatcher) status() toolResult {
	ep := d.store.GetEndpoints()
	stats := d.store.Stats()
	return jsonToolResult(map[string]any{
		"endpoints": ep,
		"stats":     stats,
	})
}

func buildToolDefs() []toolDef {
	f := false
	return []toolDef{
		{
			Name:        "observer_metrics_overview",
			Description: "List metrics currently present in the OTLP in-memory store, with compact summaries and bounded datapoint previews.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
				Properties: map[string]jsonSchema{
					"dataPointLimit":    {Type: "integer", Minimum: intPtr(0), Maximum: intPtr(200), Default: 3, Description: "Maximum datapoints to include per metric summary."},
					"metricName":        {Type: "string", Description: "Optional case-insensitive exact metric name filter."},
					"resourceAttribute": {Type: "string", Description: "Optional substring that must appear in the serialized resource attributes."},
					"scopeName":         {Type: "string", Description: "Optional case-insensitive instrumentation scope name filter."},
					"serviceName":       {Type: "string", Description: "Optional case-insensitive service.name filter."},
					"type":              {Type: "string", Enum: []string{"counter", "gauge", "histogram", "summary", "exponential_histogram"}, Description: "Optional metric kind filter."},
					"limit":             {Type: "integer", Minimum: intPtr(1), Maximum: intPtr(100), Default: 20, Description: "Maximum number of metric groups to return."},
				},
			},
			Annotations: toolAnnot{Title: "Observer Metrics Overview", ReadOnlyHint: true, IdempotentHint: true},
		},
		{
			Name:        "observer_metric_detail",
			Description: "Fetch a single metric by exact name with resource and scope context plus a larger datapoint window.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f, Required: []string{"metricName"},
				Properties: map[string]jsonSchema{
					"metricName":     {Type: "string", Description: "Exact metric name to return."},
					"dataPointLimit": {Type: "integer", Minimum: intPtr(1), Maximum: intPtr(200), Default: 50, Description: "Maximum datapoints to include for each matching metric series."},
					"scopeName":      {Type: "string", Description: "Optional case-insensitive scope filter."},
					"serviceName":    {Type: "string", Description: "Optional case-insensitive service.name filter."},
				},
			},
			Annotations: toolAnnot{Title: "Observer Metric Detail", ReadOnlyHint: true, IdempotentHint: true},
		},
		{
			Name:        "observer_traces_overview",
			Description: "List recent traces from the OTLP in-memory store with compact span previews and status summaries.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
				Properties: map[string]jsonSchema{
					"limit":            {Type: "integer", Minimum: intPtr(1), Maximum: intPtr(50), Default: 20, Description: "Maximum number of traces to return."},
					"serviceName":      {Type: "string", Description: "Optional case-insensitive service.name filter."},
					"spanName":         {Type: "string", Description: "Optional case-insensitive span name filter."},
					"status":           {Type: "string", Enum: []string{"error", "mixed", "ok", "unset"}, Description: "Optional top-level trace status filter."},
					"traceIdPrefix":    {Type: "string", Description: "Optional lowercase hex traceId prefix filter."},
					"spanPreviewCount": {Type: "integer", Minimum: intPtr(0), Maximum: intPtr(12), Default: 5, Description: "Maximum number of spans to include in each trace preview."},
				},
			},
			Annotations: toolAnnot{Title: "Observer Traces Overview", ReadOnlyHint: true, IdempotentHint: true},
		},
		{
			Name:        "observer_trace_detail",
			Description: "Fetch one trace by traceId with ordered spans, attributes, links, and bounded event details.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f, Required: []string{"traceId"},
				Properties: map[string]jsonSchema{
					"eventLimit": {Type: "integer", Minimum: intPtr(0), Maximum: intPtr(32), Default: 12, Description: "Maximum number of events to include per span."},
					"traceId":    {Type: "string", Description: "Lowercase hex traceId to fetch."},
				},
			},
			Annotations: toolAnnot{Title: "Observer Trace Detail", ReadOnlyHint: true, IdempotentHint: true},
		},
		{
			Name:        "observer_clear",
			Description: "Clear all telemetry data (traces, metrics, logs) from the in-memory store. Useful when restarting the instrumented application and wanting a clean slate.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
			},
			Annotations: toolAnnot{Title: "Observer Clear Data", DestructiveHint: true, IdempotentHint: true},
		},
		{
			Name:        "observer_status",
			Description: "Return the collector's listening endpoints (OTLP HTTP, OTLP gRPC, REST/Web UI) and current telemetry stats. Use this to discover which addresses to point instrumented applications at and where to query results.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
			},
			Annotations: toolAnnot{Title: "Observer Status", ReadOnlyHint: true, IdempotentHint: true},
		},
	}
}

func rpcResult(id any, result any) jsonRPCResponse {
	return jsonRPCResponse{ID: id, JSONRPC: "2.0", Result: result}
}

func rpcError(id any, code int, msg string) jsonRPCResponse {
	return jsonRPCResponse{ID: id, JSONRPC: "2.0", Error: &jsonRPCError{Code: code, Message: msg}}
}

func jsonToolResult(v any) toolResult {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return errorResult(err.Error())
	}
	return toolResult{Content: []toolContent{{Type: "text", Text: string(data)}}}
}

func errorResult(msg string) toolResult {
	return toolResult{Content: []toolContent{{Type: "text", Text: msg}}, IsError: true}
}

func negotiateVersion(client string) string {
	for _, v := range supportedVersions {
		if v == client {
			return v
		}
	}
	return supportedVersions[0]
}

func toMap(v any) (map[string]any, bool) {
	if m, ok := v.(map[string]any); ok {
		return m, true
	}
	return map[string]any{}, false
}

func strArg(m map[string]any, key string) string {
	v, _ := m[key].(string)
	return v
}

func intArg(m map[string]any, key string, def int) int {
	switch v := m[key].(type) {
	case float64:
		return int(v)
	case int:
		return v
	}
	return def
}

func intPtr(v int) *int { return &v }
