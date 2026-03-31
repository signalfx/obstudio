import type { ExportLogsServiceRequest } from "../../shared/otlp/collector/logs/v1/logs_service.d.mts";
import type { ExportMetricsServiceRequest } from "../../shared/otlp/collector/metrics/v1/metrics_service.d.mts";
import type { ExportTraceServiceRequest } from "../../shared/otlp/collector/trace/v1/trace_service.d.mts";
import type { AnyValue, KeyValue } from "../../shared/otlp/common/v1/common.d.mts";
import type { Metric } from "../../shared/otlp/metrics/v1/metrics.d.mts";
import {
  insertLogRecords,
  insertMetricDataPoints,
  insertSpans,
  type LogRecordRow,
  type MetricDataPointRow,
  type SpanRow,
} from "./duckdb-store.js";

const defaultConnectionId = "default";

export async function persistTraces(
  request: ExportTraceServiceRequest,
  connectionId?: string,
): Promise<void> {
  const connId = connectionId ?? defaultConnectionId;
  const rows: SpanRow[] = [];

  for (const rs of request.resourceSpans) {
    const resourceJson = JSON.stringify(attributesToRecord(rs.resource?.attributes));

    for (const ss of rs.scopeSpans) {
      const scopeJson = JSON.stringify({
        name: ss.scope?.name ?? "",
        version: ss.scope?.version ?? "",
      });

      for (const span of ss.spans) {
        rows.push({
          trace_id: bytesToHex(span.traceId),
          span_id: bytesToHex(span.spanId),
          parent_span_id: bytesToHex(span.parentSpanId),
          name: span.name,
          kind: span.kind,
          start_time_unix_nano: span.startTimeUnixNano,
          end_time_unix_nano: span.endTimeUnixNano,
          status_code: span.status?.code ?? 0,
          status_message: span.status?.message ?? "",
          attributes_json: JSON.stringify(attributesToRecord(span.attributes)),
          events_json: JSON.stringify(
            span.events.map((e) => ({
              name: e.name,
              timeUnixNano: e.timeUnixNano,
              attributes: attributesToRecord(e.attributes),
            })),
          ),
          links_json: JSON.stringify(
            span.links.map((l) => ({
              traceId: bytesToHex(l.traceId),
              spanId: bytesToHex(l.spanId),
              attributes: attributesToRecord(l.attributes),
            })),
          ),
          resource_json: resourceJson,
          resource_schema_url: rs.schemaUrl,
          scope_json: scopeJson,
          scope_schema_url: ss.schemaUrl,
          connection_id: connId,
        });
      }
    }
  }

  await insertSpans(rows);
}

export async function persistMetrics(
  request: ExportMetricsServiceRequest,
  connectionId?: string,
): Promise<void> {
  const connId = connectionId ?? defaultConnectionId;
  const rows: MetricDataPointRow[] = [];

  for (const rm of request.resourceMetrics) {
    const resourceJson = JSON.stringify(attributesToRecord(rm.resource?.attributes));

    for (const sm of rm.scopeMetrics) {
      const scopeJson = JSON.stringify({
        name: sm.scope?.name ?? "",
        version: sm.scope?.version ?? "",
      });

      for (const metric of sm.metrics) {
        const metricType = getMetricType(metric);
        const { isMonotonic, aggregationTemporality } = getMetricMetadata(metric);
        const dataPoints = getMetricDataPoints(metric);

        for (const dp of dataPoints) {
          rows.push({
            metric_name: metric.name,
            metric_type: metricType,
            metric_description: metric.description,
            metric_unit: metric.unit,
            is_monotonic: isMonotonic,
            aggregation_temporality: aggregationTemporality,
            attributes_json: JSON.stringify(attributesToRecord(dp.attributes)),
            data_point_json: JSON.stringify(dp),
            start_time_unix_nano: dp.startTimeUnixNano ?? "",
            time_unix_nano: dp.timeUnixNano ?? "",
            resource_json: resourceJson,
            resource_schema_url: rm.schemaUrl,
            scope_json: scopeJson,
            scope_schema_url: sm.schemaUrl,
            connection_id: connId,
          });
        }
      }
    }
  }

  await insertMetricDataPoints(rows);
}

export async function persistLogs(
  request: ExportLogsServiceRequest,
  connectionId?: string,
): Promise<void> {
  const connId = connectionId ?? defaultConnectionId;
  const rows: LogRecordRow[] = [];

  for (const rl of request.resourceLogs) {
    const resourceJson = JSON.stringify(attributesToRecord(rl.resource?.attributes));

    for (const sl of rl.scopeLogs) {
      const scopeJson = JSON.stringify({
        name: sl.scope?.name ?? "",
        version: sl.scope?.version ?? "",
      });

      for (const lr of sl.logRecords) {
        rows.push({
          time_unix_nano: lr.timeUnixNano,
          observed_time_unix_nano: lr.observedTimeUnixNano,
          severity_number: lr.severityNumber,
          severity_text: lr.severityText,
          body_json: JSON.stringify(anyValueToJson(lr.body)),
          attributes_json: JSON.stringify(attributesToRecord(lr.attributes)),
          trace_id: bytesToHex(lr.traceId),
          span_id: bytesToHex(lr.spanId),
          resource_json: resourceJson,
          resource_schema_url: rl.schemaUrl,
          scope_json: scopeJson,
          scope_schema_url: sl.schemaUrl,
          connection_id: connId,
        });
      }
    }
  }

  await insertLogRecords(rows);
}

function bytesToHex(value: Uint8Array): string {
  return Buffer.from(value).toString("hex");
}

function attributesToRecord(attributes: KeyValue[] | undefined): Record<string, unknown> {
  if (!attributes || attributes.length === 0) return {};
  return Object.fromEntries(attributes.map((a) => [a.key, anyValueToJson(a.value)]));
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
      return Object.fromEntries(
        value.value.kvlistValue.values.map((e) => [e.key, anyValueToJson(e.value)]),
      );
    default:
      return null;
  }
}

type DataPointLike = {
  attributes: KeyValue[];
  startTimeUnixNano?: string;
  timeUnixNano?: string;
  [key: string]: unknown;
};

function getMetricDataPoints(metric: Metric): DataPointLike[] {
  switch (metric.data?.$case) {
    case "gauge":
      return metric.data.gauge.dataPoints as unknown as DataPointLike[];
    case "sum":
      return metric.data.sum.dataPoints as unknown as DataPointLike[];
    case "histogram":
      return metric.data.histogram.dataPoints as unknown as DataPointLike[];
    case "exponentialHistogram":
      return metric.data.exponentialHistogram.dataPoints as unknown as DataPointLike[];
    case "summary":
      return metric.data.summary.dataPoints as unknown as DataPointLike[];
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

function getMetricMetadata(metric: Metric): {
  aggregationTemporality: string;
  isMonotonic: boolean;
} {
  switch (metric.data?.$case) {
    case "sum":
      return {
        isMonotonic: metric.data.sum.isMonotonic,
        aggregationTemporality: formatTemporality(metric.data.sum.aggregationTemporality),
      };
    case "histogram":
      return {
        isMonotonic: false,
        aggregationTemporality: formatTemporality(metric.data.histogram.aggregationTemporality),
      };
    case "exponentialHistogram":
      return {
        isMonotonic: false,
        aggregationTemporality: formatTemporality(metric.data.exponentialHistogram.aggregationTemporality),
      };
    default:
      return { isMonotonic: false, aggregationTemporality: "unspecified" };
  }
}

function formatTemporality(value: number): string {
  switch (value) {
    case 1:
      return "delta";
    case 2:
      return "cumulative";
    default:
      return "unspecified";
  }
}
