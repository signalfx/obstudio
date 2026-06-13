import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { TraceSummary, TraceDetail, ValidationFinding } from "../api/types";
import { fetchTraceDetail, fetchTraceFilterValues, fetchTraces, type TracesQuery } from "../api/client";
import { FilterBar, type FilterClause, type FilterDefinition } from "../FilterBar";
import { CopyTextButton, DetailPanel, ResizablePanel } from "../layout";
import { KVTable } from "../components/KVTable";
import { TraceWaterfall } from "./TraceWaterfall";
import { SpanDetailsPanel } from "./SpanDetailsPanel";
import { useKeyboardShortcuts } from "../hooks/useKeyboardShortcuts";
import type { ValidationIndex } from "../validation/utils";
import { lookupSpanValidation } from "../validation/utils";

interface TracesTabProps {
  traces: TraceSummary[];
  telemetryError: string | null;
  onInteract?: () => void;
  validationFindings: ValidationFinding[];
  validationIndex: ValidationIndex;
}

const TRACE_FILTER_DEFINITIONS: FilterDefinition[] = [
  { key: "serviceName", label: "Service", kind: "text", placeholder: "payments" },
  { key: "rootSpanName", label: "Root Span", kind: "text", placeholder: "POST /charge" },
  {
    key: "status",
    label: "Status",
    kind: "enum",
    options: [
      { label: "ok", value: "ok" },
      { label: "error", value: "error" },
      { label: "mixed", value: "mixed" },
      { label: "unset", value: "unset" },
    ],
  },
  { key: "traceId", label: "Trace ID", kind: "text", placeholder: "22222222222222222222222222222222" },
  { key: "minDurationMs", label: "Min Duration", kind: "number", placeholder: "100", chipLabel: "Min Duration", operatorLabels: { eq: ">=", neq: "<" } },
  { key: "maxDurationMs", label: "Max Duration", kind: "number", placeholder: "500", chipLabel: "Max Duration", operatorLabels: { eq: "<=", neq: ">" } },
  { key: "minSpanCount", label: "Min Span Count", kind: "number", placeholder: "1", chipLabel: "Min Span Count", operatorLabels: { eq: ">=", neq: "<" }, step: 1 },
  { key: "maxSpanCount", label: "Max Span Count", kind: "number", placeholder: "10", chipLabel: "Max Span Count", operatorLabels: { eq: "<=", neq: ">" }, step: 1 },
];
const TRACE_SUGGESTIBLE_FIELDS = new Set(["rootSpanName", "serviceName"]);
const TRACE_DETAIL_PANEL_DEFAULT_WIDTH = "min(1600px, calc(100vw - 320px))";
const TRACE_DETAIL_PANEL_MIN_WIDTH = 560;
const TRACE_DETAIL_PANEL_MAX_WIDTH = 1600;

function assignQueryFilter(query: TracesQuery, clause: FilterClause): void {
  const targetKey = clause.op === "neq" ? "notFilters" : "filters";
  query[targetKey] = { ...(query[targetKey] ?? {}), [clause.key]: clause.value };
}

function buildTracesQuery(clauses: FilterClause[]): TracesQuery {
  const query: TracesQuery = {};
  for (const clause of clauses) {
    switch (clause.key) {
      case "traceId":
      case "rootSpanName":
      case "serviceName":
      case "status":
        assignQueryFilter(query, clause);
        break;
      case "minSpanCount":
        query.ranges = {
          ...(query.ranges ?? {}),
          spanCount: {
            ...(query.ranges?.spanCount ?? {}),
            [clause.op === "neq" ? "lt" : "gte"]: clause.value,
          },
        };
        break;
      case "maxSpanCount":
        query.ranges = {
          ...(query.ranges ?? {}),
          spanCount: {
            ...(query.ranges?.spanCount ?? {}),
            [clause.op === "neq" ? "gt" : "lte"]: clause.value,
          },
        };
        break;
      case "minDurationMs":
        query.ranges = {
          ...(query.ranges ?? {}),
          durationMs: {
            ...(query.ranges?.durationMs ?? {}),
            [clause.op === "neq" ? "lt" : "gte"]: clause.value,
          },
        };
        break;
      case "maxDurationMs":
        query.ranges = {
          ...(query.ranges ?? {}),
          durationMs: {
            ...(query.ranges?.durationMs ?? {}),
            [clause.op === "neq" ? "gt" : "lte"]: clause.value,
          },
        };
        break;
      case "timeFrom":
        query.time = { ...(query.time ?? {}), [clause.op === "neq" ? "before" : "from"]: clause.value };
        break;
      case "timeTo":
        query.time = { ...(query.time ?? {}), [clause.op === "neq" ? "after" : "to"]: clause.value };
        break;
      default:
        break;
    }
  }
  return query;
}

/** Traces tab with virtualized table and waterfall detail panel. */
export function TracesTab({ traces, telemetryError, onInteract, validationFindings, validationIndex }: TracesTabProps): React.ReactElement {
  const [clauses, setClauses] = useState<FilterClause[]>([]);
  const [serverTraces, setServerTraces] = useState<TraceSummary[]>([]);
  const [isFiltering, setIsFiltering] = useState(false);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [traceDetail, setTraceDetail] = useState<TraceDetail | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const tableRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);

  const fetchIdRef = useRef(0);
  const traceDetailRef = useRef(traceDetail);
  traceDetailRef.current = traceDetail;
  const handleInteract = useCallback(() => {
    onInteract?.();
  }, [onInteract]);
  const activeQuery = useMemo(() => buildTracesQuery(clauses), [clauses]);
  const suggestTraceValues = useCallback((fieldKey: string, prefix: string, signal: AbortSignal) => {
    if (!TRACE_SUGGESTIBLE_FIELDS.has(fieldKey)) {
      return Promise.resolve<string[]>([]);
    }
    return fetchTraceFilterValues(fieldKey, prefix, buildTracesQuery(clauses.filter((clause) => clause.key !== fieldKey)), signal);
  }, [clauses]);
  const hasActiveFilter = clauses.length > 0;
  const liveTraces = Array.isArray(traces) ? traces : [];
  const visibleTraces = hasActiveFilter ? serverTraces : liveTraces;

  const loadTraceDetail = useCallback(async (traceId: string, mode: "panel" | "background" = "panel") => {
    const fetchId = ++fetchIdRef.current;
    if (mode === "panel") {
      setDetailLoading(true);
      setDetailError(null);
    }

    try {
      const detail = await fetchTraceDetail(traceId);
      if (fetchIdRef.current !== fetchId) return;
      setTraceDetail(detail);
      setDetailError(null);
    } catch {
      if (fetchIdRef.current !== fetchId) return;
      if (mode === "panel") {
        setSelectedTraceId(null);
        setTraceDetail(null);
        setDetailError(null);
      }
    } finally {
      if (mode === "panel" && fetchIdRef.current === fetchId) {
        setDetailLoading(false);
      }
    }
  }, []);

  const selectTrace = useCallback((traceId: string | null) => {
    fetchIdRef.current++;
    setSelectedTraceId(traceId);
    setSelectedSpanId(null);
    setTraceDetail(null);
    setDetailError(null);
    setDetailLoading(false);
    onInteract?.();
    if (traceId) {
      void loadTraceDetail(traceId, "panel");
    }
  }, [loadTraceDetail, onInteract]);

  const shortcuts = useMemo(() => ({
    Escape: () => {
      if (selectedSpanId) setSelectedSpanId(null);
      else if (selectedTraceId) selectTrace(null);
    },
  }), [selectedTraceId, selectedSpanId, selectTrace]);

  useKeyboardShortcuts(shortcuts);

  useEffect(() => {
    if (!hasActiveFilter) {
      setServerTraces([]);
      setIsFiltering(false);
      setFilterError(null);
      return;
    }

    const controller = new AbortController();
    setIsFiltering(true);
    fetchTraces(activeQuery, controller.signal)
      .then((nextTraces) => {
        if (controller.signal.aborted) return;
        setServerTraces(nextTraces);
        setFilterError(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setFilterError(error instanceof Error ? error.message : "Failed to filter traces");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsFiltering(false);
        }
      });

    return () => controller.abort();
  }, [activeQuery, hasActiveFilter, liveTraces]);

  // Invalidate detail when the selected trace is no longer in the list
  // (e.g., after live updates or store clear).
  // Re-fetch detail when the trace's span count changes (new spans arrived).
  const selectedSummary = visibleTraces.find((t) => t.traceId === selectedTraceId) ?? liveTraces.find((t) => t.traceId === selectedTraceId);
  useEffect(() => {
    if (!selectedTraceId) return;
    if (!selectedSummary) {
      // Trace disappeared from the list.
      fetchIdRef.current++;
      setSelectedTraceId(null);
      setTraceDetail(null);
      setSelectedSpanId(null);
      setDetailError(null);
      setDetailLoading(false);
      return;
    }
    // Trace still present — refresh detail if span count changed.
    if (traceDetailRef.current && selectedSummary.spanCount !== traceDetailRef.current.spanCount) {
      void loadTraceDetail(selectedTraceId, "background");
    }
  }, [loadTraceDetail, selectedTraceId, selectedSummary, liveTraces]);

  useEffect(() => {
    if (!selectedTraceId) return;
    if (!visibleTraces.some((trace) => trace.traceId === selectedTraceId)) {
      selectTrace(null);
    }
  }, [selectTrace, selectedTraceId, visibleTraces]);

  const virtualizer = useVirtualizer({
    count: visibleTraces.length,
    getScrollElement: () => tableRef.current,
    estimateSize: () => 36,
    overscan: 10,
  });

  const selectedSpan = traceDetail?.spans.find((s) => s.spanId === selectedSpanId) ?? null;
  const selectedSpanValidation = useMemo(
    () => (selectedSpan ? lookupSpanValidation(validationIndex, selectedSpan.traceId, selectedSpan.spanId)?.findings ?? [] : []),
    [selectedSpan, validationIndex],
  );
  const errorSpanCount = traceDetail?.spans.filter((s) => s.status.code === "ERROR").length ?? 0;

  const hasDetail = Boolean(selectedTraceId && (traceDetail || detailLoading || detailError));

  return (
    <section className="tab-panel" role="tabpanel">
      <div
        className={`signal-view signal-view--trace-detail${hasDetail ? " signal-view--with-panel" : ""}`}
        onPointerDownCapture={handleInteract}
      >
        <div className="signal-view__content">
          {liveTraces.length > 0 || hasActiveFilter ? (
            <div className="explorer__toolbar explorer__toolbar--controls">
              <FilterBar
                definitions={TRACE_FILTER_DEFINITIONS}
                clauses={clauses}
                onChange={setClauses}
                onSuggestValues={suggestTraceValues}
              />
            </div>
          ) : null}

          {filterError ? (
            <p className="explorer__status explorer__status--error">{filterError}</p>
          ) : null}

          {telemetryError ? (
            <p className="explorer__status explorer__status--error">{telemetryError}</p>
          ) : null}

          {liveTraces.length === 0 && !hasActiveFilter ? (
            <p className="explorer__status explorer__status--empty">No traces received yet. Send OTLP telemetry to port 4318 to begin exploring.</p>
          ) : isFiltering && hasActiveFilter && visibleTraces.length === 0 ? (
            <p className="explorer__status">Updating filtered traces...</p>
          ) : visibleTraces.length === 0 ? (
            <p className="explorer__status">No traces match the current filters.</p>
          ) : (
            <>
          <div ref={headRef} className="data-table__head data-table__head--traces data-table__head--left-cluster data-table__head--scroll-sync">
            <span className="data-table__th data-table__th--operation">Operation</span>
            <span className="data-table__th data-table__th--trace-id">Trace ID</span>
            <span className="data-table__th data-table__th--service">Service</span>
            <span className="data-table__th data-table__th--status">Status</span>
            <span className="data-table__th data-table__th--duration data-table__th--numeric">Duration</span>
            <span className="data-table__th data-table__th--spans data-table__th--numeric">Spans</span>
          </div>

          <div
            className="data-table__body"
            ref={tableRef}
            onScroll={(event) => {
              if (headRef.current) {
                headRef.current.scrollLeft = event.currentTarget.scrollLeft;
              }
            }}
          >
            <div className="data-table__body-inner data-table__body-inner--traces data-table__body-inner--scroll-sync" style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
              {virtualizer.getVirtualItems().map((vi) => {
                const t = visibleTraces[vi.index];
                if (!t) return null;
                const active = t.traceId === selectedTraceId;
                return (
                  <button
                    key={t.traceId}
                    className={`data-table__row data-table__row--traces ${active ? "data-table__row--active" : ""}`}
                    onClick={() => selectTrace(t.traceId)}
                    type="button"
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${vi.start}px)`,
                    }}
                    data-index={vi.index}
                    ref={virtualizer.measureElement}
                  >
                    <span className="data-table__td data-table__td--operation">
                      <span className="trace-row__operation explorer-row__primary">{t.rootSpanName}</span>
                    </span>
                    <span className="data-table__td data-table__td--trace-id">
                      <span className="trace-row__trace-id explorer-row__secondary">{t.traceId}</span>
                    </span>
                    <span className="data-table__td data-table__td--service">
                      <span className="trace-row__service explorer-row__secondary">{t.serviceName ?? "unknown"}</span>
                    </span>
                    <span className="data-table__td data-table__td--status">
                      <span className="trace-row__status">
                        <span className={`trace-status trace-status--${normalizeTraceStatusClass(t.status)}`}>{traceStatusLabel(t.status)}</span>
                      </span>
                    </span>
                    <span className="data-table__td data-table__td--duration data-table__td--numeric">
                      <span className="explorer-row__numeric">{formatTraceDuration(t.durationMs)}</span>
                    </span>
                    <span className="data-table__td data-table__td--spans data-table__td--numeric">
                      <span className="explorer-row__numeric">{t.spanCount}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
            </>
          )}
        </div>

        {/* Detail panel */}
        {selectedTraceId && traceDetail ? (
          <ResizablePanel
            className="signal-view__panel"
            defaultWidth={TRACE_DETAIL_PANEL_DEFAULT_WIDTH}
            minWidth={TRACE_DETAIL_PANEL_MIN_WIDTH}
            maxWidth={TRACE_DETAIL_PANEL_MAX_WIDTH}
            resizeLabel="Resize traces panel"
          >
            <DetailPanel
              title={traceDetail.rootSpanName}
              subtitle={`${traceDetail.spanCount} spans${errorSpanCount > 0 ? ` \u00B7 ${errorSpanCount} error${errorSpanCount > 1 ? "s" : ""}` : ""} \u00B7 ${formatTraceDuration(traceDetail.durationMs)}`}
              onClose={() => selectTrace(null)}
              footer={selectedSpan ? <SpanDetailsPanel span={selectedSpan} validationFindings={selectedSpanValidation} onClose={() => setSelectedSpanId(null)} /> : null}
            >
              <div className="trace-detail__summary">
                <KVTable rows={[{ key: "Trace ID", value: <span title={traceDetail.traceId}>{traceDetail.traceId}</span>, action: <CopyTextButton text={traceDetail.traceId} label="Trace ID" /> }]} />
              </div>
              <TraceWaterfall
                spans={traceDetail.spans}
                genAI={traceDetail.genAI ?? null}
                selectedSpanId={selectedSpanId}
                onSelectSpan={setSelectedSpanId}
                traceDurationMs={traceDetail.durationMs ?? 0}
                validationIndex={validationIndex}
              />
            </DetailPanel>
          </ResizablePanel>
        ) : selectedTraceId && detailLoading ? (
          <ResizablePanel
            className="signal-view__panel"
            defaultWidth={TRACE_DETAIL_PANEL_DEFAULT_WIDTH}
            minWidth={TRACE_DETAIL_PANEL_MIN_WIDTH}
            maxWidth={TRACE_DETAIL_PANEL_MAX_WIDTH}
            resizeLabel="Resize traces panel"
          >
            <DetailPanel title="Loading..." onClose={() => selectTrace(null)}>
              <p className="explorer__status">Fetching trace detail...</p>
            </DetailPanel>
          </ResizablePanel>
        ) : selectedTraceId && detailError ? (
          <ResizablePanel
            className="signal-view__panel"
            defaultWidth={TRACE_DETAIL_PANEL_DEFAULT_WIDTH}
            minWidth={TRACE_DETAIL_PANEL_MIN_WIDTH}
            maxWidth={TRACE_DETAIL_PANEL_MAX_WIDTH}
            resizeLabel="Resize traces panel"
          >
            <DetailPanel
              title="Trace detail unavailable"
              subtitle={selectedSummary?.rootSpanName ?? selectedTraceId.slice(-12)}
              onClose={() => selectTrace(null)}
            >
              <p className="explorer__status explorer__status--error">{detailError}</p>
              <button
                className="pill pill--muted"
                onClick={() => void loadTraceDetail(selectedTraceId, "panel")}
                type="button"
              >
                Retry
              </button>
            </DetailPanel>
          </ResizablePanel>
        ) : null}
      </div>
    </section>
  );
}

function formatTraceDuration(durationMs?: number): string {
  return `${(durationMs ?? 0).toFixed(1)}ms`;
}

export function traceStatusLabel(status: string): string | null {
  switch (status) {
    case "ok":
      return "ok";
    case "error":
      return "error";
    case "mixed":
      return "mixed";
    case "unset":
      return "unset";
    default:
      return "unknown";
  }
}

function normalizeTraceStatusClass(status: string): string {
  switch (status) {
    case "ok":
    case "error":
    case "mixed":
    case "unset":
      return status;
    default:
      return "unset";
  }
}
