import express from "express";
import type { AnyValue, KeyValue } from "../../shared/otlp/opentelemetry/proto/common/v1/common.d.mts";
import type {
  ExponentialHistogramDataPoint,
  HistogramDataPoint,
  Metric,
  NumberDataPoint,
  ResourceMetrics,
  SummaryDataPoint,
} from "../../shared/otlp/opentelemetry/proto/metrics/v1/metrics.d.mts";
import type { ResourceSpans, ScopeSpans } from "../../shared/otlp/opentelemetry/proto/trace/v1/trace.d.mts";
import { otlpInMemoryStore } from "./otlp-store.js";

const mcpHttpPath = process.env.MCP_PATH ?? "/mcp";
const mcpPayloadLimit = "1mb";
const serverName = "observer";
const serverVersion = "0.1.0";
const supportedProtocolVersions = ["2025-06-18", "2025-03-26", "2024-11-05"] as const;
const defaultProtocolVersion = supportedProtocolVersions[0];
const maxMetricDataPoints = 200;
const maxTraceResults = 50;
const maxMetricResults = 100;
const maxTraceSpanPreviewCount = 12;
const maxTraceEventCount = 32;

type JsonRpcId = number | string | null;
type JsonRpcError = {
  code: number;
  data?: unknown;
  message: string;
};
type JsonRpcRequest = {
  id?: JsonRpcId;
  jsonrpc?: "2.0";
  method?: string;
  params?: unknown;
};
type JsonRpcResponse = {
  error?: JsonRpcError;
  id: JsonRpcId;
  jsonrpc: "2.0";
  result?: unknown;
};

type JsonSchema = {
  additionalProperties?: boolean;
  default?: unknown;
  description?: string;
  enum?: readonly string[];
  items?: JsonSchema;
  maxItems?: number;
  maximum?: number;
  minItems?: number;
  minimum?: number;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  type?: "array" | "boolean" | "integer" | "number" | "object" | "string";
};

type MpcToolDefinition = {
  annotations: {
    destructiveHint: boolean;
    idempotentHint: boolean;
    openWorldHint: boolean;
    readOnlyHint: boolean;
    title: string;
  };
  description: string;
  inputSchema: JsonSchema;
  name: string;
};

type MpcToolHandler = (params: Record<string, unknown>) => MpcToolResult;
type MpcToolResult = {
  content: Array<{ text: string; type: "text" }>;
  isError?: boolean;
  structuredContent: unknown;
};

type MetricMatchFilters = {
  metricName?: string;
  resourceAttribute?: string;
  scopeName?: string;
  serviceName?: string;
  type?: string;
};

type TraceMatchFilters = {
  serviceName?: string;
  spanName?: string;
  status?: string;
  traceIdPrefix?: string;
};

type NormalizedMetric = {
  dataPointCount: number;
  dataPoints: MetricDataPointSummary[];
  description: string;
  isMonotonic?: boolean;
  name: string;
  resource: {
    attributes: Record<string, unknown>;
    schemaUrl: string;
    serviceName?: string;
  };
  scope: {
    name: string;
    schemaUrl: string;
    version: string;
  };
  temporality?: string;
  type: string;
  unit: string;
};

type MetricDataPointSummary = {
  attributes: Record<string, unknown>;
  bucketCounts?: string[];
  count?: string;
  explicitBounds?: number[];
  flags: number;
  max?: number;
  min?: number;
  quantiles?: Array<{ quantile: number; value: number }>;
  startTimeUnixNano: string;
  sum?: number;
  timeUnixNano: string;
  value?: number | string;
  zeroCount?: string;
  zeroThreshold?: number;
};

type NormalizedTrace = {
  durationMs?: number;
  rootSpanName: string;
  serviceName?: string;
  spanCount: number;
  spans: NormalizedTraceSpan[];
  status: "error" | "mixed" | "ok" | "unset";
  traceId: string;
};

type NormalizedTraceSpan = {
  attributes: Record<string, unknown>;
  durationMs?: number;
  endTimeUnixNano: string;
  events: Array<{
    attributes: Record<string, unknown>;
    name: string;
    timeUnixNano: string;
  }>;
  kind: string;
  links: Array<{
    attributes: Record<string, unknown>;
    spanId: string;
    traceId: string;
  }>;
  name: string;
  parentSpanId: string;
  resource: {
    attributes: Record<string, unknown>;
    schemaUrl: string;
    serviceName?: string;
  };
  scope: {
    name: string;
    schemaUrl: string;
    version: string;
  };
  spanId: string;
  startTimeUnixNano: string;
  status: {
    code: string;
    message: string;
  };
  traceId: string;
};

const metricsOverviewTool: MpcToolDefinition = {
  name: "observer_metrics_overview",
  description: "List metrics currently present in the OTLP in-memory store, with compact summaries and bounded datapoint previews.",
  inputSchema: {
    type: "object",
    additionalProperties: false,
    properties: {
      dataPointLimit: {
        type: "integer",
        minimum: 0,
        maximum: maxMetricDataPoints,
        default: 3,
        description: "Maximum datapoints to include per metric summary.",
      },
      metricName: {
        type: "string",
        description: "Optional case-insensitive exact metric name filter.",
      },
      resourceAttribute: {
        type: "string",
        description: "Optional substring that must appear in the serialized resource attributes.",
      },
      scopeName: {
        type: "string",
        description: "Optional case-insensitive instrumentation scope name filter.",
      },
      serviceName: {
        type: "string",
        description: "Optional case-insensitive service.name filter.",
      },
      type: {
        type: "string",
        enum: ["counter", "gauge", "histogram", "summary", "exponential_histogram"],
        description: "Optional metric kind filter.",
      },
      limit: {
        type: "integer",
        minimum: 1,
        maximum: maxMetricResults,
        default: 20,
        description: "Maximum number of metrics to return.",
      },
    },
  },
  annotations: {
    title: "Observer Metrics Overview",
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
};

const metricDetailTool: MpcToolDefinition = {
  name: "observer_metric_detail",
  description: "Fetch a single metric by exact name with resource and scope context plus a larger datapoint window.",
  inputSchema: {
    type: "object",
    additionalProperties: false,
    required: ["metricName"],
    properties: {
      metricName: {
        type: "string",
        description: "Exact metric name to return.",
      },
      dataPointLimit: {
        type: "integer",
        minimum: 1,
        maximum: maxMetricDataPoints,
        default: 50,
        description: "Maximum datapoints to include for each matching metric series.",
      },
      scopeName: {
        type: "string",
        description: "Optional case-insensitive scope filter when the same metric name exists in multiple scopes.",
      },
      serviceName: {
        type: "string",
        description: "Optional case-insensitive service.name filter when the same metric name exists in multiple resources.",
      },
    },
  },
  annotations: {
    title: "Observer Metric Detail",
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
};

const tracesOverviewTool: MpcToolDefinition = {
  name: "observer_traces_overview",
  description: "List recent traces from the OTLP in-memory store with compact span previews and status summaries.",
  inputSchema: {
    type: "object",
    additionalProperties: false,
    properties: {
      limit: {
        type: "integer",
        minimum: 1,
        maximum: maxTraceResults,
        default: 20,
        description: "Maximum number of traces to return.",
      },
      serviceName: {
        type: "string",
        description: "Optional case-insensitive service.name filter.",
      },
      spanName: {
        type: "string",
        description: "Optional case-insensitive span name filter.",
      },
      status: {
        type: "string",
        enum: ["error", "mixed", "ok", "unset"],
        description: "Optional top-level trace status filter.",
      },
      traceIdPrefix: {
        type: "string",
        description: "Optional lowercase hex traceId prefix filter.",
      },
      spanPreviewCount: {
        type: "integer",
        minimum: 0,
        maximum: maxTraceSpanPreviewCount,
        default: 5,
        description: "Maximum number of spans to include in each trace preview.",
      },
    },
  },
  annotations: {
    title: "Observer Traces Overview",
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
};

const traceDetailTool: MpcToolDefinition = {
  name: "observer_trace_detail",
  description: "Fetch one trace by traceId with ordered spans, attributes, links, and bounded event details.",
  inputSchema: {
    type: "object",
    additionalProperties: false,
    required: ["traceId"],
    properties: {
      eventLimit: {
        type: "integer",
        minimum: 0,
        maximum: maxTraceEventCount,
        default: 12,
        description: "Maximum number of events to include per span.",
      },
      traceId: {
        type: "string",
        description: "Lowercase hex traceId to fetch.",
      },
    },
  },
  annotations: {
    title: "Observer Trace Detail",
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
};

const mcpTools = new Map<string, { definition: MpcToolDefinition; handler: MpcToolHandler }>([
  [metricsOverviewTool.name, { definition: metricsOverviewTool, handler: handleMetricsOverviewTool }],
  [metricDetailTool.name, { definition: metricDetailTool, handler: handleMetricDetailTool }],
  [tracesOverviewTool.name, { definition: tracesOverviewTool, handler: handleTracesOverviewTool }],
  [traceDetailTool.name, { definition: traceDetailTool, handler: handleTraceDetailTool }],
]);

export function registerMcpHttpApi(app: express.Express): void {
  app.options(mcpHttpPath, (_request, response) => {
    applyMcpHeaders(response, defaultProtocolVersion);
    response.setHeader("Allow", "OPTIONS, POST");
    response.status(204).end();
  });

  app.get(mcpHttpPath, (_request, response) => {
    applyMcpHeaders(response, defaultProtocolVersion);
    response.setHeader("Allow", "OPTIONS, POST");
    response.status(405).json({
      error: "method_not_allowed",
      message: "This MCP endpoint accepts JSON-RPC over HTTP POST.",
      path: mcpHttpPath,
    });
  });

  app.post(mcpHttpPath, express.text({ limit: mcpPayloadLimit, type: () => true }), (request, response) => {
    const protocolVersion = getRequestedProtocolVersion(request);
    applyMcpHeaders(response, protocolVersion);

    if (!isAllowedOrigin(request)) {
      response.status(403).json({
        jsonrpc: "2.0",
        id: null,
        error: {
          code: -32001,
          message: "Origin not allowed for MCP endpoint.",
        },
      });
      return;
    }

    const parsedBody = parseJsonRpcPayload(request.body);
    if (!parsedBody.ok) {
      response.status(400).json({
        jsonrpc: "2.0",
        id: null,
        error: {
          code: -32700,
          message: parsedBody.message,
        },
      });
      return;
    }

    const requests = Array.isArray(parsedBody.value) ? parsedBody.value : [parsedBody.value];
    if (requests.length === 0) {
      response.status(400).json({
        jsonrpc: "2.0",
        id: null,
        error: {
          code: -32600,
          message: "JSON-RPC batch requests must not be empty.",
        },
      });
      return;
    }

    const responses: JsonRpcResponse[] = [];
    for (const entry of requests) {
      const rpcResponse = handleJsonRpcRequest(entry, protocolVersion);
      if (rpcResponse !== null) {
        responses.push(rpcResponse);
      }
    }

    if (responses.length === 0) {
      response.status(202).end();
      return;
    }

    response.status(200).json(Array.isArray(parsedBody.value) ? responses : responses[0]);
  });
}

function handleJsonRpcRequest(payload: unknown, protocolVersion: string): JsonRpcResponse | null {
  if (!isJsonRpcRequest(payload)) {
    return createErrorResponse(null, -32600, "Invalid JSON-RPC request.");
  }

  if (payload.method === "notifications/initialized") {
    return null;
  }

  if (payload.method === undefined) {
    return createErrorResponse(payload.id ?? null, -32600, "JSON-RPC request is missing a method.");
  }

  if (payload.jsonrpc !== "2.0") {
    return createErrorResponse(payload.id ?? null, -32600, "JSON-RPC version must be 2.0.");
  }

  switch (payload.method) {
    case "initialize":
      return handleInitializeRequest(payload.id ?? null, payload.params, protocolVersion);
    case "ping":
      return createResultResponse(payload.id ?? null, {});
    case "tools/list":
      return createResultResponse(payload.id ?? null, {
        tools: [...mcpTools.values()].map(({ definition }) => definition),
      });
    case "tools/call":
      return handleToolsCall(payload.id ?? null, payload.params);
    default:
      return createErrorResponse(payload.id ?? null, -32601, `Method not found: ${payload.method}`);
  }
}

function handleInitialize(params: unknown, requestedProtocolVersion: string) {
  const protocolVersion = resolveProtocolVersion(params, requestedProtocolVersion);
  if (protocolVersion === null) {
    return createJsonRpcError(-32602, `Unsupported MCP protocol version. Supported versions: ${supportedProtocolVersions.join(", ")}`);
  }

  return {
    capabilities: {
      tools: {
        listChanged: false,
      },
    },
    instructions:
      "This server exposes read-only telemetry tools over the Observer OTLP in-memory store. Prefer overview tools first, then fetch detail for a specific metric or trace.",
    protocolVersion,
    serverInfo: {
      name: serverName,
      version: serverVersion,
    },
  };
}

function handleInitializeRequest(id: JsonRpcId, params: unknown, requestedProtocolVersion: string): JsonRpcResponse {
  const initialized = handleInitialize(params, requestedProtocolVersion);
  if (initialized instanceof Error) {
    return createErrorResponse(id, (initialized as Error & { code?: number }).code ?? -32602, initialized.message);
  }

  return createResultResponse(id, initialized);
}

function handleToolsCall(id: JsonRpcId, params: unknown): JsonRpcResponse {
  if (!isRecord(params)) {
    return createErrorResponse(id, -32602, "tools/call params must be an object.");
  }

  const toolName = typeof params.name === "string" ? params.name : null;
  if (toolName === null) {
    return createErrorResponse(id, -32602, "tools/call params.name must be a string.");
  }

  const tool = mcpTools.get(toolName);
  if (tool === undefined) {
    return createErrorResponse(id, -32601, `Unknown tool: ${toolName}`);
  }

  const argumentsObject = isRecord(params.arguments) ? params.arguments : {};

  try {
    return createResultResponse(id, tool.handler(argumentsObject));
  } catch (error) {
    const message = error instanceof Error ? error.message : "Tool execution failed.";
    return createResultResponse(id, {
      content: [{ type: "text", text: message }],
      isError: true,
      structuredContent: { error: message, tool: toolName },
    });
  }
}

function handleMetricsOverviewTool(params: Record<string, unknown>): MpcToolResult {
  const limit = readInteger(params.limit, 20, 1, maxMetricResults);
  const dataPointLimit = readInteger(params.dataPointLimit, 3, 0, maxMetricDataPoints);
  const filters: MetricMatchFilters = {
    metricName: readOptionalString(params.metricName),
    resourceAttribute: readOptionalString(params.resourceAttribute),
    scopeName: readOptionalString(params.scopeName),
    serviceName: readOptionalString(params.serviceName),
    type: readOptionalString(params.type),
  };

  const matchedMetrics = collectNormalizedMetrics(dataPointLimit).filter((metric) => matchesMetricFilters(metric, filters)).slice(0, limit);
  const totals = collectMetricTotals();

  return {
    content: [
      {
        type: "text",
        text: matchedMetrics.length === 0
          ? `No metrics matched. Store currently has ${totals.metricCount} metric definitions across ${totals.resourceCount} resources.`
          : `Returned ${matchedMetrics.length} metric summaries from ${totals.metricCount} metric definitions across ${totals.resourceCount} resources.`,
      },
    ],
    structuredContent: {
      filters,
      totals,
      metrics: matchedMetrics,
    },
  };
}

function handleMetricDetailTool(params: Record<string, unknown>): MpcToolResult {
  const metricName = readRequiredString(params.metricName, "metricName");
  const dataPointLimit = readInteger(params.dataPointLimit, 50, 1, maxMetricDataPoints);
  const filters: MetricMatchFilters = {
    metricName,
    scopeName: readOptionalString(params.scopeName),
    serviceName: readOptionalString(params.serviceName),
  };

  const matchedMetrics = collectNormalizedMetrics(dataPointLimit).filter((metric) => matchesMetricFilters(metric, filters));
  return {
    content: [
      {
        type: "text",
        text: matchedMetrics.length === 0
          ? `Metric ${metricName} was not found in the merged OTLP store.`
          : `Found ${matchedMetrics.length} matching metric series for ${metricName}.`,
      },
    ],
    isError: matchedMetrics.length === 0,
    structuredContent: {
      metricName,
      matches: matchedMetrics,
    },
  };
}

function handleTracesOverviewTool(params: Record<string, unknown>): MpcToolResult {
  const limit = readInteger(params.limit, 20, 1, maxTraceResults);
  const spanPreviewCount = readInteger(params.spanPreviewCount, 5, 0, maxTraceSpanPreviewCount);
  const filters: TraceMatchFilters = {
    serviceName: readOptionalString(params.serviceName),
    spanName: readOptionalString(params.spanName),
    status: readOptionalString(params.status),
    traceIdPrefix: readOptionalString(params.traceIdPrefix),
  };

  const traces = collectNormalizedTraces(0)
    .filter((trace) => matchesTraceFilters(trace, filters))
    .slice(0, limit)
    .map((trace) => ({
      durationMs: trace.durationMs,
      rootSpanName: trace.rootSpanName,
      serviceName: trace.serviceName,
      spanCount: trace.spanCount,
      spanPreview: trace.spans.slice(0, spanPreviewCount).map((span) => ({
        durationMs: span.durationMs,
        kind: span.kind,
        name: span.name,
        parentSpanId: span.parentSpanId,
        spanId: span.spanId,
        status: span.status,
      })),
      status: trace.status,
      traceId: trace.traceId,
    }));

  const totalTraces = otlpInMemoryStore.getMergedTracesRequest().resourceSpans.length;

  return {
    content: [
      {
        type: "text",
        text: traces.length === 0
          ? `No traces matched. Store currently has ${totalTraces} merged traces.`
          : `Returned ${traces.length} traces from ${totalTraces} merged traces.`,
      },
    ],
    structuredContent: {
      filters,
      totalTraces,
      traces,
    },
  };
}

function handleTraceDetailTool(params: Record<string, unknown>): MpcToolResult {
  const traceId = normalizeHexId(readRequiredString(params.traceId, "traceId"));
  const eventLimit = readInteger(params.eventLimit, 12, 0, maxTraceEventCount);
  const trace = collectNormalizedTraces(eventLimit).find((entry) => entry.traceId === traceId);

  return {
    content: [
      {
        type: "text",
        text: trace === undefined ? `Trace ${traceId} was not found in the merged OTLP store.` : `Trace ${traceId} contains ${trace.spanCount} spans.`,
      },
    ],
    isError: trace === undefined,
    structuredContent: trace === undefined ? { traceId } : trace,
  };
}

function collectMetricTotals(): { metricCount: number; resourceCount: number; scopeCount: number } {
  const resourceMetrics = otlpInMemoryStore.getMergedMetricsRequest().resourceMetrics;
  return {
    metricCount: resourceMetrics.reduce(
      (count, resourceMetric) => count + resourceMetric.scopeMetrics.reduce((scopeCount, scope) => scopeCount + scope.metrics.length, 0),
      0,
    ),
    resourceCount: resourceMetrics.length,
    scopeCount: resourceMetrics.reduce((count, resourceMetric) => count + resourceMetric.scopeMetrics.length, 0),
  };
}

function collectNormalizedMetrics(dataPointLimit: number): NormalizedMetric[] {
  return otlpInMemoryStore.getMergedMetricsRequest().resourceMetrics.flatMap((resourceMetrics) =>
    flattenResourceMetrics(resourceMetrics, dataPointLimit),
  );
}

function flattenResourceMetrics(resourceMetrics: ResourceMetrics, dataPointLimit: number): NormalizedMetric[] {
  const resourceAttributes = attributesToRecord(resourceMetrics.resource?.attributes);
  const serviceName = getOptionalString(resourceAttributes["service.name"]);

  return resourceMetrics.scopeMetrics.flatMap((scopeMetrics) =>
    scopeMetrics.metrics.map((metric) => ({
      dataPointCount: getMetricDataPoints(metric).length,
      dataPoints: getMetricDataPoints(metric).slice(0, dataPointLimit).map(summarizeMetricDataPoint),
      description: metric.description,
      isMonotonic: getMetricMonotonic(metric),
      name: metric.name,
      resource: {
        attributes: resourceAttributes,
        schemaUrl: resourceMetrics.schemaUrl,
        serviceName,
      },
      scope: {
        name: scopeMetrics.scope?.name ?? "",
        schemaUrl: scopeMetrics.schemaUrl,
        version: scopeMetrics.scope?.version ?? "",
      },
      temporality: getMetricTemporality(metric),
      type: getMetricType(metric),
      unit: metric.unit,
    })),
  );
}

function getMetricDataPoints(metric: Metric): Array<NumberDataPoint | HistogramDataPoint | ExponentialHistogramDataPoint | SummaryDataPoint> {
  switch (metric.data?.$case) {
    case "gauge":
      return metric.data.gauge.dataPoints;
    case "sum":
      return metric.data.sum.dataPoints;
    case "histogram":
      return metric.data.histogram.dataPoints;
    case "exponentialHistogram":
      return metric.data.exponentialHistogram.dataPoints;
    case "summary":
      return metric.data.summary.dataPoints;
    default:
      return [];
  }
}

function getMetricType(metric: Metric): string {
  switch (metric.data?.$case) {
    case "gauge":
      return "gauge";
    case "sum":
      return metric.data.sum.isMonotonic ? "counter" : "gauge";
    case "histogram":
      return "histogram";
    case "exponentialHistogram":
      return "exponential_histogram";
    case "summary":
      return "summary";
    default:
      return "unknown";
  }
}

function getMetricTemporality(metric: Metric): string | undefined {
  switch (metric.data?.$case) {
    case "sum":
      return formatAggregationTemporality(metric.data.sum.aggregationTemporality);
    case "histogram":
      return formatAggregationTemporality(metric.data.histogram.aggregationTemporality);
    case "exponentialHistogram":
      return formatAggregationTemporality(metric.data.exponentialHistogram.aggregationTemporality);
    default:
      return undefined;
  }
}

function getMetricMonotonic(metric: Metric): boolean | undefined {
  return metric.data?.$case === "sum" ? metric.data.sum.isMonotonic : undefined;
}

function summarizeMetricDataPoint(
  dataPoint: NumberDataPoint | HistogramDataPoint | ExponentialHistogramDataPoint | SummaryDataPoint,
): MetricDataPointSummary {
  const summary: MetricDataPointSummary = {
    attributes: attributesToRecord(dataPoint.attributes),
    flags: dataPoint.flags,
    startTimeUnixNano: dataPoint.startTimeUnixNano,
    timeUnixNano: dataPoint.timeUnixNano,
  };

  if ("value" in dataPoint) {
    summary.value = dataPoint.value?.$case === "asDouble" ? dataPoint.value.asDouble : dataPoint.value?.asInt;
  }
  if ("count" in dataPoint) {
    summary.count = dataPoint.count;
  }
  if ("sum" in dataPoint && typeof dataPoint.sum === "number") {
    summary.sum = dataPoint.sum;
  }
  if ("min" in dataPoint && typeof dataPoint.min === "number") {
    summary.min = dataPoint.min;
  }
  if ("max" in dataPoint && typeof dataPoint.max === "number") {
    summary.max = dataPoint.max;
  }
  if ("bucketCounts" in dataPoint) {
    summary.bucketCounts = dataPoint.bucketCounts;
  }
  if ("explicitBounds" in dataPoint) {
    summary.explicitBounds = dataPoint.explicitBounds;
  }
  if ("zeroCount" in dataPoint) {
    summary.zeroCount = dataPoint.zeroCount;
    summary.zeroThreshold = dataPoint.zeroThreshold;
  }
  if ("quantileValues" in dataPoint) {
    summary.quantiles = dataPoint.quantileValues.map((entry) => ({ quantile: entry.quantile, value: entry.value }));
  }

  return summary;
}

function matchesMetricFilters(metric: NormalizedMetric, filters: MetricMatchFilters): boolean {
  if (filters.metricName !== undefined && metric.name.toLowerCase() !== filters.metricName.toLowerCase()) {
    return false;
  }
  if (filters.scopeName !== undefined && metric.scope.name.toLowerCase() !== filters.scopeName.toLowerCase()) {
    return false;
  }
  if (filters.serviceName !== undefined && metric.resource.serviceName?.toLowerCase() !== filters.serviceName.toLowerCase()) {
    return false;
  }
  if (filters.type !== undefined && metric.type !== filters.type.toLowerCase()) {
    return false;
  }
  if (filters.resourceAttribute !== undefined) {
    const serialized = JSON.stringify(metric.resource.attributes).toLowerCase();
    if (!serialized.includes(filters.resourceAttribute.toLowerCase())) {
      return false;
    }
  }

  return true;
}

function collectNormalizedTraces(eventLimit: number): NormalizedTrace[] {
  return otlpInMemoryStore.getMergedTracesRequest().resourceSpans.map((resourceSpans) => normalizeTrace(resourceSpans, eventLimit));
}

function normalizeTrace(resourceSpans: ResourceSpans, eventLimit: number): NormalizedTrace {
  const spans = flattenTraceSpans(resourceSpans, eventLimit);
  const rootSpan = spans.find((span) => span.parentSpanId === "") ?? spans[0];

  return {
    durationMs: calculateDurationMs(rootSpan?.startTimeUnixNano ?? "", rootSpan?.endTimeUnixNano ?? ""),
    rootSpanName: rootSpan?.name ?? "",
    serviceName: getOptionalString(rootSpan?.resource.serviceName),
    spanCount: spans.length,
    spans,
    status: getTraceStatus(spans),
    traceId: spans[0]?.traceId ?? "",
  };
}

function flattenTraceSpans(resourceSpans: ResourceSpans, eventLimit: number): NormalizedTraceSpan[] {
  const resourceAttributes = attributesToRecord(resourceSpans.resource?.attributes);
  const resourceServiceName = getOptionalString(resourceAttributes["service.name"]);

  return resourceSpans.scopeSpans.flatMap((scopeSpans) =>
    scopeSpans.spans.map((span) => ({
      attributes: attributesToRecord(span.attributes),
      durationMs: calculateDurationMs(span.startTimeUnixNano, span.endTimeUnixNano),
      endTimeUnixNano: span.endTimeUnixNano,
      events: span.events.slice(0, eventLimit).map((event) => ({
        attributes: attributesToRecord(event.attributes),
        name: event.name,
        timeUnixNano: event.timeUnixNano,
      })),
      kind: formatSpanKind(span.kind),
      links: span.links.map((link) => ({
        attributes: attributesToRecord(link.attributes),
        spanId: bytesToHex(link.spanId),
        traceId: bytesToHex(link.traceId),
      })),
      name: span.name,
      parentSpanId: bytesToHex(span.parentSpanId),
      resource: {
        attributes: resourceAttributes,
        schemaUrl: resourceSpans.schemaUrl,
        serviceName: resourceServiceName,
      },
      scope: summarizeScope(scopeSpans),
      spanId: bytesToHex(span.spanId),
      startTimeUnixNano: span.startTimeUnixNano,
      status: {
        code: formatStatusCode(span.status?.code ?? 0),
        message: span.status?.message ?? "",
      },
      traceId: bytesToHex(span.traceId),
    })),
  );
}

function summarizeScope(scopeSpans: ScopeSpans): { name: string; schemaUrl: string; version: string } {
  return {
    name: scopeSpans.scope?.name ?? "",
    schemaUrl: scopeSpans.schemaUrl,
    version: scopeSpans.scope?.version ?? "",
  };
}

function matchesTraceFilters(trace: NormalizedTrace, filters: TraceMatchFilters): boolean {
  if (filters.serviceName !== undefined && trace.serviceName?.toLowerCase() !== filters.serviceName.toLowerCase()) {
    return false;
  }
  if (filters.status !== undefined && trace.status !== filters.status.toLowerCase()) {
    return false;
  }
  if (filters.traceIdPrefix !== undefined && !trace.traceId.startsWith(normalizeHexId(filters.traceIdPrefix))) {
    return false;
  }
  if (filters.spanName !== undefined) {
    const search = filters.spanName.toLowerCase();
    if (!trace.spans.some((span) => span.name.toLowerCase().includes(search))) {
      return false;
    }
  }

  return true;
}

function getTraceStatus(spans: NormalizedTraceSpan[]): "error" | "mixed" | "ok" | "unset" {
  const codes = new Set(spans.map((span) => span.status.code));

  if (codes.has("error")) {
    return codes.size === 1 ? "error" : "mixed";
  }
  if (codes.has("ok")) {
    return codes.size === 1 ? "ok" : "mixed";
  }
  return "unset";
}

function calculateDurationMs(startTimeUnixNano: string, endTimeUnixNano: string): number | undefined {
  if (startTimeUnixNano === "" || endTimeUnixNano === "") {
    return undefined;
  }

  try {
    const durationNanoseconds = BigInt(endTimeUnixNano) - BigInt(startTimeUnixNano);
    if (durationNanoseconds < 0n) {
      return undefined;
    }
    return Number(durationNanoseconds) / 1_000_000;
  } catch {
    return undefined;
  }
}

function attributesToRecord(attributes: KeyValue[] | undefined): Record<string, unknown> {
  if (attributes === undefined || attributes.length === 0) {
    return {};
  }

  return Object.fromEntries(attributes.map((attribute) => [attribute.key, anyValueToJson(attribute.value)]));
}

function anyValueToJson(value: AnyValue | undefined): unknown {
  switch (value?.value?.$case) {
    case "stringValue":
      return value.value.stringValue;
    case "boolValue":
      return value.value.boolValue;
    case "intValue":
      return value.value.intValue;
    case "doubleValue":
      return value.value.doubleValue;
    case "bytesValue":
      return bytesToHex(value.value.bytesValue);
    case "arrayValue":
      return value.value.arrayValue.values.map(anyValueToJson);
    case "kvlistValue":
      return Object.fromEntries(value.value.kvlistValue.values.map((entry) => [entry.key, anyValueToJson(entry.value)]));
    case "stringValueStrindex":
      return value.value.stringValueStrindex;
    default:
      return null;
  }
}

function formatAggregationTemporality(value: number): string {
  switch (value) {
    case 1:
      return "delta";
    case 2:
      return "cumulative";
    default:
      return "unspecified";
  }
}

function formatSpanKind(value: number): string {
  switch (value) {
    case 1:
      return "internal";
    case 2:
      return "server";
    case 3:
      return "client";
    case 4:
      return "producer";
    case 5:
      return "consumer";
    default:
      return "unspecified";
  }
}

function formatStatusCode(value: number): string {
  switch (value) {
    case 1:
      return "ok";
    case 2:
      return "error";
    default:
      return "unset";
  }
}

function bytesToHex(value: Uint8Array): string {
  return Buffer.from(value).toString("hex");
}

function getRequestedProtocolVersion(request: express.Request): string {
  const headerValue = request.header("mcp-protocol-version");
  return headerValue !== undefined && supportedProtocolVersions.includes(headerValue as (typeof supportedProtocolVersions)[number])
    ? headerValue
    : defaultProtocolVersion;
}

function resolveProtocolVersion(params: unknown, fallbackVersion: string): string | null {
  if (!isRecord(params)) {
    return fallbackVersion;
  }

  const protocolVersion = typeof params.protocolVersion === "string" ? params.protocolVersion : fallbackVersion;
  return supportedProtocolVersions.includes(protocolVersion as (typeof supportedProtocolVersions)[number]) ? protocolVersion : null;
}

function applyMcpHeaders(response: express.Response, protocolVersion: string): void {
  response.setHeader("MCP-Protocol-Version", protocolVersion);
  response.setHeader("Cache-Control", "no-store");
}

function parseJsonRpcPayload(value: unknown): { message: string; ok: false } | { ok: true; value: unknown } {
  if (typeof value !== "string") {
    return { ok: true, value };
  }

  try {
    return { ok: true, value: JSON.parse(value) };
  } catch {
    return { ok: false, message: "Request body must be valid JSON." };
  }
}

function isJsonRpcRequest(value: unknown): value is JsonRpcRequest {
  return isRecord(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function createResultResponse(id: JsonRpcId, result: unknown): JsonRpcResponse {
  return {
    id,
    jsonrpc: "2.0",
    result,
  };
}

function createErrorResponse(id: JsonRpcId, code: number, message: string, data?: unknown): JsonRpcResponse {
  return {
    id,
    jsonrpc: "2.0",
    error: { code, data, message },
  };
}

function createJsonRpcError(code: number, message: string): Error & { code: number } {
  const error = new Error(message) as Error & { code: number };
  error.code = code;
  return error;
}

function readOptionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : undefined;
}

function readRequiredString(value: unknown, fieldName: string): string {
  const resolved = readOptionalString(value);
  if (resolved === undefined) {
    throw new Error(`${fieldName} must be a non-empty string.`);
  }
  return resolved;
}

function readInteger(value: unknown, defaultValue: number, min: number, max: number): number {
  if (value === undefined) {
    return defaultValue;
  }
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`Expected an integer between ${min} and ${max}.`);
  }
  return Math.min(max, Math.max(min, value));
}

function getOptionalString(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

function normalizeHexId(value: string): string {
  return value.trim().toLowerCase();
}

function isAllowedOrigin(request: express.Request): boolean {
  const origin = request.header("origin");
  if (origin === undefined || origin === "null") {
    return true;
  }

  try {
    const originUrl = new URL(origin);
    const requestHost = request.hostname.toLowerCase();
    const originHost = originUrl.hostname.toLowerCase();
    return originHost === requestHost || originHost === "127.0.0.1" || originHost === "localhost" || originHost === "::1";
  } catch {
    return false;
  }
}
