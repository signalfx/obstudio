// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EmptyState, TelemetryEmptyState } from "./EmptyState";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("EmptyState", () => {
  it("shows the table's columns behind the message, hidden from screen readers", () => {
    const { container } = render(
      <EmptyState
        title="No traces received yet."
        hint="Send some."
        skeleton={{
          headClassName: "data-table__head data-table__head--traces",
          rowClassName: "data-table__row data-table__row--traces",
          columns: [{ label: "Operation" }, { label: "Duration", className: "data-table__th--numeric" }],
        }}
      />,
    );

    const skeleton = container.querySelector(".empty-state__skeleton");
    expect(skeleton?.getAttribute("aria-hidden")).toBe("true");
    expect(Array.from(skeleton?.querySelectorAll(".data-table__th") ?? []).map((th) => th.textContent)).toEqual(["Operation", "Duration"]);
    // Cells get the matching __td class so column widths line up.
    expect(skeleton?.querySelector(".data-table__row--traces .data-table__td--numeric")).toBeTruthy();
    expect(screen.getByText("No traces received yet.").closest(".empty-state__overlay")).toBeTruthy();
  });
});

describe("TelemetryEmptyState", () => {
  it("names the configured OTLP endpoint and copies it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ endpoints: { otlpHttp: "http://127.0.0.1:14318" } }),
    }));
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    render(<TelemetryEmptyState title="No traces received yet." />);

    await waitFor(() => expect(screen.getByText(/at http:\/\/127\.0\.0\.1:14318,/)).toBeTruthy());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy OTLP endpoint environment variable" }));
    });
    expect(writeText).toHaveBeenCalledWith("OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14318");
    expect(screen.getByRole("button", { name: "Copy $otel-instrument command" })).toBeTruthy();
  });

  it("leaves out the port when /api/health fails", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);

    render(<TelemetryEmptyState title="No traces received yet." />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByText(/this collector's OTLP\/HTTP endpoint/)).toBeTruthy();
    expect(screen.queryByText(/OTEL_EXPORTER_OTLP_ENDPOINT/)).toBeNull();
  });
});
