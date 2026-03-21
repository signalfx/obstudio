import { Fragment } from "react";
import { getStringAttributeValue } from "../telemetry/types";
import type {
  ExponentialHistogramDataPoint,
  HistogramDataPoint,
  Metric as OtlpMetric,
  MetricsRequest,
  NumberDataPoint,
  SummaryDataPoint,
} from "../telemetry/types";

type DataPoint = {
  attributes: Record<string, string>;
  value: number;
  unit: string;
};

type Metric = {
  inlineValue?: number;
  inlineUnit?: string;
  id: string;
  name: string;
  type: "Counter" | "Gauge" | "Histogram" | "Summary";
  value?: number;
  unit?: string;
  dataPoints?: DataPoint[];
  scope: {
    name: string;
    version: string;
  };
};

type MetricsTabProps = {
  metrics: MetricsRequest;
  telemetryError: string | null;
};

function getMetricGlyph(type: Metric["type"]) {
  switch (type) {
    case "Counter":
      return "↑";
    case "Gauge":
      return "◌";
    case "Histogram":
      return "◫";
    case "Summary":
      return "✦";
    default:
      return "•";
  }
}

function getMetricTypeClass(type: Metric["type"]) {
  switch (type) {
    case "Counter":
      return "metric-type metric-type--counter";
    case "Gauge":
      return "metric-type metric-type--gauge";
    case "Histogram":
      return "metric-type metric-type--histogram";
    case "Summary":
      return "metric-type metric-type--summary";
    default:
      return "metric-type";
  }
}

export function MetricsTab({ metrics, telemetryError }: MetricsTabProps) {
  const displayMetrics = metrics.resourceMetrics.flatMap((resourceMetrics, resourceIndex) =>
    resourceMetrics.scopeMetrics.flatMap((scopeMetrics, scopeIndex) =>
      scopeMetrics.metrics.map((metric, metricIndex) => convertMetric(metric, resourceIndex, scopeIndex, metricIndex, scopeMetrics)),
    ),
  );

  const metricsByScope = displayMetrics.reduce(
    (acc, metric) => {
      const scopeKey = `${metric.scope.name}@${metric.scope.version}`;
      const group = acc[scopeKey] ?? {
        scope: metric.scope,
        metrics: [],
      };

      group.metrics.push(metric);
      acc[scopeKey] = group;
      return acc;
    },
    {} as Record<string, { metrics: Metric[]; scope: Metric["scope"] }>,
  );

  const scopeGroups = Object.values(metricsByScope);
  const histogramCount = displayMetrics.filter((metric) => metric.type === "Histogram").length;
  const gaugeCount = displayMetrics.filter((metric) => metric.type === "Gauge").length;
  const counterCount = displayMetrics.filter((metric) => metric.type === "Counter").length;
  const dataPointCount = displayMetrics.reduce((count, metric) => count + (metric.dataPoints?.length ?? 0), 0);

  return (
    <section className="tab-panel metrics-panel" role="tabpanel">
      <div className="panel-toolbar">
        <div className="panel-toolbar__title">
          <span className="panel-toolbar__glyph" aria-hidden="true">
            ◫
          </span>
          <span>{displayMetrics.length} metrics collected</span>
        </div>
        <div className="panel-toolbar__meta">
          <span>{scopeGroups.length} scopes</span>
          <span>{histogramCount} histograms</span>
          <span>{gaugeCount} gauges</span>
          <span>{counterCount} counters</span>
        </div>
      </div>

      {telemetryError !== null ? <p className="status error">{telemetryError}</p> : null}
      {displayMetrics.length === 0 ? <p className="status">No metrics received yet.</p> : null}

      <div className="metric-summary">
        <article className="summary-card">
          <p className="summary-card__label">Scopes</p>
          <p className="summary-card__value">{scopeGroups.length.toLocaleString()}</p>
          <p className="summary-card__meta">Distinct instrumentation scopes</p>
        </article>
        <article className="summary-card">
          <p className="summary-card__label">Metrics</p>
          <p className="summary-card__value">{displayMetrics.length.toLocaleString()}</p>
          <p className="summary-card__meta">Merged metric definitions</p>
        </article>
        <article className="summary-card">
          <p className="summary-card__label">Data points</p>
          <p className="summary-card__value">{dataPointCount.toLocaleString()}</p>
          <p className="summary-card__meta">Merged time series entries</p>
        </article>
      </div>

      <div className="metric-table" role="table" aria-label="Collected metrics">
        <div className="metric-table__header" role="row">
          <span>Name</span>
          <span>Type</span>
          <span>Value</span>
          <span>Unit</span>
        </div>

        <div className="metric-table__body">
          {scopeGroups.map((group) => (
            <Fragment key={`${group.scope.name}@${group.scope.version}`}>
              <div className="scope-row">
                <span className="scope-row__name">Scope: {group.scope.name}</span>
                <span className="scope-row__version">@{group.scope.version}</span>
                <span className="scope-row__count">
                  {group.metrics.length} {group.metrics.length === 1 ? "metric" : "metrics"}
                </span>
              </div>

              {group.metrics.map((metric, index) => (
                <Fragment key={metric.id}>
                  <div
                    className={
                      index < group.metrics.length - 1 && !metric.dataPoints
                        ? "metric-row metric-row--bordered"
                        : "metric-row"
                    }
                    role="row"
                  >
                    <div className="metric-row__name">
                      <span className={getMetricTypeClass(metric.type)} aria-hidden="true">
                        {getMetricGlyph(metric.type)}
                      </span>
                      <span className="metric-row__path">{metric.name}</span>
                      {metric.dataPoints ? (
                        <span className="metric-row__count">({metric.dataPoints.length})</span>
                      ) : null}
                    </div>
                    <div className="metric-row__type">
                      <span className={getMetricTypeClass(metric.type)}>{metric.type}</span>
                    </div>
                    <div className="metric-row__value">
                      {metric.inlineValue !== undefined
                        ? metric.inlineValue.toLocaleString()
                        : metric.dataPoints || metric.value === undefined
                        ? null
                        : metric.value.toLocaleString()}
                    </div>
                    <div className="metric-row__unit">
                      {metric.inlineUnit ?? (metric.dataPoints ? null : metric.unit)}
                    </div>
                  </div>

                  {metric.dataPoints?.map((dataPoint, dataPointIndex, dataPoints) => (
                    <div
                      key={`${metric.id}-${dataPointIndex}`}
                      className={
                        dataPointIndex < dataPoints.length - 1 || index < group.metrics.length - 1
                          ? "data-point-row data-point-row--bordered"
                          : "data-point-row"
                      }
                      role="row"
                    >
                      <div className="data-point-row__attributes">
                        {Object.entries(dataPoint.attributes).map(([key, value]) => (
                          <span key={key} className="attribute-pill">
                            <span className="attribute-pill__key">{key}</span>=
                            <span className="attribute-pill__value">{value}</span>
                          </span>
                        ))}
                      </div>
                      <div />
                      <div className="metric-row__value">{dataPoint.value.toLocaleString()}</div>
                      <div className="metric-row__unit">{dataPoint.unit}</div>
                    </div>
                  ))}
                </Fragment>
              ))}
            </Fragment>
          ))}
        </div>
      </div>
    </section>
  );
}

function convertMetric(
  metric: OtlpMetric,
  resourceIndex: number,
  scopeIndex: number,
  metricIndex: number,
  scopeMetrics: MetricsRequest["resourceMetrics"][number]["scopeMetrics"][number],
): Metric {
  const scope = {
    name: scopeMetrics.scope?.name || "unknown-scope",
    version: scopeMetrics.scope?.version || "unknown",
  };
  const rawDataPoints = getMetricDataPoints(metric);
  const displayDataPoints = rawDataPoints.map((dataPoint) => ({
    attributes: Object.fromEntries(
      dataPoint.attributes.map((attribute) => [
        attribute.key,
        getStringAttributeValue(attribute) ?? JSON.stringify(attribute.value?.value ?? null),
      ]),
    ),
    unit: metric.unit,
    value: getMetricPointValue(dataPoint),
  }));
  const inlineDataPoint = displayDataPoints.length === 1 && Object.keys(displayDataPoints[0].attributes).length === 0
    ? displayDataPoints[0]
    : undefined;
  const dataPoints = inlineDataPoint === undefined ? displayDataPoints : undefined;

  return {
    dataPoints,
    id: `${resourceIndex}-${scopeIndex}-${metricIndex}`,
    inlineUnit: inlineDataPoint?.unit,
    inlineValue: inlineDataPoint?.value,
    name: metric.name,
    scope,
    type: getMetricType(metric),
    unit: inlineDataPoint === undefined && displayDataPoints.length === 0 ? metric.unit : undefined,
    value: inlineDataPoint === undefined && displayDataPoints.length === 0 ? undefined : undefined,
  };
}

function getMetricType(metric: OtlpMetric): Metric["type"] {
  switch (metric.data?.$case) {
    case "gauge":
      return "Gauge";
    case "sum":
      return "Counter";
    case "histogram":
    case "exponentialHistogram":
      return "Histogram";
    case "summary":
      return "Summary";
    default:
      return "Gauge";
  }
}

function getMetricDataPoints(metric: OtlpMetric): Array<NumberDataPoint | HistogramDataPoint | ExponentialHistogramDataPoint | SummaryDataPoint> {
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

function getMetricPointValue(dataPoint: NumberDataPoint | HistogramDataPoint | ExponentialHistogramDataPoint | SummaryDataPoint): number {
  if ("value" in dataPoint) {
    switch (dataPoint.value?.$case) {
      case "asDouble":
        return dataPoint.value.asDouble;
      case "asInt":
        return Number(dataPoint.value.asInt);
      default:
        return 0;
    }
  }

  if ("sum" in dataPoint && typeof dataPoint.sum === "number") {
    return dataPoint.sum;
  }

  if ("count" in dataPoint) {
    return Number(dataPoint.count);
  }

  return 0;
}
