import type { ExportLogsServiceRequest } from "../../shared/otlp/opentelemetry/proto/collector/logs/v1/logs_service.d.mts";
import type { ExportMetricsServiceRequest } from "../../shared/otlp/opentelemetry/proto/collector/metrics/v1/metrics_service.d.mts";
import type { ExportTraceServiceRequest } from "../../shared/otlp/opentelemetry/proto/collector/trace/v1/trace_service.d.mts";
import type {
  ExponentialHistogram,
  ExponentialHistogramDataPoint,
  Gauge,
  Histogram,
  HistogramDataPoint,
  Metric,
  NumberDataPoint,
  ResourceMetrics,
  ScopeMetrics,
  Sum,
  Summary,
  SummaryDataPoint,
} from "../../shared/otlp/opentelemetry/proto/metrics/v1/metrics.d.mts";
import type { ResourceLogs } from "../../shared/otlp/opentelemetry/proto/logs/v1/logs.d.mts";
import type { ResourceSpans } from "../../shared/otlp/opentelemetry/proto/trace/v1/trace.d.mts";

type MetricDataPoint = NumberDataPoint | HistogramDataPoint | ExponentialHistogramDataPoint | SummaryDataPoint;
type TelemetrySignal = "logs" | "metrics" | "traces";

/**
 * Snapshot of OTLP signal data held in memory.
 *
 * `received` keeps the most recent payload for each signal exactly as it arrived.
 * `merged` keeps the long-lived aggregate view. Metrics are incrementally merged;
 * logs and traces are currently full-overwrite placeholders until their merge
 * semantics are defined.
 */
export type OtlpStoreState = {
  received: {
    resourceLogs: ResourceLogs[];
    resourceMetrics: ResourceMetrics[];
    resourceSpans: ResourceSpans[];
  };
  merged: {
    resourceLogs: ResourceLogs[];
    resourceMetrics: ResourceMetrics[];
    resourceSpans: ResourceSpans[];
  };
};

export type OtlpStoreUpdate =
  | { request: ExportLogsServiceRequest; signal: "logs" }
  | { request: ExportMetricsServiceRequest; signal: "metrics" }
  | { request: ExportTraceServiceRequest; signal: "traces" };

type OtlpStoreListener = (update: OtlpStoreUpdate) => void;

/**
 * In-memory OTLP signal store used by the HTTP receiver.
 *
 * The store intentionally keeps raw last-seen payloads separate from the merged
 * view so callers can inspect both the latest export and the accumulated state.
 */
export class OtlpInMemoryStore {
  private listeners = new Set<OtlpStoreListener>();
  private state: OtlpStoreState = {
    received: {
      resourceLogs: [],
      resourceMetrics: [],
      resourceSpans: [],
    },
    merged: {
      resourceLogs: [],
      resourceMetrics: [],
      resourceSpans: [],
    },
  };

  /** Logs use simple full replacement for now. */
  storeLogs(request: ExportLogsServiceRequest): void {
    const resourceLogs = clone(request.resourceLogs);
    this.state.received.resourceLogs = resourceLogs;
    this.state.merged.resourceLogs = clone(resourceLogs);
    this.emit({ request: this.getMergedLogsRequest(), signal: "logs" });
  }

  /**
   * Metrics are merged into the existing aggregate by:
   * Resource + Scope + Metric name + data point attributes.
   *
   * When a data point key already exists, the incoming data point replaces the
   * previous one in full.
   */
  storeMetrics(request: ExportMetricsServiceRequest): void {
    const resourceMetrics = normalizeIncomingResourceMetrics(request.resourceMetrics);
    this.state.received.resourceMetrics = resourceMetrics;
    this.state.merged.resourceMetrics = mergeResourceMetrics(this.state.merged.resourceMetrics, resourceMetrics);
    this.emit({ request: this.getMergedMetricsRequest(), signal: "metrics" });
  }

  /** Traces use simple full replacement for now. */
  storeTraces(request: ExportTraceServiceRequest): void {
    const resourceSpans = clone(request.resourceSpans);
    this.state.received.resourceSpans = resourceSpans;
    this.state.merged.resourceSpans = clone(resourceSpans);
    this.emit({ request: this.getMergedTracesRequest(), signal: "traces" });
  }

  /** Returns a defensive copy so callers cannot mutate store state by reference. */
  getState(): OtlpStoreState {
    return clone(this.state);
  }

  getMergedLogsRequest(): ExportLogsServiceRequest {
    return { resourceLogs: clone(this.state.merged.resourceLogs) };
  }

  getMergedMetricsRequest(): ExportMetricsServiceRequest {
    return { resourceMetrics: clone(this.state.merged.resourceMetrics) };
  }

  getMergedTracesRequest(): ExportTraceServiceRequest {
    return { resourceSpans: clone(this.state.merged.resourceSpans) };
  }

  getMergedRequest(signal: TelemetrySignal): ExportLogsServiceRequest | ExportMetricsServiceRequest | ExportTraceServiceRequest {
    switch (signal) {
      case "logs":
        return this.getMergedLogsRequest();
      case "metrics":
        return this.getMergedMetricsRequest();
      case "traces":
        return this.getMergedTracesRequest();
    }
  }

  subscribe(listener: OtlpStoreListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private emit(update: OtlpStoreUpdate): void {
    for (const listener of this.listeners) {
      listener(clone(update));
    }
  }
}

export const otlpInMemoryStore = new OtlpInMemoryStore();

/**
 * Merge resource metric batches into the aggregate store.
 *
 * Resource identity is based on resource contents plus the resource schema URL.
 */
function mergeResourceMetrics(
  existingResourceMetrics: ResourceMetrics[],
  incomingResourceMetrics: ResourceMetrics[],
): ResourceMetrics[] {
  const mergedResourceMetrics = clone(existingResourceMetrics);
  const resourceIndexByKey = new Map(mergedResourceMetrics.map((resourceMetrics, index) => [getResourceMetricsKey(resourceMetrics), index]));

  for (const incomingResourceMetricsEntry of incomingResourceMetrics) {
    const resourceMetricsKey = getResourceMetricsKey(incomingResourceMetricsEntry);
    const existingResourceMetricsIndex = resourceIndexByKey.get(resourceMetricsKey);

    if (existingResourceMetricsIndex === undefined) {
      resourceIndexByKey.set(resourceMetricsKey, mergedResourceMetrics.length);
      mergedResourceMetrics.push(clone(incomingResourceMetricsEntry));
      continue;
    }

    mergedResourceMetrics[existingResourceMetricsIndex] = mergeSingleResourceMetrics(
      mergedResourceMetrics[existingResourceMetricsIndex],
      incomingResourceMetricsEntry,
    );
  }

  return sortResourceMetricsScopes(mergedResourceMetrics);
}

/** Merge scopes within a single resource group. */
function mergeSingleResourceMetrics(existingResourceMetrics: ResourceMetrics, incomingResourceMetrics: ResourceMetrics): ResourceMetrics {
  const mergedScopeMetrics = clone(existingResourceMetrics.scopeMetrics);
  const scopeIndexByKey = new Map(mergedScopeMetrics.map((scopeMetrics, index) => [getScopeMetricsKey(scopeMetrics), index]));

  for (const incomingScopeMetrics of incomingResourceMetrics.scopeMetrics) {
    const scopeMetricsKey = getScopeMetricsKey(incomingScopeMetrics);
    const existingScopeMetricsIndex = scopeIndexByKey.get(scopeMetricsKey);

    if (existingScopeMetricsIndex === undefined) {
      scopeIndexByKey.set(scopeMetricsKey, mergedScopeMetrics.length);
      mergedScopeMetrics.push(clone(incomingScopeMetrics));
      continue;
    }

    mergedScopeMetrics[existingScopeMetricsIndex] = mergeSingleScopeMetrics(
      mergedScopeMetrics[existingScopeMetricsIndex],
      incomingScopeMetrics,
    );
  }

  return {
    ...clone(incomingResourceMetrics),
    scopeMetrics: sortScopeMetricsByName(mergedScopeMetrics),
  };
}

/** Merge metrics within a single scope by metric name. */
function mergeSingleScopeMetrics(existingScopeMetrics: ScopeMetrics, incomingScopeMetrics: ScopeMetrics): ScopeMetrics {
  const mergedMetrics = clone(existingScopeMetrics.metrics);
  const metricIndexByKey = new Map(mergedMetrics.map((metric, index) => [metric.name, index]));

  for (const incomingMetric of incomingScopeMetrics.metrics) {
    const existingMetricIndex = metricIndexByKey.get(incomingMetric.name);

    if (existingMetricIndex === undefined) {
      metricIndexByKey.set(incomingMetric.name, mergedMetrics.length);
      mergedMetrics.push(clone(incomingMetric));
      continue;
    }

    mergedMetrics[existingMetricIndex] = mergeMetric(mergedMetrics[existingMetricIndex], incomingMetric);
  }

  return {
    ...clone(incomingScopeMetrics),
    metrics: sortMetricsByName(mergedMetrics),
  };
}

/**
 * Merge metric payloads while preserving the metric container from the incoming
 * export and only deduplicating the data point set.
 */
function mergeMetric(existingMetric: Metric, incomingMetric: Metric): Metric {
  if (existingMetric.data?.$case !== incomingMetric.data?.$case || incomingMetric.data === undefined) {
    return clone(incomingMetric);
  }

  switch (incomingMetric.data.$case) {
    case "gauge": {
      const existingGauge = getGaugeData(existingMetric);
      return {
        ...clone(incomingMetric),
        data: {
          $case: "gauge",
          gauge: {
            ...clone(incomingMetric.data.gauge),
            dataPoints: mergeDataPoints(existingGauge?.dataPoints ?? [], incomingMetric.data.gauge.dataPoints),
          },
        },
      };
    }
    case "sum": {
      const existingSum = getSumData(existingMetric);
      return {
        ...clone(incomingMetric),
        data: {
          $case: "sum",
          sum: {
            ...clone(incomingMetric.data.sum),
            dataPoints: mergeDataPoints(existingSum?.dataPoints ?? [], incomingMetric.data.sum.dataPoints),
          },
        },
      };
    }
    case "histogram": {
      const existingHistogram = getHistogramData(existingMetric);
      return {
        ...clone(incomingMetric),
        data: {
          $case: "histogram",
          histogram: {
            ...clone(incomingMetric.data.histogram),
            dataPoints: mergeDataPoints(existingHistogram?.dataPoints ?? [], incomingMetric.data.histogram.dataPoints),
          },
        },
      };
    }
    case "exponentialHistogram": {
      const existingExponentialHistogram = getExponentialHistogramData(existingMetric);
      return {
        ...clone(incomingMetric),
        data: {
          $case: "exponentialHistogram",
          exponentialHistogram: {
            ...clone(incomingMetric.data.exponentialHistogram),
            dataPoints: mergeDataPoints(
              existingExponentialHistogram?.dataPoints ?? [],
              incomingMetric.data.exponentialHistogram.dataPoints,
            ),
          },
        },
      };
    }
    case "summary": {
      const existingSummary = getSummaryData(existingMetric);
      return {
        ...clone(incomingMetric),
        data: {
          $case: "summary",
          summary: {
            ...clone(incomingMetric.data.summary),
            dataPoints: mergeDataPoints(existingSummary?.dataPoints ?? [], incomingMetric.data.summary.dataPoints),
          },
        },
      };
    }
  }
}

/** Helpers keep generated discriminated unions readable in merge branches. */
function getGaugeData(metric: Metric): Gauge | undefined {
  return metric.data?.$case === "gauge" ? metric.data.gauge : undefined;
}

function getSumData(metric: Metric): Sum | undefined {
  return metric.data?.$case === "sum" ? metric.data.sum : undefined;
}

function getHistogramData(metric: Metric): Histogram | undefined {
  return metric.data?.$case === "histogram" ? metric.data.histogram : undefined;
}

function getExponentialHistogramData(metric: Metric): ExponentialHistogram | undefined {
  return metric.data?.$case === "exponentialHistogram" ? metric.data.exponentialHistogram : undefined;
}

function getSummaryData(metric: Metric): Summary | undefined {
  return metric.data?.$case === "summary" ? metric.data.summary : undefined;
}

/**
 * Merge data points by attribute-set identity.
 *
 * The attribute set is normalized into a stable key so ordering differences do
 * not create duplicate time series entries.
 */
function mergeDataPoints<TDataPoint extends MetricDataPoint>(
  existingDataPoints: TDataPoint[],
  incomingDataPoints: TDataPoint[],
): TDataPoint[] {
  const mergedDataPoints = clone(existingDataPoints);
  const dataPointIndexByKey = new Map(mergedDataPoints.map((dataPoint, index) => [getDataPointKey(dataPoint), index]));

  for (const incomingDataPoint of incomingDataPoints) {
    const dataPointKey = getDataPointKey(incomingDataPoint);
    const existingDataPointIndex = dataPointIndexByKey.get(dataPointKey);

    if (existingDataPointIndex === undefined) {
      dataPointIndexByKey.set(dataPointKey, mergedDataPoints.length);
      mergedDataPoints.push(clone(incomingDataPoint));
      continue;
    }

    mergedDataPoints[existingDataPointIndex] = clone(incomingDataPoint);
  }

  return sortDataPoints(mergedDataPoints);
}

function normalizeIncomingResourceMetrics(resourceMetrics: ResourceMetrics[]): ResourceMetrics[] {
  return clone(resourceMetrics).map((resourceMetricsEntry) => ({
    ...resourceMetricsEntry,
    scopeMetrics: sortScopeMetricsByName(
      resourceMetricsEntry.scopeMetrics.map((scopeMetricsEntry) => ({
        ...scopeMetricsEntry,
        metrics: sortMetricsByName(scopeMetricsEntry.metrics.map(normalizeMetric)),
      })),
    ),
  }));
}

function sortResourceMetricsScopes(resourceMetrics: ResourceMetrics[]): ResourceMetrics[] {
  return resourceMetrics.map((resourceMetricsEntry) => ({
    ...resourceMetricsEntry,
    scopeMetrics: sortScopeMetricsByName(resourceMetricsEntry.scopeMetrics),
  }));
}

function sortScopeMetricsByName(scopeMetrics: ScopeMetrics[]): ScopeMetrics[] {
  return [...scopeMetrics].sort((left, right) => {
    const leftName = left.scope?.name ?? "";
    const rightName = right.scope?.name ?? "";
    const nameComparison = leftName.localeCompare(rightName);
    if (nameComparison !== 0) {
      return nameComparison;
    }

    const leftVersion = left.scope?.version ?? "";
    const rightVersion = right.scope?.version ?? "";
    return leftVersion.localeCompare(rightVersion);
  });
}

function normalizeMetric(metric: Metric): Metric {
  if (metric.data === undefined) {
    return metric;
  }

  switch (metric.data.$case) {
    case "gauge":
      return {
        ...metric,
        data: {
          $case: "gauge",
          gauge: {
            ...metric.data.gauge,
            dataPoints: sortDataPoints(metric.data.gauge.dataPoints.map(sortDataPointAttributes)),
          },
        },
      };
    case "sum":
      return {
        ...metric,
        data: {
          $case: "sum",
          sum: {
            ...metric.data.sum,
            dataPoints: sortDataPoints(metric.data.sum.dataPoints.map(sortDataPointAttributes)),
          },
        },
      };
    case "histogram":
      return {
        ...metric,
        data: {
          $case: "histogram",
          histogram: {
            ...metric.data.histogram,
            dataPoints: sortDataPoints(metric.data.histogram.dataPoints.map(sortDataPointAttributes)),
          },
        },
      };
    case "exponentialHistogram":
      return {
        ...metric,
        data: {
          $case: "exponentialHistogram",
          exponentialHistogram: {
            ...metric.data.exponentialHistogram,
            dataPoints: sortDataPoints(metric.data.exponentialHistogram.dataPoints.map(sortDataPointAttributes)),
          },
        },
      };
    case "summary":
      return {
        ...metric,
        data: {
          $case: "summary",
          summary: {
            ...metric.data.summary,
            dataPoints: sortDataPoints(metric.data.summary.dataPoints.map(sortDataPointAttributes)),
          },
        },
      };
  }
}

function sortMetricsByName(metrics: Metric[]): Metric[] {
  return [...metrics].sort((left, right) => left.name.localeCompare(right.name));
}

function sortDataPoints<TDataPoint extends MetricDataPoint>(dataPoints: TDataPoint[]): TDataPoint[] {
  return [...dataPoints].sort((left, right) => getDataPointKey(left).localeCompare(getDataPointKey(right)));
}

function sortDataPointAttributes<TDataPoint extends MetricDataPoint>(dataPoint: TDataPoint): TDataPoint {
  return {
    ...dataPoint,
    attributes: [...dataPoint.attributes].sort(compareKeyValueEntries),
  };
}

/** Resource identity is the resource payload plus its schema URL. */
function getResourceMetricsKey(resourceMetrics: ResourceMetrics): string {
  return stableKey({
    resource: resourceMetrics.resource,
    schemaUrl: resourceMetrics.schemaUrl,
  });
}

/** Scope identity is the instrumentation scope payload plus its schema URL. */
function getScopeMetricsKey(scopeMetrics: ScopeMetrics): string {
  return stableKey({
    schemaUrl: scopeMetrics.schemaUrl,
    scope: scopeMetrics.scope,
  });
}

/** Data point identity is currently based only on the attribute set. */
function getDataPointKey(dataPoint: MetricDataPoint): string {
  return stableKey(dataPoint.attributes);
}

/** Serialize a normalized value into a deterministic lookup key. */
function stableKey(value: unknown): string {
  return JSON.stringify(normalizeForKey(value));
}

/**
 * Normalize values before key generation:
 * `Uint8Array` becomes base64, object keys are sorted, and OTLP KeyValue arrays
 * are sorted by attribute key/value so semantically equivalent payloads match.
 */
function normalizeForKey(value: unknown): unknown {
  if (value instanceof Uint8Array) {
    return Buffer.from(value).toString("base64");
  }

  if (globalThis.Array.isArray(value)) {
    if (value.every((entry) => isKeyValueEntry(entry))) {
      return [...value]
        .map((entry) => normalizeKeyValueEntry(entry))
        .sort((left, right) => left.key.localeCompare(right.key) || JSON.stringify(left.value).localeCompare(JSON.stringify(right.value)));
    }

    return value.map((entry) => normalizeForKey(entry));
  }

  if (value === null || typeof value !== "object") {
    return value;
  }

  const entries = Object.entries(value)
    .filter(([, entryValue]) => entryValue !== undefined)
    .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
    .map(([entryKey, entryValue]) => [entryKey, normalizeForKey(entryValue)]);
  return Object.fromEntries(entries);
}

function isKeyValueEntry(value: unknown): value is { key: string; value?: unknown } {
  return value !== null && typeof value === "object" && "key" in value && typeof value.key === "string";
}

function normalizeKeyValueEntry(entry: { key: string; value?: unknown }): { key: string; value: unknown } {
  return {
    key: entry.key,
    value: normalizeForKey(entry.value),
  };
}

function compareKeyValueEntries(
  left: { key: string; value?: unknown },
  right: { key: string; value?: unknown },
): number {
  const keyComparison = left.key.localeCompare(right.key);
  if (keyComparison !== 0) {
    return keyComparison;
  }

  return JSON.stringify(normalizeForKey(left.value)).localeCompare(JSON.stringify(normalizeForKey(right.value)));
}

/** `structuredClone` keeps stored OTLP objects isolated from caller mutations. */
function clone<TValue>(value: TValue): TValue {
  return structuredClone(value);
}
