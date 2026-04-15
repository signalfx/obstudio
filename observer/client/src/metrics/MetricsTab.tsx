import React, { useState, useMemo, useEffect, useRef } from "react";
import { TimeSeriesChart } from "./TimeSeriesChart";
import { useMetricTimeSeries, type MetricSeries } from "./useMetricTimeSeries";
import type { MetricGroup } from "../api/types";
import { DetailPanel } from "../layout";
import { TELEMETRY_SERIES_COLORS } from "../palette";

interface MetricsTabProps {
  metrics: MetricGroup[];
  telemetryError: string | null;
}

type DisplayType = "lines" | "bars" | "area";

/** Metrics tab with expandable metric cards and time series charts. */
export function MetricsTab({ metrics, telemetryError }: MetricsTabProps): React.ReactElement {
  const [query, setQuery] = useState("");
  const [expandedMetric, setExpandedMetric] = useState<string | null>(null);
  const [selectedSeriesKey, setSelectedSeriesKey] = useState<string | null>(null);
  const [displayType, setDisplayType] = useState<DisplayType>("lines");
  const seriesOrderRef = useRef<Map<string, string[]>>(new Map());

  const { allSeries, metricList } = useMetricTimeSeries(metrics);
  const visibleMetricList = useMemo(() => {
    const trimmedQuery = query.trim().toLowerCase();
    return [...metricList]
      .filter((metric) => {
        if (!trimmedQuery) {
          return true;
        }
        const haystack = [
          metric.name,
          metric.description ?? "",
          metric.serviceName ?? "",
          metric.type,
          metric.unit ?? "",
        ].join(" ").toLowerCase();
        return haystack.includes(trimmedQuery);
      })
      .sort((left, right) => left.name.localeCompare(right.name));
  }, [metricList, query]);

  const expandedSeries = useMemo(() => {
    if (!expandedMetric) return [];
    const currentSeries = allSeries.filter((s) => s.metricName === expandedMetric);
    const previousOrder = seriesOrderRef.current.get(expandedMetric) ?? [];
    const currentKeys = new Set(currentSeries.map((series) => series.key));
    const nextOrder = [
      ...previousOrder.filter((key) => currentKeys.has(key)),
      ...currentSeries.map((series) => series.key).filter((key) => !previousOrder.includes(key)),
    ];
    seriesOrderRef.current.set(expandedMetric, nextOrder);

    const seriesByKey = new Map(currentSeries.map((series) => [series.key, series] as const));
    return nextOrder
      .map((key) => seriesByKey.get(key))
      .filter((series): series is MetricSeries => series !== undefined);
  }, [allSeries, expandedMetric]);
  const expandedMeta = useMemo(
    () => (expandedMetric
      ? visibleMetricList.find((metric) => metric.name === expandedMetric)
        ?? metricList.find((metric) => metric.name === expandedMetric)
        ?? null
      : null),
    [expandedMetric, metricList, visibleMetricList],
  );

  const selectedDetail = selectedSeriesKey
    ? expandedSeries.find((s) => s.key === selectedSeriesKey) ?? null
    : null;

  const stats = useMemo(() => {
    if (!selectedDetail) return null;
    const vals = selectedDetail.points.map((p) => p.value);
    if (vals.length === 0) return null;
    return {
      min: Math.min(...vals),
      max: Math.max(...vals),
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
      count: vals.length,
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
  const selectedSubtitle = useMemo(() => {
    if (!selectedDetail) {
      return undefined;
    }
    const serviceName = selectedDetail.resource.serviceName;
    const dimensions = selectedAttributes.map(([key, value]) => `${key}=${String(value)}`);
    if (serviceName && dimensions.length > 0) {
      return `${serviceName} · ${dimensions.join(", ")}`;
    }
    if (serviceName) {
      return serviceName;
    }
    if (dimensions.length > 0) {
      return dimensions.join(", ");
    }
    return "(no dimensions)";
  }, [selectedAttributes, selectedDetail]);
  const metricSubtitle = useMemo(() => {
    if (!expandedMeta) {
      return undefined;
    }
    const parts: string[] = [];
    if (expandedMeta.description) {
      parts.push(expandedMeta.description);
    }
    if (expandedMeta.serviceCount > 1) {
      parts.push(`${expandedMeta.serviceCount} services`);
    } else if (expandedMeta.serviceName && expandedMeta.serviceName !== "unknown") {
      parts.push(expandedMeta.serviceName);
    }
    return parts.join(" · ") || undefined;
  }, [expandedMeta]);
  const hasDetail = Boolean(expandedMeta);

  useEffect(() => {
    if (!expandedMetric) return;
    if (!visibleMetricList.some((metric) => metric.name === expandedMetric)) {
      setExpandedMetric(null);
      setSelectedSeriesKey(null);
    }
  }, [expandedMetric, visibleMetricList]);

  return (
    <section className="tab-panel" role="tabpanel">
      <div className={`signal-view${hasDetail ? " signal-view--with-panel" : ""}`}>
        <div className="signal-view__content">
          {telemetryError ? (
            <p className="explorer__status explorer__status--error">{telemetryError}</p>
          ) : null}

          {metricList.length > 0 ? (
            <div className="explorer__toolbar explorer__toolbar--controls">
              <input
                className="explorer__input"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search metric, description, type, unit, or service"
              />
            </div>
          ) : null}

          {metricList.length === 0 && metrics.length === 0 ? (
            <p className="explorer__status explorer__status--empty" style={{ padding: "40px 20px" }}>
              No metrics received yet. Send OTLP telemetry to port 4318 to begin exploring.
            </p>
          ) : visibleMetricList.length === 0 ? (
            <p className="metrics-explorer__empty" style={{ padding: "24px 20px" }}>
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
            {visibleMetricList.map((m) => {
              const isExpanded = expandedMetric === m.name;

              return (
                <div key={m.name} className="metric-card">
                  <button
                    className={`data-table__row data-table__row--metrics metric-card__header ${isExpanded ? "metric-card__header--active" : ""}`}
                    onClick={() => {
                      setExpandedMetric(isExpanded ? null : m.name);
                      setSelectedSeriesKey(null);
                    }}
                    type="button"
                  >
                    <span className="data-table__td data-table__td--metric-name metric-card__info">
                      <span className="metric-card__name explorer-row__primary">{m.name}</span>
                    </span>
                    <span className="data-table__td data-table__td--metric-description">
                      <span className="metric-card__description explorer-row__secondary">{m.description || "--"}</span>
                    </span>
                    <span className="data-table__td data-table__td--metric-meta">
                      <span className="data-table__cell-content data-table__cell-content--meta metric-card__meta">
                        <span className={`metric-card__badge metric-type metric-type--${m.type}`}>{m.type}</span>
                        <span className="metric-card__meta-separator explorer-row__secondary">/</span>
                        <span className="metric-card__unit explorer-row__secondary">{m.unit || "--"}</span>
                      </span>
                    </span>
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        {expandedMeta ? (
          <div className="signal-view__panel signal-view__panel--metrics">
            <DetailPanel
              title={expandedMeta.name}
              subtitle={metricSubtitle}
              onClose={() => {
                setExpandedMetric(null);
                setSelectedSeriesKey(null);
              }}
            >
              <div className="metrics-panel">
                <div className="series-detail__tags">
                  <span className={`series-detail__tag series-detail__tag--type metric-type metric-type--${expandedMeta.type}`}>
                    {expandedMeta.type}
                  </span>
                  {expandedMeta.unit ? <span className="series-detail__tag">{expandedMeta.unit}</span> : null}
                  <span className="series-detail__tag">{expandedSeries.length} series</span>
                </div>

                <div className="metrics-explorer__controls">
                  <div className="metrics-explorer__display">
                    <span className="metrics-explorer__control-label">Display</span>
                    {(["lines", "bars", "area"] as DisplayType[]).map((dt) => (
                      <button
                        key={dt}
                        className={`pill pill--small ${displayType === dt ? "pill--accent" : "pill--muted"}`}
                        onClick={() => setDisplayType(dt)}
                        type="button"
                      >
                        {dt.charAt(0).toUpperCase() + dt.slice(1)}
                      </button>
                    ))}
                  </div>
                  <span className="metrics-explorer__query-series">{expandedSeries.length} series</span>
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
                    {expandedSeries.map((s, i) => {
                      const attrs = stableEntries(s.attributes ?? {});
                      const svcName = s.resource?.serviceName;
                      return (
                        <button
                          key={s.key}
                          className="metrics-explorer__series-row"
                          onClick={() => setSelectedSeriesKey(selectedSeriesKey === s.key ? null : s.key)}
                          type="button"
                          style={{ width: "100%", border: 0, background: selectedSeriesKey === s.key ? "var(--accent-soft)" : "transparent", cursor: "pointer", textAlign: "left", font: "inherit" }}
                        >
                          <span className="metrics-explorer__series-dot" style={{ background: TELEMETRY_SERIES_COLORS[i % TELEMETRY_SERIES_COLORS.length] }} />
                          <span className="metrics-explorer__series-attrs">
                            {svcName ? <span className="metrics-explorer__series-service">{svcName}</span> : null}
                            {attrs.length > 0 ? (
                              <span className="metrics-explorer__series-dimensions">
                                {attrs.map(([k, v]) => (
                                  <span key={k} className="metrics-explorer__series-attr">
                                    {k}={String(v)}
                                  </span>
                                ))}
                              </span>
                            ) : !svcName ? <span className="metrics-explorer__series-no-attrs">(no dimensions)</span> : null}
                          </span>
                          <span className="metrics-explorer__series-value">{formatNumber(s.latest)}</span>
                          <span className="metrics-explorer__series-points">{s.points.length} pts</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {selectedDetail ? (
                  <div className="series-detail series-detail--panel">
                    <div className="series-detail__header">
                      <div className="series-detail__title">{selectedSubtitle}</div>
                      <button className="series-detail__close" onClick={() => setSelectedSeriesKey(null)} type="button" aria-label="Clear series selection">
                        &times;
                      </button>
                    </div>

                    {stats ? (
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
                        <div className="stat-card">
                          <span className="stat-card__label">Points</span>
                          <span className="stat-card__value">{stats.count}</span>
                        </div>
                      </div>
                    ) : null}

                    <div className="series-detail__tags">
                      <span className="series-detail__tag series-detail__tag--type">{selectedDetail.type}</span>
                      {selectedDetail.unit ? <span className="series-detail__tag">{selectedDetail.unit}</span> : null}
                      {selectedDetail.temporality ? <span className="series-detail__tag">{selectedDetail.temporality}</span> : null}
                      {selectedDetail.isMonotonic ? <span className="series-detail__tag">monotonic</span> : null}
                    </div>

                    {selectedDetail.description ? <p className="series-detail__desc">{selectedDetail.description}</p> : null}

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
                            <span key={key} className="series-detail__dim-tag">
                              <span className="series-detail__dim-key">{key}:</span>
                              {String(value)}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    <div className="series-detail__section">
                      <div className="series-detail__section-title">Scope</div>
                      <div className="series-detail__tags">
                        <span className="series-detail__tag">{selectedDetail.scope.name}</span>
                        {selectedDetail.scope.version ? <span className="series-detail__tag">v{selectedDetail.scope.version}</span> : null}
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            </DetailPanel>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function formatNumber(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v % 1 === 0 ? String(v) : v.toFixed(2);
}

function stableEntries(attributes: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(attributes).sort(([left], [right]) => left.localeCompare(right));
}
