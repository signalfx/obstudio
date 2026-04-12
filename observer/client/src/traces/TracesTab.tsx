import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { TraceSummary, TraceDetail } from "../api/types";
import { fetchTraceDetail } from "../api/client";
import { DetailPanel } from "../layout";
import { TraceWaterfall } from "./TraceWaterfall";
import { SpanDetailsPanel } from "./SpanDetailsPanel";
import { useKeyboardShortcuts } from "../hooks/useKeyboardShortcuts";

interface TracesTabProps {
  traces: TraceSummary[];
  telemetryError: string | null;
  onInteract?: () => void;
}

/** Traces tab with virtualized table and waterfall detail panel. */
export function TracesTab({ traces, telemetryError, onInteract }: TracesTabProps): React.ReactElement {
  const [query, setQuery] = useState("");
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [traceDetail, setTraceDetail] = useState<TraceDetail | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const tableRef = useRef<HTMLDivElement>(null);

  const fetchIdRef = useRef(0);
  const traceDetailRef = useRef(traceDetail);
  traceDetailRef.current = traceDetail;
  const handleInteract = useCallback(() => {
    onInteract?.();
  }, [onInteract]);

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

  const filteredTraces = useMemo(() => {
    const trimmedQuery = query.trim().toLowerCase();
    if (!trimmedQuery) {
      return traces;
    }
    return traces.filter((trace) => {
      const haystack = [trace.traceId, trace.serviceName ?? "", trace.rootSpanName, trace.status].join(" ").toLowerCase();
      return haystack.includes(trimmedQuery);
    });
  }, [query, traces]);

  // Invalidate detail when the selected trace is no longer in the list
  // (e.g., after live updates or store clear).
  // Re-fetch detail when the trace's span count changes (new spans arrived).
  const selectedSummary = filteredTraces.find((t) => t.traceId === selectedTraceId) ?? traces.find((t) => t.traceId === selectedTraceId);
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
  }, [loadTraceDetail, selectedTraceId, selectedSummary, traces]);

  useEffect(() => {
    if (!selectedTraceId) return;
    if (!filteredTraces.some((trace) => trace.traceId === selectedTraceId)) {
      selectTrace(null);
    }
  }, [filteredTraces, selectTrace, selectedTraceId]);

  const virtualizer = useVirtualizer({
    count: filteredTraces.length,
    getScrollElement: () => tableRef.current,
    estimateSize: () => 36,
    overscan: 10,
  });

  const selectedSpan = traceDetail?.spans.find((s) => s.spanId === selectedSpanId) ?? null;
  const errorSpanCount = traceDetail?.spans.filter((s) => s.status.code === "ERROR").length ?? 0;

  const hasDetail = Boolean(selectedTraceId && (traceDetail || detailLoading || detailError));

  return (
    <section className="tab-panel" role="tabpanel">
      <div
        className={`signal-view${hasDetail ? " signal-view--with-panel" : ""}`}
        onPointerDownCapture={handleInteract}
      >
        <div className="signal-view__content">
          {traces.length > 0 ? (
            <div className="explorer__toolbar explorer__toolbar--controls">
              <span className="explorer__count">{filteredTraces.length} traces</span>
              <input
                className="explorer__input"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search operation, trace ID, service, or status"
              />
            </div>
          ) : null}

          {telemetryError ? (
            <p className="explorer__status explorer__status--error">{telemetryError}</p>
          ) : null}

          {traces.length === 0 ? (
            <p className="explorer__status">Waiting for traces... Send OTLP data to port 4318.</p>
          ) : filteredTraces.length === 0 ? (
            <p className="explorer__status">No traces match the current search.</p>
          ) : (
            <>
          <div className="data-table__head data-table__head--traces data-table__head--left-cluster">
            <span className="data-table__th data-table__th--operation">Operation</span>
            <span className="data-table__th data-table__th--trace-id">Trace ID</span>
            <span className="data-table__th data-table__th--service">Service</span>
            <span className="data-table__th data-table__th--status">Status</span>
            <span className="data-table__th data-table__th--duration data-table__th--numeric">Duration</span>
            <span className="data-table__th data-table__th--spans data-table__th--numeric">Spans</span>
          </div>

          <div className="data-table__body" ref={tableRef}>
            <div className="data-table__body-inner data-table__body-inner--traces" style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
              {virtualizer.getVirtualItems().map((vi) => {
                const t = filteredTraces[vi.index];
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
                        <span className={`trace-status trace-status--plain trace-status--${normalizeTraceStatusClass(t.status)}`}>{traceStatusLabel(t.status)}</span>
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
          <div className="signal-view__panel">
            <DetailPanel
              title={traceDetail.rootSpanName}
              subtitle={`${traceDetail.spanCount} spans${errorSpanCount > 0 ? ` \u00B7 ${errorSpanCount} error${errorSpanCount > 1 ? "s" : ""}` : ""} \u00B7 ${formatTraceDuration(traceDetail.durationMs)}`}
              onClose={() => selectTrace(null)}
            >
              <TraceWaterfall
                spans={traceDetail.spans}
                selectedSpanId={selectedSpanId}
                onSelectSpan={setSelectedSpanId}
                traceDurationMs={traceDetail.durationMs ?? 0}
              />
              {selectedSpan ? <SpanDetailsPanel span={selectedSpan} /> : null}
            </DetailPanel>
          </div>
        ) : selectedTraceId && detailLoading ? (
          <div className="signal-view__panel">
            <DetailPanel title="Loading..." onClose={() => selectTrace(null)}>
              <p className="explorer__status">Fetching trace detail...</p>
            </DetailPanel>
          </div>
        ) : selectedTraceId && detailError ? (
          <div className="signal-view__panel">
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
          </div>
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
