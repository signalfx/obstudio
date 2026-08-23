import React, { useEffect, useMemo, useState } from "react";
import { FilterBar, type FilterClause, type FilterDefinition } from "../FilterBar";
import { EmptyState } from "../components/EmptyState";
import { fetchServiceStats, type ServiceStats } from "../api/client";

interface ServicesTabProps {
  serviceNames: string[];
}

type SortKey = keyof ServiceStats;
type SortDir = "asc" | "desc";

const SERVICE_FILTER_DEFINITIONS: FilterDefinition[] = [
  { key: "serviceName", label: "Service", kind: "text", placeholder: "checkout" },
];

function matchesClauses(row: ServiceStats, clauses: FilterClause[]): boolean {
  for (const clause of clauses) {
    if (clause.key === "serviceName") {
      const matches = row.name.toLowerCase() === clause.value.toLowerCase();
      if (clause.op === "neq" ? matches : !matches) return false;
    }
  }
  return true;
}

export function ServicesTab({ serviceNames }: ServicesTabProps): React.ReactElement {
  const [rows, setRows] = useState<ServiceStats[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [clauses, setClauses] = useState<FilterClause[]>([]);
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

  const filtered = useMemo(
    () => clauses.length === 0 ? rows : rows.filter((r) => matchesClauses(r, clauses)),
    [rows, clauses],
  );

  const sorted = useMemo(() => [...filtered].sort((a, b) => {
    let cmp = 0;
    if (sortKey === "name") {
      cmp = a.name.localeCompare(b.name);
    } else {
      const av = a[sortKey] ?? -1;
      const bv = b[sortKey] ?? -1;
      cmp = (av as number) - (bv as number);
    }
    return sortDir === "asc" ? cmp : -cmp;
  }), [filtered, sortKey, sortDir]);

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

  function sortLabel(key: SortKey, label: string): string {
    if (key !== sortKey) return label;
    return `${label}, sorted ${sortDir === "asc" ? "ascending" : "descending"}`;
  }

  if (rows.length === 0 && serviceNames.length === 0) {
    return (
      <section id="panel-services" className="tab-panel" role="tabpanel" aria-label="Services">
        <EmptyState
          title="No services observed yet."
          hint="Send OTLP telemetry to port 4318 to begin exploring."
        />
      </section>
    );
  }

  return (
    <section id="panel-services" className="tab-panel" role="tabpanel" aria-label="Services">
      <div className="explorer__toolbar explorer__toolbar--controls">
        <FilterBar
          definitions={SERVICE_FILTER_DEFINITIONS}
          clauses={clauses}
          onChange={setClauses}
        />
      </div>
      <div className="services-table-scroll">
        <div className="services-table">
          <div className="services-table__head">
            <button type="button" className="data-table__th data-table__th--sortable" onClick={() => handleSort("name")} aria-label={sortLabel("name", "Service")}>
              Service{arrow("name")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("traceCount")} aria-label={sortLabel("traceCount", "Traces")}>
              Traces{arrow("traceCount")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("spanCount")} aria-label={sortLabel("spanCount", "Spans")}>
              Spans{arrow("spanCount")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("errorCount")} aria-label={sortLabel("errorCount", "Errors")}>
              Errors{arrow("errorCount")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("avgDurationMs")} aria-label={sortLabel("avgDurationMs", "Avg Duration")}>
              Avg Duration{arrow("avgDurationMs")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("avgClientDurationMs")} aria-label={sortLabel("avgClientDurationMs", "Avg Client")}>
              Avg Client{arrow("avgClientDurationMs")}
            </button>
            <button type="button" className="data-table__th data-table__th--sortable data-table__th--numeric" onClick={() => handleSort("avgServerDurationMs")} aria-label={sortLabel("avgServerDurationMs", "Avg Server")}>
              Avg Server{arrow("avgServerDurationMs")}
            </button>
          </div>

          {sorted.length === 0 && clauses.length > 0 ? (
            <p className="explorer__status" role="status">No services match the current filter.</p>
          ) : sorted.map((row) => (
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
