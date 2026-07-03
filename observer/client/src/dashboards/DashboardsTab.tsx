import React, { useEffect, useRef, useState } from "react";
import { DashboardGrid } from "./DashboardGrid";
import { DashboardPanel, OtlpEndpointContext } from "./DashboardPanel";
import { useDashboardPreview } from "./useDashboardPreview";
import type { PreviewPanel, PreviewResponse } from "./types";

/** Stable panel identity — stored instead of the panel object to avoid stale data. */
interface PanelId {
  groupIdx: number;
  dashIdx: number;
  panelLabel: string;
}

function resolvePanel(data: PreviewResponse | null, id: PanelId): PreviewPanel | null {
  const group = data?.groups[id.groupIdx];
  const dash = group?.dashboards[id.dashIdx];
  return dash?.panels.find((p) => p.label === id.panelLabel) ?? null;
}

const TIME_WINDOWS = [
  { label: "1 min",  ms: 60_000 },
  { label: "5 min",  ms: 5 * 60_000 },
  { label: "1 hour", ms: 60 * 60_000 },
  { label: "24 hrs", ms: 24 * 60 * 60_000 },
  { label: "All",    ms: 0 },
] as const;

const DEFAULT_WINDOW_MS = 60_000;

/** Shape of the fields we read from GET /api/health. */
interface HealthResponse {
  endpoints?: { otlpHttp?: string; otlpGrpc?: string; rest?: string; mcp?: string };
}

/**
 * Fetch the OTLP/HTTP receiver endpoint from /api/health once on mount so the
 * unmatched-panel hint names the actually-configured receiver instead of a
 * hardcoded port (#19). Returns `null` until loaded or on failure; the hint
 * falls back to a port-free message in that case.
 */
function useOtlpEndpoint(): string | null {
  const [endpoint, setEndpoint] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal })
      .then((r) => (r.ok ? (r.json() as Promise<HealthResponse>) : null))
      .then((health) => {
        const otlpHttp = health?.endpoints?.otlpHttp;
        if (otlpHttp) setEndpoint(otlpHttp);
      })
      .catch(() => {
        /* leave null → hint uses the port-free fallback */
      });
    return () => controller.abort();
  }, []);
  return endpoint;
}

interface DashboardsTabProps {
  telemetryError?: string | null;
  paused?: boolean;
}

export function DashboardsTab({ telemetryError, paused = false }: DashboardsTabProps): React.ReactElement {
  const { data, loading, error, refresh } = useDashboardPreview(paused);
  const otlpEndpoint = useOtlpEndpoint();
  const [expandedId, setExpandedId] = useState<PanelId | null>(null);
  const expandedPanel = expandedId ? resolvePanel(data, expandedId) : null;
  const [windowMs, setWindowMs] = useState(DEFAULT_WINDOW_MS);
  // Refs for modal focus management (#5): the dialog element to trap focus
  // within, and the trigger to restore focus to on close.
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const lastTriggerRef = useRef<HTMLElement | null>(null);

  // Close expanded panel on Escape.
  useEffect(() => {
    if (!expandedId) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setExpandedId(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expandedId]);

  // Focus management for the expand modal (#5): remember the trigger, move
  // focus into the dialog on open, and restore it to the trigger on close so
  // keyboard users are not stranded.
  useEffect(() => {
    if (!expandedPanel) return;
    lastTriggerRef.current = (document.activeElement as HTMLElement | null) ?? null;
    // Focus the dialog itself (tabindex=-1) so the next Tab lands on the first
    // control inside it.
    dialogRef.current?.focus();
    const trigger = lastTriggerRef.current;
    return () => {
      // Restore focus to the element that opened the modal.
      if (trigger && typeof trigger.focus === "function") trigger.focus();
    };
  }, [expandedPanel]);

  // Trap Tab focus within the dialog while it is open (#5).
  const onDialogKeyDown = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    if (e.key !== "Tab") return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
    );
    if (focusable.length === 0) {
      e.preventDefault();
      dialog.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === dialog)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    // role="tabpanel" mirrors the Metrics/Traces/Logs/Services tabs so the
    // Dashboards content is exposed as a tab panel to assistive tech (#22). The
    // sibling tab buttons in AppView carry no ids, so we match their pattern
    // (role only) rather than reference a non-existent tab id via aria-labelledby.
    // The OTLP endpoint from /api/health is provided to every panel so the
    // unmatched-panel hint names the real receiver (#19).
    <OtlpEndpointContext.Provider value={otlpEndpoint}>
    <section className="dashboards-tab" role="tabpanel">
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

      {renderState({ data, loading, error, windowMs, onExpand: setExpandedId })}

      {expandedPanel ? (
        <div className="dashboard-expand-overlay" onClick={() => setExpandedId(null)}>
          {/* The dialog carries the modal role + an accessible name from the
              panel title, is focusable (tabindex=-1) so focus can move into it
              on open, and traps Tab within itself; focus is restored to the
              trigger on close by the effect above (#5). */}
          <div
            ref={dialogRef}
            className="dashboard-expand-panel"
            role="dialog"
            aria-modal="true"
            aria-label={`Expanded panel: ${expandedPanel.title || expandedPanel.label}`}
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={onDialogKeyDown}
          >
            {/* Close button lives in the header flow (not absolutely positioned)
                so it no longer overlaps the panel-type badge (#21). */}
            <div className="dashboard-expand-panel__head">
              <button
                type="button"
                className="dashboard-expand-close"
                aria-label="Close expanded panel"
                onClick={() => setExpandedId(null)}
              >
                ✕
              </button>
            </div>
            <DashboardPanel panel={expandedPanel} windowMs={windowMs} />
          </div>
        </div>
      ) : null}
    </section>
    </OtlpEndpointContext.Provider>
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
  onExpand: (id: PanelId) => void;
}): React.ReactElement {
  if (loading && !data) {
    return <div className="dashboards-tab__message">Loading dashboard preview…</div>;
  }
  // Only replace the whole view with the error message when there is no data to
  // show. A transient auto-refresh failure with data already rendered surfaces
  // as a small inline banner above the existing grid (see below) instead of
  // blanking a valid dashboard.
  if (error && !data) {
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
      {error ? (
        <div className="dashboards-tab__refresh-error" role="status">
          Refresh failed (showing last result): {error}
        </div>
      ) : null}
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
              <DashboardGrid
                panels={dashboard.panels}
                windowMs={windowMs}
                onExpand={(panel) => onExpand({ groupIdx: gi, dashIdx: di, panelLabel: panel.label })}
              />
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
