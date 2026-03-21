import { getStringAttributeValue, type LogsRequest, type TelemetryAttribute } from "../telemetry/types";

type LogsTabProps = {
  logs: LogsRequest;
};

export function LogsTab({ logs }: LogsTabProps) {
  const logRecords = logs.resourceLogs.flatMap((resourceLog) =>
    resourceLog.scopeLogs.flatMap((scopeLog) =>
      scopeLog.logRecords.map((logRecord) => ({
        body: getStringAttributeValue({ key: "body", value: { value: logRecord.body?.value } }) ?? "Structured payload",
        resource: getStringAttribute(resourceLog.resource?.attributes, "service.name") ?? "unknown-service",
        severity: logRecord.severityText || "UNSPECIFIED",
        timestamp: logRecord.timeUnixNano || logRecord.observedTimeUnixNano || "0",
      })),
    ),
  );

  return (
    <section className="tab-panel" role="tabpanel">
      <div className="panel-toolbar">
        <div className="panel-toolbar__title">
          <span className="panel-toolbar__glyph" aria-hidden="true">
            L
          </span>
          <span>Recent logs</span>
        </div>
        <div className="panel-toolbar__meta">
          <span>{logRecords.length} records</span>
          <span>OTLP stream</span>
        </div>
      </div>

      {logRecords.length === 0 ? <p className="status">No logs received yet.</p> : null}

      <div className="trace-list">
        {logRecords.map((logRecord, index) => (
          <article key={`${logRecord.timestamp}-${index}`} className="trace-card">
            <div className="trace-card__main">
              <div className="trace-card__header">
                <span className="trace-card__id">{logRecord.resource}</span>
                <span className="trace-status trace-status--ok">{logRecord.severity}</span>
              </div>
              <p className="trace-card__name">{logRecord.body}</p>
              <p className="trace-card__service">timeUnixNano={logRecord.timestamp}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function getStringAttribute(
  attributes: ReadonlyArray<TelemetryAttribute> | undefined,
  key: string,
): string | undefined {
  const attribute = attributes?.find((entry) => entry.key === key);
  return getStringAttributeValue(attribute);
}
