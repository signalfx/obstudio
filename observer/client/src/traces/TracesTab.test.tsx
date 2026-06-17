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
  it("renders unfiltered traces from the live websocket snapshot without a REST query", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TracesTab
        traces={[
          { traceId: "trace-websocket", rootSpanName: "GET /live-websocket", serviceName: "checkout", spanCount: 1, durationMs: 1, status: "ok" },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    expect(screen.getByText("GET /live-websocket")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("differentiates GenAI traces in the trace list", () => {
    render(
      <TracesTab
        traces={[
          { traceId: "trace-genai", rootSpanName: "POST /v2/assistant/sessions", serviceName: "assistant", spanCount: 4, durationMs: 120, status: "ok", isGenAI: true },
          { traceId: "trace-http", rootSpanName: "GET /health", serviceName: "api", spanCount: 1, durationMs: 3, status: "ok" },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    expect(screen.getByLabelText("GenAI trace")).toBeTruthy();
    expect(screen.getByText("POST /v2/assistant/sessions")).toBeTruthy();
    expect(screen.getByText("GET /health")).toBeTruthy();
  });

  it("refreshes filtered traces from REST when live telemetry changes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { traceId: "trace-1", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 1, durationMs: 10, status: "ok" },
        ],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { traceId: "trace-2", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 2, durationMs: 20, status: "ok" },
        ],
      });
    vi.stubGlobal("fetch", fetchMock);

    const view = render(
      <TracesTab
        traces={[
          { traceId: "live-1", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 1, durationMs: 1, status: "ok" },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "rootSpanName" },
    });
    fireEvent.change(screen.getByLabelText("rootSpanName value"), {
      target: { value: "GET /orders" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await screen.findByText("trace-1");

    view.rerender(
      <TracesTab
        traces={[
          { traceId: "live-2", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 2, durationMs: 2, status: "ok" },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    await screen.findByText("trace-2");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/query/traces?filter%5BrootSpanName%5D%5Beq%5D=GET+%2Forders", expect.any(Object));
  });

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
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    fireEvent.change(await screen.findByLabelText("Filter field"), {
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
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    expect(screen.getAllByText("0.0ms")).toHaveLength(2);
    expect(screen.queryByText("--")).toBeNull();
  });

  it("opens selected trace details at the widest usable panel width", async () => {
    const fetchMock = vi.fn(async () => ({
        ok: true,
        json: async () => ({
          traceId: "trace-1",
          rootSpanName: "GET /orders",
          serviceName: "checkout",
          spanCount: 1,
          durationMs: 42,
          status: "ok",
          spans: [
            {
              traceId: "trace-1",
              spanId: "span-1",
              parentSpanId: "",
              name: "GET /orders",
              kind: "SERVER",
              startTimeUnixNano: "2026-06-12T18:00:00.000Z",
              endTimeUnixNano: "2026-06-12T18:00:00.042Z",
              durationMs: 42,
              status: { code: "OK" },
              attributes: {},
              events: [],
              links: [],
              resource: { attributes: {}, serviceName: "checkout" },
              scope: { name: "test" },
            },
          ],
        }),
      }) as Response);
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(
      <TracesTab
        traces={[
          { traceId: "trace-1", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 1, durationMs: 42, status: "ok" },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    const traceRow = (await screen.findByText("GET /orders")).closest("button");
    expect(traceRow).toBeTruthy();
    fireEvent.click(traceRow as HTMLButtonElement);

    await screen.findByText("Trace ID");

    const panel = container.querySelector<HTMLElement>(".resizable-panel.signal-view__panel");
    expect(panel?.style.getPropertyValue("--panel-width")).toBe("min(1600px, calc(100vw - 320px))");
    expect(fetchMock).toHaveBeenCalledWith("/api/query/traces/trace-1", undefined);
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
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    fireEvent.change(await screen.findByLabelText("Filter field"), {
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
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    fireEvent.change(await screen.findByLabelText("Filter field"), {
      target: { value: "minDurationMs" },
    });
    fireEvent.click(screen.getByRole("button", { name: "<" }));
    fireEvent.change(screen.getByLabelText("minDurationMs value"), {
      target: { value: "100" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/traces?range%5BdurationMs%5D%5Blt%5D=100", expect.any(Object));
  });

  it("keeps the trace detail panel at the side for typical app widths", async () => {
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
      "<div class=\"signal-view signal-view--trace-detail signal-view--with-panel\"><div class=\"signal-view__content\"></div><div class=\"signal-view__panel\"></div></div>";

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

    expect(css).toContain("width: var(--panel-width, min(560px, calc(100vw - 320px)));");
    expect(css).toContain("flex: 0 0 var(--panel-width, min(560px, calc(100vw - 320px)));");
    expect(layoutStyles.flexDirection).toBe("row");
    expect(panelStyles.position).toBe("static");
    expect(panelStyles.borderTopWidth).toBe("0px");
    expect(panelStyles.borderLeftWidth).toBe("1px");
    expect(panelStyles.borderLeftStyle).toBe("solid");
    expect(contentStyles.minWidth).toBe("0");
  });

  it("stacks the trace detail panel below the list only on very narrow widths", async () => {
    const [{ Window }, { readFile }, { resolve }] = await Promise.all([
      import("happy-dom"),
      import("node:fs/promises"),
      import("node:path"),
    ]);
    const css = await readFile(resolve(process.cwd(), "src/styles.css"), "utf8");
    const window = new Window({ width: 640, height: 700, url: "http://localhost" });
    const style = window.document.createElement("style");
    style.textContent = css;
    window.document.head.appendChild(style);
    window.document.body.innerHTML =
      "<div class=\"signal-view signal-view--trace-detail signal-view--with-panel\"><div class=\"signal-view__content\"></div><div class=\"signal-view__panel\"></div></div>";

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
