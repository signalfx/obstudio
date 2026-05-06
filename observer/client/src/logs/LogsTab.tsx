import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { LogRecord } from "../api/types";
import { fetchLogFilterValues, fetchLogs, type LogsQuery } from "../api/client";
import { FilterBar, type FilterClause, type FilterDefinition } from "../FilterBar";
import { CopyTextButton, DetailPanel, ResizablePanel } from "../layout";
import { KVTable } from "../components/KVTable";

interface LogsTabProps {
  logs: LogRecord[];
  onInteract?: () => void;
}

type DetailTab = "overview" | "json";
type SeverityBucket = "error" | "warn" | "info" | "debug" | "default";
type SeverityFilterValue = "" | "trace" | "debug" | "info" | "warn" | "error" | "fatal";
const LOG_FILTER_DEFINITIONS: FilterDefinition[] = [
  { key: "serviceName", label: "Service", kind: "text", placeholder: "payments" },
  { key: "severityDisplay", label: "Severity", kind: "text", placeholder: "TRACE2" },
  { key: "bodyContains", label: "Message", kind: "text", placeholder: "payment failed", chipLabel: "Message" },
  { key: "traceId", label: "Trace ID", kind: "text", placeholder: "22222222222222222222222222222222" },
  { key: "spanId", label: "Span ID", kind: "text", placeholder: "bbbbbbbbbbbbbbbb" },
  { key: "scopeName", label: "Scope", kind: "text", placeholder: "demo.logs" },
];
const LOG_SUGGESTIBLE_FIELDS = new Set(["serviceName", "scopeName", "severityDisplay"]);

function assignQueryFilter(query: LogsQuery, clause: FilterClause): void {
  const targetKey = clause.op === "neq" ? "notFilters" : "filters";
  query[targetKey] = { ...(query[targetKey] ?? {}), [clause.key]: clause.value };
}

function buildLogsQuery(clauses: FilterClause[]): LogsQuery {
  const query: LogsQuery = {};
  for (const clause of clauses) {
    switch (clause.key) {
      case "serviceName":
      case "severityDisplay":
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

function severityFromNumber(severityNumber?: number): string {
  if (severityNumber === undefined) return "";
  switch (severityNumber) {
    case 1: return "TRACE";
    case 2: return "TRACE2";
    case 3: return "TRACE3";
    case 4: return "TRACE4";
    case 5: return "DEBUG";
    case 6: return "DEBUG2";
    case 7: return "DEBUG3";
    case 8: return "DEBUG4";
    case 9: return "INFO";
    case 10: return "INFO2";
    case 11: return "INFO3";
    case 12: return "INFO4";
    case 13: return "WARN";
    case 14: return "WARN2";
    case 15: return "WARN3";
    case 16: return "WARN4";
    case 17: return "ERROR";
    case 18: return "ERROR2";
    case 19: return "ERROR3";
    case 20: return "ERROR4";
    case 21: return "FATAL";
    case 22: return "FATAL2";
    case 23: return "FATAL3";
    case 24: return "FATAL4";
    default:
      return "";
  }
}

function severityFilterFromNumber(severityNumber?: number): SeverityFilterValue {
  if (severityNumber === undefined || severityNumber === 0) return "";
  if (severityNumber >= 1 && severityNumber <= 4) return "trace";
  if (severityNumber >= 5 && severityNumber <= 8) return "debug";
  if (severityNumber >= 9 && severityNumber <= 12) return "info";
  if (severityNumber >= 13 && severityNumber <= 16) return "warn";
  if (severityNumber >= 17 && severityNumber <= 20) return "error";
  if (severityNumber >= 21 && severityNumber <= 24) return "fatal";
  return "";
}

function severityFilterFromText(severityText?: string): SeverityFilterValue {
  const text = severityText?.trim().toUpperCase() ?? "";
  if (!text) return "";
  if (/(^|[^A-Z])(FATAL)([^A-Z]|$)/.test(text)) return "fatal";
  if (/(^|[^A-Z])(CRITICAL|CRIT|SEVERE|ALERT|EMERG|EMERGENCY|PANIC|ERROR)([^A-Z]|$)/.test(text)) return "error";
  if (/(^|[^A-Z])(WARN|WARNING)([^A-Z]|$)/.test(text)) return "warn";
  if (/(^|[^A-Z])(INFO|INFORMATIONAL|NOTICE)([^A-Z]|$)/.test(text)) return "info";
  if (/(^|[^A-Z])(TRACE)([^A-Z]|$)/.test(text)) return "trace";
  if (/(^|[^A-Z])(DEBUG|VERBOSE|FINE|FINER|FINEST)([^A-Z]|$)/.test(text)) return "debug";
  return "";
}

function severityBucket(record: LogRecord): SeverityBucket {
  const severityText = record.severityText?.trim();
  const filterValue = severityText ? severityFilterFromText(severityText) : severityFilterFromNumber(record.severityNumber);
  if (filterValue === "error" || filterValue === "fatal") return "error";
  if (filterValue === "warn") return "warn";
  if (filterValue === "info") return "info";
  if (filterValue === "debug" || filterValue === "trace") return "debug";
  return "default";
}

function displaySeverity(record: LogRecord): string {
  const severityText = record.severityText?.trim();
  if (severityText) return severityText;
  return severityFromNumber(record.severityNumber);
}

/** Returns the canonical display label for a severity bucket. */

function logKey(r: LogRecord): string {
  return r.id || `${r.timeUnixNano}|${r.resource?.serviceName ?? ""}|${r.severityText ?? ""}|${r.severityNumber ?? ""}|${r.body}`;
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
                const severity = displaySeverity(r);
                const cls = severityBucket(r);
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
                    <span
                      className={`data-table__td data-table__td--severity sev-badge sev-badge--${cls}`}
                    >
                      {severity || "--"}
                    </span>
                    <span className="data-table__td data-table__td--timestamp">
                      <span
                        className="explorer-row__secondary"
                        title={formatTimestampFull(r.timeUnixNano)}
                      >
                        {formatTimestamp(r.timeUnixNano)}
                      </span>
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
              title={truncateMessage(selectedLog.body) || displaySeverity(selectedLog) || "Log"}
              subtitle={[displaySeverity(selectedLog), selectedLog.resource?.serviceName].filter(Boolean).join(" · ")}
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
                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "8px", marginBottom: "6px" }}>
                      <h4 className="log-detail__heading" style={{ margin: 0 }}>Message</h4>
                      {selectedLog.body ? <CopyTextButton text={selectedLog.body} label="Message" /> : null}
                    </div>
                    <pre className="log-detail__body">{selectedLog.body}</pre>
                  </div>

                  {selectedLog.traceId ? (
                    <div className="log-detail__section">
                      <h4 className="log-detail__heading">Trace Correlation</h4>
                      <KVTable rows={[
                        { key: "Trace ID", value: <span title={selectedLog.traceId}>{selectedLog.traceId}</span>, action: <CopyTextButton text={selectedLog.traceId} label="Trace ID" /> },
                        ...(selectedLog.spanId ? [{ key: "Span ID", value: <span title={selectedLog.spanId}>{selectedLog.spanId}</span>, action: <CopyTextButton text={selectedLog.spanId} label="Span ID" /> }] : []),
                      ]} />
                    </div>
                  ) : null}

                  {selectedLog.resource ? (
                    <div className="log-detail__section">
                      <h4 className="log-detail__heading">Resource</h4>
                      <KVTable rows={[
                        ...(selectedLog.resource.serviceName ? [{ key: "Service", value: selectedLog.resource.serviceName }] : []),
                        ...Object.entries(selectedLog.resource?.attributes ?? {})
                          .filter(([k]) => k !== "service.name")
                          .map(([k, v]) => ({ key: k, value: formatAttrValue(v) })),
                      ]} />
                    </div>
                  ) : null}

                  {selectedLog.scope?.name ? (
                    <div className="log-detail__section">
                      <h4 className="log-detail__heading">Scope</h4>
                      <KVTable rows={[
                        { key: "Name", value: `${selectedLog.scope.name}${selectedLog.scope.version ? ` v${selectedLog.scope.version}` : ""}` },
                      ]} />
                    </div>
                  ) : null}

                  {Object.keys(selectedLog.attributes ?? {}).length > 0 ? (
                    <div className="log-detail__section">
                      <h4 className="log-detail__heading">Attributes</h4>
                      <KVTable rows={Object.entries(selectedLog.attributes ?? {}).map(([k, v]) => ({ key: k, value: formatAttrValue(v) }))} />
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="log-detail">
                  <div className="log-detail__section">
                    <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "6px" }}>
                      <CopyTextButton text={JSON.stringify(selectedLog, null, 2)} label="JSON" />
                    </div>
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

/**
 * Formats a timestamp string as HH:MM:SS.mmm.
 * Accepts either a nanosecond integer string or an ISO-8601 date string,
 * since the Go backend serializes time.Time as RFC3339.
 * The full ISO date is available via {@link formatTimestampFull}.
 */
function formatTimestamp(ts: string): string {
  if (!ts) return "--";
  try {
    let d: Date;
    // Numeric-only strings are nanosecond Unix epoch values.
    if (/^\d+$/.test(ts)) {
      const ms = Number(BigInt(ts) / BigInt(1_000_000));
      d = new Date(ms);
    } else {
      d = new Date(ts);
    }
    if (isNaN(d.getTime())) return "--";
    return d.toISOString().slice(11, 23);
  } catch {
    return "--";
  }
}

function formatAttrValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

/** Truncates a log message body to a reasonable panel title length. */
function truncateMessage(body: string | undefined): string {
  const MAX_TITLE_LENGTH = 80;
  if (!body) return "";
  const trimmed = body.trim().replace(/\s+/g, " ");
  return trimmed.length > MAX_TITLE_LENGTH ? `${trimmed.slice(0, MAX_TITLE_LENGTH)}…` : trimmed;
}

/** Returns the full ISO timestamp for use in title/tooltip attributes. */
function formatTimestampFull(ts: string): string {
  if (!ts) return "";
  try {
    let d: Date;
    if (/^\d+$/.test(ts)) {
      const ms = Number(BigInt(ts) / BigInt(1_000_000));
      d = new Date(ms);
    } else {
      d = new Date(ts);
    }
    if (isNaN(d.getTime())) return "";
    return d.toISOString();
  } catch {
    return "";
  }
}
