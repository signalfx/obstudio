import React, { useState } from "react";
import { TimeSeriesChart } from "../metrics/TimeSeriesChart";
import { useMetricTimeSeries } from "../metrics/useMetricTimeSeries";
import type { MetricGroup, MetricDataPoint } from "../api/types";
import type { PreviewPanel, ParsedQuery } from "./types";

interface DashboardPanelProps {
  panel: PreviewPanel;
  windowMs?: number;
  onExpand?: (panel: PreviewPanel) => void;
}

export function DashboardPanel({ panel, windowMs = 0, onExpand }: DashboardPanelProps): React.ReactElement {
  const prepared = usePreparedMetrics(panel.metrics ?? [], windowMs, panel.query);
  const { allSeries } = useMetricTimeSeries(prepared);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  return (
    <div className="dashboard-panel" data-chart-type={panel.chartType}>
      <div className="dashboard-panel__head">
        <span className="dashboard-panel__title">{panel.title || panel.label}</span>
        <div className="dashboard-panel__head-right">
          {(panel.query?.ignoredFilters?.length ?? 0) > 0 ? (
            <span
              className="dashboard-panel__chip dashboard-panel__chip--ignored"
              title={`Filter constraints not applied (preview may over-match): ${panel.query!.ignoredFilters!.join(", ")}`}
            >
              ⚠ filters partial
            </span>
          ) : null}
          <span className="dashboard-panel__type">{chartTypeLabel(panel.chartType)}</span>
          {onExpand ? (
            <button
              type="button"
              className="dashboard-panel__expand"
              title="Expand panel"
              onClick={() => onExpand(panel)}
              aria-label="Expand panel"
            >
              ⤢
            </button>
          ) : null}
        </div>
      </div>
      <div className="dashboard-panel__body">{renderBody(panel, allSeries, selectedKey, setSelectedKey, windowMs)}</div>
    </div>
  );
}

function renderBody(
  panel: PreviewPanel,
  allSeries: ReturnType<typeof useMetricTimeSeries>["allSeries"],
  selectedKey: string | null,
  setSelectedKey: (key: string) => void,
  windowMs: number,
): React.ReactElement {
  // Text / event panels carry markdown, not a query.
  if (panel.chartType === "text" || panel.chartType === "event") {
    return <div className="dashboard-panel__text">{panel.text ?? ""}</div>;
  }

  // Couldn't recover a metric from the SignalFlow.
  if (panel.query?.parseError) {
    return (
      <div className="dashboard-panel__empty dashboard-panel__empty--parse">
        <span className="dashboard-panel__empty-title">Couldn't parse SignalFlow</span>
        <span className="dashboard-panel__empty-hint">{panel.query.parseError}</span>
      </div>
    );
  }

  // No local series matches the panel's metric + filters.
  if (!panel.matched) {
    return (
      <div className="dashboard-panel__empty">
        <span className="dashboard-panel__empty-title">
          No local series matches <code>{panel.query?.metricName ?? "(unknown metric)"}</code>
        </span>
        <FilterChips filters={panel.query?.filters} />
        <IgnoredFilterChips keys={panel.query?.ignoredFilters} />
        <span className="dashboard-panel__empty-hint">Emit it to localhost:4318 to preview this panel.</span>
      </div>
    );
  }

  if (panel.chartType === "single_value") {
    const latest = allSeries.length > 0 ? allSeries[allSeries.length - 1].latest : 0;
    return (
      <div className="dashboard-panel__single-value">
        <span className="dashboard-panel__single-value-number">{formatNumber(latest)}</span>
        {allSeries.length > 1 ? (
          <span className="dashboard-panel__single-value-note">{allSeries.length} series · latest shown</span>
        ) : null}
      </div>
    );
  }

  if (panel.chartType === "list") {
    return (
      <table className="dashboard-panel__list">
        <tbody>
          {allSeries.map((s) => (
            <tr key={s.key}>
              <td className="dashboard-panel__list-label">{seriesLabel(s.resource?.serviceName, s.attributes)}</td>
              <td className="dashboard-panel__list-value">{formatNumber(s.latest)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (panel.chartType === "heatmap") {
    const latest = allSeries.length > 0 ? allSeries[allSeries.length - 1].latest : 0;
    return (
      <div className="dashboard-panel__single-value">
        <span className="dashboard-panel__single-value-number">{formatNumber(latest)}</span>
        <span className="dashboard-panel__single-value-note">heatmap shown as latest value (approximate)</span>
      </div>
    );
  }

  // time_series (and any unknown chart type) → the shared SVG chart.
  return (
    <TimeSeriesChart
      series={allSeries}
      displayType="lines"
      selectedKey={selectedKey}
      onSelectSeries={setSelectedKey}
      windowMs={windowMs}
    />
  );
}

const CHART_TYPE_LABELS: Record<string, string> = {
  time_series: "Time series",
  single_value: "Single value",
  list: "List",
  heatmap: "Heatmap",
  text: "Text",
  event: "Events",
};

function chartTypeLabel(t: string): string {
  return CHART_TYPE_LABELS[t] ?? t;
}

function FilterChips({ filters }: { filters?: Record<string, string[]> }): React.ReactElement | null {
  const entries = Object.entries(filters ?? {});
  if (entries.length === 0) return null;
  return (
    <div className="dashboard-panel__chips">
      {entries.map(([k, vs]) => (
        <span key={k} className="dashboard-panel__chip">
          {k}={vs.join(" | ")}
        </span>
      ))}
    </div>
  );
}

function IgnoredFilterChips({ keys }: { keys?: string[] }): React.ReactElement | null {
  if (!keys || keys.length === 0) return null;
  return (
    <div className="dashboard-panel__chips dashboard-panel__chips--ignored" title="These filter constraints could not be applied; the preview may match more series than the real dashboard.">
      {keys.map((k) => (
        <span key={k} className="dashboard-panel__chip dashboard-panel__chip--ignored">
          {k} (not applied)
        </span>
      ))}
    </div>
  );
}

function seriesLabel(serviceName: string | undefined, attributes: Record<string, unknown>): string {
  const attrs = Object.entries(attributes);
  const attrStr = attrs.length > 0 ? attrs.map(([k, v]) => `${k}=${v}`).join(", ") : "";
  if (serviceName) return attrStr ? `${serviceName} · ${attrStr}` : serviceName;
  return attrStr || "(no dimensions)";
}

function formatNumber(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(v % 1 === 0 ? 0 : 2);
}

/**
 * Window + type-aware + query-aware transform pipeline.
 *
 * Window: keep only points within the last windowMs (0 = all). Fresh Date.now()
 * on every call — no useMemo — so the cutoff stays current with the auto-refresh.
 *
 * Monotonic counter (type=sum, isMonotonic=true):
 *   Rate = Δvalue/Δt(s). Converts cumulative totals to msgs/s.
 *
 * UpDownCounter (type=sum, isMonotonic=false/null) + Gauge: plot raw value.
 *
 * Histogram (type=histogram): behaviour driven by query.aggregation:
 *   - "percentile" (query.percentile=N): linear-interpolation within the
 *     containing bucket over the *delta* bucket distribution each interval.
 *     This is how Splunk's .percentile(pct=N) works on histograms.
 *   - "mean": Δsum/Δcount per interval.
 *   - anything else (or no aggregation): Δsum/Δcount (mean, safe fallback).
 */
function usePreparedMetrics(groups: MetricGroup[], windowMs: number, query?: ParsedQuery): MetricGroup[] {
  const cutoffMs = windowMs > 0 ? Date.now() - windowMs : 0;

  return groups.map((g): MetricGroup => {
    const raw = (g.dataPoints ?? [])
      .filter((dp) => {
        if (!cutoffMs) return true;
        const t = new Date(dp.timeUnixNano).getTime();
        return !isNaN(t) && t >= cutoffMs;
      })
      .sort((a, b) => new Date(a.timeUnixNano).getTime() - new Date(b.timeUnixNano).getTime());

    const isMonotonicCounter = g.type === "sum" && raw.length > 0 && raw[0].isMonotonic === true;
    const isHistogram = g.type === "histogram";

    if (isMonotonicCounter) {
      const rateDps: MetricDataPoint[] = [];
      for (let i = 1; i < raw.length; i++) {
        const prev = raw[i - 1];
        const curr = raw[i];
        const dt = (new Date(curr.timeUnixNano).getTime() - new Date(prev.timeUnixNano).getTime()) / 1000;
        if (dt <= 0) continue;
        const rate = Math.max(0, ((curr.value ?? 0) - (prev.value ?? 0)) / dt);
        rateDps.push({ ...curr, value: rate });
      }
      return { ...g, dataPoints: rateDps };
    }

    if (isHistogram) {
      const agg = query?.aggregation ?? "mean";
      const pct = query?.percentile;

      const outDps: MetricDataPoint[] = [];
      for (let i = 1; i < raw.length; i++) {
        const prev = raw[i - 1];
        const curr = raw[i];
        const dCount = (curr.count ?? 0) - (prev.count ?? 0);
        if (dCount <= 0) continue;

        let value: number;
        if (agg === "percentile" && pct != null && curr.bucketCounts && curr.explicitBounds) {
          value = interpolatePercentile(
            curr.bucketCounts.map((c, j) => c - (prev.bucketCounts?.[j] ?? 0)),
            curr.explicitBounds,
            pct / 100,
          );
        } else {
          // mean fallback
          const dSum = (curr.sum ?? 0) - (prev.sum ?? 0);
          value = dSum / dCount;
        }
        outDps.push({ ...curr, value, sum: undefined, count: undefined });
      }
      return { ...g, dataPoints: outDps };
    }

    return { ...g, dataPoints: raw };
  }).filter((g) => (g.dataPoints ?? []).length > 0);
}

/**
 * Linear interpolation of a percentile from a histogram bucket delta distribution.
 * bounds has N-1 entries for N buckets (last bucket is +Inf).
 * frac is 0..1 (e.g. 0.99 for P99).
 */
function interpolatePercentile(deltaCounts: number[], bounds: number[], frac: number): number {
  const total = deltaCounts.reduce((s, c) => s + Math.max(0, c), 0);
  if (total <= 0) return 0;

  const target = frac * total;
  let cumulative = 0;
  for (let b = 0; b < deltaCounts.length; b++) {
    const count = Math.max(0, deltaCounts[b]);
    if (count <= 0) continue;
    const lo = b === 0 ? 0 : bounds[b - 1];
    const hi = b < bounds.length ? bounds[b] : bounds[bounds.length - 1] * 2; // +Inf bucket: double last bound
    const prev = cumulative;
    cumulative += count;
    if (cumulative >= target) {
      // Linear interpolate within this bucket.
      const fraction = count > 0 ? (target - prev) / count : 0;
      return lo + fraction * (hi - lo);
    }
  }
  // Should not reach here; return last upper bound as fallback.
  return bounds[bounds.length - 1];
}
