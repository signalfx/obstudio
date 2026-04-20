import React, { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { fetchMetricFilterValues, fetchMetrics, type MetricsQuery } from "../api/client";
import { FilterBar, type FilterClause, type FilterDefinition } from "../FilterBar";
import { TimeSeriesChart } from "./TimeSeriesChart";
import { useMetricTimeSeries, type MetricSeries } from "./useMetricTimeSeries";
import type { MetricGroup } from "../api/types";
import { DetailPanel, ResizablePanel } from "../layout";
import { TELEMETRY_SERIES_COLORS } from "../palette";

interface MetricsTabProps {
  metrics: MetricGroup[];
  telemetryError: string | null;
  onInteract?: () => void;
}

type DisplayType = "lines" | "bars" | "area";

const METRIC_FILTER_DEFINITIONS: FilterDefinition[] = [
  { key: "metricName", label: "Metric", kind: "text", placeholder: "http.server.duration" },
  { key: "serviceName", label: "Service", kind: "text", placeholder: "checkout" },
  { key: "scopeName", label: "Scope", kind: "text", placeholder: "otel.http" },
];
const METRIC_SUGGESTIBLE_FIELDS = new Set(["metricName", "serviceName", "scopeName"]);

function assignQueryFilter(query: MetricsQuery, clause: FilterClause): void {
  const targetKey = clause.op === "neq" ? "notFilters" : "filters";
  query[targetKey] = { ...(query[targetKey] ?? {}), [clause.key]: clause.value };
}

function buildMetricsQuery(clauses: FilterClause[]): MetricsQuery {
  const query: MetricsQuery = {};
  for (const clause of clauses) {
    switch (clause.key) {
      case "metricName":
      case "serviceName":
      case "scopeName":
        assignQueryFilter(query, clause);
        break;
      default:
        break;
    }
  }
  return query;
}

/** Metrics tab with list view and a right-side detail panel for the selected metric. */
export function MetricsTab({ metrics, telemetryError, onInteract }: MetricsTabProps): React.ReactElement {
  const [clauses, setClauses] = useState<FilterClause[]>([]);
  const [serverMetrics, setServerMetrics] = useState<MetricGroup[]>([]);
  const [hasResolvedFilteredMetrics, setHasResolvedFilteredMetrics] = useState(false);
  const [isFiltering, setIsFiltering] = useState(false);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [expandedMetricKey, setExpandedMetricKey] = useState<string | null>(null);
  const [selectedSeriesKey, setSelectedSeriesKey] = useState<string | null>(null);
  const [displayType, setDisplayType] = useState<DisplayType>("lines");
  const seriesOrderRef = useRef<Map<string, string[]>>(new Map());
  const handleInteract = useCallback(() => {
    onInteract?.();
  }, [onInteract]);

  const activeQuery = useMemo(() => buildMetricsQuery(clauses), [clauses]);
  const suggestMetricValues = useCallback((fieldKey: string, prefix: string, signal: AbortSignal) => {
    if (!METRIC_SUGGESTIBLE_FIELDS.has(fieldKey)) {
      return Promise.resolve<string[]>([]);
    }
    return fetchMetricFilterValues(fieldKey, prefix, buildMetricsQuery(clauses.filter((clause) => clause.key !== fieldKey)), signal);
  }, [clauses]);
  const hasActiveFilter = clauses.length > 0;
  const liveMetrics = Array.isArray(metrics) ? metrics : [];
  const visibleMetrics = hasActiveFilter
    ? (hasResolvedFilteredMetrics ? serverMetrics : liveMetrics)
    : liveMetrics;
  const { allSeries, metricList } = useMetricTimeSeries(visibleMetrics);
  const visibleMetricList = useMemo(() => {
    return [...metricList].sort((left, right) => {
      const nameCompare = left.name.localeCompare(right.name);
      if (nameCompare !== 0) {
        return nameCompare;
      }
      const serviceCompare = left.serviceName.localeCompare(right.serviceName);
      if (serviceCompare !== 0) {
        return serviceCompare;
      }
      return left.scopeName.localeCompare(right.scopeName);
    });
  }, [metricList]);

  const expandedSeries = useMemo(() => {
    if (!expandedMetricKey) return [];
    const currentSeries = allSeries.filter((series) => series.metricKey === expandedMetricKey);
    const previousOrder = seriesOrderRef.current.get(expandedMetricKey) ?? [];
    const currentKeys = new Set(currentSeries.map((series) => series.key));
    const nextOrder = [
      ...previousOrder.filter((key) => currentKeys.has(key)),
      ...currentSeries.map((series) => series.key).filter((key) => !previousOrder.includes(key)),
    ];
    seriesOrderRef.current.set(expandedMetricKey, nextOrder);

    const seriesByKey = new Map(currentSeries.map((series) => [series.key, series] as const));
    return nextOrder
      .map((key) => seriesByKey.get(key))
      .filter((series): series is MetricSeries => series !== undefined);
  }, [allSeries, expandedMetricKey]);

  const expandedMeta = useMemo(
    () => (expandedMetricKey
      ? visibleMetricList.find((metric) => metric.key === expandedMetricKey)
        ?? metricList.find((metric) => metric.key === expandedMetricKey)
        ?? null
      : null),
    [expandedMetricKey, metricList, visibleMetricList],
  );

  const selectedDetail = selectedSeriesKey
    ? expandedSeries.find((series) => series.key === selectedSeriesKey) ?? null
    : null;

  const stats = useMemo(() => {
    if (!selectedDetail) return null;
    const values = selectedDetail.points.map((point) => point.value);
    if (values.length === 0) return null;
    return {
      min: Math.min(...values),
      max: Math.max(...values),
      avg: values.reduce((left, right) => left + right, 0) / values.length,
      count: values.length,
      latest: selectedDetail.latest,
    };
  }, [selectedDetail]);

  const selectedAttributes = useMemo(
    () => stableEntries(selectedDetail?.attributes ?? {}),
    [selectedDetail],
  );
  const selectedResourceAttributes = useMemo(
    () => stableEntries(selectedDetail?.resource.attributes ?? {}),
    [selectedDetail],
  );
  const showSelectedDescription = useMemo(() => {
    if (!selectedDetail?.description) {
      return false;
    }
    return normalizeText(selectedDetail.description) !== normalizeText(expandedMeta?.description ?? "");
  }, [expandedMeta?.description, selectedDetail?.description]);
  const metricSubtitle = useMemo(() => {
    if (!expandedMeta) {
      return undefined;
    }
    const parts: string[] = [];
    if (expandedMeta.description) {
      parts.push(expandedMeta.description);
    }
    if (expandedMeta.serviceName && expandedMeta.serviceName !== "unknown") {
      parts.push(expandedMeta.serviceName);
    }
    if (expandedMeta.scopeName) {
      parts.push(expandedMeta.scopeName);
    }
    return parts.join(" · ") || undefined;
  }, [expandedMeta]);
  const chartValueLabel = useMemo(
    () => (expandedMeta ? chartValueLabelForType(expandedMeta.type) : undefined),
    [expandedMeta],
  );
  const hasDetail = Boolean(expandedMeta);

  useEffect(() => {
    if (!hasActiveFilter) {
      setServerMetrics([]);
      setHasResolvedFilteredMetrics(false);
      setIsFiltering(false);
      setFilterError(null);
      return;
    }

    const controller = new AbortController();
    setIsFiltering(true);
    fetchMetrics(activeQuery, controller.signal)
      .then((nextMetrics) => {
        if (controller.signal.aborted) return;
        setServerMetrics(nextMetrics);
        setHasResolvedFilteredMetrics(true);
        setFilterError(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setHasResolvedFilteredMetrics(true);
        setFilterError(error instanceof Error ? error.message : "Failed to filter metrics");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsFiltering(false);
        }
      });

    return () => controller.abort();
  }, [activeQuery, hasActiveFilter]);

  useEffect(() => {
    if (!expandedMetricKey) return;
    if (!visibleMetricList.some((metric) => metric.key === expandedMetricKey)) {
      setExpandedMetricKey(null);
      setSelectedSeriesKey(null);
    }
  }, [expandedMetricKey, visibleMetricList]);

  return (
    <section className="tab-panel" role="tabpanel">
      <div className={`signal-view${hasDetail ? " signal-view--with-panel" : ""}`} onPointerDownCapture={handleInteract}>
        <div className="signal-view__content">
          {telemetryError ? (
            <p className="explorer__status explorer__status--error">{telemetryError}</p>
          ) : null}

          {filterError ? (
            <p className="explorer__status explorer__status--error">{filterError}</p>
          ) : null}

          {visibleMetricList.length > 0 || hasActiveFilter ? (
            <div className="explorer__toolbar explorer__toolbar--controls">
              <FilterBar
                definitions={METRIC_FILTER_DEFINITIONS}
                clauses={clauses}
                onChange={setClauses}
                fieldPlaceholder="Add filter"
                onSuggestValues={suggestMetricValues}
              />
            </div>
          ) : null}

          {visibleMetricList.length === 0 && liveMetrics.length === 0 && !hasActiveFilter ? (
            <p className="explorer__status explorer__status--empty">
              No metrics received yet. Send OTLP telemetry to port 4318 to begin exploring.
            </p>
          ) : isFiltering && hasActiveFilter && visibleMetricList.length === 0 ? (
            <p className="metrics-explorer__empty">
              Updating filtered metrics...
            </p>
          ) : visibleMetricList.length === 0 ? (
            <p className="metrics-explorer__empty">
              No metrics match the current filters.
            </p>
          ) : null}

          {visibleMetricList.length > 0 ? (
            <div className="data-table__head data-table__head--metrics metrics-card-list__head">
              <span className="data-table__th">Metric</span>
              <span className="data-table__th">Description</span>
              <span className="data-table__th">Type / Unit</span>
            </div>
          ) : null}

          <div className="metrics-card-list">
            {visibleMetricList.map((metric) => {
              const isExpanded = expandedMetricKey === metric.key;
              return (
                <div key={metric.key} className="metric-card">
                  <button
                    className={`data-table__row data-table__row--metrics metric-card__header ${isExpanded ? "metric-card__header--active" : ""}`}
                    onClick={() => {
                      setExpandedMetricKey(isExpanded ? null : metric.key);
                      setSelectedSeriesKey(null);
                    }}
                    type="button"
                  >
                    <span className="data-table__td data-table__td--metric-name metric-card__info">
                      <span className="metric-card__name explorer-row__primary">{metric.name}</span>
                    </span>
                    <span className="data-table__td data-table__td--metric-description">
                      <span className="metric-card__description explorer-row__secondary">{formatMetricDescription(metric)}</span>
                    </span>
                    <span className="data-table__td data-table__td--metric-meta">
                      <span className="data-table__cell-content data-table__cell-content--meta metric-card__meta">
                        <span className={`metric-card__badge metric-type metric-type--${metric.type}`}>{metric.type}</span>
                        <span className="metric-card__meta-separator explorer-row__secondary">/</span>
                        <span className="metric-card__unit explorer-row__secondary">{metric.unit || "--"}</span>
                      </span>
                    </span>
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        {expandedMeta ? (
          <ResizablePanel className="signal-view__panel signal-view__panel--metrics" resizeLabel="Resize metrics panel">
            <DetailPanel
              title={expandedMeta.name}
              subtitle={metricSubtitle}
              scrollResetKey={expandedMeta.key}
              onClose={() => {
                setExpandedMetricKey(null);
                setSelectedSeriesKey(null);
              }}
            >
              <div className="metrics-panel">
                <div className="metrics-explorer__controls">
                  <div className="metrics-explorer__display">
                    <span className="metrics-explorer__control-label">Display</span>
                    {(["lines", "bars", "area"] as DisplayType[]).map((nextDisplayType) => (
                      <button
                        key={nextDisplayType}
                        className={`pill pill--small ${displayType === nextDisplayType ? "pill--accent" : "pill--muted"}`}
                        onClick={() => setDisplayType(nextDisplayType)}
                        type="button"
                      >
                        {nextDisplayType.charAt(0).toUpperCase() + nextDisplayType.slice(1)}
                      </button>
                    ))}
                  </div>
                  <div className="metrics-explorer__control-summary">
                    {chartValueLabel ? <span className="metrics-explorer__plot-label">{chartValueLabel}</span> : null}
                    <span className="metrics-explorer__query-series">{expandedSeries.length} series</span>
                  </div>
                </div>

                <div className="metrics-explorer__chart">
                  <TimeSeriesChart
                    series={expandedSeries}
                    displayType={displayType}
                    selectedKey={selectedSeriesKey}
                    onSelectSeries={setSelectedSeriesKey}
                  />
                </div>

                <div className="metrics-explorer__detail">
                  <div className="metrics-explorer__detail-header">
                    <span className="metrics-explorer__detail-title">Series ({expandedSeries.length})</span>
                  </div>
                  <div className="metrics-explorer__detail-body">
                    {expandedSeries.map((series, index) => {
                      const attributes = stableEntries(series.attributes ?? {});
                      const serviceName = series.resource?.serviceName;
                      return (
                        <button
                          key={series.key}
                          className="metrics-explorer__series-row"
                          onClick={() => setSelectedSeriesKey(selectedSeriesKey === series.key ? null : series.key)}
                          type="button"
                          style={{ width: "100%", border: 0, background: selectedSeriesKey === series.key ? "var(--accent-soft)" : "transparent", cursor: "pointer", textAlign: "left", font: "inherit" }}
                        >
                          <span className="metrics-explorer__series-dot" style={{ background: TELEMETRY_SERIES_COLORS[index % TELEMETRY_SERIES_COLORS.length] }} />
                          <span className="metrics-explorer__series-attrs">
                            {serviceName ? <span className="metrics-explorer__series-service">{serviceName}</span> : null}
                            {attributes.length > 0 ? (
                              <span className="metrics-explorer__series-dimensions">
                                {attributes.map(([key, value]) => (
                                  <span key={key} className="metrics-explorer__series-attr">
                                    {key}={String(value)}
                                  </span>
                                ))}
                              </span>
                            ) : !serviceName ? <span className="metrics-explorer__series-no-attrs">(no dimensions)</span> : null}
                          </span>
                          <span className="metrics-explorer__series-value">{formatNumber(series.latest)}</span>
                          <span className="metrics-explorer__series-points">{series.points.length} pts</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {selectedDetail ? (
                  <div className="series-detail series-detail--panel">
                    {stats ? (
                      <>
                        <div className="series-detail__stats">
                          <div className="stat-card">
                            <span className="stat-card__label">Latest</span>
                            <span className="stat-card__value">{formatNumber(stats.latest)}</span>
                          </div>
                          <div className="stat-card">
                            <span className="stat-card__label">Min</span>
                            <span className="stat-card__value">{formatNumber(stats.min)}</span>
                          </div>
                          <div className="stat-card">
                            <span className="stat-card__label">Max</span>
                            <span className="stat-card__value">{formatNumber(stats.max)}</span>
                          </div>
                          <div className="stat-card">
                            <span className="stat-card__label">Avg</span>
                            <span className="stat-card__value">{formatNumber(stats.avg)}</span>
                          </div>
                        </div>
                        <div className="series-detail__meta-line">{formatPointCount(stats.count)}</div>
                      </>
                    ) : null}

                    {showSelectedDescription ? <p className="series-detail__desc">{selectedDetail.description}</p> : null}

                    <div className="series-detail__section">
                      <div className="series-detail__section-title">Dimensions</div>
                      <div className="series-detail__tags">
                        {selectedAttributes.length > 0 ? (
                          selectedAttributes.map(([key, value]) => (
                            <span key={key} className="series-detail__dim-tag">
                              <span className="series-detail__dim-key">{key}:</span>
                              {String(value)}
                            </span>
                          ))
                        ) : (
                          <span className="series-detail__tag">(no dimensions)</span>
                        )}
                      </div>
                    </div>

                    {selectedResourceAttributes.length > 0 ? (
                      <div className="series-detail__section">
                        <div className="series-detail__section-title">Resource</div>
                        <div className="series-detail__tags">
                          {selectedResourceAttributes.map(([key, value]) => (
                            <span key={key} className="series-detail__resource-tag">
                              <span className="series-detail__dim-key">{key}:</span>
                              {String(value)}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    <div className="series-detail__section">
                      <div className="series-detail__section-title">Scope</div>
                      <div className="series-detail__scope-line">
                        {selectedDetail.scope.name}
                        {selectedDetail.scope.version ? ` v${selectedDetail.scope.version}` : ""}
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            </DetailPanel>
          </ResizablePanel>
        ) : null}
      </div>
    </section>
  );
}

function formatNumber(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value % 1 === 0 ? String(value) : value.toFixed(2);
}

function formatMetricDescription(metric: { description: string; serviceName: string; scopeName: string }): string {
  const parts: string[] = [];
  const hasService = metric.serviceName && metric.serviceName !== "unknown";
  if (metric.description) {
    parts.push(metric.description);
  }
  if (hasService) {
    parts.push(metric.serviceName);
  }
  if (metric.scopeName) {
    parts.push(metric.scopeName);
  }
  return parts.join(" · ") || "--";
}

function formatPointCount(count: number): string {
  return `${count} ${count === 1 ? "point" : "points"} retained`;
}

function stableEntries(attributes: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(attributes).sort(([left], [right]) => left.localeCompare(right));
}

function normalizeText(value: string): string {
  return value.trim().toLowerCase();
}

function chartValueLabelForType(type: string): string {
  switch (type) {
    case "histogram":
    case "exponential_histogram":
    case "summary":
      return "Plotting mean value";
    default:
      return "Plotting raw value";
  }
}
