// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TracesTab } from "./TracesTab";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 36,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: index,
        start: index * 36,
        end: (index + 1) * 36,
        size: 36,
      })),
    measureElement: () => undefined,
  }),
}));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("TracesTab", () => {
  it("filters traces from the compact explorer toolbar via the REST query endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { traceId: "trace-2", rootSpanName: "POST /charge", serviceName: "payments", spanCount: 5, durationMs: 88, status: "error" },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TracesTab
        traces={[
          { traceId: "trace-1", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 3, durationMs: 42, status: "ok" },
          { traceId: "trace-2", rootSpanName: "POST /charge", serviceName: "payments", spanCount: 5, durationMs: 88, status: "error" },
        ]}
        telemetryError={null}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "rootSpanName" },
    });
    expect((screen.getByRole("button", { name: "=" }) as HTMLButtonElement).classList.contains("filter-builder__operator--active")).toBe(true);
    fireEvent.change(screen.getByLabelText("rootSpanName value"), {
      target: { value: "POST /charge" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/traces?filter%5BrootSpanName%5D%5Beq%5D=POST+%2Fcharge", expect.any(Object));
    expect(screen.getByText("POST /charge")).toBeTruthy();
    expect(screen.queryByText("GET /orders")).toBeNull();
  });

  it("renders zero-duration traces as 0.0ms instead of dashes", () => {
    render(
      <TracesTab
        traces={[
          { traceId: "trace-0", rootSpanName: "GET /health", serviceName: "api", spanCount: 1, durationMs: 0, status: "ok" },
          { traceId: "trace-missing", rootSpanName: "GET /ready", serviceName: "api", spanCount: 1, status: "ok" } as any,
        ]}
        telemetryError={null}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    expect(screen.getAllByText("0.0ms")).toHaveLength(2);
    expect(screen.queryByText("--")).toBeNull();
  });

  it("handles a null filtered trace response without crashing", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => null,
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TracesTab
        traces={[
          { traceId: "trace-1", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 3, durationMs: 42, status: "ok" },
        ]}
        telemetryError={null}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "serviceName" },
    });
    expect((screen.getByRole("button", { name: "=" }) as HTMLButtonElement).classList.contains("filter-builder__operator--active")).toBe(true);
    fireEvent.change(screen.getByLabelText("serviceName value"), {
      target: { value: "missing" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(screen.getByText("No traces match the current filters.")).toBeTruthy();
  });

  it("maps not-equal range filters to the complementary server-side range", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { traceId: "trace-1", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 3, durationMs: 42, status: "ok" },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TracesTab
        traces={[
          { traceId: "trace-1", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 3, durationMs: 42, status: "ok" },
        ]}
        telemetryError={null}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "minDurationMs" },
    });
    expect((screen.getByRole("button", { name: ">=" }) as HTMLButtonElement).classList.contains("filter-builder__operator--active")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "<" }));
    fireEvent.change(screen.getByLabelText("minDurationMs value"), {
      target: { value: "100" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/traces?range%5BdurationMs%5D%5Blt%5D=100", expect.any(Object));
  });

  it("shows bound-aware operators for max filters", () => {
    render(
      <TracesTab
        traces={[
          { traceId: "trace-1", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 3, durationMs: 42, status: "ok" },
        ]}
        telemetryError={null}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "maxDurationMs" },
    });

    expect((screen.getByRole("button", { name: "<=" }) as HTMLButtonElement).classList.contains("filter-builder__operator--active")).toBe(true);
    expect(screen.getByRole("button", { name: ">" })).toBeTruthy();
  });

  it("stacks the detail panel below the list on narrow widths", async () => {
    const [{ Window }, { readFile }, { resolve }] = await Promise.all([
      import("happy-dom"),
      import("node:fs/promises"),
      import("node:path"),
    ]);
    const css = await readFile(resolve(process.cwd(), "src/styles.css"), "utf8");
    const window = new Window({ width: 800, height: 700, url: "http://localhost" });
    const style = window.document.createElement("style");
    style.textContent = css;
    window.document.head.appendChild(style);
    window.document.body.innerHTML =
      "<div class=\"signal-view signal-view--with-panel\"><div class=\"signal-view__content\"></div><div class=\"signal-view__panel\"></div></div>";

    const layout = window.document.querySelector(".signal-view");
    const panel = window.document.querySelector(".signal-view__panel");
    const content = window.document.querySelector(".signal-view__content");
    expect(layout).toBeTruthy();
    expect(panel).toBeTruthy();
    expect(content).toBeTruthy();
    if (!layout || !panel || !content) {
      throw new Error("expected responsive layout shell");
    }

    const layoutStyles = window.getComputedStyle(layout);
    const panelStyles = window.getComputedStyle(panel);
    const contentStyles = window.getComputedStyle(content);

    expect(layoutStyles.flexDirection).toBe("column");
    expect(panelStyles.position).toBe("static");
    expect(panelStyles.borderTopWidth).toBe("1px");
    expect(panelStyles.borderTopStyle).toBe("solid");
    expect(panelStyles.borderLeftWidth).toBe("0px");
    expect(contentStyles.minHeight).toBe("0");
  });
});
