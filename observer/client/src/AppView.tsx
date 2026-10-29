import React, { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { CloudTab, type CloudConnectionState } from "./cloud/CloudTab";
import { DashboardsTab } from "./dashboards";
import { LogsTab } from "./logs";
import { MetricsTab } from "./metrics";
import { OverviewTab } from "./overview";
import { ServicesTab } from "./services";
import type { TelemetryHandle } from "./telemetry";
import { TracesTab } from "./traces";
import { KeyboardHelp } from "./components/KeyboardHelp";
import { FindingsTab } from "./components/FindingsTab";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import { buildValidationIndex, buildValidationIssues } from "./validation/utils";

interface AppViewProps {
  telemetry: TelemetryHandle;
}

type AppTab = "overview" | "services" | "metrics" | "traces" | "logs" | "validation" | "dashboards" | "cloud";

/** Main application view with tab navigation, summary cards, and live/paused toggle. */
export function AppView({ telemetry }: AppViewProps): React.ReactElement {
  const [activeTab, setActiveTab] = useState<AppTab>(() => initialTabFromLocation());
  const tabsRef = useRef<HTMLDivElement>(null);
  const [tabOverflow, setTabOverflow] = useState({ left: false, right: false });
  const [showHelp, setShowHelp] = useState(false);
  const [cloudConnectionState, setCloudConnectionState] = useState<CloudConnectionState | null>(null);

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
    "1": () => switchTab("overview"),
    "2": () => switchTab("metrics"),
    "3": () => switchTab("traces"),
    "4": () => switchTab("logs"),
    "5": () => switchTab("services"),
    "6": () => switchTab("validation"),
    "7": () => switchTab("dashboards"),
    "8": () => switchTab("cloud"),
  }), [toggle, switchTab]);

  useKeyboardShortcuts(shortcuts);

  const updateTabOverflow = useCallback(() => {
    const container = tabsRef.current;
    if (!container) return;
    const left = container.scrollLeft > 1;
    const right = container.scrollLeft + container.clientWidth < container.scrollWidth - 1;
    setTabOverflow((prev) => (prev.left === left && prev.right === right ? prev : { left, right }));
  }, []);

  const scrollTabs = (direction: -1 | 1) => {
    const container = tabsRef.current;
    if (!container) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
    container.scrollBy({ left: direction * container.clientWidth * 0.7, behavior: reduceMotion ? "auto" : "smooth" });
  };

  useEffect(() => {
    function scrollActiveTabIntoView() {
      const tab = document.getElementById(`tab-${activeTab}`);
      const container = tabsRef.current;
      if (!tab || !container) return;
      const tabRect = tab.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      if (tabRect.right > containerRect.right) {
        container.scrollLeft += tabRect.right - containerRect.right;
      } else if (tabRect.left < containerRect.left) {
        container.scrollLeft -= containerRect.left - tabRect.left;
      }
    }

    scrollActiveTabIntoView();
    updateTabOverflow();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => requestAnimationFrame(() => {
      scrollActiveTabIntoView();
      updateTabOverflow();
    }));
    const container = tabsRef.current;
    if (container) {
      observer.observe(container);
      // Tab widths change when their counts appear, without resizing the strip.
      container.querySelectorAll('[role="tab"]').forEach((tab) => observer.observe(tab));
    }
    return () => observer.disconnect();
  }, [activeTab, updateTabOverflow]);

  return (
    <main className="app-shell">
      <section className="app-frame">
        <div className="tab-bar">
          {/* Mouse affordance only: keyboard users move through the tablist with
              the arrow keys, which already scrolls the active tab into view. */}
          {tabOverflow.left ? (
            <button
              type="button"
              className="tab-bar__scroll tab-bar__scroll--left"
              aria-label="Scroll tabs left"
              tabIndex={-1}
              onClick={() => scrollTabs(-1)}
            >
              <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="12" height="12">
                <path d="M10 3 5 8l5 5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          ) : null}
          <div
            ref={tabsRef}
            className="tab-bar__tabs"
            role="tablist"
            aria-label="Splunk Observability Studio sections"
            onScroll={updateTabOverflow}
            onKeyDown={(e) => {
              const order: AppTab[] = ["overview", "metrics", "traces", "logs", "services", "validation", "dashboards", "cloud"];
              const idx = order.indexOf(activeTab);
              let next = idx;
              if (e.key === "ArrowRight") next = (idx + 1) % order.length;
              else if (e.key === "ArrowLeft") next = (idx - 1 + order.length) % order.length;
              else if (e.key === "Home") next = 0;
              else if (e.key === "End") next = order.length - 1;
              else return;
              e.preventDefault();
              switchTab(order[next]);
              document.getElementById(`tab-${order[next]}`)?.focus();
            }}
          >
          <button
            id="tab-overview"
            type="button"
            role="tab"
            aria-selected={activeTab === "overview"}
            aria-controls={activeTab === "overview" ? "panel-overview" : undefined}
            aria-label="Overview"
            className={activeTab === "overview" ? "tab-button is-active" : "tab-button"}
            tabIndex={activeTab === "overview" ? 0 : -1}
            onClick={() => switchTab("overview")}
          >
            Overview
          </button>
          <button
            id="tab-metrics"
            type="button"
            role="tab"
            aria-selected={activeTab === "metrics"}
            aria-controls={activeTab === "metrics" ? "panel-metrics" : undefined}
            aria-label={formatTabAriaLabel("Metrics", state.metrics?.length, "metric", "metrics")}
            className={activeTab === "metrics" ? "tab-button is-active" : "tab-button"}
            tabIndex={activeTab === "metrics" ? 0 : -1}
            onClick={() => switchTab("metrics")}
          >
            Metrics
            {state.metrics?.length ? <span className="tab-button__count" aria-hidden="true">{state.metrics.length}</span> : null}
          </button>
          <button
            id="tab-traces"
            type="button"
            role="tab"
            aria-selected={activeTab === "traces"}
            aria-controls={activeTab === "traces" ? "panel-traces" : undefined}
            aria-label={formatTabAriaLabel("Traces", state.stats?.traceCount, "trace", "traces")}
            className={activeTab === "traces" ? "tab-button is-active" : "tab-button"}
            tabIndex={activeTab === "traces" ? 0 : -1}
            onClick={() => switchTab("traces")}
          >
            Traces
            {state.stats?.traceCount ? <span className="tab-button__count" aria-hidden="true">{state.stats.traceCount}</span> : null}
          </button>
          <button
            id="tab-logs"
            type="button"
            role="tab"
            aria-selected={activeTab === "logs"}
            aria-controls={activeTab === "logs" ? "panel-logs" : undefined}
            aria-label={formatTabAriaLabel("Logs", state.stats?.logCount, "log", "logs")}
            className={activeTab === "logs" ? "tab-button is-active" : "tab-button"}
            tabIndex={activeTab === "logs" ? 0 : -1}
            onClick={() => switchTab("logs")}
          >
            Logs
            {state.stats?.logCount ? <span className="tab-button__count" aria-hidden="true">{state.stats.logCount}</span> : null}
          </button>
          <button
            id="tab-services"
            type="button"
            role="tab"
            aria-selected={activeTab === "services"}
            aria-controls={activeTab === "services" ? "panel-services" : undefined}
            aria-label={formatTabAriaLabel("Services", state.stats?.serviceNames?.length, "service", "services")}
            className={activeTab === "services" ? "tab-button is-active" : "tab-button"}
            tabIndex={activeTab === "services" ? 0 : -1}
            onClick={() => switchTab("services")}
          >
            Services
            {state.stats?.serviceNames?.length ? <span className="tab-button__count" aria-hidden="true">{state.stats.serviceNames.length}</span> : null}
          </button>
          <button
            id="tab-validation"
            type="button"
            role="tab"
            aria-selected={activeTab === "validation"}
            aria-controls={activeTab === "validation" ? "panel-validation" : undefined}
            aria-label={formatTabAriaLabel("Validation", validationIssues.length, "issue", "issues")}
            className={activeTab === "validation" ? "tab-button is-active" : "tab-button"}
            tabIndex={activeTab === "validation" ? 0 : -1}
            onClick={() => switchTab("validation")}
          >
            Validation
            {validationIssues.length > 0 ? <span className="tab-button__count tab-button__count--warn" aria-hidden="true">{validationIssues.length}</span> : null}
          </button>
          <button
            id="tab-dashboards"
            type="button"
            role="tab"
            aria-selected={activeTab === "dashboards"}
            aria-controls={activeTab === "dashboards" ? "panel-dashboards" : undefined}
            aria-label="Dashboards"
            className={activeTab === "dashboards" ? "tab-button is-active" : "tab-button"}
            tabIndex={activeTab === "dashboards" ? 0 : -1}
            onClick={() => switchTab("dashboards")}
          >
            Dashboards
          </button>
          <button
            id="tab-cloud"
            type="button"
            role="tab"
            aria-selected={activeTab === "cloud"}
            aria-controls={activeTab === "cloud" ? "panel-cloud" : undefined}
            aria-label="Cloud"
            className={activeTab === "cloud" ? "tab-button is-active" : "tab-button"}
            tabIndex={activeTab === "cloud" ? 0 : -1}
            onClick={() => switchTab("cloud")}
          >
            Cloud
          </button>
          </div>
          {tabOverflow.right ? (
            <button
              type="button"
              className="tab-bar__scroll tab-bar__scroll--right"
              aria-label="Scroll tabs right"
              tabIndex={-1}
              onClick={() => scrollTabs(1)}
            >
              <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="12" height="12">
                <path d="m6 3 5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          ) : null}

          <div className="tab-bar__actions">
            {activeTab !== "cloud" ? (
              <>
                <span
                  role="status"
                  className={`stream-toggle stream-toggle--status stream-toggle--stream ${paused ? "stream-toggle--paused" : "stream-toggle--live"}`}
                >
                  <span className="stream-toggle__dot" aria-hidden="true" />
                  <span className="stream-toggle__label">{paused ? "Paused" : "Live"}</span>
                </span>
                <button
                  type="button"
                  className="tab-bar__icon-button"
                  onClick={toggle}
                  aria-label={paused ? "Resume live updates" : "Pause live updates"}
                  title={paused ? "Resume live updates (P)" : "Pause live updates (P)"}
                >
                  {paused ? (
                    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="10" height="10">
                      <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
                    </svg>
                  ) : (
                    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="10" height="10">
                      <rect x="3" y="2.5" width="3.5" height="11" rx="0.75" fill="currentColor" />
                      <rect x="9.5" y="2.5" width="3.5" height="11" rx="0.75" fill="currentColor" />
                    </svg>
                  )}
                </button>
              </>
            ) : (
              <span
                role="status"
                aria-live="polite"
                className={`stream-toggle stream-toggle--status ${
                  cloudConnectionState === "connected" ? "stream-toggle--live"
                  : cloudConnectionState === "configured" ? "stream-toggle--paused"
                  : "stream-toggle--muted"
                }`}
              >
                {cloudConnectionState !== null ? <span className="stream-toggle__dot" aria-hidden="true" /> : null}
                {cloudConnectionState === "connected" ? "Connected"
                  : cloudConnectionState === "configured" ? "Configured, not connected"
                  : cloudConnectionState === "disconnected" ? "Not connected"
                  : "Checking connection…"}
              </span>
            )}
            {activeTab !== "cloud" && paused && hasNewUpdates ? (
              <button
                className="pending-badge"
                onClick={resume}
                title="New updates available — click to resume live view"
              >
                updates available — resume
              </button>
            ) : null}
            {activeTab !== "cloud" && state.error !== null ? (
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

        {activeTab === "overview" ? (
          <OverviewTab onOpenCloud={() => switchTab("cloud")} />
        ) : null}
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
        {activeTab === "dashboards" ? (
          <DashboardsTab telemetryError={state.error} paused={paused} />
        ) : null}
        {activeTab === "cloud" ? <CloudTab onConnectionChange={setCloudConnectionState} /> : null}
      </section>

      {showHelp ? <KeyboardHelp onClose={() => setShowHelp(false)} /> : null}
    </main>
  );
}

function initialTabFromLocation(): AppTab {
  if (typeof window === "undefined") return "overview";
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  switch (tab) {
    case "overview":
    case "services":
    case "metrics":
    case "traces":
    case "logs":
    case "validation":
    case "dashboards":
    case "cloud":
      return tab;
    default:
      return "overview";
  }
}

function formatTabAriaLabel(label: string, count: number | undefined, singular: string, plural: string): string {
  if (!count || count <= 0) {
    return label;
  }
  return `${label}, ${count} ${count === 1 ? singular : plural}`;
}
