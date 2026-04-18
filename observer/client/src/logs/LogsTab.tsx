import React, { useState, useEffect, useRef, useMemo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { LogRecord } from "../api/types";
import { DetailPanel } from "../layout";

interface LogsTabProps {
  logs: LogRecord[];
}

type DetailTab = "overview" | "json";
type SeverityBucket = "error" | "warn" | "info" | "default";
type SeverityFilterValue = "" | "trace" | "debug" | "info" | "warn" | "error" | "fatal";

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
  }
  return "";
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

function severityFilterValue(record: LogRecord): SeverityFilterValue {
  const byNumber = severityFilterFromNumber(record.severityNumber);
  if (byNumber) return byNumber;
  return severityFilterFromText(record.severityText);
}

function severityBucket(record: LogRecord): SeverityBucket {
  const filterValue = severityFilterValue(record);
  if (filterValue === "error" || filterValue === "fatal") return "error";
  if (filterValue === "warn") return "warn";
  if (filterValue === "info") return "info";
  return "default";
}

function displaySeverity(record: LogRecord): string {
  const severityFromNum = severityFromNumber(record.severityNumber);
  const severityText = record.severityText?.trim();
  if (severityFromNum && severityText) return `${severityFromNum} (${severityText})`;
  if (severityFromNum) return severityFromNum;
  if (severityText) return severityText;
  return "";
}

function logKey(r: LogRecord): string {
  return r.id || `${r.timeUnixNano}|${r.resource?.serviceName ?? ""}|${r.severityText ?? ""}|${r.body}`;
}

/** Logs tab with virtualized table and detail panel for selected log records. */
export function LogsTab({ logs }: LogsTabProps): React.ReactElement {
  const [query, setQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [selectedLog, setSelectedLog] = useState<LogRecord | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const tableRef = useRef<HTMLDivElement>(null);

  const selectedKey = useMemo(() => selectedLog ? logKey(selectedLog) : null, [selectedLog]);
  const filteredLogs = useMemo(() => {
    const trimmedQuery = query.trim().toLowerCase();
    return logs.filter((record) => {
      const severity = displaySeverity(record);
      const filterValue = severityFilterValue(record);
      if (severityFilter && filterValue !== severityFilter) {
        return false;
      }
      if (!trimmedQuery) {
        return true;
      }
      const haystack = [
        severity,
        filterValue,
        record.body,
        record.resource?.serviceName ?? "",
        record.traceId ?? "",
      ].join(" ").toLowerCase();
      return haystack.includes(trimmedQuery);
    });
  }, [logs, query, severityFilter]);
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
      >
        <div className="signal-view__content">
          {logs.length > 0 ? (
            <div className="explorer__toolbar explorer__toolbar--controls">
              <select
                className="explorer__select"
                value={severityFilter}
                onChange={(event) => setSeverityFilter(event.target.value)}
                aria-label="Filter logs by severity"
              >
                <option value="">All severities</option>
                <option value="trace">TRACE</option>
                <option value="debug">DEBUG</option>
                <option value="info">INFO</option>
                <option value="warn">WARN</option>
                <option value="error">ERROR</option>
                <option value="fatal">FATAL</option>
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
            <p className="explorer__status explorer__status--empty">No logs received yet. Send OTLP telemetry to port 4318 to begin exploring.</p>
          ) : filteredLogs.length === 0 ? (
            <p className="explorer__status">No logs match the current filters.</p>
          ) : (
            <>
          <div className="data-table__head data-table__head--logs data-table__head--left-cluster data-table__head--left-cluster-logs">
            <span className="data-table__th data-table__th--severity">Severity</span>
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
                const severity = displaySeverity(r);
                const cls = severityBucket(r);
                return (
                  <button
                    key={logKey(r)}
                    className={`data-table__row data-table__row--logs data-table__row--sev-${cls} ${active ? "data-table__row--active" : ""}`}
                    onClick={() => {
                      setSelectedLog(r);
                      setDetailTab("overview");
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
                    <span className="data-table__td data-table__td--severity">
                      <span className={`sev-badge sev-badge--${cls}`}>
                        {severity || "--"}
                      </span>
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
              title={displaySeverity(selectedLog) || "LOG"}
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
                    <h4 className="log-detail__heading">Summary</h4>
                    <div className="span-details__detail-row">
                      <span className="span-details__detail-label">Timestamp</span>
                      <span className="span-details__detail-value" style={{ fontFamily: '"Cascadia Code", monospace', fontSize: "11px" }}>
                        {selectedLog.timeUnixNano || "--"}
                      </span>
                    </div>
                    {selectedLog.severityNumber !== undefined ? (
                      <div className="span-details__detail-row">
                        <span className="span-details__detail-label">Severity Number</span>
                        <span className="span-details__detail-value">{selectedLog.severityNumber}</span>
                      </div>
                    ) : null}
                    {selectedLog.severityText ? (
                      <div className="span-details__detail-row">
                        <span className="span-details__detail-label">Severity Text</span>
                        <span className="span-details__detail-value">{selectedLog.severityText}</span>
                      </div>
                    ) : null}
                  </div>

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

                  {Object.keys(selectedLog.attributes ?? {}).length > 0 ? (
                    <div className="log-detail__section">
                      <h4 className="log-detail__heading">Attributes</h4>
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
                    </div>
                  ) : null}

                  {hasLogResourceDetails(selectedLog) ? (
                    <div className="log-detail__section">
                      <h4 className="log-detail__heading">Resource Attributes</h4>
                      {selectedLog.resource.schemaUrl ? (
                        <div className="span-details__detail-row">
                          <span className="span-details__detail-label">Schema URL</span>
                          <span className="span-details__detail-value" style={{ fontFamily: '"Cascadia Code", monospace', fontSize: "11px" }}>
                            {selectedLog.resource.schemaUrl}
                          </span>
                        </div>
                      ) : null}
                      {Object.keys(resourceDetailAttributes(selectedLog)).length > 0 ? (
                        <table className="log-detail__attrs">
                          <tbody>
                            {Object.entries(resourceDetailAttributes(selectedLog)).map(([k, v]) => (
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

function resourceDetailAttributes(record: LogRecord): Record<string, unknown> {
  const attributes = { ...(record.resource?.attributes ?? {}) };
  if (attributes["service.name"] === record.resource?.serviceName) {
    delete attributes["service.name"];
  }
  return attributes;
}

function hasLogResourceDetails(record: LogRecord): boolean {
  return Boolean(record.resource?.schemaUrl) || Object.keys(resourceDetailAttributes(record)).length > 0;
}
