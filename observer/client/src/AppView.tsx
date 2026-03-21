import { useState } from "react";
import type { User } from "@observer/shared";
import { MetricsTab } from "./metrics";
import { TracesTab } from "./traces";
import { UsersTab } from "./users";

type AppViewProps = {
  error: string | null;
  isLoading: boolean;
  users: User[];
};

export function AppView({ error, isLoading, users }: AppViewProps) {
  const [activeTab, setActiveTab] = useState<"users" | "metrics" | "traces">("users");

  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Observer</p>
        <h1>Shared types now drive both the API and the React client.</h1>
        <p className="lede">
          The server returns a typed user list from <code>/api/users</code> and
          streams updates from <code>/api/ws/</code>; this client renders each
          new list as it arrives.
        </p>
        <div className="tab-bar" role="tablist" aria-label="Observer sections">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "users"}
            className={activeTab === "users" ? "tab-button is-active" : "tab-button"}
            onClick={() => {
              setActiveTab("users");
            }}
          >
            Users
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "metrics"}
            className={activeTab === "metrics" ? "tab-button is-active" : "tab-button"}
            onClick={() => {
              setActiveTab("metrics");
            }}
          >
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
            Traces
          </button>
        </div>
        {activeTab === "users" ? <UsersTab error={error} isLoading={isLoading} users={users} /> : null}
        {activeTab === "metrics" ? <MetricsTab /> : null}
        {activeTab === "traces" ? <TracesTab /> : null}
      </section>
    </main>
  );
}
