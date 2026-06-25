// Package mcp implements the Model Context Protocol server for AI assistant integration.
package mcp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
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
	store             *store.Store
	validationService *validator.Service
	splunkMetricsCtrl *otlp.SplunkMetricsExportController
	tools             []toolDef
}

// NewDispatcher creates a new transport-agnostic MCP dispatcher.
func NewDispatcher(s *store.Store, params ...any) *Dispatcher {
	var validationStore *validator.Store
	var runner validator.Runner
	var splunkMetricsCtrl *otlp.SplunkMetricsExportController
	for _, param := range params {
		switch value := param.(type) {
		case *validator.Store:
			if value != nil {
				validationStore = value
			}
		case validator.Runner:
			if value != nil {
				runner = value
			}
		case *otlp.SplunkMetricsExportController:
			if value != nil {
				splunkMetricsCtrl = value
			}
		}
	}
	if validationStore == nil {
		validationStore = validator.NewStore()
	}
	return &Dispatcher{
		store:             s,
		validationService: validator.NewService(validationStore, runner),
		splunkMetricsCtrl: splunkMetricsCtrl,
		tools:             buildToolDefs(splunkMetricsCtrl != nil),
	}
}

// Dispatch processes a single JSON-RPC request and returns a response.
// It returns (response, handled). When handled is false the caller should
// send an HTTP 202 or similar acknowledgement (e.g. for notifications).
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
	params, ok := toMap(req.Params)
	if !ok {
		params = make(map[string]any)
	}
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
	params, ok := toMap(req.Params)
	if !ok {
		params = make(map[string]any)
	}
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
	case "observer_logs_overview":
		result = d.logsOverview(args)
	case "observer_clear":
		result = d.clearStore()
	case "observer_status":
		result = d.status()
	case "observer_validation_status":
		result = d.validationStatus()
	case "observer_validation_analyze":
		result = d.validationAnalyze(args)
	case "observer_validation_refresh":
		result = d.validationRefresh(args)
	case "observer_splunk_metrics_export_status",
		"observer_splunk_metrics_export_configure",
		"observer_splunk_metrics_export_test":
		// These tools are only advertised in tools/list when a Splunk metrics
		// controller is configured. Reject direct calls otherwise so a crafted
		// request cannot reach a nil controller.
		if d.splunkMetricsCtrl == nil {
			return rpcError(req.ID, -32602, fmt.Sprintf("Unknown tool: %s", toolName))
		}
		switch toolName {
		case "observer_splunk_metrics_export_status":
			result = d.splunkMetricsExportStatus()
		case "observer_splunk_metrics_export_configure":
			result = d.splunkMetricsExportConfigure(args)
		case "observer_splunk_metrics_export_test":
			result = d.splunkMetricsExportTest(args)
		}
	default:
		return rpcError(req.ID, -32602, fmt.Sprintf("Unknown tool: %s", toolName))
	}

	return rpcResult(req.ID, result)
}

func (d *Dispatcher) metricsOverview(args map[string]any) toolResult {
	groups := d.store.QueryMetricsFiltered(
		strArg(args, "metricName"),
		strArg(args, "serviceName"),
		strArg(args, "scopeName"),
		strArg(args, "type"),
		strArg(args, "resourceAttribute"),
		intArg(args, "limit", 20),
		intArg(args, "dataPointLimit", 3),
	)
	return jsonToolResult(groups)
}

func (d *Dispatcher) metricDetail(args map[string]any) toolResult {
	name := strArg(args, "metricName")
	if name == "" {
		return errorResult("metricName is required")
	}
	groups := d.store.QueryMetricsFiltered(
		name,
		strArg(args, "serviceName"),
		strArg(args, "scopeName"),
		"", "", 1,
		intArg(args, "dataPointLimit", 50),
	)
	if len(groups) == 0 {
		return errorResult(fmt.Sprintf("No metric found with name %q", name))
	}
	return jsonToolResult(groups[0])
}

func (d *Dispatcher) tracesOverview(args map[string]any) toolResult {
	traces := d.store.QueryTracesFiltered(
		strArg(args, "serviceName"),
		strArg(args, "spanName"),
		strArg(args, "status"),
		strArg(args, "traceIdPrefix"),
		intArg(args, "limit", 20),
		intArg(args, "spanPreviewCount", 5),
	)
	return jsonToolResult(traces)
}

func (d *Dispatcher) traceDetail(args map[string]any) toolResult {
	traceID := strArg(args, "traceId")
	if traceID == "" {
		return errorResult("traceId is required")
	}
	detail := d.store.Trace(traceID, intArg(args, "eventLimit", 12))
	if detail == nil {
		return errorResult(fmt.Sprintf("No trace found with id %q", traceID))
	}
	return jsonToolResult(detail)
}

func (d *Dispatcher) logsOverview(args map[string]any) toolResult {
	logs := d.store.QueryLogsFiltered(
		strArg(args, "serviceName"),
		strArg(args, "severityText"),
		strArg(args, "body"),
		strArg(args, "traceId"),
		intArg(args, "limit", 50),
	)
	return jsonToolResult(logs)
}

func (d *Dispatcher) clearStore() toolResult {
	d.store.Clear()
	return toolResult{Content: []toolContent{{Type: "text", Text: "All telemetry data cleared."}}}
}

func (d *Dispatcher) status() toolResult {
	ep := d.store.Endpoints()
	stats := d.store.Stats()
	return jsonToolResult(map[string]any{
		"endpoints":  ep,
		"stats":      stats,
		"validation": d.validationService.Summary(),
	})
}

func (d *Dispatcher) validationStatus() toolResult {
	return jsonToolResult(d.validationService.Summary())
}

func (d *Dispatcher) validationAnalyze(args map[string]any) toolResult {
	query := validationQueryFromArgs(args)
	timeout := durationArgSeconds(args, "timeoutSeconds", 90*time.Second, 5*time.Second, 5*time.Minute)
	freshness := freshnessArg(args, "freshness", validator.FreshnessAuto)
	analysis, err := d.validationService.Analyze(context.Background(), query, freshness, timeout)
	if err != nil {
		suggestedTool := "observer_validation_analyze"
		if freshness == validator.FreshnessLatestOK {
			suggestedTool = "observer_validation_refresh"
		}
		return jsonValidationErrorResult(err, suggestedTool, "observer_validation_status")
	}
	return jsonToolResult(analysis)
}

func (d *Dispatcher) validationRefresh(args map[string]any) toolResult {
	timeout := durationArgSeconds(args, "timeoutSeconds", 90*time.Second, 5*time.Second, 5*time.Minute)
	analysis, err := d.validationService.Refresh(context.Background(), validationQueryFromArgs(args), timeout)
	if err != nil {
		return jsonValidationErrorResult(err, "observer_validation_status")
	}
	return jsonToolResult(analysis)
}

func (d *Dispatcher) splunkMetricsExportStatus() toolResult {
	return jsonToolResult(d.splunkMetricsCtrl.Status())
}

func (d *Dispatcher) splunkMetricsExportConfigure(args map[string]any) toolResult {
	cfg := otlp.SplunkMetricsExporterConfig{
		Enabled:     boolArg(args, "enabled", false),
		Realm:       strArg(args, "realm"),
		Endpoint:    strArg(args, "endpoint"),
		AccessToken: strArg(args, "accessToken"),
	}
	if seconds := intArg(args, "timeoutSeconds", 0); seconds > 0 {
		cfg.Timeout = time.Duration(seconds) * time.Second
	}
	if err := d.splunkMetricsCtrl.Configure(cfg); err != nil {
		return errorResult(fmt.Sprintf("configure Splunk metrics export: %v", err))
	}
	return jsonToolResult(d.splunkMetricsCtrl.Status())
}

func (d *Dispatcher) splunkMetricsExportTest(args map[string]any) toolResult {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	status, err := d.splunkMetricsCtrl.TestConnection(ctx, strArg(args, "metricName"))
	if err != nil {
		return jsonErrorResult(map[string]any{"error": err.Error(), "status": status})
	}
	return jsonToolResult(status)
}

func buildToolDefs(withSplunk bool) []toolDef {
	f := false
	tools := []toolDef{
		{
			Name:        "observer_metrics_overview",
			Description: "List metrics currently present in the OTLP in-memory store, with compact summaries and bounded datapoint previews. Use this when the user asks what metrics are flowing right now or wants a quick metrics inventory.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
				Properties: map[string]jsonSchema{
					"dataPointLimit":    {Type: "integer", Minimum: intPtr(0), Maximum: intPtr(200), Default: 3, Description: "Maximum datapoints to include per metric summary."},
					"metricName":        {Type: "string", Description: "Optional case-insensitive exact metric name filter."},
					"resourceAttribute": {Type: "string", Description: "Optional substring that must appear in the serialized resource attributes."},
					"scopeName":         {Type: "string", Description: "Optional case-insensitive instrumentation scope name filter."},
					"serviceName":       {Type: "string", Description: "Optional case-insensitive service.name filter."},
					"type":              {Type: "string", Enum: []string{"sum", "gauge", "histogram", "summary", "exponential_histogram"}, Description: "Optional metric type filter."},
					"limit":             {Type: "integer", Minimum: intPtr(1), Maximum: intPtr(100), Default: 20, Description: "Maximum number of metric groups to return."},
				},
			},
			Annotations: toolAnnot{Title: "Observer Metrics Overview", ReadOnlyHint: true, IdempotentHint: true},
		},
		{
			Name:        "observer_metric_detail",
			Description: "Fetch a single metric by exact name with resource and scope context plus a larger datapoint window. Use this when the user asks about one specific metric or wants to inspect a metric mentioned by validation.",
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
			Description: "List recent traces from the OTLP in-memory store with compact span previews and status summaries. Use this when the user asks what traces are flowing, whether tracing is working, or which recent traces look interesting.",
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
			Description: "Fetch one trace by traceId with ordered spans, attributes, links, and bounded event details. Use this after observer_traces_overview or when validation points at a specific trace/span.",
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
			Name:        "observer_logs_overview",
			Description: "List recent log records from the OTLP in-memory store, with filtering by service, severity, body text, and trace correlation. Use this when the user asks what logs are flowing or wants logs related to a trace or validation issue.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
				Properties: map[string]jsonSchema{
					"limit":        {Type: "integer", Minimum: intPtr(1), Maximum: intPtr(200), Default: 50, Description: "Maximum number of log records to return."},
					"serviceName":  {Type: "string", Description: "Optional case-insensitive service.name filter."},
					"severityText": {Type: "string", Enum: []string{"TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"}, Description: "Optional severity level filter."},
					"body":         {Type: "string", Description: "Optional case-insensitive substring filter on the log body."},
					"traceId":      {Type: "string", Description: "Optional traceId to find logs correlated with a specific trace."},
				},
			},
			Annotations: toolAnnot{Title: "Observer Logs Overview", ReadOnlyHint: true, IdempotentHint: true},
		},
		{
			Name:        "observer_validation_status",
			Description: "Return validator runtime state, freshness metadata, run identifiers, and summary counts for the latest retained validation result. Use this when the user explicitly asks whether validation has run, whether a result exists, whether it is stale, or whether a run is currently in progress.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
			},
			Annotations: toolAnnot{Title: "Observer Validation Status", ReadOnlyHint: true, IdempotentHint: true},
		},
		{
			Name:        "observer_validation_analyze",
			Description: "Primary validation tool. Use this for almost all user requests about validation, missing telemetry, semantic convention issues, or what needs fixing. If validation has never run, this automatically runs validation and returns the result. If the latest retained result is stale, it still returns analysis and explicitly says the analysis is based on the prior run time.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
				Properties: map[string]jsonSchema{
					"freshness":      {Type: "string", Enum: []string{"auto", "fresh_required", "latest_ok"}, Default: "auto", Description: "Choose how strictly to require a fresh validation. auto runs validation only when no retained result exists. fresh_required always runs validation now. latest_ok never auto-runs and only uses the latest retained result."},
					"timeoutSeconds": {Type: "integer", Minimum: intPtr(5), Maximum: intPtr(300), Default: 90, Description: "Maximum time to wait for a fresh validation run to finish."},
					"limit":          {Type: "integer", Minimum: intPtr(1), Maximum: intPtr(500), Default: 50, Description: "Maximum findings to include in the returned report."},
					"logBody":        {Type: "string", Description: "Optional substring filter for log body findings."},
					"metricName":     {Type: "string", Description: "Optional exact metric name filter."},
					"ruleId":         {Type: "string", Description: "Optional case-insensitive rule identifier filter."},
					"serviceName":    {Type: "string", Description: "Optional case-insensitive service.name filter."},
					"severity":       {Type: "string", Enum: []string{"information", "improvement", "violation"}, Description: "Optional severity filter."},
					"signalType":     {Type: "string", Enum: []string{"resource", "span", "span_event", "metric", "log"}, Description: "Optional signal type filter."},
					"spanId":         {Type: "string", Description: "Optional exact span id filter."},
					"traceId":        {Type: "string", Description: "Optional exact trace id filter."},
				},
			},
			Annotations: toolAnnot{Title: "Observer Validation Analyze"},
		},
		{
			Name:        "observer_validation_refresh",
			Description: "Explicitly run validation against the current in-memory telemetry snapshot and wait for that run to complete. Use this only when the user explicitly asks to run, re-run, refresh, or validate the current telemetry now.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
				Properties: map[string]jsonSchema{
					"timeoutSeconds": {Type: "integer", Minimum: intPtr(5), Maximum: intPtr(300), Default: 90, Description: "Maximum time to wait for the new validation run to finish."},
					"limit":          {Type: "integer", Minimum: intPtr(1), Maximum: intPtr(500), Default: 50, Description: "Maximum findings to return."},
					"logBody":        {Type: "string", Description: "Optional substring filter for log body findings."},
					"metricName":     {Type: "string", Description: "Optional exact metric name filter."},
					"ruleId":         {Type: "string", Description: "Optional case-insensitive rule identifier filter."},
					"serviceName":    {Type: "string", Description: "Optional case-insensitive service.name filter."},
					"severity":       {Type: "string", Enum: []string{"information", "improvement", "violation"}, Description: "Optional severity filter."},
					"signalType":     {Type: "string", Enum: []string{"resource", "span", "span_event", "metric", "log"}, Description: "Optional signal type filter."},
					"spanId":         {Type: "string", Description: "Optional exact span id filter."},
					"traceId":        {Type: "string", Description: "Optional exact trace id filter."},
				},
			},
			Annotations: toolAnnot{Title: "Observer Validation Refresh"},
		},
		{
			Name:        "observer_clear",
			Description: "Clear all telemetry data (traces, metrics, logs) from the in-memory store. Use this only when the user explicitly asks to clear or reset the observer state.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
			},
			Annotations: toolAnnot{Title: "Observer Clear Data", DestructiveHint: true, IdempotentHint: true},
		},
		{
			Name:        "observer_status",
			Description: "Return the collector's listening endpoints (OTLP HTTP, OTLP gRPC, REST/Web UI) and current telemetry stats. Use this when the user asks whether telemetry is arriving, what ports to send OTLP to, or whether the observer backend is up.",
			InputSchema: jsonSchema{
				Type: "object", AdditionalProperties: &f,
			},
			Annotations: toolAnnot{Title: "Observer Status", ReadOnlyHint: true, IdempotentHint: true},
		},
	}
	if withSplunk {
		tools = append(tools,
			toolDef{
				Name:        "observer_splunk_metrics_export_status",
				Description: "Return the current Splunk Observability Cloud metrics forwarding status, including configured endpoints, token presence, and the last export attempt. Use this to check whether Splunk metrics export is active.",
				InputSchema: jsonSchema{Type: "object", AdditionalProperties: &f},
				Annotations: toolAnnot{Title: "Splunk Metrics Export Status", ReadOnlyHint: true, IdempotentHint: true},
			},
			toolDef{
				Name:        "observer_splunk_metrics_export_configure",
				Description: "Update the Splunk Observability Cloud metrics forwarding configuration at runtime. Use this to enable, disable, or change the realm, endpoint, or access token without restarting obstudio.",
				InputSchema: jsonSchema{
					Type: "object", AdditionalProperties: &f,
					Properties: map[string]jsonSchema{
						"enabled":        {Type: "boolean", Description: "Enable or disable Splunk metrics forwarding."},
						"realm":          {Type: "string", Description: "Splunk realm (e.g. us0, us1, eu0). Ignored when endpoint is set."},
						"endpoint":       {Type: "string", Description: "Custom OTLP ingest endpoint URL. Overrides realm-derived URL."},
						"accessToken":    {Type: "string", Description: "Splunk access token for authentication."},
						"timeoutSeconds": {Type: "integer", Minimum: intPtr(1), Maximum: intPtr(120), Description: "Per-export HTTP timeout in seconds."},
					},
				},
				Annotations: toolAnnot{Title: "Splunk Metrics Export Configure", IdempotentHint: true},
			},
			toolDef{
				Name:        "observer_splunk_metrics_export_test",
				Description: "Send a single canary metric to the configured Splunk Observability Cloud endpoint to verify connectivity and token validity. Returns the updated export status including the outcome of the test send.",
				InputSchema: jsonSchema{
					Type: "object", AdditionalProperties: &f,
					Properties: map[string]jsonSchema{
						"metricName": {Type: "string", Description: "Optional metric name for the canary datapoint. Defaults to obstudio.splunk_exporter.test."},
					},
				},
				Annotations: toolAnnot{Title: "Splunk Metrics Export Test"},
			},
		)
	}
	return tools
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

func jsonErrorResult(v any) toolResult {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return errorResult(err.Error())
	}
	return toolResult{Content: []toolContent{{Type: "text", Text: string(data)}}, IsError: true}
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

const maxIntArg = 10_000

func intArg(m map[string]any, key string, def int) int {
	var n int
	switch v := m[key].(type) {
	case float64:
		n = int(v)
	case int:
		n = v
	default:
		return def
	}
	if n < 0 {
		return def
	}
	if n > maxIntArg {
		return maxIntArg
	}
	return n
}

func intPtr(v int) *int { return &v }

func boolArg(m map[string]any, key string, def bool) bool {
	v, ok := m[key].(bool)
	if !ok {
		return def
	}
	return v
}

func durationArgSeconds(m map[string]any, key string, def, min, max time.Duration) time.Duration {
	seconds := intArg(m, key, int(def/time.Second))
	duration := time.Duration(seconds) * time.Second
	if duration < min {
		return min
	}
	if duration > max {
		return max
	}
	return duration
}

func freshnessArg(m map[string]any, key string, def validator.FreshnessMode) validator.FreshnessMode {
	switch strings.ToLower(strArg(m, key)) {
	case string(validator.FreshnessAuto):
		return validator.FreshnessAuto
	case string(validator.FreshnessFreshRequired):
		return validator.FreshnessFreshRequired
	case string(validator.FreshnessLatestOK):
		return validator.FreshnessLatestOK
	default:
		return def
	}
}

func validationQueryFromArgs(args map[string]any) validator.Query {
	return validator.Query{
		ServiceName: strArg(args, "serviceName"),
		SignalType:  strArg(args, "signalType"),
		Severity:    strArg(args, "severity"),
		RuleID:      strArg(args, "ruleId"),
		TraceID:     strArg(args, "traceId"),
		SpanID:      strArg(args, "spanId"),
		MetricName:  strArg(args, "metricName"),
		LogBody:     strArg(args, "logBody"),
		Limit:       intArg(args, "limit", 50),
	}
}

func jsonValidationErrorResult(err error, suggestedTools ...string) toolResult {
	var serviceErr *validator.ServiceError
	if !errors.As(err, &serviceErr) {
		payload := map[string]any{"error": err.Error()}
		if len(suggestedTools) > 0 {
			payload["suggestedTool"] = suggestedTools[0]
			payload["suggestedTools"] = suggestedTools
		}
		return jsonErrorResult(payload)
	}

	payload := map[string]any{
		"error":   serviceErr.Error(),
		"summary": serviceErr.Summary,
	}
	if serviceErr.RequestedRunID != "" {
		payload["requestedRunId"] = serviceErr.RequestedRunID
	}
	if serviceErr.AvailableResultID != "" {
		payload["availableResultId"] = serviceErr.AvailableResultID
	}
	if len(suggestedTools) > 0 {
		payload["suggestedTool"] = suggestedTools[0]
		payload["suggestedTools"] = suggestedTools
	}
	if serviceErr.Kind == validator.ErrRunStillRunning {
		payload["suggestedTool"] = "observer_validation_status"
		payload["suggestedTools"] = []string{"observer_validation_status"}
	}
	return jsonErrorResult(payload)
}
