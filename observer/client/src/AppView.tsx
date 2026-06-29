import React, { useState, useMemo, useCallback } from "react";
import { LogsTab } from "./logs";
import { MetricsTab } from "./metrics";
import { ServicesTab } from "./services";
import { CloudTab } from "./cloud";
import type { TelemetryHandle } from "./telemetry";
import { TracesTab } from "./traces";
import { KeyboardHelp } from "./components/KeyboardHelp";
import { FindingsTab } from "./components/FindingsTab";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import { buildValidationIndex, buildValidationIssues } from "./validation/utils";

interface AppViewProps {
  telemetry: TelemetryHandle;
}

type AppTab = "services" | "metrics" | "traces" | "logs" | "validation" | "cloud";

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
    "4": () => switchTab("services"),
    "5": () => switchTab("validation"),
    "6": () => switchTab("cloud"),
  }), [toggle, switchTab]);

  useKeyboardShortcuts(shortcuts);

  return (
    <main className="app-shell">
      <section className="app-frame">
        <div className="tab-bar">
          <div className="tab-bar__tabs" role="tablist" aria-label="Observer sections">
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
            aria-selected={activeTab === "services"}
            aria-label={formatTabAriaLabel("Services", state.stats?.serviceNames?.length, "service", "services")}
            className={activeTab === "services" ? "tab-button is-active" : "tab-button"}
            onClick={() => switchTab("services")}
          >
            Services
            {state.stats?.serviceNames?.length ? <span className="tab-button__count" aria-hidden="true">{state.stats.serviceNames.length}</span> : null}
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
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "cloud"}
            aria-label="Cloud"
            className={activeTab === "cloud" ? "tab-button is-active" : "tab-button"}
            onClick={() => switchTab("cloud")}
          >
            Cloud
          </button>
          </div>

          <div className="tab-bar__actions">
            <button
              className={`stream-toggle ${paused ? "stream-toggle--paused" : "stream-toggle--live"}`}
              onClick={toggle}
              title={paused ? "Resume live updates (p)" : "Pause live updates (p)"}
            >
              <span className="stream-toggle__icon" aria-hidden="true">
                {paused ? "▶" : "❚❚"}
              </span>
              {paused ? "Paused" : "Live"}
            </button>
            {paused && hasNewUpdates ? (
              <button
                className="pending-badge"
                onClick={resume}
                title="New updates available — click to resume live view"
              >
                updates available — resume
              </button>
            ) : null}
            {state.error !== null ? (
              <span className="pill pill--error">{state.error}</span>
            ) : null}
            <button
              className="tab-bar__help"
              onClick={() => setShowHelp(true)}
              title="Keyboard shortcuts (?)"
              type="button"
              aria-label="Keyboard shortcuts"
            >
              ?
            </button>
          </div>
        </div>

        {activeTab === "services" ? (
          <ServicesTab
            serviceNames={state.stats?.serviceNames ?? []}
          />
        ) : null}
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
        {activeTab === "cloud" ? (
          <CloudTab />
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
    case "services":
    case "metrics":
    case "traces":
    case "logs":
    case "validation":
    case "cloud":
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
