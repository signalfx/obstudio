import React, { useState } from "react";
import type { Span } from "../api/types";

interface SpanDetailsPanelProps {
  span: Span;
}

type TabId = "info" | "attributes" | "events" | "links";

function relativeTime(eventNano: string, spanStartNano: string): string {
  const eventMs = new Date(eventNano).getTime();
  const spanMs = new Date(spanStartNano).getTime();
  const diff = eventMs - spanMs;
  if (isNaN(diff)) return "";
  if (diff < 1) return "+0ms";
  return `+${diff.toFixed(1)}ms`;
}

/** Tabbed detail view for a single span showing info, attributes, events, and links. */
export function SpanDetailsPanel({ span }: SpanDetailsPanelProps): React.ReactElement {
  const [activeTab, setActiveTab] = useState<TabId>("info");

  const attrCount = Object.keys(span.attributes ?? {}).length;
  const eventCount = (span.events ?? []).length;
  const linkCount = (span.links ?? []).length;

  const tabs: { id: TabId; label: string; count?: number }[] = [
    { id: "info", label: "Info" },
    { id: "attributes", label: "Attributes", count: attrCount },
    { id: "events", label: "Events", count: eventCount },
    { id: "links", label: "Links", count: linkCount },
  ];

  return (
    <div className="span-details">
      <div className="span-details__header">
        <div>
          <div className="span-details__name">{span.name}</div>
          <div className="span-details__meta">
            <span className="span-details__service">{span.resource?.serviceName ?? "unknown"}</span>
            <span className={`trace-status trace-status--plain trace-status--${span.status.code === "ERROR" ? "error" : span.status.code === "OK" ? "ok" : "unset"}`}>
              {span.status.code}
            </span>
            <span className="span-details__duration">{span.durationMs.toFixed(2)}ms</span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="span-details__tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`span-details__tab ${activeTab === tab.id ? "span-details__tab--active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
            type="button"
          >
            {tab.label}
            {tab.count != null && tab.count > 0 ? (
              <span className="span-details__tab-count">{tab.count}</span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="span-details__body">
        {activeTab === "info" ? (
          <div className="span-details__section">
            <div className="span-details__section-body">
              <div className="span-details__detail-row">
                <span className="span-details__detail-label">Kind</span>
                <span className="span-details__detail-value">{span.kind}</span>
              </div>
              <div className="span-details__detail-row">
                <span className="span-details__detail-label">Status</span>
                <span className="span-details__detail-value">
                  {span.status.code}
                  {span.status.message ? `: ${span.status.message}` : ""}
                </span>
              </div>
              <div className="span-details__detail-row">
                <span className="span-details__detail-label">Span ID</span>
                <span className="span-details__detail-value" style={{ fontFamily: '"Cascadia Code", monospace', fontSize: "11px" }}>
                  {span.spanId}
                </span>
              </div>
              {span.parentSpanId ? (
                <div className="span-details__detail-row">
                  <span className="span-details__detail-label">Parent</span>
                  <span className="span-details__detail-value" style={{ fontFamily: '"Cascadia Code", monospace', fontSize: "11px" }}>
                    {span.parentSpanId}
                  </span>
                </div>
              ) : null}
              <div className="span-details__detail-row">
                <span className="span-details__detail-label">Start</span>
                <span className="span-details__detail-value" style={{ fontFamily: '"Cascadia Code", monospace', fontSize: "11px" }}>
                  {formatNanoTimestamp(span.startTimeUnixNano)}
                </span>
              </div>
              <div className="span-details__detail-row">
                <span className="span-details__detail-label">Duration</span>
                <span className="span-details__detail-value" style={{ fontFamily: '"Cascadia Code", monospace', fontSize: "11px" }}>
                  {formatDuration(span.durationMs)}
                </span>
              </div>
              {span.resource?.serviceName ? (
                <div className="span-details__detail-row">
                  <span className="span-details__detail-label">Service</span>
                  <span className="span-details__detail-value">{span.resource.serviceName}</span>
                </div>
              ) : null}
              {span.scope?.name ? (
                <div className="span-details__detail-row">
                  <span className="span-details__detail-label">Scope</span>
                  <span className="span-details__detail-value">
                    {span.scope.name}
                    {span.scope.version ? ` v${span.scope.version}` : ""}
                  </span>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {activeTab === "attributes" ? (
          <div className="span-details__section">
            <div className="span-details__section-body span-details__attrs">
              {attrCount > 0 ? (
                Object.entries(span.attributes ?? {}).map(([k, v]) => (
                  <div key={k} className="span-details__attr-row">
                    <span className="span-details__attr-key">{k}</span>
                    <span className="span-details__attr-value">{String(v)}</span>
                  </div>
                ))
              ) : (
                <p className="span-details__empty">No attributes</p>
              )}
            </div>
          </div>
        ) : null}

        {activeTab === "events" ? (
          <div className="span-details__section">
            <div className="span-details__section-body">
              {eventCount > 0 ? (
                (span.events ?? []).map((e, i) => (
                  <div key={e.name + '-' + i} className="span-details__event">
                    <span className="span-details__event-name">{e.name}</span>
                    <span className="span-details__event-time">
                      {relativeTime(e.timeUnixNano, span.startTimeUnixNano)}
                    </span>
                    {Object.keys(e.attributes ?? {}).length > 0 ? (
                      <div className="span-details__event-attrs">
                        {Object.entries(e.attributes ?? {}).map(([k, v]) => (
                          <div key={k} className="span-details__attr-row">
                            <span className="span-details__attr-key">{k}</span>
                            <span className="span-details__attr-value">{String(v)}</span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))
              ) : (
                <p className="span-details__empty">No events</p>
              )}
            </div>
          </div>
        ) : null}

        {activeTab === "links" ? (
          <div className="span-details__section">
            <div className="span-details__section-body">
              {linkCount > 0 ? (
                (span.links ?? []).map((link, i) => (
                  <div key={link.traceId + '-' + link.spanId} className="span-details__link">
                    <span className="span-details__link-label">
                      Trace: {link.traceId.slice(0, 16)}
                    </span>
                    <span className="span-details__link-label">
                      Span: {link.spanId}
                    </span>
                    {Object.keys(link.attributes ?? {}).length > 0 ? (
                      <div className="span-details__event-attrs">
                        {Object.entries(link.attributes ?? {}).map(([k, v]) => (
                          <div key={k} className="span-details__attr-row">
                            <span className="span-details__attr-key">{k}</span>
                            <span className="span-details__attr-value">{String(v)}</span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))
              ) : (
                <p className="span-details__empty">No links</p>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function formatNanoTimestamp(ts: string): string {
  if (!ts) return "--";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "--";
  return d.toISOString().slice(11, 23);
}

function formatDuration(ms: number): string {
  if (ms < 1) return `${(ms * 1000).toFixed(0)}\u00B5s`;
  if (ms < 1000) return `${ms.toFixed(2)}ms`;
  return `${(ms / 1000).toFixed(3)}s`;
}
