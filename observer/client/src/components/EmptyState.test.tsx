// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EmptyState, TelemetryEmptyState, type EmptyStateSkeleton } from "./EmptyState";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** Answers /api/health with the given OTLP/HTTP endpoint. */
function stubHealth(otlpHttp: string): ReturnType<typeof vi.fn> {
  const fn = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/health")) {
      return { ok: true, status: 200, json: async () => ({ endpoints: { otlpHttp } }) };
    }
    return { ok: true, status: 200, json: async () => [] };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const SKELETON: EmptyStateSkeleton = {
  headClassName: "data-table__head data-table__head--traces",
  rowClassName: "data-table__row data-table__row--traces",
  columns: [
    { label: "Operation", modifiers: ["operation"] },
    { label: "Duration", modifiers: ["duration", "numeric"] },
  ],
};

describe("EmptyState", () => {
  it("renders the title, hint, and actions", () => {
    render(
      <EmptyState
        title="Nothing yet."
        hint="Do the thing."
        actions={<button type="button">Do it</button>}
      />,
    );
    expect(screen.getByText("Nothing yet.")).toBeTruthy();
    expect(screen.getByText("Do the thing.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Do it" })).toBeTruthy();
  });

  it("previews the table columns behind the message without exposing them to assistive tech", () => {
    const { container } = render(<EmptyState title="Nothing yet." hint="Do the thing." skeleton={SKELETON} />);

    const skeleton = container.querySelector(".empty-state__skeleton");
    expect(skeleton?.getAttribute("aria-hidden")).toBe("true");
    const headers = Array.from(skeleton?.querySelectorAll(".data-table__th") ?? []).map((th) => th.textContent);
    expect(headers).toEqual(["Operation", "Duration"]);
    // Header and cells carry the real table's column classes, so its widths
    // and narrow-viewport rules apply to the preview too.
    expect(skeleton?.querySelector(".data-table__head--traces .data-table__th--duration.data-table__th--numeric")).toBeTruthy();
    expect(skeleton?.querySelectorAll(".data-table__row--traces").length).toBeGreaterThan(0);
    expect(skeleton?.querySelector(".data-table__td--duration.data-table__td--numeric .empty-state__bar")).toBeTruthy();
    expect(screen.getByText("Nothing yet.").closest(".empty-state__overlay")).toBeTruthy();
  });

  it("renders the card variant as a labelled region", () => {
    render(<EmptyState title="Nothing yet." hint="Do the thing." variant="card" />);
    expect(screen.getByRole("region", { name: "Nothing yet." })).toBeTruthy();
  });
});

describe("TelemetryEmptyState", () => {
  it("names the configured OTLP endpoint and copies it as an exporter variable", async () => {
    stubHealth("http://127.0.0.1:14318");
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    render(<TelemetryEmptyState title="No traces received yet." />);

    await waitFor(() => expect(screen.getByText(/at http:\/\/127\.0\.0\.1:14318,/)).toBeTruthy());
    expect(screen.getByText("OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14318")).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy OTLP endpoint environment variable" }));
    });
    expect(writeText).toHaveBeenCalledWith("OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14318");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy $otel-instrument command" }));
    });
    expect(writeText).toHaveBeenLastCalledWith("$otel-instrument");
  });

  it("falls back to a port-free hint when /api/health is unavailable", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);

    render(<TelemetryEmptyState title="No traces received yet." />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByText(/this collector's OTLP\/HTTP endpoint/)).toBeTruthy();
    expect(screen.queryByText(/OTEL_EXPORTER_OTLP_ENDPOINT/)).toBeNull();
    expect(screen.queryByText(/4318/)).toBeNull();
    // The skill pointer does not depend on the endpoint.
    expect(screen.getByRole("button", { name: "Copy $otel-instrument command" })).toBeTruthy();
  });
});
