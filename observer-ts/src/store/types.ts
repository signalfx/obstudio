// All data types — must produce identical JSON to observer-go/internal/store.

export type Signal = "traces" | "metrics" | "logs";

export type Resource = {
  serviceName?: string;
  attributes: Record<string, unknown>;
  schemaUrl?: string;
};

export type Scope = {
  name: string;
  version?: string;
  schemaUrl?: string;
};

export type SpanStatus = {
  code: string; // "OK" | "ERROR" | "UNSET"
  message?: string;
};

export type SpanEvent = {
  name: string;
  timeUnixNano: string;
  attributes: Record<string, unknown>;
};

export type SpanLink = {
  traceId: string;
  spanId: string;
  attributes: Record<string, unknown>;
};

export type Span = {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
  name: string;
  kind: string; // "INTERNAL" | "SERVER" | "CLIENT" | "PRODUCER" | "CONSUMER" | "UNSPECIFIED"
  startTimeUnixNano: string;
  endTimeUnixNano: string;
  durationMs: number;
  status: SpanStatus;
  attributes: Record<string, unknown>;
  events: SpanEvent[];
  links: SpanLink[];
  resource: Resource;
  scope: Scope;
};

export type QuantileValue = {
  quantile: number;
  value: number;
};

export type MetricDataPoint = {
  name: string;
  description?: string;
  unit?: string;
  type: string; // "gauge" | "sum" | "histogram" | "summary" | "exponential_histogram"
  timeUnixNano: string;
  startTimeUnixNano?: string;
  attributes: Record<string, unknown>;
  resource: Resource;
  scope: Scope;
  flags?: number;
  value?: number;
  isMonotonic?: boolean;
  temporality?: string;
  count?: number;
  sum?: number;
  min?: number;
  max?: number;
  bucketCounts?: number[];
  explicitBounds?: number[];
  quantiles?: QuantileValue[];
};

export type LogRecord = {
  timeUnixNano: string;
  severityNumber?: number;
  severityText?: string;
  body: string;
  attributes: Record<string, unknown>;
  traceId?: string;
  spanId?: string;
  resource: Resource;
  scope: Scope;
};

// --- Query filter types ---

export type TraceFilter = {
  serviceName?: string;
  spanName?: string;
  status?: string;
  traceIdPrefix?: string;
  limit?: number;
  spanPreviewCount?: number;
};

export type MetricFilter = {
  metricName?: string;
  serviceName?: string;
  scopeName?: string;
  type?: string;
  resourceAttribute?: string;
  limit?: number;
  dataPointLimit?: number;
};

export type LogFilter = {
  serviceName?: string;
  severityText?: string;
  body?: string;
  traceId?: string;
  limit?: number;
};

// --- Query result types ---

export type SpanPreview = {
  spanId: string;
  name: string;
  kind: string;
  durationMs: number;
  statusCode: string;
};

export type TraceSummary = {
  traceId: string;
  rootSpanName: string;
  serviceName?: string;
  spanCount: number;
  durationMs?: number;
  status: string;
  spans?: SpanPreview[];
};

export type TraceDetail = {
  traceId: string;
  rootSpanName: string;
  serviceName?: string;
  spanCount: number;
  durationMs?: number;
  status: string;
  spans: Span[];
};

export type MetricGroup = {
  name: string;
  description?: string;
  unit?: string;
  type: string;
  serviceName?: string;
  scopeName?: string;
  dataPointCount: number;
  dataPoints?: MetricDataPoint[];
};

export type Stats = {
  spanCount: number;
  metricCount: number;
  metricNameCount: number;
  logCount: number;
  traceCount: number;
  serviceNames: string[];
};

export type ServiceNode = {
  id: string;
  label: string;
  spanCount: number;
  errorCount: number;
};

export type ServiceEdge = {
  source: string;
  target: string;
  callCount: number;
  errorCount: number;
};

export type ServiceMap = {
  nodes: ServiceNode[];
  edges: ServiceEdge[];
};
