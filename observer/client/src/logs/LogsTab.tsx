import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { LogRecord } from "../api/types";
import { DetailPanel } from "../layout";

interface LogsTabProps {
  logs: LogRecord[];
  onInteract?: () => void;
}

type DetailTab = "overview" | "json";

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
  const [query, setQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [selectedLog, setSelectedLog] = useState<LogRecord | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const tableRef = useRef<HTMLDivElement>(null);

  const selectedKey = useMemo(() => selectedLog ? logKey(selectedLog) : null, [selectedLog]);
  const filteredLogs = useMemo(() => {
    const trimmedQuery = query.trim().toLowerCase();
    return logs.filter((record) => {
      const severity = record.severityText ?? "";
      if (severityFilter && !severity.toLowerCase().includes(severityFilter)) {
        return false;
      }
      if (!trimmedQuery) {
        return true;
      }
      const haystack = [
        severity,
        record.body,
        record.resource?.serviceName ?? "",
        record.traceId ?? "",
      ].join(" ").toLowerCase();
      return haystack.includes(trimmedQuery);
    });
  }, [logs, query, severityFilter]);
  const handleInteract = useCallback(() => {
    onInteract?.();
  }, [onInteract]);

  // Invalidate selection when the selected log is no longer in the snapshot
  // (e.g., after store clear, WebSocket reconnect, or eviction from the buffer).
  useEffect(() => {
    if (selectedKey && !logs.some((r) => logKey(r) === selectedKey)) {
      setSelectedLog(null);
    }
  }, [logs, selectedKey]);

  useEffect(() => {
    if (selectedKey && !filteredLogs.some((record) => logKey(record) === selectedKey)) {
      setSelectedLog(null);
    }
  }, [filteredLogs, selectedKey]);

  const virtualizer = useVirtualizer({
    count: filteredLogs.length,
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
          {logs.length > 0 ? (
            <div className="explorer__toolbar explorer__toolbar--controls">
              <span className="explorer__count">{filteredLogs.length} logs</span>
              <select
                className="explorer__select"
                value={severityFilter}
                onChange={(event) => setSeverityFilter(event.target.value)}
                aria-label="Filter logs by severity"
              >
                <option value="">All levels</option>
                <option value="error">Error</option>
                <option value="warn">Warn</option>
                <option value="info">Info</option>
                <option value="debug">Debug</option>
              </select>
              <input
                className="explorer__input"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search message, service, or trace ID"
              />
            </div>
          ) : null}

          {logs.length === 0 ? (
            <p className="explorer__status">Waiting for logs... Send OTLP data to port 4318.</p>
          ) : filteredLogs.length === 0 ? (
            <p className="explorer__status">No logs match the current filters.</p>
          ) : (
            <>
          <div className="data-table__head data-table__head--logs data-table__head--left-cluster data-table__head--left-cluster-logs">
            <span className="data-table__th data-table__th--severity">Level</span>
            <span className="data-table__th data-table__th--timestamp">Timestamp</span>
            <span className="data-table__th data-table__th--service">Service</span>
            <span className="data-table__th data-table__th--message">Message</span>
          </div>

          <div className="data-table__body" ref={tableRef}>
            <div className="data-table__body-inner data-table__body-inner--logs" style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
              {virtualizer.getVirtualItems().map((vi) => {
                const r = filteredLogs[vi.index];
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
          <div className="signal-view__panel">
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
                        <span className="span-details__detail-value" style={{ fontFamily: '"Cascadia Code", monospace', fontSize: "11px" }}>
                          {selectedLog.traceId.slice(-16)}
                        </span>
                      </div>
                      {selectedLog.spanId ? (
                        <div className="span-details__detail-row">
                          <span className="span-details__detail-label">Span ID</span>
                          <span className="span-details__detail-value" style={{ fontFamily: '"Cascadia Code", monospace', fontSize: "11px" }}>
                            {selectedLog.spanId}
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
          </div>
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
