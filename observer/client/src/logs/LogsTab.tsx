import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { LogRecord } from "../api/types";
import { fetchLogFilterValues, fetchLogs, type LogsQuery } from "../api/client";
import { FilterBar, type FilterClause, type FilterDefinition } from "../FilterBar";
import { CopyTextButton, DetailPanel, ResizablePanel } from "../layout";

interface LogsTabProps {
  logs: LogRecord[];
  onInteract?: () => void;
}

type DetailTab = "overview" | "json";
const LOG_FILTER_DEFINITIONS: FilterDefinition[] = [
  { key: "serviceName", label: "Service", kind: "text", placeholder: "payments" },
  {
    key: "severityText",
    label: "Severity",
    kind: "enum",
    options: [
      { label: "TRACE", value: "TRACE" },
      { label: "DEBUG", value: "DEBUG" },
      { label: "INFO", value: "INFO" },
      { label: "WARN", value: "WARN" },
      { label: "ERROR", value: "ERROR" },
      { label: "FATAL", value: "FATAL" },
    ],
  },
  { key: "bodyContains", label: "Message", kind: "text", placeholder: "payment failed", chipLabel: "Message" },
  { key: "traceId", label: "Trace ID", kind: "text", placeholder: "22222222222222222222222222222222" },
  { key: "spanId", label: "Span ID", kind: "text", placeholder: "bbbbbbbbbbbbbbbb" },
  { key: "scopeName", label: "Scope", kind: "text", placeholder: "demo.logs" },
  { key: "severityNumber", label: "Severity Number", kind: "number", placeholder: "17", step: 1 },
];
const LOG_SUGGESTIBLE_FIELDS = new Set(["serviceName", "scopeName"]);

function assignQueryFilter(query: LogsQuery, clause: FilterClause): void {
  const targetKey = clause.op === "neq" ? "notFilters" : "filters";
  query[targetKey] = { ...(query[targetKey] ?? {}), [clause.key]: clause.value };
}

function buildLogsQuery(clauses: FilterClause[]): LogsQuery {
  const query: LogsQuery = {};
  for (const clause of clauses) {
    switch (clause.key) {
      case "serviceName":
      case "severityText":
      case "severityNumber":
      case "bodyContains":
      case "traceId":
      case "spanId":
      case "scopeName":
        assignQueryFilter(query, clause);
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

function severityClass(sev: string): string {
  const s = sev.toUpperCase();
  if (s.includes("ERROR") || s.includes("FATAL")) return "error";
  if (s.includes("WARN")) return "warn";
  if (s.includes("INFO")) return "info";
  if (s.includes("DEBUG") || s.includes("TRACE")) return "debug";
  return "default";
}

function logKey(r: LogRecord): string {
  return r.id || `${r.timeUnixNano}|${r.resource?.serviceName ?? ""}|${r.severityText ?? ""}|${r.body}`;
}

/** Logs tab with virtualized table and detail panel for selected log records. */
export function LogsTab({ logs, onInteract }: LogsTabProps): React.ReactElement {
  const [clauses, setClauses] = useState<FilterClause[]>([]);
  const [serverLogs, setServerLogs] = useState<LogRecord[]>([]);
  const [isFiltering, setIsFiltering] = useState(false);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [selectedLog, setSelectedLog] = useState<LogRecord | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const tableRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);

  const selectedKey = useMemo(() => selectedLog ? logKey(selectedLog) : null, [selectedLog]);
  const activeQuery = useMemo(() => buildLogsQuery(clauses), [clauses]);
  const suggestLogValues = useCallback((fieldKey: string, prefix: string, signal: AbortSignal) => {
    if (!LOG_SUGGESTIBLE_FIELDS.has(fieldKey)) {
      return Promise.resolve<string[]>([]);
    }
    return fetchLogFilterValues(fieldKey, prefix, buildLogsQuery(clauses.filter((clause) => clause.key !== fieldKey)), signal);
  }, [clauses]);
  const hasActiveFilter = clauses.length > 0;
  const liveLogs = Array.isArray(logs) ? logs : [];
  const visibleLogs = hasActiveFilter ? serverLogs : liveLogs;
  const handleInteract = useCallback(() => {
    onInteract?.();
  }, [onInteract]);

  useEffect(() => {
    if (!hasActiveFilter) {
      setServerLogs([]);
      setIsFiltering(false);
      setFilterError(null);
      return;
    }

    const controller = new AbortController();
    setIsFiltering(true);
    fetchLogs(activeQuery, controller.signal)
      .then((nextLogs) => {
        if (controller.signal.aborted) return;
        setServerLogs(nextLogs);
        setFilterError(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setFilterError(error instanceof Error ? error.message : "Failed to filter logs");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsFiltering(false);
        }
      });

    return () => controller.abort();
  }, [activeQuery, hasActiveFilter, liveLogs]);

  // Invalidate selection when the selected log is no longer in the snapshot
  // (e.g., after store clear, WebSocket reconnect, or eviction from the buffer).
  useEffect(() => {
    if (selectedKey && !liveLogs.some((r) => logKey(r) === selectedKey)) {
      setSelectedLog(null);
    }
  }, [liveLogs, selectedKey]);

  useEffect(() => {
    if (selectedKey && !visibleLogs.some((record) => logKey(record) === selectedKey)) {
      setSelectedLog(null);
    }
  }, [selectedKey, visibleLogs]);

  const virtualizer = useVirtualizer({
    count: visibleLogs.length,
    getScrollElement: () => tableRef.current,
    estimateSize: () => 36,
    overscan: 10,
  });

  return (
    <section className="tab-panel" role="tabpanel">
      <div
        className={`signal-view${selectedLog ? " signal-view--with-panel" : ""}`}
        onPointerDownCapture={handleInteract}
      >
        <div className="signal-view__content">
          {liveLogs.length > 0 || hasActiveFilter ? (
            <div className="explorer__toolbar explorer__toolbar--controls">
              <FilterBar
                definitions={LOG_FILTER_DEFINITIONS}
                clauses={clauses}
                onChange={setClauses}
                onSuggestValues={suggestLogValues}
              />
            </div>
          ) : null}

          {filterError ? (
            <p className="explorer__status explorer__status--error">{filterError}</p>
          ) : liveLogs.length === 0 && !hasActiveFilter ? (
            <p className="explorer__status explorer__status--empty">No logs received yet. Send OTLP telemetry to port 4318 to begin exploring.</p>
          ) : isFiltering && hasActiveFilter && visibleLogs.length === 0 ? (
            <p className="explorer__status">Updating filtered logs...</p>
          ) : visibleLogs.length === 0 ? (
            <p className="explorer__status">No logs match the current filters.</p>
          ) : (
            <>
          <div
            ref={headRef}
            className="data-table__head data-table__head--logs data-table__head--left-cluster data-table__head--left-cluster-logs data-table__head--scroll-sync"
          >
            <span className="data-table__th data-table__th--severity">Level</span>
            <span className="data-table__th data-table__th--timestamp">Timestamp</span>
            <span className="data-table__th data-table__th--service">Service</span>
            <span className="data-table__th data-table__th--message">Message</span>
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
            <div className="data-table__body-inner data-table__body-inner--logs data-table__body-inner--scroll-sync" style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
              {virtualizer.getVirtualItems().map((vi) => {
                const r = visibleLogs[vi.index];
                if (!r) return null;
                const active = selectedKey !== null && logKey(r) === selectedKey;
                const cls = severityClass(r.severityText ?? "");
                return (
                  <button
                    key={logKey(r)}
                    className={`data-table__row data-table__row--logs data-table__row--sev-${cls} ${active ? "data-table__row--active" : ""}`}
                    onClick={() => {
                      setSelectedLog(r);
                      setDetailTab("overview");
                      onInteract?.();
                    }}
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
                    <span className={`data-table__td data-table__td--severity sev-badge sev-badge--${cls}`}>
                      {r.severityText ?? "--"}
                    </span>
                    <span className="data-table__td data-table__td--timestamp">
                      <span className="explorer-row__secondary">{formatTimestamp(r.timeUnixNano)}</span>
                    </span>
                    <span className="data-table__td data-table__td--service">
                      <span className="explorer-row__secondary">{r.resource?.serviceName ?? "unknown"}</span>
                    </span>
                    <span className="data-table__td data-table__td--message">
                      <span className="explorer-row__primary">{r.body}</span>
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
        {selectedLog ? (
          <ResizablePanel className="signal-view__panel" resizeLabel="Resize logs panel">
            <DetailPanel
              title={selectedLog.severityText ?? "LOG"}
              subtitle={selectedLog.resource?.serviceName}
              onClose={() => setSelectedLog(null)}
            >
              <div className="span-details__tabs">
                <button
                  className={`span-details__tab ${detailTab === "overview" ? "span-details__tab--active" : ""}`}
                  onClick={() => setDetailTab("overview")}
                  type="button"
                >
                  Overview
                </button>
                <button
                  className={`span-details__tab ${detailTab === "json" ? "span-details__tab--active" : ""}`}
                  onClick={() => setDetailTab("json")}
                  type="button"
                >
                  JSON
                </button>
              </div>

              {detailTab === "overview" ? (
                <div className="log-detail">
                  <div className="log-detail__section">
                    <h4 className="log-detail__heading">Message</h4>
                    <pre className="log-detail__body">{selectedLog.body}</pre>
                  </div>

                  {selectedLog.traceId ? (
                    <div className="log-detail__section">
                      <h4 className="log-detail__heading">Trace Correlation</h4>
                      <div className="span-details__detail-row">
                        <span className="span-details__detail-label">Trace ID</span>
                        <span className="span-details__detail-value">
                          <span title={selectedLog.traceId}>{selectedLog.traceId}</span>
                          <CopyTextButton text={selectedLog.traceId} label="Trace ID" />
                        </span>
                      </div>
                      {selectedLog.spanId ? (
                        <div className="span-details__detail-row">
                          <span className="span-details__detail-label">Span ID</span>
                          <span className="span-details__detail-value">
                            <span title={selectedLog.spanId}>{selectedLog.spanId}</span>
                            <CopyTextButton text={selectedLog.spanId} label="Span ID" />
                          </span>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {selectedLog.resource ? (
                    <div className="log-detail__section">
                      <h4 className="log-detail__heading">Resource</h4>
                      {selectedLog.resource.serviceName ? (
                        <div className="span-details__detail-row">
                          <span className="span-details__detail-label">Service</span>
                          <span className="span-details__detail-value">{selectedLog.resource.serviceName}</span>
                        </div>
                      ) : null}
                      {Object.keys(selectedLog.resource?.attributes ?? {}).length > 0 ? (
                        <table className="log-detail__attrs">
                          <tbody>
                            {Object.entries(selectedLog.resource?.attributes ?? {}).map(([k, v]) => (
                              <tr key={k}>
                                <td className="log-detail__attr-key">{k}</td>
                                <td className="log-detail__attr-val">{String(v)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : null}
                    </div>
                  ) : null}

                  {selectedLog.scope?.name ? (
                    <div className="log-detail__section">
                      <h4 className="log-detail__heading">Scope</h4>
                      <div className="span-details__detail-row">
                        <span className="span-details__detail-label">Name</span>
                        <span className="span-details__detail-value">
                          {selectedLog.scope.name}
                          {selectedLog.scope.version ? ` v${selectedLog.scope.version}` : ""}
                        </span>
                      </div>
                    </div>
                  ) : null}

                  <div className="log-detail__section">
                    <h4 className="log-detail__heading">Attributes</h4>
                    {Object.keys(selectedLog.attributes ?? {}).length > 0 ? (
                      <table className="log-detail__attrs">
                        <tbody>
                          {Object.entries(selectedLog.attributes ?? {}).map(([k, v]) => (
                            <tr key={k}>
                              <td className="log-detail__attr-key">{k}</td>
                              <td className="log-detail__attr-val">{String(v)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <p className="log-detail__empty">No attributes</p>
                    )}
                  </div>
                </div>
              ) : (
                <div className="log-detail">
                  <div className="log-detail__section">
                    <pre className="log-detail__body">{JSON.stringify(selectedLog, null, 2)}</pre>
                  </div>
                </div>
              )}
            </DetailPanel>
          </ResizablePanel>
        ) : null}
      </div>
    </section>
  );
}

function formatTimestamp(ts: string): string {
  if (!ts) return "--";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "--";
  return d.toISOString().slice(11, 23);
}
