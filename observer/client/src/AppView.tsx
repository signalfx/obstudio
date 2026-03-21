import { useState } from "react";
import type { User } from "@observer/shared";
import { LogsTab } from "./logs";
import { MetricsTab } from "./metrics";
import type { TelemetryState } from "./telemetry";
import { TracesTab } from "./traces";
import { UsersTab } from "./users";

type AppViewProps = {
  error: string | null;
  isLoading: boolean;
  telemetry: TelemetryState;
  users: User[];
};

export function AppView({ error, isLoading, telemetry, users }: AppViewProps) {
  const [activeTab, setActiveTab] = useState<"users" | "metrics" | "traces" | "logs">("metrics");

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
            <span className="pill">{isLoading ? "Syncing" : "Live"}</span>
            <span className="pill pill--muted">{users.length} users cached</span>
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
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "users"}
            className={activeTab === "users" ? "tab-button is-active" : "tab-button"}
            onClick={() => {
              setActiveTab("users");
            }}
          >
            <span className="tab-button__glyph" aria-hidden="true">
              U
            </span>
            Users
          </button>
        </div>

        {activeTab === "users" ? <UsersTab error={error} isLoading={isLoading} users={users} /> : null}
        {activeTab === "metrics" ? <MetricsTab metrics={telemetry.metrics} telemetryError={telemetry.error} /> : null}
        {activeTab === "traces" ? <TracesTab telemetryError={telemetry.error} traces={telemetry.traces} /> : null}
        {activeTab === "logs" ? <LogsTab logs={telemetry.logs} /> : null}
      </section>
    </main>
  );
}
