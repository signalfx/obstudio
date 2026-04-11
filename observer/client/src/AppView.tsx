import React, { useState, useMemo, useCallback } from "react";
import { LogsTab } from "./logs";
import { MetricsTab } from "./metrics";
import type { TelemetryHandle } from "./telemetry";
import { TracesTab } from "./traces";
import { KeyboardHelp } from "./components/KeyboardHelp";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";

interface AppViewProps {
  telemetry: TelemetryHandle;
}

/** Main application view with tab navigation, summary cards, and live/paused toggle. */
export function AppView({ telemetry }: AppViewProps): React.ReactElement {
  const [activeTab, setActiveTab] = useState<"metrics" | "traces" | "logs">("metrics");
  const [showHelp, setShowHelp] = useState(false);

  const { state, paused, hasNewUpdates, pause, resume, toggle } = telemetry;

  // pause() is already idempotent (no-op when already paused)
  // so pass it directly — no wrapper needed.

  const switchTab = useCallback((tab: "metrics" | "traces" | "logs") => {
    setActiveTab(tab);
  }, []);

  const shortcuts = useMemo(() => ({
    "?": () => setShowHelp((v) => !v),
    p: () => toggle(),
    "1": () => switchTab("metrics"),
    "2": () => switchTab("traces"),
    "3": () => switchTab("logs"),
  }), [toggle, switchTab]);

  useKeyboardShortcuts(shortcuts);

  return (
    <main className="app-shell">
      <section className="app-frame">
        <header className="title-bar">
          <div className="title-bar__brand">
            <span className="title-bar__dot" aria-hidden="true" />
            <div>
              <p className="title-bar__eyebrow">Observer</p>
              <h1 className="title-bar__title">Telemetry Explorer</h1>
            </div>
          </div>
          <div className="title-bar__meta">
            {/* Pause / Resume toggle */}
            <button
              className={`stream-toggle ${paused ? "stream-toggle--paused" : "stream-toggle--live"}`}
              onClick={toggle}
              title={paused ? "Resume live updates (p)" : "Pause live updates (p)"}
            >
              <span className="stream-toggle__icon" aria-hidden="true">
                {paused ? "\u25B6" : "\u275A\u275A"}
              </span>
              {paused ? "Paused" : "Live"}
            </button>
            {/* Pending updates badge */}
            {paused && hasNewUpdates ? (
              <button className="pending-badge" onClick={resume} title="Click to apply updates and resume">
                new updates available
              </button>
            ) : null}
            {state.error !== null ? (
              <span className="pill pill--error">{state.error}</span>
            ) : null}
            <span className="pill pill--muted">Telemetry stream</span>
            <button
              className="pill pill--muted"
              onClick={() => setShowHelp(true)}
              title="Keyboard shortcuts (?)"
              style={{ cursor: "pointer", border: "1px solid var(--border)" }}
            >
              ?
            </button>
          </div>
        </header>

        {/* Summary cards — hidden when no data */}
        {(state.stats?.traceCount || state.stats?.metricNameCount || state.stats?.logCount) ? (
          <div className="metric-summary">
            {state.stats.traceCount ? (
              <div className="summary-card">
                <p className="summary-card__label">Traces</p>
                <p className="summary-card__value">{state.stats.traceCount}</p>
              </div>
            ) : null}
            {state.stats.metricNameCount ? (
              <div className="summary-card">
                <p className="summary-card__label">Metrics</p>
                <p className="summary-card__value">{state.stats.metricNameCount}</p>
              </div>
            ) : null}
            {state.stats.logCount ? (
              <div className="summary-card">
                <p className="summary-card__label">Logs</p>
                <p className="summary-card__value">{state.stats.logCount}</p>
              </div>
            ) : null}
            {state.stats.serviceNames?.length ? (
              <div className="summary-card">
                <p className="summary-card__label">Services</p>
                <p className="summary-card__value">{state.stats.serviceNames.length}</p>
                <p className="summary-card__meta">{state.stats.serviceNames.join(", ")}</p>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="tab-bar" role="tablist" aria-label="Observer sections">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "metrics"}
            className={activeTab === "metrics" ? "tab-button is-active" : "tab-button"}
            onClick={() => switchTab("metrics")}
          >
            <span className="tab-button__glyph" aria-hidden="true">M</span>
            Metrics
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "traces"}
            className={activeTab === "traces" ? "tab-button is-active" : "tab-button"}
            onClick={() => switchTab("traces")}
          >
            <span className="tab-button__glyph" aria-hidden="true">T</span>
            Traces
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "logs"}
            className={activeTab === "logs" ? "tab-button is-active" : "tab-button"}
            onClick={() => switchTab("logs")}
          >
            <span className="tab-button__glyph" aria-hidden="true">L</span>
            Logs
          </button>
        </div>

        {activeTab === "metrics" ? <MetricsTab metrics={state.metrics ?? []} telemetryError={state.error} /> : null}
        {activeTab === "traces" ? <TracesTab telemetryError={state.error} traces={state.traces ?? []} onInteract={pause} /> : null}
        {activeTab === "logs" ? <LogsTab logs={state.logs ?? []} onInteract={pause} /> : null}
      </section>

      {showHelp ? <KeyboardHelp onClose={() => setShowHelp(false)} /> : null}
    </main>
  );
}
