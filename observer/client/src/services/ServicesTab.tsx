import React, { useMemo, useState } from "react";
import type { TraceSummary } from "../api/types";

interface ServicesTabProps {
  traces: TraceSummary[];
  serviceNames: string[];
}

interface ServiceRow {
  name: string;
  traceCount: number;
  spanCount: number;
  errorCount: number;
  avgDurationMs: number | null;
  avgClientDurationMs: number | null;
  avgServerDurationMs: number | null;
}

type SortKey = "name" | "traceCount" | "spanCount" | "errorCount" | "avgDurationMs" | "avgClientDurationMs" | "avgServerDurationMs";
type SortDir = "asc" | "desc";

export function ServicesTab({ traces, serviceNames }: ServicesTabProps): React.ReactElement {
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const rows = useMemo<ServiceRow[]>(() => {
    const map = new Map<string, ServiceRow>();
    const clientCounts = new Map<string, number>();
    const serverCounts = new Map<string, number>();

    const get = (name: string): ServiceRow => {
      let row = map.get(name);
      if (!row) {
        row = { name, traceCount: 0, spanCount: 0, errorCount: 0, avgDurationMs: null, avgClientDurationMs: null, avgServerDurationMs: null };
        map.set(name, row);
      }
      return row;
    };

    // seed from the authoritative service name list so zero-signal services appear
    for (const name of serviceNames) get(name);

    for (const trace of traces) {
      const svc = trace.serviceName ?? "unknown";
      const row = get(svc);
      row.traceCount += 1;
      if (trace.status === "error") row.errorCount += 1;
      if (trace.durationMs !== undefined) {
        const prev = row.avgDurationMs ?? 0;
        row.avgDurationMs = (prev * (row.traceCount - 1) + trace.durationMs) / row.traceCount;
      }
      for (const span of trace.spans ?? []) {
        const spanSvc = span.serviceName ?? svc;
        const spanRow = get(spanSvc);
        spanRow.spanCount += 1;
        if (span.kind === "CLIENT") {
          const n = (clientCounts.get(spanSvc) ?? 0) + 1;
          clientCounts.set(spanSvc, n);
          spanRow.avgClientDurationMs = ((spanRow.avgClientDurationMs ?? 0) * (n - 1) + span.durationMs) / n;
        } else if (span.kind === "SERVER") {
          const n = (serverCounts.get(spanSvc) ?? 0) + 1;
          serverCounts.set(spanSvc, n);
          spanRow.avgServerDurationMs = ((spanRow.avgServerDurationMs ?? 0) * (n - 1) + span.durationMs) / n;
        }
      }
    }

    return [...map.values()];
  }, [traces, serviceNames]);

  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") {
        cmp = a.name.localeCompare(b.name);
      } else if (sortKey === "avgDurationMs") {
        cmp = (a.avgDurationMs ?? -1) - (b.avgDurationMs ?? -1);
      } else if (sortKey === "avgClientDurationMs") {
        cmp = (a.avgClientDurationMs ?? -1) - (b.avgClientDurationMs ?? -1);
      } else if (sortKey === "avgServerDurationMs") {
        cmp = (a.avgServerDurationMs ?? -1) - (b.avgServerDurationMs ?? -1);
      } else {
        cmp = (a[sortKey] as number) - (b[sortKey] as number);
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, sortKey, sortDir]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  }

  function arrow(key: SortKey): string {
    if (key !== sortKey) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  if (rows.length === 0) {
    return (
      <section className="tab-panel" role="tabpanel">
        <p className="explorer__status explorer__status--empty">
          No services observed yet. Send OTLP telemetry to port 4318 to begin exploring.
        </p>
      </section>
    );
  }

  return (
    <section className="tab-panel" role="tabpanel">
      <div className="signal-view">
        <div className="signal-view__content">
          <div className="data-table__head data-table__head--services">
            <button type="button" className="data-table__th data-table__th--sortable" onClick={() => handleSort("name")}>
              Service{arrow("name")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("traceCount")}>
              Traces{arrow("traceCount")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("spanCount")}>
              Spans{arrow("spanCount")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("errorCount")}>
              Errors{arrow("errorCount")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("avgDurationMs")}>
              Avg Duration{arrow("avgDurationMs")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("avgClientDurationMs")}>
              Avg Client{arrow("avgClientDurationMs")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("avgServerDurationMs")}>
              Avg Server{arrow("avgServerDurationMs")}
            </button>
          </div>

          <div className="data-table__body">
            <div className="data-table__body-inner data-table__body-inner--services">
              {sorted.map((row) => (
                <div key={row.name} className="data-table__row data-table__row--services">
                  <span className="data-table__td data-table__td--service-name">
                    <span className="explorer-row__primary">{row.name}</span>
                  </span>
                  <span className="data-table__td data-table__td--numeric">
                    <span className="explorer-row__numeric">{row.traceCount || "—"}</span>
                  </span>
                  <span className="data-table__td data-table__td--numeric">
                    <span className="explorer-row__numeric">{row.spanCount || "—"}</span>
                  </span>
                  <span className="data-table__td data-table__td--numeric">
                    {row.errorCount > 0
                      ? <span className="explorer-row__numeric services-tab__error-count">{row.errorCount}</span>
                      : <span className="explorer-row__numeric explorer-row__numeric--muted">—</span>}
                  </span>
                  <span className="data-table__td data-table__td--numeric">
                    <span className="explorer-row__numeric">
                      {row.avgDurationMs !== null ? `${row.avgDurationMs.toFixed(1)} ms` : "—"}
                    </span>
                  </span>
                  <span className="data-table__td data-table__td--numeric">
                    <span className="explorer-row__numeric">
                      {row.avgClientDurationMs !== null ? `${row.avgClientDurationMs.toFixed(1)} ms` : "—"}
                    </span>
                  </span>
                  <span className="data-table__td data-table__td--numeric">
                    <span className="explorer-row__numeric">
                      {row.avgServerDurationMs !== null ? `${row.avgServerDurationMs.toFixed(1)} ms` : "—"}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
