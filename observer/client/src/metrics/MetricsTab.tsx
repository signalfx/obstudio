import React, { useState, useMemo } from "react";
import { TimeSeriesChart } from "./TimeSeriesChart";
import { useMetricTimeSeries } from "./useMetricTimeSeries";
import type { MetricGroup } from "../api/types";

interface MetricsTabProps {
  metrics: MetricGroup[];
  telemetryError: string | null;
}

type DisplayType = "lines" | "bars" | "area";

const TYPE_GLYPHS: Record<string, string> = {
  counter: "\u2191",
  gauge: "\u25CC",
  histogram: "\u25EB",
  summary: "\u2726",
  exponential_histogram: "\u25EB",
};

/** Metrics tab with expandable metric cards and time series charts. */
export function MetricsTab({ metrics, telemetryError }: MetricsTabProps): React.ReactElement {
  const [expandedMetric, setExpandedMetric] = useState<string | null>(null);
  const [selectedSeriesKey, setSelectedSeriesKey] = useState<string | null>(null);
  const [displayType, setDisplayType] = useState<DisplayType>("lines");

  const { allSeries, metricList } = useMetricTimeSeries(metrics);

  const expandedSeries = useMemo(() => {
    if (!expandedMetric) return [];
    return allSeries.filter((s) => s.metricName === expandedMetric);
  }, [allSeries, expandedMetric]);

  const selectedDetail = selectedSeriesKey
    ? allSeries.find((s) => s.key === selectedSeriesKey) ?? null
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

  return (
    <section className="tab-panel" role="tabpanel">
      {telemetryError ? (
        <p className="explorer__status explorer__status--error">{telemetryError}</p>
      ) : null}

      {metricList.length === 0 && metrics.length === 0 ? (
        <p className="metrics-explorer__empty" style={{ padding: "40px 20px" }}>
          Waiting for metrics... Send OTLP data to port 4318.
        </p>
      ) : null}

      <div className="metrics-card-list">
        {metricList.map((m) => {
          const isExpanded = expandedMetric === m.name;
          const series = isExpanded ? expandedSeries : [];
          const expandedMeta = isExpanded ? m : null;

          return (
            <div key={m.name} className="metric-card">
              <button
                className={`metric-card__header ${isExpanded ? "metric-card__header--active" : ""}`}
                onClick={() => {
                  setExpandedMetric(isExpanded ? null : m.name);
                  setSelectedSeriesKey(null);
                }}
                type="button"
              >
                <span className="metric-card__glyph">{TYPE_GLYPHS[m.type] ?? "\u25CF"}</span>
                <span className="metric-card__info">
                  <span className="metric-card__name">{m.name}</span>
                  {m.description ? <span className="metric-card__desc">{m.description}</span> : null}
                </span>
                <span className={`metric-card__badge metric-type metric-type--${m.type}`}>{m.type}</span>
                {m.unit ? <span className="metric-card__unit">{m.unit}</span> : null}
                {m.serviceCount > 1 ? <span className="metric-card__services">{m.serviceCount} svc</span> : null}
                <span className="metric-card__chevron">{isExpanded ? "\u25B2" : "\u25BC"}</span>
              </button>

              {isExpanded && expandedMeta ? (
                <div className="metric-card__body">
                  {/* Display controls */}
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
                    <span className="metrics-explorer__query-series">{series.length} series</span>
                  </div>

                  {/* Chart */}
                  <div className="metrics-explorer__chart">
                    <TimeSeriesChart
                      series={series}
                      displayType={displayType}
                      selectedKey={selectedSeriesKey}
                      onSelectSeries={setSelectedSeriesKey}
                    />
                  </div>

                  {/* Series list */}
                  <div className="metrics-explorer__detail">
                    <div className="metrics-explorer__detail-header">
                      <span className="metrics-explorer__detail-title">Series ({series.length})</span>
                    </div>
                    <div className="metrics-explorer__detail-body">
                      {series.map((s, i) => {
                        const attrs = Object.entries(s.attributes ?? {});
                        const svcName = s.resource?.serviceName;
                        return (
                          <button
                            key={s.key}
                            className="metrics-explorer__series-row"
                            onClick={() => setSelectedSeriesKey(selectedSeriesKey === s.key ? null : s.key)}
                            type="button"
                            style={{ width: "100%", border: 0, background: selectedSeriesKey === s.key ? "var(--accent-soft)" : "transparent", cursor: "pointer", textAlign: "left", font: "inherit" }}
                          >
                            <span className="metrics-explorer__series-dot" style={{ background: COLORS[i % COLORS.length] }} />
                            <span className="metrics-explorer__series-attrs">
                              {svcName ? <span>{svcName}</span> : null}
                              {attrs.length > 0
                                ? attrs.map(([k, v]) => <span key={k}>{k}={String(v)}</span>)
                                : !svcName ? <span className="metrics-explorer__series-no-attrs">(no dimensions)</span> : null}
                            </span>
                            <span className="metrics-explorer__series-value">{formatNumber(s.latest)}</span>
                            <span className="metrics-explorer__series-points">{s.points.length} pts</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Selected series detail */}
                  {selectedDetail && stats ? (
                    <div className="series-detail">
                      <div className="series-detail__header">
                        <div className="series-detail__title">
                          {selectedDetail.resource?.serviceName
                            ? selectedDetail.resource.serviceName
                            : null}
                          {Object.entries(selectedDetail.attributes ?? {}).length > 0
                            ? (selectedDetail.resource?.serviceName ? " · " : "") + Object.entries(selectedDetail.attributes ?? {}).map(([k, v]) => `${k}=${v}`).join(", ")
                            : !selectedDetail.resource?.serviceName ? "(no dimensions)" : null}
                        </div>
                        <button className="series-detail__close" onClick={() => setSelectedSeriesKey(null)} type="button">&times;</button>
                      </div>
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
                      <div className="series-detail__tags">
                        <span className="series-detail__tag series-detail__tag--type">{selectedDetail.type}</span>
                        {selectedDetail.unit ? <span className="series-detail__tag">{selectedDetail.unit}</span> : null}
                        {selectedDetail.temporality ? <span className="series-detail__tag">{selectedDetail.temporality}</span> : null}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

const COLORS = ["#4fc1ff", "#4ec9b0", "#c586c0", "#dcdcaa", "#ce9178", "#569cd6", "#d16969"];

function formatNumber(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v % 1 === 0 ? String(v) : v.toFixed(2);
}
