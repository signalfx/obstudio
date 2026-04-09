import React, { useState, useMemo } from "react";
import type { Span } from "../api/types";
import { buildWaterfallTree, flattenTree, type WaterfallSpan } from "./waterfall-layout";

interface TraceWaterfallProps {
  spans: Span[];
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
  traceDurationMs: number;
}

// Consistent service colors — same service always gets same color
const SERVICE_COLORS = [
  "#4fc1ff", "#4ec9b0", "#c586c0", "#dcdcaa", "#ce9178",
  "#569cd6", "#d16969", "#89d185", "#b5cea8", "#d7ba7d",
];

function getServiceColorMap(spans: Span[]): Map<string, string> {
  const map = new Map<string, string>();
  let idx = 0;
  for (const s of spans) {
    const svc = s.resource?.serviceName ?? "unknown";
    if (!map.has(svc)) {
      map.set(svc, SERVICE_COLORS[idx % SERVICE_COLORS.length]);
      idx++;
    }
  }
  return map;
}

/** Renders a collapsible span waterfall with timing bars and service colors. */
export function TraceWaterfall({ spans, selectedSpanId, onSelectSpan, traceDurationMs }: TraceWaterfallProps): React.ReactElement {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const serviceColors = useMemo(() => getServiceColorMap(spans), [spans]);

  const roots = buildWaterfallTree(spans);
  const flat = flattenTree(roots).filter((s) => {
    let parent = spans.find((p) => p.spanId === s.parentSpanId);
    while (parent) {
      if (collapsed.has(parent.spanId)) return false;
      parent = spans.find((p) => p.spanId === parent!.parentSpanId);
    }
    return true;
  });

  const toggleCollapse = (e: React.MouseEvent, spanId: string) => {
    e.stopPropagation();
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(spanId) ? next.delete(spanId) : next.add(spanId);
      return next;
    });
  };

  const traceStartMs = spans.length > 0
    ? Math.min(...spans.map((s) => new Date(s.startTimeUnixNano).getTime()))
    : 0;

  // Count error spans
  const errorCount = spans.filter((s) => s.status.code === "ERROR").length;

  return (
    <div className="waterfall">
      {/* Waterfall header with trace metadata */}
      <div className="waterfall__header">
        <div className="waterfall__header-left">
          <span className="waterfall__span-count">{spans.length} spans</span>
          {errorCount > 0 ? (
            <span className="trace-status trace-status--error">{errorCount} error{errorCount > 1 ? "s" : ""}</span>
          ) : null}
        </div>
        <div className="waterfall__header-right">
          <span className="waterfall__duration">{traceDurationMs.toFixed(1)}ms</span>
        </div>
      </div>

      <div className="waterfall__timeline-header">
        <div className="waterfall__col-service">Service / Operation</div>
        <div className="waterfall__col-timeline">
          <span>0ms</span>
          <span>{traceDurationMs.toFixed(0)}ms</span>
        </div>
      </div>
      <div className="waterfall__rows">
        {flat.map((s) => {
          const startMs = new Date(s.startTimeUnixNano).getTime() - traceStartMs;
          const leftPct = traceDurationMs > 0 ? (startMs / traceDurationMs) * 100 : 0;
          const widthPct = traceDurationMs > 0 ? Math.max((s.durationMs / traceDurationMs) * 100, 0.5) : 100;
          const isError = s.status.code === "ERROR";
          const hasChildren = s.children.length > 0;
          const svcColor = serviceColors.get(s.resource?.serviceName ?? "unknown") ?? SERVICE_COLORS[0];
          const childCount = countDescendants(s);

          return (
            <div
              key={s.spanId}
              className={`waterfall__row ${s.spanId === selectedSpanId ? "waterfall__row--selected" : ""}`}
              onClick={() => onSelectSpan(s.spanId)}
            >
              <div className="waterfall__row-service" style={{ paddingLeft: `${8 + s.depth * 16}px` }}>
                {hasChildren ? (
                  <button className="waterfall__toggle" onClick={(e) => toggleCollapse(e, s.spanId)} type="button">
                    {collapsed.has(s.spanId) ? "\u25B6" : "\u25BC"}
                    {collapsed.has(s.spanId) ? (
                      <span className="waterfall__child-count">{childCount}</span>
                    ) : null}
                  </button>
                ) : (
                  <span className="waterfall__toggle-spacer" />
                )}
                <span className="waterfall__service-dot" style={{ background: svcColor }} />
                <span className="waterfall__service-name">{s.resource?.serviceName ?? ""}</span>
                <span className="waterfall__span-name">{s.name}</span>
              </div>
              <div className="waterfall__row-timeline">
                <div
                  className="waterfall__bar"
                  style={{
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    background: isError
                      ? "rgba(244, 135, 113, 0.5)"
                      : hexToRgba(svcColor, 0.5),
                    borderColor: isError
                      ? "rgba(244, 135, 113, 0.7)"
                      : hexToRgba(svcColor, 0.7),
                    borderWidth: "1px",
                    borderStyle: "solid",
                  }}
                >
                  <span className="waterfall__bar-label">{s.durationMs.toFixed(1)}ms</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function countDescendants(span: WaterfallSpan): number {
  let count = span.children.length;
  for (const child of span.children) {
    count += countDescendants(child);
  }
  return count;
}

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
