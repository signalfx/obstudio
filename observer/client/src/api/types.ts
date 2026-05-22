// Types matching Go JSON responses from observer/internal/store

/** OpenTelemetry resource describing the entity producing telemetry. */
export interface Resource {
  serviceName?: string;
  attributes: Record<string, unknown>;
  schemaUrl?: string;
}

/** Instrumentation scope that produced a signal. */
export interface Scope {
  name: string;
  version?: string;
  schemaUrl?: string;
}

/** Status of a span (ok, error, or unset). */
export interface SpanStatus {
  code: string;
  message?: string;
}

/** A timestamped event recorded on a span. */
export interface SpanEvent {
  name: string;
  timeUnixNano: string;
  attributes: Record<string, unknown>;
}

/** A link from one span to another, possibly in a different trace. */
export interface SpanLink {
  traceId: string;
  spanId: string;
  attributes: Record<string, unknown>;
}

/** A single span representing a unit of work in a trace. */
export interface Span {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
  name: string;
  kind: string;
  startTimeUnixNano: string;
  endTimeUnixNano: string;
  durationMs: number;
  status: SpanStatus;
  attributes: Record<string, unknown>;
  events: SpanEvent[];
  links: SpanLink[];
  resource: Resource;
  scope: Scope;
}

/** A single quantile measurement within a summary metric. */
export interface QuantileValue {
  quantile: number;
  value: number;
}

/** A single metric data point with its resource and scope context. */
export interface MetricDataPoint {
  name: string;
  description?: string;
  unit?: string;
  type: string;
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
}

/** A log record with resource/scope context and optional trace correlation. */
export interface LogRecord {
  id: string;
  timeUnixNano: string;
  severityNumber?: number;
  severityText?: string;
  body: string;
  attributes: Record<string, unknown>;
  traceId?: string;
  spanId?: string;
  resource: Resource;
  scope: Scope;
}

/** Compact preview of a single span within a trace summary. */
export interface SpanPreview {
  spanId: string;
  name: string;
  kind: string;
  durationMs: number;
  statusCode: string;
  serviceName?: string;
}

/** Summary of a trace with optional span previews. */
export interface TraceSummary {
  traceId: string;
  rootSpanName: string;
  serviceName?: string;
  spanCount: number;
  durationMs?: number;
  status: string;
  spans?: SpanPreview[];
}

/** Full trace detail including all spans. */
export interface TraceDetail {
  traceId: string;
  rootSpanName: string;
  serviceName?: string;
  spanCount: number;
  durationMs?: number;
  status: string;
  spans: Span[];
}

/** A metric grouped by name, service, and scope with bounded data points. */
export interface MetricGroup {
  name: string;
  description?: string;
  unit?: string;
  type: string;
  serviceName?: string;
  scopeName?: string;
  seriesCount?: number;
  dataPointCount: number;
  dataPoints?: MetricDataPoint[];
}

/** Aggregate statistics for the telemetry store. */
export interface Stats {
  spanCount: number;
  dataPointCount: number;
  metricNameCount: number;
  logCount: number;
  traceCount: number;
  serviceNames: string[];
}

export type ValidationSeverity = "information" | "improvement" | "violation";

export interface ValidationSignalRef {
  type: string;
  serviceName?: string;
  traceId?: string;
  spanId?: string;
  spanName?: string;
  metricName?: string;
  scopeName?: string;
  logBody?: string;
}

export interface ValidationFinding {
  entityKey: string;
  source: string;
  ruleId: string;
  severity: ValidationSeverity;
  message: string;
  context?: Record<string, unknown>;
  signal: ValidationSignalRef;
  updatedAt: string;
}

export interface ValidationIssue {
  key: string;
  severity: ValidationSeverity;
  message: string;
  signalType: string;
  targetLabel: string;
  serviceName: string;
  scopeName: string;
  count: number;
  violationCount: number;
  improvementCount: number;
  informationCount: number;
  affectedEntityCount: number;
  firstSeen: string;
  lastSeen: string;
  findings: ValidationFinding[];
}

export interface ValidationSummary {
  enabled: boolean;
  ready: boolean;
  status: "disabled" | "idle" | "running" | "ready" | "error";
  message?: string;
  lastError?: string;
  hasResult: boolean;
  stale: boolean;
  needsRun: boolean;
  activeRunId?: string;
  resultRunId?: string;
  lastRunStartedAt?: string;
  lastRunCompletedAt?: string;
  lastTelemetryAt?: string;
  totalEntities: number;
  totalAdvisories: number;
  noAdviceCount: number;
  severityCounts: Record<string, number>;
  highestSeverityCounts: Record<string, number>;
  signalCounts: Record<string, number>;
  updatedAt: string;
}

export interface ValidationSnapshot {
  summary: ValidationSummary;
  findings: ValidationFinding[];
  issues: ValidationIssue[];
}
