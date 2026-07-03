import React from "react";
import type { MetricSeries } from "./useMetricTimeSeries";
import { TELEMETRY_SERIES_COLORS } from "../palette";

type DisplayType = "lines" | "bars" | "area";

interface TimeSeriesChartProps {
  series: MetricSeries[];
  displayType: DisplayType;
  selectedKey: string | null;
  onSelectSeries: (key: string) => void;
  /** When set, fixes the X-axis domain to [now - windowMs, now] so the
   *  time range matches the selected window regardless of data density. */
  windowMs?: number;
}

const CHART_W = 800;
const CHART_H = 240;
const PAD = { top: 10, right: 10, bottom: 36, left: 60 };

/** SVG time series chart supporting line, bar, and area display modes. */
export function TimeSeriesChart({ series, displayType, selectedKey, onSelectSeries, windowMs }: TimeSeriesChartProps): React.ReactElement {
  if (series.length === 0 || series.every((s) => s.points.length === 0)) {
    return (
      <div className="ts-chart--empty">
        <span>No data points to display.</span>
        <span className="ts-chart__hint">Waiting for metric data…</span>
      </div>
    );
  }

  const allPoints = series.flatMap((s) => s.points);
  const timestamps = allPoints.map((p) => new Date(p.timestamp).getTime()).filter((t) => !isNaN(t));
  const values = allPoints.map((p) => p.value);

  // When a windowMs is provided, fix the axis to [now - windowMs, now] so the
  // X-axis always spans the full selected window, matching O11y's behaviour.
  // NOTE: no useMemo — fresh Date.now() every render so the axis scrolls live.
  const now = Date.now();
  // Guard the spread to avoid Math.min/max of an empty array returning ±Infinity
  // when all timestamps are unparseable (#23).
  const minT = windowMs && windowMs > 0 ? now - windowMs : (timestamps.length > 0 ? Math.min(...timestamps) : now - 60_000);
  const maxT = windowMs && windowMs > 0 ? now : (timestamps.length > 0 ? Math.max(...timestamps) : now);

  const minV = Math.min(0, ...values);
  const maxV = Math.max(...values) || 1;
  const rangeT = maxT - minT || 1;
  const rangeV = maxV - minV || 1;

  const innerW = CHART_W - PAD.left - PAD.right;
  const innerH = CHART_H - PAD.top - PAD.bottom;

  function x(t: number): number {
    return PAD.left + ((t - minT) / rangeT) * innerW;
  }
  function y(v: number): number {
    return PAD.top + innerH - ((v - minV) / rangeV) * innerH;
  }

  return (
    <div className="ts-chart">
      <svg className="ts-chart__svg" viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="xMidYMid meet">
        {/* Grid lines + Y labels */}
        {[0, 0.25, 0.5, 0.75, 1].map((frac) => {
          const val = minV + frac * rangeV;
          const yPos = y(val);
          return (
            <g key={frac}>
              <line x1={PAD.left} x2={CHART_W - PAD.right} y1={yPos} y2={yPos} stroke="var(--border-soft)" strokeWidth={1} />
              <text x={PAD.left - 5} y={yPos + 4} className="ts-chart__axis-label" textAnchor="end">
                {formatValue(val)}
              </text>
            </g>
          );
        })}

        {/* X-axis time ticks */}
        {[0, 0.25, 0.5, 0.75, 1].map((frac) => {
          const t = minT + frac * rangeT;
          const xPos = x(t);
          const label = formatTime(t, rangeT);
          return (
            <g key={`xt-${frac}`}>
              <line x1={xPos} x2={xPos} y1={PAD.top + innerH} y2={PAD.top + innerH + 4} stroke="var(--border)" strokeWidth={1} />
              <text x={xPos} y={PAD.top + innerH + 16} className="ts-chart__axis-label" textAnchor="middle">
                {label}
              </text>
            </g>
          );
        })}

        {/* Series */}
        {series.map((s, si) => {
          const color = TELEMETRY_SERIES_COLORS[si % TELEMETRY_SERIES_COLORS.length];
          const opacity = selectedKey === null || selectedKey === s.key ? 1 : 0.2;
          const sorted = [...s.points]
            .map((p) => ({ x: x(new Date(p.timestamp).getTime()), y: y(p.value) }))
            .sort((a, b) => a.x - b.x);

          if (sorted.length === 0) return null;

          if (displayType === "bars") {
            const barW = Math.max(innerW / Math.max(allPoints.length, 1) - 2, 2);
            return (
              <g key={s.key} opacity={opacity} onClick={() => onSelectSeries(s.key)} style={{ cursor: "pointer" }}>
                {sorted.map((p, i) => (
                  <rect key={i} x={p.x - barW / 2} y={p.y} width={barW} height={y(minV) - p.y} fill={color} />
                ))}
              </g>
            );
          }

          const path = sorted.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");

          if (displayType === "area") {
            const areaPath = `${path} L${sorted[sorted.length - 1].x},${y(minV)} L${sorted[0].x},${y(minV)} Z`;
            return (
              <g key={s.key} opacity={opacity} onClick={() => onSelectSeries(s.key)} style={{ cursor: "pointer" }}>
                <path d={areaPath} fill={color} fillOpacity={0.15} />
                <path d={path} fill="none" stroke={color} strokeWidth={2} />
              </g>
            );
          }

          // lines (default)
          return (
            <g key={s.key} opacity={opacity} onClick={() => onSelectSeries(s.key)} style={{ cursor: "pointer" }}>
              <path d={path} fill="none" stroke={color} strokeWidth={2} />
              {sorted.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r={3} fill={color} />
              ))}
            </g>
          );
        })}
      </svg>

      {/* Series annotations */}
      <div className="ts-chart__annotations">
        {series.map((s, si) => {
          const color = TELEMETRY_SERIES_COLORS[si % TELEMETRY_SERIES_COLORS.length];
          const attrs = Object.entries(s.attributes);
          const svcName = s.resource?.serviceName;
          const attrStr = attrs.length > 0 ? attrs.map(([k, v]) => `${k}=${v}`).join(", ") : "";
          const label = svcName ? (attrStr ? `${svcName} · ${attrStr}` : svcName) : (attrStr || "(no dimensions)");
          const isActive = selectedKey === s.key;
          const isDimmed = selectedKey !== null && selectedKey !== s.key;

          return (
            <button
              key={s.key}
              className={`ts-chart__annotation ${isActive ? "ts-chart__annotation--active" : ""} ${isDimmed ? "ts-chart__annotation--dimmed" : ""}`}
              onClick={() => onSelectSeries(s.key)}
              type="button"
            >
              <span className="ts-chart__annotation-dot" style={{ background: color }} />
              <span className="ts-chart__annotation-label">{label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function formatValue(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(v % 1 === 0 ? 0 : 1);
}

function formatTime(ts: number, rangeMs: number): string {
  const d = new Date(ts);
  if (rangeMs < 90_000) {
    // < 90s: show HH:MM:SS
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  }
  if (rangeMs < 3_600_000) {
    // < 1h: show HH:MM
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  // longer: show MM/DD HH:MM
  return `${d.getMonth() + 1}/${d.getDate()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}
