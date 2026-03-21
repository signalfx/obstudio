import { useState } from "react";
import { LogsTab } from "./logs";
import { MetricsTab } from "./metrics";
import type { TelemetryState } from "./telemetry";
import { TracesTab } from "./traces";

type AppViewProps = {
  telemetry: TelemetryState;
};

export function AppView({ telemetry }: AppViewProps) {
  const [activeTab, setActiveTab] = useState<"metrics" | "traces" | "logs">("metrics");

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
            <span className="pill">{telemetry.error === null ? "Live" : "Degraded"}</span>
            <span className="pill pill--muted">Telemetry stream</span>
          </div>
        </header>

        <div className="tab-bar" role="tablist" aria-label="Observer sections">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "metrics"}
            className={activeTab === "metrics" ? "tab-button is-active" : "tab-button"}
            onClick={() => {
              setActiveTab("metrics");
            }}
          >
            <span className="tab-button__glyph" aria-hidden="true">
              M
            </span>
            Metrics
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "traces"}
            className={activeTab === "traces" ? "tab-button is-active" : "tab-button"}
            onClick={() => {
              setActiveTab("traces");
            }}
          >
            <span className="tab-button__glyph" aria-hidden="true">
              T
            </span>
            Traces
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "logs"}
            className={activeTab === "logs" ? "tab-button is-active" : "tab-button"}
            onClick={() => {
              setActiveTab("logs");
            }}
          >
            <span className="tab-button__glyph" aria-hidden="true">
              L
            </span>
            Logs
          </button>
        </div>

        {activeTab === "metrics" ? <MetricsTab metrics={telemetry.metrics} telemetryError={telemetry.error} /> : null}
        {activeTab === "traces" ? <TracesTab telemetryError={telemetry.error} traces={telemetry.traces} /> : null}
        {activeTab === "logs" ? <LogsTab logs={telemetry.logs} /> : null}
      </section>
    </main>
  );
}
