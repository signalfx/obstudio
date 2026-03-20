import {
  getAttributeDisplayInfo,
  getStringAttributeValue,
  type TelemetryAttribute,
  type TracesRequest,
} from "../telemetry/types";

type TracesTabProps = {
  telemetryError: string | null;
  traces: TracesRequest;
};

type TraceEntry = {
  duration: string;
  id: string;
  service: string;
  spanCount: number;
  spans: SpanEntry[];
  startTimeUnixNano: string;
};

type SpanEntry = {
  attributes: TelemetryAttribute[];
  duration: string;
  id: string;
  name: string;
  statusLabel: string;
  statusTone: "error" | "ok" | "warn";
};

type TraceSpanNode = {
  attributes: TelemetryAttribute[];
  endTimeUnixNano: string;
  id: string;
  index: number;
  name: string;
  parentId: string;
  startTimeUnixNano: string;
  status?: {
    code?: number;
    message: string;
  };
};

export function TracesTab({ telemetryError, traces }: TracesTabProps) {
  const entries: TraceEntry[] = traces.resourceSpans.map((resourceSpans) => {
    const traceSpans = resourceSpans.scopeSpans.flatMap((scopeSpans) =>
      scopeSpans.spans.map((span) => ({
        attributes: span.attributes ?? [],
        id: toHex(span.spanId) || "unknown-span",
        index: 0,
        name: span.name || "unnamed span",
        parentId: toHex(span.parentSpanId),
        startTimeUnixNano: span.startTimeUnixNano,
        endTimeUnixNano: span.endTimeUnixNano,
        status: span.status,
      })),
    ).map((span, index) => ({ ...span, index }));
    const spans = buildTraceSpanEntries(traceSpans);

    const traceId = resourceSpans.scopeSpans.flatMap((scopeSpans) => scopeSpans.spans)[0]?.traceId ?? new Uint8Array(0);

    return {
      duration: spans[0]?.duration ?? "--",
      id: toHex(traceId).slice(0, 8) || "trace",
      service: getStringAttribute(resourceSpans.resource?.attributes, "service.name") ?? "unknown-service",
      spanCount: spans.length,
      startTimeUnixNano: getTraceStartTimeUnixNano(resourceSpans.scopeSpans.flatMap((scopeSpans) => scopeSpans.spans)),
      spans,
    };
  }).sort((left, right) => compareUnixNanoDescending(left.startTimeUnixNano, right.startTimeUnixNano) || left.id.localeCompare(right.id));

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
          <span>{entries.length} traces</span>
          <span>Tail mode</span>
        </div>
      </div>

      {telemetryError !== null ? <p className="status error">{telemetryError}</p> : null}
      {entries.length === 0 ? <p className="status">No traces received yet.</p> : null}

      <div className="trace-list">
        {entries.map((trace) => (
          <article key={trace.id} className="trace-card trace-card--stacked">
            <div className="trace-card__main">
              <div className="trace-card__header">
                <span className="trace-card__id">{trace.id}</span>
                <span className="trace-status trace-status--ok">{trace.spanCount} spans</span>
              </div>
              <p className="trace-card__name">{trace.service}</p>
              <p className="trace-card__service">traceId={trace.id}</p>
            </div>
            <div className="trace-card__duration">{trace.duration}</div>

            <div className="trace-span-list">
              {trace.spans.map((span) => (
                <div key={span.id} className="trace-span-row">
                  <div className="trace-span-row__content">
                    <div className="trace-span-row__summary">
                      <div className="trace-span-row__identity">
                        <span className="trace-span-row__id">{span.id}</span>
                        <span className="trace-span-row__name">{span.name}</span>
                        <span className={`trace-status trace-status--plain trace-status--${span.statusTone}`}>{span.statusLabel}</span>
                      </div>
                      <div className="trace-span-row__attributes">
                        {span.attributes.length > 0 ? (
                          span.attributes.map((attribute) => {
                            const display = getAttributeDisplayInfo(attribute);
                            return (
                              <span key={attribute.key} className="attribute-pill">
                                <span className="attribute-pill__key">{attribute.key}</span>=
                                <span className={`attribute-pill__value attribute-pill__value--${display.type}`}>{display.value}</span>
                              </span>
                            );
                          })
                        ) : (
                          <span className="trace-span-row__empty">No attributes</span>
                        )}
                      </div>
                      <div className="trace-span-row__meta">
                        <span className="trace-span-row__duration">{span.duration}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
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

function getSpanStatusTone(status: { code?: number; message: string } | undefined): "error" | "ok" | "warn" {
  if (status?.code === 2) {
    return "error";
  }

  return (status?.code ?? 0) === 0 && !status?.message ? "ok" : "warn";
}

function getSpanStatusLabel(status: { code?: number; message: string } | undefined): string {
  if (status?.message) {
    return status.message;
  }

  if ((status?.code ?? 0) !== 0) {
    return `code=${status?.code}`;
  }

  return "ok";
}

function getTraceStartTimeUnixNano(spans: Array<{ startTimeUnixNano: string }>): string {
  return spans.reduce((minimum, span) => {
    if (minimum === "") {
      return span.startTimeUnixNano;
    }

    return compareUnixNanoAscending(span.startTimeUnixNano, minimum) < 0 ? span.startTimeUnixNano : minimum;
  }, "");
}

function buildTraceSpanEntries(spans: TraceSpanNode[]): SpanEntry[] {
  const spanById = new Map(spans.map((span) => [span.id, span] as const));
  const childrenByParentId = new Map<string, TraceSpanNode[]>();
  const roots: TraceSpanNode[] = [];

  for (const span of spans) {
    if (span.parentId === "" || span.parentId === span.id || !spanById.has(span.parentId)) {
      roots.push(span);
      continue;
    }

    const siblings = childrenByParentId.get(span.parentId);
    if (siblings) {
      siblings.push(span);
    } else {
      childrenByParentId.set(span.parentId, [span]);
    }
  }

  const compareSpanNodes = (left: TraceSpanNode, right: TraceSpanNode) =>
    compareUnixNanoAscending(left.startTimeUnixNano, right.startTimeUnixNano) || left.index - right.index;

  roots.sort(compareSpanNodes);
  for (const siblings of childrenByParentId.values()) {
    siblings.sort(compareSpanNodes);
  }

  const orderedSpans: SpanEntry[] = [];
  const visited = new Set<string>();

  roots.forEach((root) => {
    appendTraceSpanEntries(root, childrenByParentId, visited, orderedSpans);
  });

  for (const span of [...spans].sort((left, right) => left.index - right.index)) {
    appendTraceSpanEntries(span, childrenByParentId, visited, orderedSpans);
  }

  return orderedSpans;
}

function appendTraceSpanEntries(
  span: TraceSpanNode,
  childrenByParentId: Map<string, TraceSpanNode[]>,
  visited: Set<string>,
  orderedSpans: SpanEntry[],
): void {
  if (visited.has(span.id)) {
    return;
  }

  visited.add(span.id);
  orderedSpans.push({
    attributes: span.attributes,
    duration: formatDuration(span.endTimeUnixNano, span.startTimeUnixNano),
    id: span.id,
    name: span.name,
    statusLabel: getSpanStatusLabel(span.status),
    statusTone: getSpanStatusTone(span.status),
  });

  const children = childrenByParentId.get(span.id) ?? [];
  children.forEach((child) => {
    appendTraceSpanEntries(child, childrenByParentId, visited, orderedSpans);
  });
}

function compareUnixNanoDescending(left: string, right: string): number {
  return compareUnixNanoAscending(right, left);
}

function compareUnixNanoAscending(left: string, right: string): number {
  const leftValue = parseUnixNano(left);
  const rightValue = parseUnixNano(right);

  if (leftValue !== null && rightValue !== null) {
    if (leftValue < rightValue) {
      return -1;
    }
    if (leftValue > rightValue) {
      return 1;
    }
    return 0;
  }

  if (leftValue !== null) {
    return -1;
  }
  if (rightValue !== null) {
    return 1;
  }

  return left.localeCompare(right);
}

function parseUnixNano(value: string): bigint | null {
  if (value.trim() === "") {
    return null;
  }

  try {
    return BigInt(value);
  } catch {
    return null;
  }
}
