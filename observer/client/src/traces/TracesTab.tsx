import { getStringAttributeValue, type TelemetryAttribute, type TracesRequest } from "../telemetry/types";

type TracesTabProps = {
  telemetryError: string | null;
  traces: TracesRequest;
};

export function TracesTab({ telemetryError, traces }: TracesTabProps) {
  const entries = traces.resourceSpans.flatMap((resourceSpans) =>
    resourceSpans.scopeSpans.flatMap((scopeSpans) =>
      scopeSpans.spans.map((span) => ({
        duration: formatDuration(span.endTimeUnixNano, span.startTimeUnixNano),
        id: toHex(span.traceId).slice(0, 8) || "trace",
        name: span.name || "unnamed span",
        service: getStringAttribute(resourceSpans.resource?.attributes, "service.name") ?? "unknown-service",
        status: span.status?.message ? "warn" : "ok",
      })),
    ),
  );

  return (
    <section className="tab-panel" role="tabpanel">
      <div className="panel-toolbar">
        <div className="panel-toolbar__title">
          <span className="panel-toolbar__glyph" aria-hidden="true">
            T
          </span>
          <span>Recent traces</span>
        </div>
        <div className="panel-toolbar__meta">
          <span>{entries.length} samples</span>
          <span>Tail mode</span>
        </div>
      </div>

      {telemetryError !== null ? <p className="status error">{telemetryError}</p> : null}
      {entries.length === 0 ? <p className="status">No traces received yet.</p> : null}

      <div className="trace-list">
        {entries.map((trace) => (
          <article key={trace.id} className="trace-card">
            <div className="trace-card__main">
              <div className="trace-card__header">
                <span className="trace-card__id">{trace.id}</span>
                <span className={`trace-status trace-status--${trace.status}`}>{trace.status}</span>
              </div>
              <p className="trace-card__name">{trace.name}</p>
              <p className="trace-card__service">{trace.service}</p>
            </div>
            <div className="trace-card__duration">{trace.duration}</div>
          </article>
        ))}
      </div>
    </section>
  );
}

function toHex(value: Uint8Array): string {
  return Array.from(value, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function formatDuration(endTimeUnixNano: string, startTimeUnixNano: string): string {
  const durationNs = Number(endTimeUnixNano) - Number(startTimeUnixNano);
  if (!Number.isFinite(durationNs) || durationNs <= 0) {
    return "--";
  }

  return `${(durationNs / 1_000_000).toFixed(2)} ms`;
}

function getStringAttribute(
  attributes: ReadonlyArray<TelemetryAttribute> | undefined,
  key: string,
): string | undefined {
  const attribute = attributes?.find((entry) => entry.key === key);
  return getStringAttributeValue(attribute);
}
