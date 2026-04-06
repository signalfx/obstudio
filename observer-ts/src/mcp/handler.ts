// MCP (Model Context Protocol) JSON-RPC 2.0 dispatcher.
// 5 tools matching observer-go exactly.

import type { Store } from "../store/store.ts";
import { queryTraces, getTrace, queryMetrics, queryLogs, stats, queryServiceMap } from "../store/query.ts";

// --- JSON-RPC types ---

export type JsonRpcRequest = {
  id?: unknown;
  jsonrpc: string;
  method: string;
  params?: unknown;
};

export type JsonRpcResponse = {
  id: unknown;
  jsonrpc: string;
  result?: unknown;
  error?: JsonRpcError;
};

type JsonRpcError = {
  code: number;
  message: string;
  data?: unknown;
};

type ToolContent = {
  type: "text";
  text: string;
};

type ToolResult = {
  content: ToolContent[];
  isError?: boolean;
};

type ToolDef = {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  annotations: {
    title: string;
    readOnlyHint?: boolean;
    destructiveHint?: boolean;
    idempotentHint?: boolean;
    openWorldHint?: boolean;
  };
};

// --- Protocol versions ---

const SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"];

// --- Tool definitions ---

const TOOLS: ToolDef[] = [
  {
    name: "observer_traces_overview",
    description: "List recent traces with compact span previews and status summaries",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        limit: { type: "integer", minimum: 1, maximum: 50, default: 20, description: "Maximum number of traces to return" },
        serviceName: { type: "string", description: "Optional case-insensitive service.name filter" },
        spanName: { type: "string", description: "Optional case-insensitive span name filter" },
        status: { type: "string", enum: ["error", "mixed", "ok", "unset"], description: "Optional top-level trace status filter" },
        traceIdPrefix: { type: "string", description: "Optional lowercase hex traceId prefix filter" },
        spanPreviewCount: { type: "integer", minimum: 0, maximum: 12, default: 5, description: "Maximum number of spans to include in each trace preview" },
      },
    },
    annotations: { title: "Observer Traces Overview", readOnlyHint: true, idempotentHint: true },
  },
  {
    name: "observer_trace_detail",
    description: "Fetch one trace by traceId with ordered spans, attributes, links, and bounded event details",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["traceId"],
      properties: {
        traceId: { type: "string", description: "Lowercase hex traceId to fetch" },
        eventLimit: { type: "integer", minimum: 0, maximum: 32, default: 12, description: "Maximum number of events to include per span" },
      },
    },
    annotations: { title: "Observer Trace Detail", readOnlyHint: true, idempotentHint: true },
  },
  {
    name: "observer_metrics_overview",
    description: "List metrics with compact summaries and bounded datapoint previews",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        limit: { type: "integer", minimum: 1, maximum: 100, default: 20, description: "Maximum number of metric groups to return" },
        metricName: { type: "string", description: "Optional case-insensitive exact metric name filter" },
        serviceName: { type: "string", description: "Optional case-insensitive service.name filter" },
        scopeName: { type: "string", description: "Optional case-insensitive instrumentation scope name filter" },
        type: { type: "string", enum: ["counter", "gauge", "histogram", "summary", "exponential_histogram"], description: "Optional metric kind filter" },
        resourceAttribute: { type: "string", description: "Optional substring that must appear in the serialized resource attributes" },
        dataPointLimit: { type: "integer", minimum: 0, maximum: 200, default: 3, description: "Maximum datapoints to include per metric summary" },
      },
    },
    annotations: { title: "Observer Metrics Overview", readOnlyHint: true, idempotentHint: true },
  },
  {
    name: "observer_metric_detail",
    description: "Fetch a single metric by exact name with resource and scope context plus larger datapoint window",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["metricName"],
      properties: {
        metricName: { type: "string", description: "Exact metric name to return" },
        serviceName: { type: "string", description: "Optional case-insensitive service.name filter" },
        scopeName: { type: "string", description: "Optional case-insensitive scope filter" },
        dataPointLimit: { type: "integer", minimum: 1, maximum: 200, default: 50, description: "Maximum datapoints to include for each matching metric series" },
      },
    },
    annotations: { title: "Observer Metric Detail", readOnlyHint: true, idempotentHint: true },
  },
  {
    name: "observer_clear",
    description: "Clear all telemetry data (traces, metrics, logs) from the in-memory store",
    inputSchema: { type: "object", additionalProperties: false, properties: {} },
    annotations: { title: "Observer Clear Data", destructiveHint: true, idempotentHint: true },
  },
];

// --- Dispatcher ---

export class McpDispatcher {
  constructor(private store: Store) {}

  dispatch(req: JsonRpcRequest): JsonRpcResponse | null {
    switch (req.method) {
      case "initialize":
        return this.handleInitialize(req);
      case "notifications/initialized":
        return null; // Notification, no response.
      case "tools/list":
        return this.handleToolsList(req);
      case "tools/call":
        return this.handleToolsCall(req);
      default:
        return {
          id: req.id,
          jsonrpc: "2.0",
          error: { code: -32601, message: `Method not found: ${req.method}` },
        };
    }
  }

  private handleInitialize(req: JsonRpcRequest): JsonRpcResponse {
    const params = (req.params ?? {}) as Record<string, unknown>;
    const clientVersion = params.protocolVersion as string | undefined;

    let negotiatedVersion = SUPPORTED_VERSIONS[0]!;
    if (clientVersion && SUPPORTED_VERSIONS.includes(clientVersion)) {
      negotiatedVersion = clientVersion;
    }

    return {
      id: req.id,
      jsonrpc: "2.0",
      result: {
        protocolVersion: negotiatedVersion,
        capabilities: {
          tools: { listChanged: false },
        },
        serverInfo: {
          name: "obstudio",
          version: "0.1.0",
        },
      },
    };
  }

  private handleToolsList(req: JsonRpcRequest): JsonRpcResponse {
    return {
      id: req.id,
      jsonrpc: "2.0",
      result: { tools: TOOLS },
    };
  }

  private handleToolsCall(req: JsonRpcRequest): JsonRpcResponse {
    const params = (req.params ?? {}) as Record<string, unknown>;
    const toolName = params.name as string;
    const args = (params.arguments ?? {}) as Record<string, unknown>;

    let result: ToolResult;

    switch (toolName) {
      case "observer_traces_overview":
        result = this.tracesOverview(args);
        break;
      case "observer_trace_detail":
        result = this.traceDetail(args);
        break;
      case "observer_metrics_overview":
        result = this.metricsOverview(args);
        break;
      case "observer_metric_detail":
        result = this.metricDetail(args);
        break;
      case "observer_clear":
        result = this.clearData();
        break;
      default:
        return {
          id: req.id,
          jsonrpc: "2.0",
          error: { code: -32602, message: `Unknown tool: ${toolName}` },
        };
    }

    return { id: req.id, jsonrpc: "2.0", result };
  }

  // --- Tool implementations ---

  private tracesOverview(args: Record<string, unknown>): ToolResult {
    const traces = queryTraces(this.store, {
      serviceName: strArg(args, "serviceName"),
      spanName: strArg(args, "spanName"),
      status: strArg(args, "status"),
      traceIdPrefix: strArg(args, "traceIdPrefix"),
      limit: intArg(args, "limit", 20),
      spanPreviewCount: intArg(args, "spanPreviewCount", 5),
    });
    return jsonToolResult(traces);
  }

  private traceDetail(args: Record<string, unknown>): ToolResult {
    const traceId = strArg(args, "traceId");
    if (!traceId) return errorResult("traceId is required");

    const detail = getTrace(this.store, traceId, intArg(args, "eventLimit", 12));
    if (!detail) return errorResult(`No trace found with id "${traceId}"`);

    return jsonToolResult(detail);
  }

  private metricsOverview(args: Record<string, unknown>): ToolResult {
    const groups = queryMetrics(this.store, {
      metricName: strArg(args, "metricName"),
      serviceName: strArg(args, "serviceName"),
      scopeName: strArg(args, "scopeName"),
      type: strArg(args, "type"),
      resourceAttribute: strArg(args, "resourceAttribute"),
      limit: intArg(args, "limit", 20),
      dataPointLimit: intArg(args, "dataPointLimit", 3),
    });
    return jsonToolResult(groups);
  }

  private metricDetail(args: Record<string, unknown>): ToolResult {
    const name = strArg(args, "metricName");
    if (!name) return errorResult("metricName is required");

    const groups = queryMetrics(this.store, {
      metricName: name,
      serviceName: strArg(args, "serviceName"),
      scopeName: strArg(args, "scopeName"),
      limit: 1,
      dataPointLimit: intArg(args, "dataPointLimit", 50),
    });

    if (groups.length === 0) return errorResult(`No metric found with name "${name}"`);
    return jsonToolResult(groups[0]);
  }

  private clearData(): ToolResult {
    this.store.clear();
    return {
      content: [{ type: "text", text: "All telemetry data cleared." }],
    };
  }
}

// --- Helpers ---

function strArg(args: Record<string, unknown>, key: string): string | undefined {
  const v = args[key];
  return typeof v === "string" ? v : undefined;
}

function intArg(args: Record<string, unknown>, key: string, fallback: number): number {
  const v = args[key];
  if (typeof v !== "number") return fallback;
  // Clamp to reasonable bounds (matching JSON schema limits across all tools).
  return Math.max(0, Math.min(Math.floor(v), 1000));
}

function jsonToolResult(data: unknown): ToolResult {
  return {
    content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
  };
}

function errorResult(message: string): ToolResult {
  return {
    content: [{ type: "text", text: message }],
    isError: true,
  };
}
