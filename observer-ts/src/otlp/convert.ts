// Convert OTLP JSON structures to store types.
// Handles both JSON-encoded OTLP and decoded protobuf (same shape after decode).

import type { Span, MetricDataPoint, LogRecord, Resource, Scope, SpanEvent, SpanLink } from "../store/types.ts";

// --- OTLP JSON shapes (subset needed for conversion) ---

type OtlpAnyValue =
  | { stringValue: string }
  | { intValue: string | number }
  | { doubleValue: number }
  | { boolValue: boolean }
  | { arrayValue: { values: OtlpAnyValue[] } }
  | { kvlistValue: { values: OtlpKeyValue[] } }
  | { bytesValue: string };

type OtlpKeyValue = {
  key: string;
  value: OtlpAnyValue;
};

type OtlpResource = {
  attributes?: OtlpKeyValue[];
  droppedAttributesCount?: number;
};

type OtlpScope = {
  name?: string;
  version?: string;
  attributes?: OtlpKeyValue[];
};

// --- Traces ---

type OtlpSpan = {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
  name: string;
  kind?: number | string;
  startTimeUnixNano: string;
  endTimeUnixNano: string;
  attributes?: OtlpKeyValue[];
  events?: OtlpSpanEvent[];
  links?: OtlpSpanLink[];
  status?: { code?: number | string; message?: string };
};

type OtlpSpanEvent = {
  name: string;
  timeUnixNano: string;
  attributes?: OtlpKeyValue[];
};

type OtlpSpanLink = {
  traceId: string;
  spanId: string;
  attributes?: OtlpKeyValue[];
};

type OtlpScopeSpans = {
  scope?: OtlpScope;
  spans?: OtlpSpan[];
  schemaUrl?: string;
};

type OtlpResourceSpans = {
  resource?: OtlpResource;
  scopeSpans?: OtlpScopeSpans[];
  schemaUrl?: string;
};

export type OtlpTracesPayload = {
  resourceSpans?: OtlpResourceSpans[];
};

// --- Metrics ---

type OtlpNumberDataPoint = {
  attributes?: OtlpKeyValue[];
  startTimeUnixNano?: string;
  timeUnixNano: string;
  asInt?: string | number;
  asDouble?: number;
  flags?: number;
};

type OtlpHistogramDataPoint = {
  attributes?: OtlpKeyValue[];
  startTimeUnixNano?: string;
  timeUnixNano: string;
  count?: string | number;
  sum?: number;
  min?: number;
  max?: number;
  bucketCounts?: (string | number)[];
  explicitBounds?: number[];
  flags?: number;
};

type OtlpSummaryDataPoint = {
  attributes?: OtlpKeyValue[];
  startTimeUnixNano?: string;
  timeUnixNano: string;
  count?: string | number;
  sum?: number;
  quantileValues?: { quantile: number; value: number }[];
  flags?: number;
};

type OtlpMetric = {
  name: string;
  description?: string;
  unit?: string;
  gauge?: { dataPoints?: OtlpNumberDataPoint[] };
  sum?: { dataPoints?: OtlpNumberDataPoint[]; isMonotonic?: boolean; aggregationTemporality?: number | string };
  histogram?: { dataPoints?: OtlpHistogramDataPoint[]; aggregationTemporality?: number | string };
  summary?: { dataPoints?: OtlpSummaryDataPoint[] };
  exponentialHistogram?: { dataPoints?: OtlpHistogramDataPoint[]; aggregationTemporality?: number | string };
};

type OtlpScopeMetrics = {
  scope?: OtlpScope;
  metrics?: OtlpMetric[];
  schemaUrl?: string;
};

type OtlpResourceMetrics = {
  resource?: OtlpResource;
  scopeMetrics?: OtlpScopeMetrics[];
  schemaUrl?: string;
};

export type OtlpMetricsPayload = {
  resourceMetrics?: OtlpResourceMetrics[];
};

// --- Logs ---

type OtlpLogRecord = {
  timeUnixNano?: string;
  observedTimeUnixNano?: string;
  severityNumber?: number;
  severityText?: string;
  body?: OtlpAnyValue;
  attributes?: OtlpKeyValue[];
  traceId?: string;
  spanId?: string;
  flags?: number;
};

type OtlpScopeLogs = {
  scope?: OtlpScope;
  logRecords?: OtlpLogRecord[];
  schemaUrl?: string;
};

type OtlpResourceLogs = {
  resource?: OtlpResource;
  scopeLogs?: OtlpScopeLogs[];
  schemaUrl?: string;
};

export type OtlpLogsPayload = {
  resourceLogs?: OtlpResourceLogs[];
};

// ─── Converters ────────────────────────────────────────

export function convertTraces(payload: OtlpTracesPayload): Span[] {
  const spans: Span[] = [];
  for (const rs of payload.resourceSpans ?? []) {
    const resource = convertResource(rs.resource);
    for (const ss of rs.scopeSpans ?? []) {
      const scope = convertScope(ss.scope);
      for (const sp of ss.spans ?? []) {
        const startNano = sp.startTimeUnixNano || "0";
        const endNano = sp.endTimeUnixNano || "0";
        const durationMs = (Number(endNano) - Number(startNano)) / 1_000_000;

        spans.push({
          traceId: decodeHexId(sp.traceId),
          spanId: decodeHexId(sp.spanId),
          parentSpanId: sp.parentSpanId ? decodeHexId(sp.parentSpanId) : undefined,
          name: sp.name,
          kind: spanKindToString(sp.kind),
          startTimeUnixNano: startNano,
          endTimeUnixNano: endNano,
          durationMs,
          status: {
            code: statusCodeToString(sp.status?.code),
            message: sp.status?.message || undefined,
          },
          attributes: convertAttributes(sp.attributes),
          events: (sp.events ?? []).map(convertEvent),
          links: (sp.links ?? []).map(convertLink),
          resource,
          scope,
        });
      }
    }
  }
  return spans;
}

export function convertMetrics(payload: OtlpMetricsPayload): MetricDataPoint[] {
  const points: MetricDataPoint[] = [];
  for (const rm of payload.resourceMetrics ?? []) {
    const resource = convertResource(rm.resource);
    for (const sm of rm.scopeMetrics ?? []) {
      const scope = convertScope(sm.scope);
      for (const m of sm.metrics ?? []) {
        if (m.gauge?.dataPoints) {
          for (const dp of m.gauge.dataPoints) {
            points.push(convertNumberPoint(m, dp, "gauge", resource, scope));
          }
        }
        if (m.sum?.dataPoints) {
          for (const dp of m.sum.dataPoints) {
            const p = convertNumberPoint(m, dp, "sum", resource, scope);
            p.isMonotonic = m.sum!.isMonotonic;
            p.temporality = temporalityToString(m.sum!.aggregationTemporality);
            points.push(p);
          }
        }
        if (m.histogram?.dataPoints) {
          for (const dp of m.histogram.dataPoints) {
            points.push(convertHistogramPoint(m, dp, "histogram", resource, scope, m.histogram!.aggregationTemporality));
          }
        }
        if (m.summary?.dataPoints) {
          for (const dp of m.summary.dataPoints) {
            points.push(convertSummaryPoint(m, dp, resource, scope));
          }
        }
        if (m.exponentialHistogram?.dataPoints) {
          for (const dp of m.exponentialHistogram.dataPoints) {
            points.push(convertHistogramPoint(m, dp, "exponential_histogram", resource, scope, m.exponentialHistogram!.aggregationTemporality));
          }
        }
      }
    }
  }
  return points;
}

export function convertLogs(payload: OtlpLogsPayload): LogRecord[] {
  const logs: LogRecord[] = [];
  for (const rl of payload.resourceLogs ?? []) {
    const resource = convertResource(rl.resource);
    for (const sl of rl.scopeLogs ?? []) {
      const scope = convertScope(sl.scope);
      for (const lr of sl.logRecords ?? []) {
        logs.push({
          timeUnixNano: lr.timeUnixNano || lr.observedTimeUnixNano || "0",
          severityNumber: lr.severityNumber,
          severityText: lr.severityText || undefined,
          body: anyValueToString(lr.body),
          attributes: convertAttributes(lr.attributes),
          traceId: lr.traceId ? decodeHexId(lr.traceId) : undefined,
          spanId: lr.spanId ? decodeHexId(lr.spanId) : undefined,
          resource,
          scope,
        });
      }
    }
  }
  return logs;
}

// ─── Helpers ───────────────────────────────────────────

function convertResource(r?: OtlpResource): Resource {
  const attrs = convertAttributes(r?.attributes);
  const serviceName = attrs["service.name"] as string | undefined;
  return {
    serviceName: serviceName || undefined,
    attributes: attrs,
  };
}

function convertScope(s?: OtlpScope): Scope {
  return {
    name: s?.name ?? "",
    version: s?.version || undefined,
  };
}

function convertAttributes(kvs?: OtlpKeyValue[]): Record<string, unknown> {
  if (!kvs) return {};
  const attrs: Record<string, unknown> = {};
  for (const kv of kvs) {
    attrs[kv.key] = anyValueToJs(kv.value);
  }
  return attrs;
}

function anyValueToJs(v: OtlpAnyValue | undefined): unknown {
  if (!v) return undefined;
  if ("stringValue" in v) return v.stringValue;
  if ("intValue" in v) return typeof v.intValue === "string" ? parseInt(v.intValue, 10) : v.intValue;
  if ("doubleValue" in v) return v.doubleValue;
  if ("boolValue" in v) return v.boolValue;
  if ("arrayValue" in v) return (v.arrayValue.values ?? []).map(anyValueToJs);
  if ("kvlistValue" in v) {
    const obj: Record<string, unknown> = {};
    for (const kv of v.kvlistValue.values ?? []) {
      obj[kv.key] = anyValueToJs(kv.value);
    }
    return obj;
  }
  if ("bytesValue" in v) return v.bytesValue;
  return undefined;
}

function anyValueToString(v?: OtlpAnyValue): string {
  if (!v) return "";
  const js = anyValueToJs(v);
  return typeof js === "string" ? js : JSON.stringify(js);
}

function convertEvent(e: OtlpSpanEvent): SpanEvent {
  return {
    name: e.name,
    timeUnixNano: e.timeUnixNano || "0",
    attributes: convertAttributes(e.attributes),
  };
}

function convertLink(l: OtlpSpanLink): SpanLink {
  return {
    traceId: decodeHexId(l.traceId),
    spanId: decodeHexId(l.spanId),
    attributes: convertAttributes(l.attributes),
  };
}

function convertNumberPoint(
  m: OtlpMetric,
  dp: OtlpNumberDataPoint,
  type: string,
  resource: Resource,
  scope: Scope,
): MetricDataPoint {
  return {
    name: m.name,
    description: m.description || undefined,
    unit: m.unit || undefined,
    type,
    timeUnixNano: dp.timeUnixNano,
    startTimeUnixNano: dp.startTimeUnixNano || undefined,
    attributes: convertAttributes(dp.attributes),
    resource,
    scope,
    flags: dp.flags,
    value: dp.asDouble ?? (dp.asInt != null ? Number(dp.asInt) : undefined),
  };
}

function convertHistogramPoint(
  m: OtlpMetric,
  dp: OtlpHistogramDataPoint,
  type: string,
  resource: Resource,
  scope: Scope,
  temporality?: number | string,
): MetricDataPoint {
  return {
    name: m.name,
    description: m.description || undefined,
    unit: m.unit || undefined,
    type,
    timeUnixNano: dp.timeUnixNano,
    startTimeUnixNano: dp.startTimeUnixNano || undefined,
    attributes: convertAttributes(dp.attributes),
    resource,
    scope,
    flags: dp.flags,
    count: dp.count != null ? Number(dp.count) : undefined,
    sum: dp.sum,
    min: dp.min,
    max: dp.max,
    bucketCounts: dp.bucketCounts?.map(Number),
    explicitBounds: dp.explicitBounds,
    temporality: temporalityToString(temporality),
  };
}

function convertSummaryPoint(
  m: OtlpMetric,
  dp: OtlpSummaryDataPoint,
  resource: Resource,
  scope: Scope,
): MetricDataPoint {
  return {
    name: m.name,
    description: m.description || undefined,
    unit: m.unit || undefined,
    type: "summary",
    timeUnixNano: dp.timeUnixNano,
    startTimeUnixNano: dp.startTimeUnixNano || undefined,
    attributes: convertAttributes(dp.attributes),
    resource,
    scope,
    flags: dp.flags,
    count: dp.count != null ? Number(dp.count) : undefined,
    sum: dp.sum,
    quantiles: dp.quantileValues,
  };
}

// ─── Enum conversions ──────────────────────────────────

const SPAN_KIND_MAP: Record<number, string> = {
  0: "UNSPECIFIED",
  1: "INTERNAL",
  2: "SERVER",
  3: "CLIENT",
  4: "PRODUCER",
  5: "CONSUMER",
};

function spanKindToString(kind?: number | string): string {
  if (typeof kind === "string") {
    // Already a string (e.g. "SPAN_KIND_SERVER" or "SERVER").
    return kind.replace("SPAN_KIND_", "");
  }
  return SPAN_KIND_MAP[kind ?? 0] ?? "UNSPECIFIED";
}

function statusCodeToString(code?: number | string): string {
  if (typeof code === "string") {
    return code.replace("STATUS_CODE_", "");
  }
  switch (code) {
    case 0: return "UNSET";
    case 1: return "OK";
    case 2: return "ERROR";
    default: return "UNSET";
  }
}

function temporalityToString(t?: number | string): string | undefined {
  if (typeof t === "string") return t;
  switch (t) {
    case 1: return "delta";
    case 2: return "cumulative";
    default: return undefined;
  }
}

/** Decode hex or base64 IDs to lowercase hex. */
function decodeHexId(id: string): string {
  if (!id) return "";
  // OTLP JSON uses base64 for IDs; OTLP HTTP JSON uses hex.
  // If it looks like hex already (16 or 32 hex chars), return lowercase.
  if (/^[0-9a-fA-F]+$/.test(id)) return id.toLowerCase();
  // Try base64 decode only if it looks like valid base64 (correct length, charset).
  if (/^[A-Za-z0-9+/]+=*$/.test(id) && id.length >= 12) {
    try {
      const bytes = Buffer.from(id, "base64");
      if (bytes.length === 8 || bytes.length === 16) {
        return bytes.toString("hex");
      }
    } catch {
      // Fall through.
    }
  }
  // Return as-is for non-standard IDs.
  return id;
}
