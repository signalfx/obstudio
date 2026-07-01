// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardsTab } from "./DashboardsTab";
import { makePreviewResponse } from "./testFixtures";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.useRealTimers();
});

function stubFetchOnce(payload: unknown): ReturnType<typeof vi.fn> {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, statusText: "OK", json: async () => payload });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("DashboardsTab", () => {
  it("always shows the approximate badge", async () => {
    stubFetchOnce(makePreviewResponse({ available: false, groups: [], message: "Run $splunk-dashboard." }));
    render(<DashboardsTab />);
    expect(screen.getByText(/Approximate · local-data preview/i)).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/No dashboard preview yet/i)).toBeTruthy());
  });

  it("renders the available:false empty state with the spec message", async () => {
    stubFetchOnce(makePreviewResponse({ available: false, groups: [], message: "Run $splunk-dashboard to generate it." }));
    render(<DashboardsTab />);

    await waitFor(() => expect(screen.getByText(/No dashboard preview yet/i)).toBeTruthy());
    expect(screen.getByText(/Run \$splunk-dashboard to generate it\./i)).toBeTruthy();
  });

  it("renders group, dashboard, and panel headings when populated", async () => {
    stubFetchOnce(makePreviewResponse());
    const { container } = render(<DashboardsTab />);

    await waitFor(() => expect(screen.getByText("Checkout RED")).toBeTruthy());
    // "checkout" also appears as a chart series annotation, so target the group heading.
    expect(container.querySelector(".dashboards-tab__group-name")?.textContent).toBe("checkout");
    expect(screen.getByText("P99 Latency")).toBeTruthy();
  });

  it("re-fetches when Refresh is clicked", async () => {
    const fetchFn = stubFetchOnce(makePreviewResponse());
    render(<DashboardsTab />);

    await waitFor(() => expect(screen.getByText("Checkout RED")).toBeTruthy());
    const callsBefore = fetchFn.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));

    await waitFor(() => expect(fetchFn.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("surfaces a telemetry error pill when provided", async () => {
    stubFetchOnce(makePreviewResponse());
    render(<DashboardsTab telemetryError="ingest stalled" />);
    expect(screen.getByText("ingest stalled")).toBeTruthy();
  });

  it("F7: a failing refresh keeps the grid and surfaces the error inline (does not blank the dashboard)", async () => {
    // First fetch succeeds (renders the grid); the next fetch (the Refresh
    // click) rejects. The grid must stay rendered with a small inline error.
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: "OK", json: async () => makePreviewResponse() })
      .mockRejectedValue(new Error("network down"));
    vi.stubGlobal("fetch", fetchFn);

    const { container } = render(<DashboardsTab paused />);

    await waitFor(() => expect(screen.getByText("Checkout RED")).toBeTruthy());
    expect(container.querySelector(".dashboard-grid")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));

    // The inline refresh-error banner appears...
    await waitFor(() => expect(container.querySelector(".dashboards-tab__refresh-error")).not.toBeNull());
    expect(screen.getByText(/network down/i)).toBeTruthy();

    // ...and the grid is STILL rendered (not replaced by the full-page error).
    expect(container.querySelector(".dashboard-grid")).not.toBeNull();
    expect(screen.getByText("Checkout RED")).toBeTruthy();
    expect(screen.queryByText(/Failed to load preview/i)).toBeNull();
  });

  it("M1: keeps the grid mounted during background auto-refresh (no teardown flash)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    // The fetch mock resolves immediately every call.
    const fetchFn = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => makePreviewResponse(),
    });
    vi.stubGlobal("fetch", fetchFn);

    const { container } = render(<DashboardsTab />);

    // Let the initial fetch microtasks flush.
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.getByText("Checkout RED")).toBeTruthy());

    const gridBefore = container.querySelector(".dashboard-grid");
    expect(gridBefore).not.toBeNull();

    const callsBefore = fetchFn.mock.calls.length;

    // Advance past the 5s auto-refresh interval.
    await act(async () => {
      vi.advanceTimersByTime(6_000);
      await Promise.resolve();
    });

    // A second fetch was triggered.
    expect(fetchFn.mock.calls.length).toBeGreaterThan(callsBefore);

    // Grid is still in the DOM — no loading-state teardown.
    const gridAfter = container.querySelector(".dashboard-grid");
    expect(gridAfter).not.toBeNull();

    // No "Loading…" message visible while data is present.
    expect(screen.queryByText(/Loading dashboard preview/i)).toBeNull();
  });
});
