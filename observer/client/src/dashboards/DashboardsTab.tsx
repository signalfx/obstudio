import React, { useEffect, useState } from "react";
import { DashboardGrid } from "./DashboardGrid";
import { DashboardPanel } from "./DashboardPanel";
import { useDashboardPreview } from "./useDashboardPreview";
import type { PreviewPanel } from "./types";

const TIME_WINDOWS = [
  { label: "1 min",  ms: 60_000 },
  { label: "5 min",  ms: 5 * 60_000 },
  { label: "1 hour", ms: 60 * 60_000 },
  { label: "24 hrs", ms: 24 * 60 * 60_000 },
  { label: "All",    ms: 0 },
] as const;

const DEFAULT_WINDOW_MS = 60_000;

interface DashboardsTabProps {
  telemetryError?: string | null;
  paused?: boolean;
}

export function DashboardsTab({ telemetryError, paused = false }: DashboardsTabProps): React.ReactElement {
  const { data, loading, error, refresh } = useDashboardPreview(paused);
  const [expandedPanel, setExpandedPanel] = useState<PreviewPanel | null>(null);
  const [windowMs, setWindowMs] = useState(DEFAULT_WINDOW_MS);

  // Close expanded panel on Escape.
  useEffect(() => {
    if (!expandedPanel) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setExpandedPanel(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expandedPanel]);

  return (
    <div className="dashboards-tab">
      <div className="dashboards-tab__bar">
        <span className="dashboards-tab__badge" title="SignalFlow executes on Splunk's backend; this previews layout and metric targeting using local OTLP data.">
          Approximate · local-data preview
        </span>
        <div className="dashboards-tab__bar-actions">
          {data?.generatedAt ? (
            <span className="dashboards-tab__hint">generated {data.generatedAt}</span>
          ) : null}
          <span className="dashboards-tab__hint dashboards-tab__hint--live">
            {paused ? "⏸ paused" : "↻ auto-refresh 5s"}
          </span>
          <select
            className="dashboards-tab__window-select"
            value={windowMs}
            onChange={(e) => setWindowMs(Number(e.target.value))}
            aria-label="Time window"
          >
            {TIME_WINDOWS.map((w) => (
              <option key={w.ms} value={w.ms}>{w.label}</option>
            ))}
          </select>
          <button type="button" className="pill pill--small pill--muted" onClick={refresh}>
            Refresh
          </button>
        </div>
      </div>

      {telemetryError ? <div className="pill pill--error">{telemetryError}</div> : null}

      {renderState({ data, loading, error, windowMs, onExpand: setExpandedPanel })}

      {expandedPanel ? (
        <div className="dashboard-expand-overlay" role="dialog" aria-modal="true" onClick={() => setExpandedPanel(null)}>
          <div className="dashboard-expand-panel" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="dashboard-expand-close"
              aria-label="Close"
              onClick={() => setExpandedPanel(null)}
            >
              ✕
            </button>
            <DashboardPanel panel={expandedPanel} windowMs={windowMs} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function renderState({
  data,
  loading,
  error,
  windowMs,
  onExpand,
}: {
  data: ReturnType<typeof useDashboardPreview>["data"];
  loading: boolean;
  error: string | null;
  windowMs: number;
  onExpand: (panel: PreviewPanel) => void;
}): React.ReactElement {
  if (loading && !data) {
    return <div className="dashboards-tab__message">Loading dashboard preview…</div>;
  }
  if (error) {
    return <div className="dashboards-tab__message dashboards-tab__message--error">Failed to load preview: {error}</div>;
  }
  if (!data || !data.available) {
    return (
      <div className="dashboards-tab__empty">
        <span className="dashboards-tab__empty-title">No dashboard preview yet</span>
        <span className="dashboards-tab__empty-hint">
          {data?.message ?? "Run $splunk-dashboard to generate .observe/dashboards.preview.json."}
        </span>
      </div>
    );
  }

  return (
    <div className="dashboards-tab__groups">
      {data.groups.map((group, gi) => (
        <section key={`${group.name}-${gi}`} className="dashboards-tab__group">
          <h2 className="dashboards-tab__group-name">{group.name}</h2>
          {group.description ? <p className="dashboards-tab__group-desc">{group.description}</p> : null}
          {group.dashboards.map((dashboard, di) => (
            <div key={`${dashboard.name}-${di}`} className="dashboards-tab__dashboard">
              <h3 className="dashboards-tab__dashboard-name">{dashboard.name}</h3>
              {dashboard.description ? (
                <p className="dashboards-tab__dashboard-desc">{dashboard.description}</p>
              ) : null}
              <DashboardGrid panels={dashboard.panels} windowMs={windowMs} onExpand={onExpand} />
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
