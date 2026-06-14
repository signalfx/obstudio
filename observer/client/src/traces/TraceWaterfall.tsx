import React, { useState, useMemo } from "react";
import type { GenAITraceSummary, Span } from "../api/types";
import { buildWaterfallTree, flattenTree, type WaterfallSpan } from "./waterfall-layout";
import { ValidationBadge } from "../components/ValidationBadge";
import type { ValidationIndex } from "../validation/utils";
import { lookupSpanValidation } from "../validation/utils";
import { TELEMETRY_SERIES_COLORS } from "../palette";
import { GenAITraceOverview } from "./GenAITraceOverview";
import { formatEvaluationName, getSpanEvaluations } from "./genai-evaluations";

type GenAISpanFilterType = "security" | "privacy" | "llm" | "tool" | "loop" | "quality";

interface TraceWaterfallProps {
  spans: Span[];
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string | null) => void;
  traceDurationMs: number;
  validationIndex: ValidationIndex;
  genAI?: GenAITraceSummary | null;
}

// Consistent service colors — same service always gets same color
function getServiceColorMap(spans: Span[]): Map<string, string> {
  const map = new Map<string, string>();
  let idx = 0;
  for (const s of spans) {
    const svc = s.resource?.serviceName ?? "unknown";
    if (!map.has(svc)) {
      map.set(svc, TELEMETRY_SERIES_COLORS[idx % TELEMETRY_SERIES_COLORS.length]);
      idx++;
    }
  }
  return map;
}

/** Renders a collapsible span waterfall with timing bars and service colors. */
export function TraceWaterfall({ spans, selectedSpanId, onSelectSpan, traceDurationMs, validationIndex, genAI }: TraceWaterfallProps): React.ReactElement {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [genAISpanFilter, setGenAISpanFilter] = useState<{ type: GenAISpanFilterType; spanIds: string[] } | null>(null);

  const serviceColors = useMemo(() => getServiceColorMap(spans), [spans]);
  const evaluationsBySpanId = useMemo(() => {
    const result = new Map<string, ReturnType<typeof getSpanEvaluations>>();
    for (const span of spans) {
      const evaluations = getSpanEvaluations(span);
      if (evaluations.length > 0) {
        result.set(span.spanId, evaluations);
      }
    }
    return result;
  }, [spans]);

  const roots = buildWaterfallTree(spans);
  const allFlat = flattenTree(roots);
  const collapsedFlat = allFlat.filter((s) => {
    let parent = spans.find((p) => p.spanId === s.parentSpanId);
    while (parent) {
      if (collapsed.has(parent.spanId)) return false;
      parent = spans.find((p) => p.spanId === parent!.parentSpanId);
    }
    return true;
  });
  const filteredSpanIds = genAISpanFilter ? new Set(genAISpanFilter.spanIds) : null;
  const flat = filteredSpanIds ? allFlat.filter((s) => filteredSpanIds.has(s.spanId)) : collapsedFlat;
  const selectedSpanVisible = selectedSpanId ? flat.some((s) => s.spanId === selectedSpanId) : false;

  const applyGenAISpanFilter = (type: GenAISpanFilterType, spanIds: string[]) => {
    setGenAISpanFilter({ type, spanIds });
    setCollapsed(new Set());
    onSelectSpan(null);
  };

  const clearGenAISpanFilter = () => {
    setGenAISpanFilter(null);
  };

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
      <GenAITraceOverview
        summary={genAI ?? null}
        selectedSpanId={selectedSpanId}
        onSelectSpan={onSelectSpan}
        onApplySpanFilter={applyGenAISpanFilter}
        validationIndex={validationIndex}
      />

      {/* Waterfall header with trace metadata */}
      <div className="waterfall__header">
        <div className="waterfall__header-left">
          <span className="waterfall__span-count">
            {genAISpanFilter ? `${flat.length} / ${spans.length} spans` : `${spans.length} spans`}
          </span>
          {errorCount > 0 ? (
            <span className="trace-status trace-status--error">{errorCount} error{errorCount > 1 ? "s" : ""}</span>
          ) : null}
          {genAISpanFilter ? (
            <button className="waterfall__filter-chip" type="button" onClick={clearGenAISpanFilter}>
              {formatGenAISpanFilterLabel(genAISpanFilter.type)}: {flat.length}
              <span aria-hidden="true">×</span>
            </button>
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
          const svcColor = serviceColors.get(s.resource?.serviceName ?? "unknown") ?? TELEMETRY_SERIES_COLORS[0];
          const childCount = countDescendants(s);
          const validation = lookupSpanValidation(validationIndex, s.traceId, s.spanId);
          const evaluations = evaluationsBySpanId.get(s.spanId) ?? [];
          const failedEvaluations = evaluations.filter((evaluation) => !evaluation.passed);

          return (
            <div
              key={s.spanId}
              className={`waterfall__row ${s.spanId === selectedSpanId && selectedSpanVisible ? "waterfall__row--selected" : ""}`}
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
                {failedEvaluations.length > 0 ? (
                  <span className="waterfall__ai-chip waterfall__ai-chip--issue" data-tooltip={formatEvaluationTooltip(failedEvaluations)}>
                    <span className="waterfall__ai-chip-label">{formatWaterfallEvaluationChipLabel(failedEvaluations)}</span>
                  </span>
                ) : evaluations.length > 0 ? (
                  <span className="waterfall__ai-chip waterfall__ai-chip--ok" data-tooltip="No quality issues">
                    <span className="waterfall__ai-chip-label">Quality</span>
                  </span>
                ) : null}
                <ValidationBadge count={validation?.count ?? 0} severity={validation?.highestSeverity ?? null} />
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

function formatWaterfallEvaluationChipLabel(evaluations: ReturnType<typeof getSpanEvaluations>): string {
  const firstName = evaluations[0]?.name ? formatEvaluationName(evaluations[0].name) : "Quality";
  return evaluations.length > 1 ? `${firstName}...(+${evaluations.length - 1})` : firstName;
}

function formatEvaluationTooltip(evaluations: ReturnType<typeof getSpanEvaluations>): string {
  if (evaluations.length === 1) {
    return `${formatEvaluationName(evaluations[0].name)} quality issue`;
  }
  return `${evaluations.length} quality issues: ${evaluations.map((evaluation) => formatEvaluationName(evaluation.name)).join(", ")}`;
}

function countDescendants(span: WaterfallSpan): number {
  let count = span.children.length;
  for (const child of span.children) {
    count += countDescendants(child);
  }
  return count;
}

function formatGenAISpanFilterLabel(type: GenAISpanFilterType): string {
  switch (type) {
    case "security":
      return "Security risk spans";
    case "privacy":
      return "Privacy risk spans";
    case "llm":
      return "LLM call spans";
    case "tool":
      return "Tool call spans";
    case "loop":
      return "Loop spans";
    case "quality":
      return "Quality issue spans";
  }
}

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
