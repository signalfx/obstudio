import React, { useMemo, useState } from "react";
import type { Span, ValidationFinding } from "../api/types";
import { CopyTextButton } from "../layout";
import { KVTable } from "../components/KVTable";

interface SpanDetailsPanelProps {
  span: Span;
  validationFindings: ValidationFinding[];
}

type TabId = "info" | "attributes" | "events" | "links";

function nanoToMs(ts: string): number {
  if (/^\d+$/.test(ts)) {
    return Number(BigInt(ts) / BigInt(1_000_000));
  }
  return new Date(ts).getTime();
}

function relativeTime(eventNano: string, spanStartNano: string): string {
  const eventMs = nanoToMs(eventNano);
  const spanMs = nanoToMs(spanStartNano);
  const diff = eventMs - spanMs;
  if (isNaN(diff)) return "";
  if (diff < 1) return "+0ms";
  return `+${diff.toFixed(1)}ms`;
}

/** Tabbed detail view for a single span showing info, attributes, events, and links. */
export function SpanDetailsPanel({ span, validationFindings }: SpanDetailsPanelProps): React.ReactElement {
  const [activeTab, setActiveTab] = useState<TabId>("info");
  const [attributeFilter, setAttributeFilter] = useState("");

  const attrCount = Object.keys(span.attributes ?? {}).length;
  const eventCount = (span.events ?? []).length;
  const linkCount = (span.links ?? []).length;
  const filteredAttributes = useMemo(
    () => Object.entries(span.attributes ?? {}).filter(([key, value]) => attributeMatchesFilter(key, value, attributeFilter)),
    [attributeFilter, span.attributes],
  );

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
              {validationFindings.length > 0 ? (
                <div className="span-details__validation">
                  {validationFindings.map((finding) => (
                    <div key={`${finding.entityKey}:${finding.ruleId}:${finding.updatedAt}`} className={`validation-inline validation-inline--${finding.severity}`}>
                      <span
                        className={`validation-inline__severity-dot validation-inline__severity-dot--${finding.severity}`}
                        aria-hidden="true"
                      />
                      <span>{finding.message}</span>
                    </div>
                  ))}
                </div>
              ) : null}
              <KVTable rows={[
                { key: "Kind", value: span.kind },
                { key: "Status", value: <span style={{ color: span.status.code === "ERROR" ? "var(--red, #f48771)" : span.status.code === "OK" ? "var(--green, #7ec699)" : "var(--orange)" }}>{span.status.code}{span.status.message ? `: ${span.status.message}` : ""}</span> },
                { key: "Trace ID", value: <span title={span.traceId}>{span.traceId}</span>, action: <CopyTextButton text={span.traceId} label="Trace ID" /> },
                { key: "Span ID", value: <span title={span.spanId}>{span.spanId}</span>, action: <CopyTextButton text={span.spanId} label="Span ID" /> },
                ...(span.parentSpanId ? [{ key: "Parent", value: <span title={span.parentSpanId}>{span.parentSpanId}</span>, action: <CopyTextButton text={span.parentSpanId} label="Parent span ID" /> }] : []),
                { key: "Start", value: formatNanoTimestamp(span.startTimeUnixNano) },
                { key: "Duration", value: formatDuration(span.durationMs) },
                ...(span.resource?.serviceName ? [{ key: "Service", value: span.resource.serviceName }] : []),
                ...(span.scope?.name ? [{ key: "Scope", value: `${span.scope.name}${span.scope.version ? ` v${span.scope.version}` : ""}` }] : []),
              ]} />
            </div>
          </div>
        ) : null}

        {activeTab === "attributes" ? (
          <div className="span-details__section">
            <div className="span-details__section-body span-details__attrs">
              {attrCount > 0 ? (
                <input
                  type="text"
                  className="span-details__attr-filter"
                  placeholder="Filter attributes"
                  value={attributeFilter}
                  onChange={(event) => setAttributeFilter(event.target.value)}
                  aria-label="Filter span attributes"
                />
              ) : null}
              {attrCount > 0 ? (
                filteredAttributes.length > 0 ? (
                  <KVTable rows={filteredAttributes.map(([k, v]) => ({ key: k, value: formatAttrValue(v) }))} />
                ) : <p className="span-details__empty">No attributes match the current filter</p>
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
                        <KVTable rows={Object.entries(e.attributes ?? {}).map(([k, v]) => ({ key: k, value: formatAttrValue(v) }))} />
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
                  <div key={link.traceId + '-' + link.spanId + '-' + i} className="span-details__link">
                    <KVTable rows={[
                      { key: "Trace ID", value: link.traceId },
                      { key: "Span ID", value: link.spanId },
                      ...Object.entries(link.attributes ?? {}).map(([k, v]) => ({ key: k, value: formatAttrValue(v) })),
                    ]} />
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

function attributeMatchesFilter(key: string, value: unknown, filter: string): boolean {
  const normalizedFilter = normalizeFilterText(filter);
  if (!normalizedFilter) {
    return true;
  }
  return normalizeFilterText(key).includes(normalizedFilter) || normalizeFilterText(String(value)).includes(normalizedFilter);
}

function normalizeFilterText(value: string): string {
  return value.trim().toLowerCase();
}

function formatAttrValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}
