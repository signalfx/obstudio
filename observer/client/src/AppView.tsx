import React, { useState, useMemo, useCallback } from "react";
import { LogsTab } from "./logs";
import { MetricsTab } from "./metrics";
import type { TelemetryHandle } from "./telemetry";
import { TracesTab } from "./traces";
import { KeyboardHelp } from "./components/KeyboardHelp";
import { FindingsTab } from "./components/FindingsTab";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import { buildValidationIndex, buildValidationIssues } from "./validation/utils";

interface AppViewProps {
  telemetry: TelemetryHandle;
}

type AppTab = "metrics" | "traces" | "logs" | "validation";

/** Main application view with tab navigation, summary cards, and live/paused toggle. */
export function AppView({ telemetry }: AppViewProps): React.ReactElement {
  const [activeTab, setActiveTab] = useState<AppTab>(() => initialTabFromLocation());
  const [showHelp, setShowHelp] = useState(false);

  const { state, paused, hasNewUpdates, resume, toggle } = telemetry;
  const validationSummary = state.validation?.summary ?? null;
  const validationFindings = state.validation?.findings ?? [];
  const backendValidationIssues = state.validation?.issues ?? [];
  const validationIndex = useMemo(() => buildValidationIndex(validationFindings), [validationFindings]);
  const validationIssues = useMemo(
    () => (backendValidationIssues.length > 0 || validationFindings.length === 0
      ? backendValidationIssues
      : buildValidationIssues(validationFindings)),
    [backendValidationIssues, validationFindings],
  );

  const switchTab = useCallback((tab: AppTab) => {
    setActiveTab(tab);
  }, []);

  const shortcuts = useMemo(() => ({
    "?": () => setShowHelp((v) => !v),
    p: () => toggle(),
    "1": () => switchTab("metrics"),
    "2": () => switchTab("traces"),
    "3": () => switchTab("logs"),
    "4": () => switchTab("validation"),
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
            <button
              className="title-bar__help"
              onClick={() => setShowHelp(true)}
              title="Keyboard shortcuts (?)"
              type="button"
              aria-label="Keyboard shortcuts"
            >
              ?
            </button>
          </div>
        </header>

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
              <div className="summary-card" title={state.stats.serviceNames.join(", ")}>
                <p className="summary-card__label">Services</p>
                <p className="summary-card__value">{state.stats.serviceNames.length}</p>
                <p className="summary-card__services">
                  {state.stats.serviceNames.map((name) => (
                    <span key={name} className="summary-card__service-tag">{name}</span>
                  ))}
                </p>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="tab-bar" role="tablist" aria-label="Observer sections">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "metrics"}
            aria-label={formatTabAriaLabel("Metrics", state.stats?.metricNameCount, "metric name", "metric names")}
            className={activeTab === "metrics" ? "tab-button is-active" : "tab-button"}
            onClick={() => switchTab("metrics")}
          >
            Metrics
            {state.stats?.metricNameCount ? <span className="tab-button__count" aria-hidden="true">{state.stats.metricNameCount}</span> : null}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "traces"}
            aria-label={formatTabAriaLabel("Traces", state.stats?.traceCount, "trace", "traces")}
            className={activeTab === "traces" ? "tab-button is-active" : "tab-button"}
            onClick={() => switchTab("traces")}
          >
            Traces
            {state.stats?.traceCount ? <span className="tab-button__count" aria-hidden="true">{state.stats.traceCount}</span> : null}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "logs"}
            aria-label={formatTabAriaLabel("Logs", state.stats?.logCount, "log", "logs")}
            className={activeTab === "logs" ? "tab-button is-active" : "tab-button"}
            onClick={() => switchTab("logs")}
          >
            Logs
            {state.stats?.logCount ? <span className="tab-button__count" aria-hidden="true">{state.stats.logCount}</span> : null}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "validation"}
            aria-label={formatTabAriaLabel("Validation", validationIssues.length, "issue", "issues")}
            className={activeTab === "validation" ? "tab-button is-active" : "tab-button"}
            onClick={() => switchTab("validation")}
          >
            Validation
            {validationIssues.length > 0 ? <span className="tab-button__count tab-button__count--warn" aria-hidden="true">{validationIssues.length}</span> : null}
          </button>
        </div>

        {activeTab === "metrics" ? (
          <MetricsTab
            metrics={state.metrics ?? []}
            telemetryError={state.error}
          />
        ) : null}
        {activeTab === "traces" ? (
          <TracesTab
            telemetryError={state.error}
            traces={state.traces ?? []}
            validationFindings={validationFindings}
            validationIndex={validationIndex}
          />
        ) : null}
        {activeTab === "logs" ? (
          <LogsTab
            logs={state.logs ?? []}
          />
        ) : null}
        {activeTab === "validation" ? (
          <FindingsTab
            issues={validationIssues}
            summary={validationSummary}
          />
        ) : null}
      </section>

      {showHelp ? <KeyboardHelp onClose={() => setShowHelp(false)} /> : null}
    </main>
  );
}

function initialTabFromLocation(): AppTab {
  if (typeof window === "undefined") return "metrics";
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  switch (tab) {
    case "metrics":
    case "traces":
    case "logs":
    case "validation":
      return tab;
    default:
      return "metrics";
  }
}

function formatTabAriaLabel(label: string, count: number | undefined, singular: string, plural: string): string {
  if (!count || count <= 0) {
    return label;
  }
  return `${label}, ${count} ${count === 1 ? singular : plural}`;
}
