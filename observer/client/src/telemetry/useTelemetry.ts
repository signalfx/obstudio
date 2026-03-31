import { useEffect, useRef, useState } from "react";
import type { LogsRequest, MetricsRequest, TelemetryAttribute, TracesRequest } from "./types";

export type TelemetryState = {
  error: string | null;
  logs: LogsRequest;
  metrics: MetricsRequest;
  traces: TracesRequest;
};

const emptyTelemetryState: TelemetryState = {
  error: null,
  logs: { resourceLogs: [] },
  metrics: { resourceMetrics: [] },
  traces: { resourceSpans: [] },
};

type SSEEvent = {
  signals: Array<"logs" | "metrics" | "traces">;
};

export function useTelemetry(): TelemetryState {
  const [telemetry, setTelemetry] = useState<TelemetryState>(emptyTelemetryState);
  const fetchingRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    let isActive = true;
    let reconnectTimer: number | null = null;
    let eventSource: EventSource | null = null;

    async function fetchSignal(signal: "logs" | "metrics" | "traces"): Promise<void> {
      if (fetchingRef.current.has(signal)) return;
      fetchingRef.current.add(signal);

      try {
        const response = await fetch(`/api/telemetry/${signal}`);
        if (!response.ok || !isActive) return;
        const data = await response.json();

        setTelemetry((current) => {
          switch (signal) {
            case "traces":
              return { ...current, error: null, traces: buildTracesRequest(data.spans ?? []) };
            case "metrics":
              return { ...current, error: null, metrics: buildMetricsRequest(data.metricDataPoints ?? []) };
            case "logs":
              return { ...current, error: null, logs: buildLogsRequest(data.logRecords ?? []) };
          }
        });
      } catch {
        if (isActive) {
          setTelemetry((current) => ({ ...current, error: "Failed to fetch telemetry data." }));
        }
      } finally {
        fetchingRef.current.delete(signal);
      }
    }

    function connect(): void {
      eventSource = new EventSource("/api/events");

      eventSource.addEventListener("telemetry-changed", (event) => {
        if (!isActive) return;
        try {
          const payload = JSON.parse(event.data) as SSEEvent;
          for (const signal of payload.signals) {
            void fetchSignal(signal);
          }
        } catch {
          // ignore malformed SSE events
        }
      });

      eventSource.addEventListener("error", () => {
        eventSource?.close();
        if (isActive) {
          reconnectTimer = window.setTimeout(connect, 2000);
        }
      });

      eventSource.addEventListener("open", () => {
        void fetchSignal("traces");
        void fetchSignal("metrics");
        void fetchSignal("logs");
      });
    }

    connect();

    return () => {
      isActive = false;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      eventSource?.close();
    };
  }, []);

  return telemetry;
}

type SpanRow = Record<string, unknown>;
type MetricRow = Record<string, unknown>;
type LogRow = Record<string, unknown>;

function buildTracesRequest(rows: SpanRow[]): TracesRequest {
  const traceMap = new Map<string, SpanRow[]>();

  for (const row of rows) {
    const traceId = String(row.trace_id ?? "");
    const existing = traceMap.get(traceId);
    if (existing) {
      existing.push(row);
    } else {
      traceMap.set(traceId, [row]);
    }
  }

  const resourceSpans = [...traceMap.values()].map((spans) => {
    const first = spans[0];
    const resource = safeParseJson(first?.resource_json) as Record<string, unknown>;

    return {
      resource: {
        attributes: recordToAttributes(resource),
      },
      scopeSpans: [{
        spans: spans.map((row) => ({
          attributes: recordToAttributes(safeParseJson(row.attributes_json) as Record<string, unknown>),
          endTimeUnixNano: String(row.end_time_unix_nano ?? ""),
          name: String(row.name ?? ""),
          parentSpanId: String(row.parent_span_id ?? ""),
          spanId: String(row.span_id ?? ""),
          startTimeUnixNano: String(row.start_time_unix_nano ?? ""),
          status: {
            code: Number(row.status_code ?? 0),
            message: String(row.status_message ?? ""),
          },
          traceId: String(row.trace_id ?? ""),
        })),
      }],
    };
  });

  return { resourceSpans };
}

function buildMetricsRequest(rows: MetricRow[]): MetricsRequest {
  type GroupKey = string;
  type MetricGroup = {
    resource: Record<string, unknown>;
    resourceSchemaUrl: string;
    scope: Record<string, string>;
    scopeSchemaUrl: string;
    metricsByName: Map<string, {
      name: string;
      description: string;
      unit: string;
      type: string;
      isMonotonic: boolean;
      aggregationTemporality: string;
      dataPoints: Array<{ attributes: Record<string, unknown>; dataPoint: Record<string, unknown> }>;
    }>;
  };

  const groups = new Map<GroupKey, MetricGroup>();

  for (const row of rows) {
    const resourceJson = String(row.resource_json ?? "{}");
    const scopeJson = String(row.scope_json ?? "{}");
    const key = `${resourceJson}|${scopeJson}`;

    let group = groups.get(key);
    if (!group) {
      group = {
        resource: safeParseJson(resourceJson) as Record<string, unknown>,
        resourceSchemaUrl: String(row.resource_schema_url ?? ""),
        scope: safeParseJson(scopeJson) as Record<string, string>,
        scopeSchemaUrl: String(row.scope_schema_url ?? ""),
        metricsByName: new Map(),
      };
      groups.set(key, group);
    }

    const metricName = String(row.metric_name ?? "");
    let metric = group.metricsByName.get(metricName);
    if (!metric) {
      metric = {
        name: metricName,
        description: String(row.metric_description ?? ""),
        unit: String(row.metric_unit ?? ""),
        type: String(row.metric_type ?? "unknown"),
        isMonotonic: row.is_monotonic === true,
        aggregationTemporality: String(row.aggregation_temporality ?? "unspecified"),
        dataPoints: [],
      };
      group.metricsByName.set(metricName, metric);
    }

    metric.dataPoints.push({
      attributes: safeParseJson(row.attributes_json) as Record<string, unknown>,
      dataPoint: safeParseJson(row.data_point_json) as Record<string, unknown>,
    });
  }

  const resourceMetrics = [...groups.values()].map((group) => ({
    schemaUrl: group.resourceSchemaUrl,
    resource: {
      attributes: recordToAttributes(group.resource),
    },
    scopeMetrics: [{
      schemaUrl: group.scopeSchemaUrl,
      scope: {
        name: group.scope.name ?? "",
        version: group.scope.version ?? "",
      },
      metrics: [...group.metricsByName.values()].map((m) => buildMetric(m)),
    }],
  }));

  return { resourceMetrics };
}

function buildMetric(m: {
  name: string;
  description: string;
  unit: string;
  type: string;
  isMonotonic: boolean;
  aggregationTemporality: string;
  dataPoints: Array<{ attributes: Record<string, unknown>; dataPoint: Record<string, unknown> }>;
}) {
  const temporality = m.aggregationTemporality === "delta" ? 1 : m.aggregationTemporality === "cumulative" ? 2 : 0;

  const buildNumberDP = (dp: { attributes: Record<string, unknown>; dataPoint: Record<string, unknown> }) => {
    const raw = dp.dataPoint;
    const value = raw.value;
    let typedValue: { $case: "asDouble"; asDouble: number } | { $case: "asInt"; asInt: string } | undefined;

    if (typeof value === "number") {
      typedValue = { $case: "asDouble" as const, asDouble: value };
    } else if (raw.asDouble !== undefined) {
      typedValue = { $case: "asDouble" as const, asDouble: Number(raw.asDouble) };
    } else if (raw.asInt !== undefined) {
      typedValue = { $case: "asInt" as const, asInt: String(raw.asInt) };
    }

    return { attributes: recordToAttributes(dp.attributes), value: typedValue };
  };

  const buildHistDP = (dp: { attributes: Record<string, unknown>; dataPoint: Record<string, unknown> }) => ({
    attributes: recordToAttributes(dp.attributes),
    count: String(dp.dataPoint.count ?? "0"),
    sum: typeof dp.dataPoint.sum === "number" ? dp.dataPoint.sum : undefined,
  });

  switch (m.type) {
    case "gauge":
      return {
        name: m.name, description: m.description, unit: m.unit, metadata: [],
        data: { $case: "gauge" as const, gauge: { dataPoints: m.dataPoints.map(buildNumberDP) } },
      };
    case "counter":
      return {
        name: m.name, description: m.description, unit: m.unit, metadata: [],
        data: {
          $case: "sum" as const,
          sum: { dataPoints: m.dataPoints.map(buildNumberDP), isMonotonic: m.isMonotonic, aggregationTemporality: temporality },
        },
      };
    case "histogram":
      return {
        name: m.name, description: m.description, unit: m.unit, metadata: [],
        data: {
          $case: "histogram" as const,
          histogram: { dataPoints: m.dataPoints.map(buildHistDP), aggregationTemporality: temporality },
        },
      };
    case "exponential_histogram":
      return {
        name: m.name, description: m.description, unit: m.unit, metadata: [],
        data: {
          $case: "exponentialHistogram" as const,
          exponentialHistogram: { dataPoints: m.dataPoints.map(buildHistDP), aggregationTemporality: temporality },
        },
      };
    case "summary":
      return {
        name: m.name, description: m.description, unit: m.unit, metadata: [],
        data: {
          $case: "summary" as const,
          summary: { dataPoints: m.dataPoints.map((dp) => ({ attributes: recordToAttributes(dp.attributes), count: String(dp.dataPoint.count ?? "0"), sum: Number(dp.dataPoint.sum ?? 0) })) },
        },
      };
    default:
      return {
        name: m.name, description: m.description, unit: m.unit, metadata: [],
        data: { $case: "gauge" as const, gauge: { dataPoints: m.dataPoints.map(buildNumberDP) } },
      };
  }
}

function buildLogsRequest(rows: LogRow[]): LogsRequest {
  const grouped = new Map<string, LogRow[]>();

  for (const row of rows) {
    const key = String(row.resource_json ?? "{}");
    const existing = grouped.get(key);
    if (existing) {
      existing.push(row);
    } else {
      grouped.set(key, [row]);
    }
  }

  const resourceLogs = [...grouped.values()].map((logRows) => {
    const first = logRows[0];
    const resource = safeParseJson(first?.resource_json) as Record<string, unknown>;

    return {
      resource: {
        attributes: recordToAttributes(resource),
      },
      scopeLogs: [{
        logRecords: logRows.map((row) => {
          const bodyJson = safeParseJson(row.body_json);
          const bodyValue = typeof bodyJson === "string"
            ? { value: { $case: "stringValue" as const, stringValue: bodyJson } }
            : undefined;

          return {
            body: bodyValue,
            observedTimeUnixNano: String(row.observed_time_unix_nano ?? ""),
            severityText: String(row.severity_text ?? ""),
            timeUnixNano: String(row.time_unix_nano ?? ""),
          };
        }),
      }],
    };
  });

  return { resourceLogs };
}

function recordToAttributes(record: Record<string, unknown>): TelemetryAttribute[] {
  return Object.entries(record).map(([key, value]) => toAttribute(key, value));
}

function toAttribute(key: string, value: unknown): TelemetryAttribute {
  if (typeof value === "string") {
    return { key, value: { value: { $case: "stringValue", stringValue: value } } };
  }
  if (typeof value === "boolean") {
    return { key, value: { value: { $case: "boolValue", boolValue: value } } };
  }
  if (typeof value === "number") {
    if (Number.isInteger(value)) {
      return { key, value: { value: { $case: "intValue", intValue: String(value) } } };
    }
    return { key, value: { value: { $case: "doubleValue", doubleValue: value } } };
  }
  return { key, value: { value: { $case: "stringValue", stringValue: String(value ?? "") } } };
}

function safeParseJson(value: unknown): unknown {
  if (typeof value !== "string") return value ?? {};
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}
