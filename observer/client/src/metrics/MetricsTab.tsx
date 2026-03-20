import { Fragment } from "react";
import { getAttributeDisplayInfo, getStringAttributeValue } from "../telemetry/types";
import type {
  AttributeDisplayType,
  ExponentialHistogramDataPoint,
  HistogramDataPoint,
  Metric as OtlpMetric,
  MetricsRequest,
  NumberDataPoint,
  SummaryDataPoint,
  TelemetryAttribute,
} from "../telemetry/types";

type DataPoint = {
  attributes: Array<DisplayAttribute>;
  value: number;
  unit: string;
};

type DisplayAttribute = {
  key: string;
  value: string;
  valueType: AttributeDisplayType;
};

type Metric = {
  description?: string;
  inlineValue?: number;
  inlineUnit?: string;
  id: string;
  metadata?: DisplayAttribute[];
  monotonic?: string;
  name: string;
  temporality?: string;
  type: "Counter" | "Gauge" | "Histogram" | "Summary";
  value?: number;
  unit?: string;
  dataPoints?: DataPoint[];
  scope: {
    name: string;
    version: string;
  };
};

type ResourceGroup = {
  attributes: DisplayAttribute[];
  entities: Array<{
    attributes: DisplayAttribute[];
    id: string;
    schemaUrl: string;
    type: string;
  }>;
  id: string;
  label: string;
  metricCount: number;
  schemaUrl: string;
  scopes: Array<{
    metrics: Metric[];
    schemaUrl: string;
    scope: Metric["scope"];
  }>;
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

function getResourceGlyph() {
  return "⬢";
}

function getScopeGlyph() {
  return "◎";
}

export function MetricsTab({ metrics, telemetryError }: MetricsTabProps) {
  const resourceGroups = metrics.resourceMetrics.map((resourceMetrics, resourceIndex) => {
    const scopes = resourceMetrics.scopeMetrics.map((scopeMetrics, scopeIndex) => ({
      metrics: scopeMetrics.metrics.map((metric, metricIndex) =>
        convertMetric(metric, resourceIndex, scopeIndex, metricIndex, scopeMetrics),
      ),
      scope: {
        name: scopeMetrics.scope?.name || "unknown-scope",
        version: scopeMetrics.scope?.version || "unknown",
      },
      schemaUrl: scopeMetrics.schemaUrl,
    }));
    const attributes = (resourceMetrics.resource?.attributes ?? []).map(toDisplayAttribute);
    const attributesByKey = new Map(attributes.map((attribute) => [attribute.key, attribute]));
    const entities = (resourceMetrics.resource?.entityRefs ?? []).map((entityRef, entityIndex) => ({
      attributes: [...entityRef.idKeys, ...entityRef.descriptionKeys].map((key) => ({
        ...(attributesByKey.get(key) ?? { key, value: "missing", valueType: "unknown" as const }),
        key,
      })),
      id: `${resourceIndex}-${entityIndex}-${entityRef.type}`,
      schemaUrl: entityRef.schemaUrl,
      type: entityRef.type,
    }));

    return {
      attributes,
      entities,
      id: `${resourceIndex}-${getResourceLabel(resourceMetrics.resource?.attributes)}`,
      label: getResourceLabel(resourceMetrics.resource?.attributes),
      metricCount: scopes.reduce((count, scope) => count + scope.metrics.length, 0),
      schemaUrl: resourceMetrics.schemaUrl,
      scopes,
    };
  });

  const displayMetrics = resourceGroups.flatMap((resourceGroup) => resourceGroup.scopes.flatMap((scopeGroup) => scopeGroup.metrics));
  const scopeGroups = resourceGroups.flatMap((resourceGroup) => resourceGroup.scopes);
  const resourceCount = resourceGroups.length;
  const histogramCount = displayMetrics.filter((metric) => metric.type === "Histogram").length;
  const gaugeCount = displayMetrics.filter((metric) => metric.type === "Gauge").length;
  const counterCount = displayMetrics.filter((metric) => metric.type === "Counter").length;
  const dataPointCount = displayMetrics.reduce((count, metric) => count + (metric.dataPoints?.length ?? 0), 0);
  const scopeCount = scopeGroups.length;

  return (
    <section className="tab-panel metrics-panel" role="tabpanel">
      {telemetryError !== null ? <p className="status error">{telemetryError}</p> : null}
      {displayMetrics.length === 0 ? <p className="status">No metrics received yet.</p> : null}

      <div className="metric-summary">
        <article className="summary-card">
          <p className="summary-card__label">Resources</p>
          <p className="summary-card__value">{resourceCount.toLocaleString()}</p>
        </article>
        <article className="summary-card">
          <p className="summary-card__label">Scopes</p>
          <p className="summary-card__value">{scopeCount.toLocaleString()}</p>
        </article>
        <article className="summary-card">
          <p className="summary-card__label">Metrics</p>
          <p className="summary-card__value">{displayMetrics.length.toLocaleString()}</p>
        </article>
        <article className="summary-card">
          <p className="summary-card__label">Data points</p>
          <p className="summary-card__value">{dataPointCount.toLocaleString()}</p>
        </article>
      </div>

      <div className="metric-table" role="table" aria-label="Collected metrics">
        <div className="metric-table__body">
          {resourceGroups.map((resourceGroup, resourceGroupIndex) => (
            <Fragment key={resourceGroup.id}>
              <div className="resource-row">
                <div className="resource-row__main">
                  <div className="resource-row__line">
                    <span className="resource-row__glyph" aria-hidden="true">
                      {getResourceGlyph()}
                    </span>
                    <div className="resource-row__content">
                      <span className="resource-row__label">Resource: {resourceGroup.label}</span>
                    </div>
                  </div>
                  <div className="resource-row__line">
                    <span className="resource-row__glyph" aria-hidden="true" />
                    <div className="resource-row__content">
                      <span className="resource-row__schema">{formatSchemaUrl(resourceGroup.schemaUrl)}</span>
                    </div>
                  </div>
                  {resourceGroup.attributes.length > 0 ? (
                    <div className="resource-row__line">
                      <span className="resource-row__glyph" aria-hidden="true" />
                      <div className="resource-row__content resource-row__attributes">
                        {resourceGroup.attributes.map((attribute) => (
                          <span key={attribute.key} className="attribute-pill">
                            <span className="attribute-pill__key">{attribute.key}</span>=
                            <span className={getAttributeValueClassName("attribute-pill__value", attribute.valueType)}>
                              {attribute.value}
                            </span>
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {resourceGroup.entities.length > 0 ? (
                    <div className="resource-row__line">
                      <span className="resource-row__glyph" aria-hidden="true" />
                      {resourceGroup.entities.map((entity) => (
                        <div key={entity.id} className="entity-card">
                          <span className="entity-card__label">Entity: {entity.type}</span>
                          {entity.schemaUrl ? <span className="entity-card__schema">{entity.schemaUrl}</span> : null}
                          {entity.attributes.map((attribute) => (
                            <span key={`${entity.id}-${attribute.key}`} className="attribute-pill">
                              <span className="attribute-pill__key">{attribute.key}</span>=
                              <span className={getAttributeValueClassName("attribute-pill__value", attribute.valueType)}>
                                {attribute.value}
                              </span>
                            </span>
                          ))}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
                <span className="resource-row__count">
                  {resourceGroup.scopes.length} {resourceGroup.scopes.length === 1 ? "scope" : "scopes"} / {resourceGroup.metricCount}{" "}
                  {resourceGroup.metricCount === 1 ? "metric" : "metrics"}
                </span>
              </div>

              {resourceGroup.scopes.map((group, scopeIndex) => (
                <Fragment key={`${resourceGroup.id}-${group.scope.name}@${group.scope.version}`}>
                  <div className="scope-row">
                    <span className="scope-row__glyph" aria-hidden="true">
                      {getScopeGlyph()}
                    </span>
                    <div className="scope-row__main">
                      <div className="scope-row__line">
                        <span className="scope-row__name">{group.scope.name}</span>
                      </div>
                      <div className="scope-row__line">
                        <span className="scope-row__schema">{formatSchemaUrl(group.schemaUrl)}</span>
                        <span className="scope-row__version">@{group.scope.version}</span>
                      </div>
                    </div>
                    <span className="scope-row__count">
                      {group.metrics.length} {group.metrics.length === 1 ? "metric" : "metrics"}
                    </span>
                  </div>

                  {group.metrics.map((metric, index) => (
                    <Fragment key={metric.id}>
                      <div
                        className={
                          index < group.metrics.length - 1 || metric.dataPoints
                            ? "metric-row metric-row--bordered"
                            : "metric-row"
                        }
                        role="row"
                      >
                        <div className="metric-row__name">
                          <span className={`metric-row__glyph ${getMetricTypeClass(metric.type)}`} aria-hidden="true">
                            {getMetricGlyph(metric.type)}
                          </span>
                          <div className="metric-row__meta">
                            <span className="metric-row__path">{metric.name}</span>
                            {metric.description ? <span className="metric-row__description">{metric.description}</span> : null}
                          </div>
                        </div>
                        <div className="metric-row__type">
                          <div className="metric-row__type-main">
                            <span className="metric-row__type-label">Type:</span>{" "}
                            <span className={getMetricTypeClass(metric.type)}>{metric.type}</span>
                          </div>
                          {metric.temporality ? (
                            <div className="metric-row__temporality">Temporality: {metric.temporality}</div>
                          ) : null}
                          {metric.monotonic ? <div className="metric-row__temporality">Monotonic: {metric.monotonic}</div> : null}
                          {metric.metadata?.length ? (
                            <div className="metric-row__metadata">
                              {metric.metadata.map((attribute) => (
                                <span key={attribute.key} className="metadata-pill">
                                  <span className="metadata-pill__key">{attribute.key}</span>=
                                  <span className={getAttributeValueClassName("metadata-pill__value", attribute.valueType)}>
                                    {attribute.value}
                                  </span>
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </div>
                        <div className="metric-row__value">
                          {metric.inlineValue !== undefined
                            ? metric.inlineValue.toLocaleString()
                            : metric.dataPoints || metric.value === undefined
                            ? null
                            : metric.value.toLocaleString()}
                        </div>
                        <div className="metric-row__unit">
                          {metric.dataPoints ? (
                            <span className="metric-row__summary-count">
                              {metric.dataPoints.length} {metric.dataPoints.length === 1 ? "point" : "points"}
                            </span>
                          ) : (
                            metric.inlineUnit ?? metric.unit
                          )}
                        </div>
                      </div>

                      {metric.dataPoints?.map((dataPoint, dataPointIndex, dataPoints) => (
                        <div
                          key={`${metric.id}-${dataPointIndex}`}
                          className={
                            dataPointIndex < dataPoints.length - 1 ||
                            index < group.metrics.length - 1 ||
                            scopeIndex < resourceGroup.scopes.length - 1 ||
                            resourceGroupIndex < resourceGroups.length - 1
                              ? "data-point-row data-point-row--bordered"
                              : "data-point-row"
                          }
                          role="row"
                        >
                          <div className="data-point-row__attributes">
                            {dataPoint.attributes.map((attribute) => (
                              <span key={attribute.key} className="attribute-pill">
                                <span className="attribute-pill__key">{attribute.key}</span>=
                                <span className={getAttributeValueClassName("attribute-pill__value", attribute.valueType)}>
                                  {attribute.value}
                                </span>
                              </span>
                            ))}
                          </div>
                          <div className="data-point-row__reading">
                            <span className="metric-row__value">{dataPoint.value.toLocaleString()}</span>
                            <span className="metric-row__unit">{dataPoint.unit}</span>
                          </div>
                        </div>
                      ))}
                    </Fragment>
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

function getResourceLabel(attributes: TelemetryAttribute[] | undefined): string {
  return (
    getStringAttributeValue(attributes?.find((attribute) => attribute.key === "service.name")) ??
    getStringAttributeValue(attributes?.find((attribute) => attribute.key === "host.name")) ??
    getStringAttributeValue(attributes?.find((attribute) => attribute.key === "telemetry.sdk.language")) ??
    "unknown-resource"
  );
}

function toDisplayAttribute(attribute: TelemetryAttribute): DisplayAttribute {
  const { type, value } = getAttributeDisplayInfo(attribute);
  return { key: attribute.key, value, valueType: type };
}

function getAttributeValueClassName(baseClassName: string, valueType: AttributeDisplayType): string {
  return `${baseClassName} ${baseClassName}--${valueType}`;
}

function formatSchemaUrl(schemaUrl: string | undefined): string {
  return `schema: ${schemaUrl || "none"}`;
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
    attributes: dataPoint.attributes.map(toDisplayAttribute),
    unit: metric.unit,
    value: getMetricPointValue(metric, dataPoint),
  }));
  const inlineDataPoint = displayDataPoints.length === 1 && Object.keys(displayDataPoints[0].attributes).length === 0
    ? displayDataPoints[0]
    : undefined;
  const dataPoints = inlineDataPoint === undefined ? displayDataPoints : undefined;

  return {
    description: metric.description || undefined,
    dataPoints,
    id: `${resourceIndex}-${scopeIndex}-${metricIndex}`,
    inlineUnit: inlineDataPoint?.unit,
    inlineValue: inlineDataPoint?.value,
    metadata: metric.metadata.length
      ? metric.metadata.map((attribute) => ({
          ...toDisplayAttribute(attribute),
        }))
      : undefined,
    monotonic: getMetricMonotonic(metric),
    name: metric.name,
    scope,
    temporality: getMetricTemporality(metric),
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

function getMetricTemporality(metric: OtlpMetric): string | undefined {
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

function getMetricMonotonic(metric: OtlpMetric): string | undefined {
  switch (metric.data?.$case) {
    case "sum":
      return metric.data.sum.isMonotonic ? "Yes" : "No";
    default:
      return undefined;
  }
}

function formatAggregationTemporality(aggregationTemporality: number): string | undefined {
  switch (aggregationTemporality) {
    case 1:
      return "Delta";
    case 2:
      return "Cumulative";
    default:
      return "Unspecified";
  }
}

function getMetricPointValue(
  metric: OtlpMetric,
  dataPoint: NumberDataPoint | HistogramDataPoint | ExponentialHistogramDataPoint | SummaryDataPoint,
): number {
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

  if (
    (metric.data?.$case === "histogram" || metric.data?.$case === "exponentialHistogram") &&
    "sum" in dataPoint &&
    typeof dataPoint.sum === "number" &&
    "count" in dataPoint
  ) {
    const count = Number(dataPoint.count);
    if (count > 0) {
      return dataPoint.sum / count;
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
