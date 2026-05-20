// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ServicesTab } from "./ServicesTab";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function makeStats(overrides: Partial<{
  name: string;
  traceCount: number;
  spanCount: number;
  errorCount: number;
  avgDurationMs: number | null;
  avgClientDurationMs: number | null;
  avgServerDurationMs: number | null;
}> = {}) {
  return {
    name: "checkout",
    traceCount: 3,
    spanCount: 12,
    errorCount: 0,
    avgDurationMs: 42.5,
    avgClientDurationMs: 10.0,
    avgServerDurationMs: 32.5,
    ...overrides,
  };
}

describe("ServicesTab", () => {
  it("fetches service stats from /api/query/stats/services on mount", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [makeStats()],
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      render(<ServicesTab serviceNames={["checkout"]} />);
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/query/stats/services", expect.any(Object));
  });

  it("renders a row for each service returned by the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        makeStats({ name: "checkout", traceCount: 2, spanCount: 8, errorCount: 0 }),
        makeStats({ name: "payments", traceCount: 2, spanCount: 4, errorCount: 1 }),
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      render(<ServicesTab serviceNames={["checkout", "payments"]} />);
    });

    expect(screen.getByText("checkout")).toBeTruthy();
    expect(screen.getByText("payments")).toBeTruthy();
  });

  it("shows traceCount for a child service that does not own any root span", async () => {
    // payments appears only as a child service — backend still returns traceCount=2
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        makeStats({ name: "frontend", traceCount: 2, spanCount: 2 }),
        makeStats({ name: "payments", traceCount: 2, spanCount: 4 }),
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = await act(async () =>
      render(<ServicesTab serviceNames={["frontend", "payments"]} />),
    );

    const rows = container.querySelectorAll(".services-table__row");
    expect(rows.length).toBe(2);

    const paymentsRow = Array.from(rows).find((r) => r.textContent?.includes("payments"));
    expect(paymentsRow).toBeTruthy();
    // traceCount "2" must be visible — not "—"
    expect(paymentsRow?.textContent).toContain("2");
  });

  it("shows dash for zero error count and numeric value for non-zero", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        makeStats({ name: "checkout", errorCount: 0 }),
        makeStats({ name: "payments", errorCount: 3 }),
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = await act(async () =>
      render(<ServicesTab serviceNames={["checkout", "payments"]} />),
    );

    const checkoutRow = Array.from(container.querySelectorAll(".services-table__row")).find(
      (r) => r.textContent?.includes("checkout"),
    );
    const paymentsRow = Array.from(container.querySelectorAll(".services-table__row")).find(
      (r) => r.textContent?.includes("payments"),
    );

    // Zero errors → muted dash
    expect(checkoutRow?.querySelector(".explorer-row__numeric--muted")?.textContent).toBe("—");
    // Non-zero errors → error count styled element
    expect(paymentsRow?.querySelector(".services-tab__error-count")?.textContent).toBe("3");
  });

  it("renders dash for null duration fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        makeStats({ name: "svc", avgDurationMs: null, avgClientDurationMs: null, avgServerDurationMs: null }),
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = await act(async () =>
      render(<ServicesTab serviceNames={["svc"]} />),
    );

    const row = container.querySelector(".services-table__row");
    // Three duration columns should all show "—"
    const cells = row?.querySelectorAll(".data-table__td--numeric");
    const dashCells = Array.from(cells ?? []).filter((c) => c.textContent?.trim() === "—");
    expect(dashCells.length).toBeGreaterThanOrEqual(3);
  });

  it("shows empty state when backend returns no rows and serviceNames is empty", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      render(<ServicesTab serviceNames={[]} />);
    });

    expect(screen.getByText(/No services observed yet/)).toBeTruthy();
  });
});
