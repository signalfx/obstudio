import React, { useEffect, useState } from "react";
import { fetchServiceStats, type ServiceStats } from "../api/client";

interface ServicesTabProps {
  serviceNames: string[];
}

type SortKey = keyof ServiceStats;
type SortDir = "asc" | "desc";

export function ServicesTab({ serviceNames }: ServicesTabProps): React.ReactElement {
  const [rows, setRows] = useState<ServiceStats[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const serviceNamesKey = serviceNames.join("\0");

  useEffect(() => {
    const controller = new AbortController();
    fetchServiceStats(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setRows(data);
        }
      })
      .catch(() => {});
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceNamesKey]);

  const sorted = [...rows].sort((a, b) => {
    let cmp = 0;
    if (sortKey === "name") {
      cmp = a.name.localeCompare(b.name);
    } else {
      const av = a[sortKey] ?? -1;
      const bv = b[sortKey] ?? -1;
      cmp = (av as number) - (bv as number);
    }
    return sortDir === "asc" ? cmp : -cmp;
  });

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

  if (rows.length === 0 && serviceNames.length === 0) {
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
      <div className="services-table-scroll">
        <div className="services-table">
          <div className="services-table__head">
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

          {sorted.map((row) => (
            <div key={row.name} className="services-table__row">
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
    </section>
  );
}
