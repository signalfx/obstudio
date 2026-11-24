// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RegisteredWorkspace, WorkspaceList } from "../api/client";
import { AppView } from "../AppView";
import type { TelemetryHandle } from "../telemetry";
import { WORKSPACES_REFRESH_MS } from "./useRepoSelection";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 36,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 36, end: (index + 1) * 36, size: 36 })),
    measureElement: () => undefined,
  }),
}));

const CHECKOUT: RegisteredWorkspace = { name: "checkout-api", folder: "checkout-api", service: "checkout" };
const PAYMENTS: RegisteredWorkspace = { name: "payments-api", folder: "payments-api", service: "payments" };
const INVENTORY: RegisteredWorkspace = { name: "inventory", folder: "inventory" };
const SCRATCH: RegisteredWorkspace = { name: "scratch", folder: "scratch" };

let workspaceList: WorkspaceList;
let fetchMock: ReturnType<typeof vi.fn>;

function telemetry(serviceNames: string[]): TelemetryHandle {
  return {
    state: {
      error: null,
      traces: [],
      metrics: [],
      logs: [],
      stats: { spanCount: 4, dataPointCount: 2, metricNameCount: 1, logCount: 1, traceCount: 2, serviceNames },
      validation: null,
    },
    paused: false,
    hasNewUpdates: false,
    pause: vi.fn(),
    resume: vi.fn(),
    toggle: vi.fn(),
  } as unknown as TelemetryHandle;
}

function respond(path: string): unknown {
  if (path === "/api/workspaces") return workspaceList;
  if (path === "/api/health") return { apiVersion: "v1", kind: "obstudio", configManager: false, endpoints: {} };
  if (path.startsWith("/api/audit/score")) return { available: false, source: "otel-audit.json", gaps: [], antiPatterns: [], recommendations: [] };
  if (path.startsWith("/api/query/stats/services")) {
    return ["checkout", "payments", "inventory"].map((name) => ({
      name, traceCount: 1, spanCount: 2, errorCount: 0, avgDurationMs: 5, avgClientDurationMs: null, avgServerDurationMs: null,
    }));
  }
  if (path.startsWith("/api/query/")) return [];
  return {};
}

function requestedPaths(): string[] {
  return fetchMock.mock.calls.map(([path]) => String(path));
}

function renderAt(search: string, serviceNames = ["checkout", "payments", "inventory"]) {
  window.history.replaceState({}, "", `/${search}`);
  return render(<AppView telemetry={telemetry(serviceNames)} />);
}

async function repoSelect(): Promise<HTMLSelectElement> {
  return (await screen.findByRole("combobox", { name: "Repo" })) as HTMLSelectElement;
}

beforeEach(() => {
  workspaceList = { active: "checkout-api", workspaces: [CHECKOUT, PAYMENTS] };
  fetchMock = vi.fn(async (path: string) => ({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => respond(path),
  }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState({}, "", "/");
});

describe("repo switcher", () => {
  it("stays hidden with one registered repo and leaves telemetry unscoped", async () => {
    workspaceList = { active: "checkout-api", workspaces: [CHECKOUT] };
    renderAt("?tab=traces");

    await waitFor(() => expect(requestedPaths()).toContain("/api/workspaces"));
    expect(screen.queryByRole("combobox", { name: "Repo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove filter spanServiceName" })).toBeNull();
  });

  it("lists the registered repos and starts on the active one", async () => {
    renderAt("?tab=traces");

    const select = await repoSelect();
    expect(select.value).toBe("checkout-api");
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual(["checkout-api", "payments-api"]);
    // The accessible name survives the narrow layout, which only hides the label visually.
    expect(select.closest("label")?.textContent).toContain("Repo");
  });

  it("scopes the telemetry tabs to the selected repo's service and switches with the repo", async () => {
    const user = userEvent.setup();
    renderAt("?tab=traces");

    const chip = await screen.findByRole("button", { name: "Remove filter spanServiceName" });
    expect(chip.textContent).toContain("Any span service = checkout");
    await waitFor(() => expect(requestedPaths().some((path) =>
      path.startsWith("/api/query/traces?") && path.includes(encodeURIComponent("filter[spanServiceName][eq]") + "=checkout"))).toBe(true));

    const select = await repoSelect();
    select.focus();
    expect(document.activeElement).toBe(select);
    await user.selectOptions(select, "payments-api");

    expect(select.value).toBe("payments-api");
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove filter spanServiceName" }).textContent).toContain("Any span service = payments"));
    expect(screen.getAllByRole("button", { name: "Remove filter spanServiceName" })).toHaveLength(1);
    expect(new URLSearchParams(window.location.search).get("repo")).toBe("payments-api");
    await waitFor(() => expect(requestedPaths().some((path) =>
      path.startsWith("/api/query/traces?") && path.includes("=payments"))).toBe(true));
  });

  it("lets the repo chip be removed to see every service", async () => {
    const user = userEvent.setup();
    renderAt("?tab=logs");

    await user.click(await screen.findByRole("button", { name: "Remove filter serviceName" }));
    expect(screen.queryByRole("button", { name: "Remove filter serviceName" })).toBeNull();
  });

  it("filters the Services tab to the repo's service", async () => {
    renderAt("?tab=services");

    await screen.findByRole("button", { name: "Remove filter serviceName" });
    await waitFor(() => expect(screen.getAllByText("checkout").length).toBeGreaterThan(0));
    expect(screen.queryByText("payments")).toBeNull();
    expect(screen.queryByText("inventory")).toBeNull();
  });

  it("reads the selected repo's audit and dashboards", async () => {
    const user = userEvent.setup();
    const view = renderAt("?tab=overview");

    await user.selectOptions(await repoSelect(), "payments-api");
    await waitFor(() => expect(requestedPaths()).toContain("/api/audit/score?workspace=payments-api"));

    view.unmount();
    renderAt("?tab=dashboards&repo=payments-api");
    await waitFor(() => expect(requestedPaths()).toContain("/api/dashboards/preview?workspace=payments-api"));
    expect(requestedPaths()).toContain("/api/workspace?workspace=payments-api");
  });

  it("restores a repo picked in the URL", async () => {
    renderAt("?tab=metrics&repo=payments-api");

    expect((await repoSelect()).value).toBe("payments-api");
    expect((await screen.findByRole("button", { name: "Remove filter serviceName" })).textContent).toContain("Service = payments");
  });

  it("falls back to the active repo when the picked one is no longer registered", async () => {
    renderAt("?tab=traces&repo=gone");

    await waitFor(async () => expect((await repoSelect()).value).toBe("checkout-api"));
    await waitFor(() => expect(new URLSearchParams(window.location.search).has("repo")).toBe(false));
  });

  it("uses a service named like the repo folder when the repo has no audit", async () => {
    workspaceList = { active: "inventory", workspaces: [CHECKOUT, INVENTORY] };
    renderAt("?tab=traces");

    expect((await screen.findByRole("button", { name: "Remove filter spanServiceName" })).textContent).toContain("Any span service = inventory");
    expect(document.querySelector(".repo-scope-note")?.textContent).toBe("");
  });

  it("shows every service with a note when a repo has no audit and no matching service", async () => {
    workspaceList = { active: "scratch", workspaces: [CHECKOUT, SCRATCH] };
    renderAt("?tab=traces");

    await waitFor(() => expect(screen.getByText("No audit for scratch yet, so all services are shown.")).toBeTruthy());
    expect(screen.queryByRole("button", { name: "Remove filter spanServiceName" })).toBeNull();
  });

  it("warns when another repo reports the same service", async () => {
    const twin: RegisteredWorkspace = { name: "checkout-web", folder: "checkout-web", service: "checkout" };
    workspaceList = { active: "checkout-api", workspaces: [CHECKOUT, twin] };
    renderAt("?tab=metrics");

    await waitFor(() => expect(screen.getByText(
      "checkout-web also reports service checkout, so this view can include its telemetry too.",
    )).toBeTruthy());
  });

  it("is not offered on the Cloud tab, which does not depend on a repo", async () => {
    renderAt("?tab=cloud");

    await waitFor(() => expect(requestedPaths()).toContain("/api/workspaces"));
    expect(screen.queryByRole("combobox", { name: "Repo" })).toBeNull();
  });

  it("picks up a repo that registers after the page loaded", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    workspaceList = { active: "checkout-api", workspaces: [CHECKOUT] };
    renderAt("?tab=traces");
    await waitFor(() => expect(requestedPaths()).toContain("/api/workspaces"));
    expect(screen.queryByRole("combobox", { name: "Repo" })).toBeNull();

    workspaceList = { active: "payments-api", workspaces: [CHECKOUT, PAYMENTS] };
    await act(async () => {
      vi.advanceTimersByTime(WORKSPACES_REFRESH_MS);
    });

    expect((await repoSelect()).value).toBe("payments-api");
  });
});
