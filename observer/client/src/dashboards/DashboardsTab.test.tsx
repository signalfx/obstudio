// @vitest-environment happy-dom

import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardsTab } from "./DashboardsTab";
import { makePreviewResponse } from "./testFixtures";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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
});
