// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function selectFilterField(label: string): void {
  fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
  const menu = document.querySelector<HTMLElement>(".filter-builder__menu")!;
  const items = menu.querySelectorAll<HTMLElement>(".filter-builder__menu-item");
  const target = Array.from(items).find((el) => el.querySelector(".filter-builder__menu-key")?.textContent === label);
  if (!target) throw new Error(`Filter field "${label}" not found in menu`);
  fireEvent.mouseDown(target);
}

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

  it("labels a compact provider trace span count as a retained lower bound", () => {
    render(
      <TracesTab
        traces={[
          {
            traceId: "trace-retained",
            rootSpanName: "session_task",
            serviceName: "codex-app-server",
            spanCount: 8,
            durationMs: 120,
            status: "ok",
            retentionTruncated: true,
          },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    const count = screen.getByLabelText("at least 8 retained spans");
    expect(count.textContent).toBe("8+");
    expect(count.title).toBe("at least 8 retained spans");

    const duration = screen.getByLabelText("at least 120.0ms retained duration");
    expect(duration.textContent).toBe("120.0ms+");
    expect(duration.title).toBe("at least 120.0ms retained duration");
  });

  it("uses a singular retained-span label for a compact one-span trace", () => {
    render(
      <TracesTab
        traces={[
          {
            traceId: "trace-retained-single",
            rootSpanName: "session_task",
            serviceName: "claude-code",
            spanCount: 1,
            durationMs: 10,
            status: "ok",
            retentionTruncated: true,
          },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    expect(screen.getByLabelText("at least 1 retained span").textContent).toBe("1+");
  });

  it("marks a retained trace with unavailable observation history as unknown", () => {
    render(
      <TracesTab
        traces={[
          {
            traceId: "trace-retention-unknown",
            rootSpanName: "session_task",
            serviceName: "claude-code",
            spanCount: 1,
            durationMs: 10,
            status: "ok",
            retentionTruncated: true,
            retentionUnknown: true,
          },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    expect(screen.getByLabelText("1 retained span; full count unknown").textContent).toBe("1?");
    expect(screen.getByLabelText("10.0ms retained duration; full duration unknown").textContent).toBe("10.0ms?");
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

    selectFilterField("Root Span");
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

    selectFilterField("Root Span");
    expect((screen.getByRole("radio", { name: "=" }) as HTMLButtonElement).classList.contains("filter-builder__operator--active")).toBe(true);
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

  it("refreshes an open compact trace when its retained span projection rotates", async () => {
    const detail = (spanId: string) => ({
      traceId: "trace-retained",
      rootSpanName: "claude_code.interaction",
      serviceName: "claude-code",
      spanCount: 8,
      durationMs: 42,
      status: "ok",
      retentionTruncated: true,
      spans: [{
        traceId: "trace-retained",
        spanId,
        parentSpanId: "",
        name: "claude_code.interaction",
        kind: "INTERNAL",
        startTimeUnixNano: "2026-06-12T18:00:00.000Z",
        endTimeUnixNano: "2026-06-12T18:00:00.042Z",
        durationMs: 42,
        status: { code: "OK" },
        attributes: {},
        events: [],
        links: [],
        resource: { attributes: {}, serviceName: "claude-code" },
        scope: { name: "claude-code" },
      }],
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => detail("span-old") })
      .mockResolvedValueOnce({ ok: true, json: async () => detail("span-new") });
    vi.stubGlobal("fetch", fetchMock);

    const summary = (spanId: string) => ({
      traceId: "trace-retained",
      rootSpanName: "claude_code.interaction",
      serviceName: "claude-code",
      spanCount: 8,
      durationMs: 42,
      status: "ok",
      retentionTruncated: true,
      spans: [{ spanId, name: "claude_code.interaction", kind: "INTERNAL", durationMs: 42, statusCode: "OK", serviceName: "claude-code" }],
    });
    const props = {
      telemetryError: null,
      onInteract: vi.fn(),
      validationFindings: [],
      validationIndex: { trace: new Map(), span: new Map(), metric: new Map(), log: new Map() },
    };
    const view = render(<TracesTab {...props} traces={[summary("span-old")]} />);

    fireEvent.click((await screen.findByText("claude_code.interaction")).closest("button") as HTMLButtonElement);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.getByText(/at least 42\.0ms retained duration/)).toBeTruthy();

    view.rerender(<TracesTab {...props} traces={[summary("span-new")]} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("refreshes an open trace when its retention status changes", async () => {
    const detail = (retentionTruncated: boolean) => ({
      traceId: "trace-retention-change",
      rootSpanName: "claude_code.interaction",
      serviceName: "claude-code",
      spanCount: 8,
      durationMs: 42,
      status: "ok",
      retentionTruncated,
      spans: [{
        traceId: "trace-retention-change",
        spanId: "span-1",
        parentSpanId: "",
        name: "claude_code.interaction",
        kind: "INTERNAL",
        startTimeUnixNano: "2026-06-12T18:00:00.000Z",
        endTimeUnixNano: "2026-06-12T18:00:00.042Z",
        durationMs: 42,
        status: { code: "OK" },
        attributes: {},
        events: [],
        links: [],
        resource: { attributes: {}, serviceName: "claude-code" },
        scope: { name: "claude-code" },
      }],
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => detail(false) })
      .mockResolvedValueOnce({ ok: true, json: async () => detail(true) });
    vi.stubGlobal("fetch", fetchMock);

    const summary = (retentionTruncated: boolean) => ({
      traceId: "trace-retention-change",
      rootSpanName: "claude_code.interaction",
      serviceName: "claude-code",
      spanCount: 8,
      durationMs: 42,
      status: "ok",
      retentionTruncated,
      spans: [{ spanId: "span-1", name: "claude_code.interaction", kind: "INTERNAL", durationMs: 42, statusCode: "OK", serviceName: "claude-code" }],
    });
    const props = {
      telemetryError: null,
      onInteract: vi.fn(),
      validationFindings: [],
      validationIndex: { trace: new Map(), span: new Map(), metric: new Map(), log: new Map() },
    };
    const view = render(<TracesTab {...props} traces={[summary(false)]} />);

    fireEvent.click((await screen.findByText("claude_code.interaction")).closest("button") as HTMLButtonElement);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    view.rerender(<TracesTab {...props} traces={[summary(true)]} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("refreshes an open trace when a same-count span is retransmitted with new details", async () => {
    const detail = (durationMs: number) => ({
      traceId: "trace-retransmitted",
      rootSpanName: "GET /orders",
      serviceName: "checkout",
      spanCount: 1,
      durationMs,
      status: "ok",
      spans: [{
        traceId: "trace-retransmitted",
        spanId: "span-1",
        parentSpanId: "",
        name: "GET /orders",
        kind: "SERVER",
        startTimeUnixNano: "2026-06-12T18:00:00.000Z",
        endTimeUnixNano: "2026-06-12T18:00:00.042Z",
        durationMs,
        status: { code: "OK" },
        attributes: {},
        events: [],
        links: [],
        resource: { attributes: {}, serviceName: "checkout" },
        scope: { name: "test" },
      }],
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => detail(10) })
      .mockResolvedValueOnce({ ok: true, json: async () => detail(12) });
    vi.stubGlobal("fetch", fetchMock);

    const summary = (durationMs: number) => ({
      traceId: "trace-retransmitted",
      rootSpanName: "GET /orders",
      serviceName: "checkout",
      spanCount: 1,
      durationMs,
      status: "ok",
      spans: [{ spanId: "span-1", name: "GET /orders", kind: "SERVER", durationMs, statusCode: "OK", serviceName: "checkout" }],
    });
    const props = {
      telemetryError: null,
      onInteract: vi.fn(),
      validationFindings: [],
      validationIndex: { trace: new Map(), span: new Map(), metric: new Map(), log: new Map() },
    };
    const view = render(<TracesTab {...props} traces={[summary(10)]} />);

    fireEvent.click((await screen.findByText("GET /orders")).closest("button") as HTMLButtonElement);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    view.rerender(<TracesTab {...props} traces={[summary(12)]} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("does not refresh unchanged duplicate records that share a span ID", async () => {
    const span = (durationMs: number) => ({
      traceId: "trace-duplicates",
      spanId: "span-shared",
      parentSpanId: "",
      name: "GET /orders",
      kind: "SERVER",
      startTimeUnixNano: "2026-06-12T18:00:00.000Z",
      endTimeUnixNano: "2026-06-12T18:00:00.042Z",
      durationMs,
      status: { code: "OK" },
      attributes: {},
      events: [],
      links: [],
      resource: { attributes: {}, serviceName: "checkout" },
      scope: { name: "test" },
    });
    const detail = {
      traceId: "trace-duplicates",
      rootSpanName: "GET /orders",
      serviceName: "checkout",
      spanCount: 2,
      durationMs: 42,
      status: "ok",
      revision: 2,
      spans: [span(10), span(12)],
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => detail });
    vi.stubGlobal("fetch", fetchMock);

    const summary = () => ({
      traceId: "trace-duplicates",
      rootSpanName: "GET /orders",
      serviceName: "checkout",
      spanCount: 2,
      durationMs: 42,
      status: "ok",
      revision: 2,
      spans: [
        { spanId: "span-shared", name: "GET /orders", kind: "SERVER", durationMs: 10, statusCode: "OK", serviceName: "checkout" },
        { spanId: "span-shared", name: "GET /orders", kind: "SERVER", durationMs: 12, statusCode: "OK", serviceName: "checkout" },
      ],
    });
    const props = {
      telemetryError: null,
      onInteract: vi.fn(),
      validationFindings: [],
      validationIndex: { trace: new Map(), span: new Map(), metric: new Map(), log: new Map() },
    };
    const view = render(<TracesTab {...props} traces={[summary()]} />);

    fireEvent.click((await screen.findByText("GET /orders")).closest("button") as HTMLButtonElement);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    view.rerender(<TracesTab {...props} traces={[summary()]} />);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refreshes an open trace when its revision changes without preview changes", async () => {
    const detail = (revision: number, attributeValue: string) => ({
      traceId: "trace-revision",
      rootSpanName: "GET /orders",
      serviceName: "checkout",
      spanCount: 1,
      durationMs: 42,
      status: "ok",
      revision,
      spans: [{
        traceId: "trace-revision",
        spanId: "span-1",
        parentSpanId: "",
        name: "GET /orders",
        kind: "SERVER",
        startTimeUnixNano: "2026-06-12T18:00:00.000Z",
        endTimeUnixNano: "2026-06-12T18:00:00.042Z",
        durationMs: 42,
        status: { code: "OK" },
        attributes: { version: attributeValue },
        events: [],
        links: [],
        resource: { attributes: {}, serviceName: "checkout" },
        scope: { name: "test" },
      }],
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => detail(1, "old") })
      .mockResolvedValueOnce({ ok: true, json: async () => detail(2, "new") });
    vi.stubGlobal("fetch", fetchMock);

    const summary = (revision: number) => ({
      traceId: "trace-revision",
      rootSpanName: "GET /orders",
      serviceName: "checkout",
      spanCount: 1,
      durationMs: 42,
      status: "ok",
      revision,
      spans: [{ spanId: "span-1", name: "GET /orders", kind: "SERVER", durationMs: 42, statusCode: "OK", serviceName: "checkout" }],
    });
    const props = {
      telemetryError: null,
      onInteract: vi.fn(),
      validationFindings: [],
      validationIndex: { trace: new Map(), span: new Map(), metric: new Map(), log: new Map() },
    };
    const view = render(<TracesTab {...props} traces={[summary(1)]} />);

    fireEvent.click((await screen.findByText("GET /orders")).closest("button") as HTMLButtonElement);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    view.rerender(<TracesTab {...props} traces={[summary(2)]} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("coalesces rapid background detail refreshes", async () => {
    const detail = (revision: number) => ({
      traceId: "trace-coalesced",
      rootSpanName: "GET /orders",
      serviceName: "checkout",
      spanCount: 1,
      durationMs: 42,
      status: "ok",
      revision,
      spans: [{
        traceId: "trace-coalesced",
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
      }],
    });
    let resolveSecond: ((response: { ok: boolean; json: () => Promise<ReturnType<typeof detail>> }) => void) | undefined;
    let resolveThird: ((response: { ok: boolean; json: () => Promise<ReturnType<typeof detail>> }) => void) | undefined;
    const second = new Promise<{ ok: boolean; json: () => Promise<ReturnType<typeof detail>> }>((resolve) => { resolveSecond = resolve; });
    const third = new Promise<{ ok: boolean; json: () => Promise<ReturnType<typeof detail>> }>((resolve) => { resolveThird = resolve; });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => detail(1) })
      .mockReturnValueOnce(second)
      .mockReturnValueOnce(third);
    vi.stubGlobal("fetch", fetchMock);

    const summary = (revision: number) => ({
      traceId: "trace-coalesced",
      rootSpanName: "GET /orders",
      serviceName: "checkout",
      spanCount: 1,
      durationMs: 42,
      status: "ok",
      revision,
      spans: [{ spanId: "span-1", name: "GET /orders", kind: "SERVER", durationMs: 42, statusCode: "OK", serviceName: "checkout" }],
    });
    const props = {
      telemetryError: null,
      onInteract: vi.fn(),
      validationFindings: [],
      validationIndex: { trace: new Map(), span: new Map(), metric: new Map(), log: new Map() },
    };
    const view = render(<TracesTab {...props} traces={[summary(1)]} />);
    fireEvent.click((await screen.findByText("GET /orders")).closest("button") as HTMLButtonElement);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    view.rerender(<TracesTab {...props} traces={[summary(2)]} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    view.rerender(<TracesTab {...props} traces={[summary(3)]} />);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock).toHaveBeenCalledTimes(2);

    resolveSecond?.({ ok: true, json: async () => detail(2) });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    resolveThird?.({ ok: true, json: async () => detail(3) });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
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

    selectFilterField("Service");
    expect((screen.getByRole("radio", { name: "=" }) as HTMLButtonElement).classList.contains("filter-builder__operator--active")).toBe(true);
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

    selectFilterField("Min Duration");
    fireEvent.click(screen.getByRole("radio", { name: "<" }));
    fireEvent.change(screen.getByLabelText("minDurationMs value"), {
      target: { value: "100" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/traces?range%5BdurationMs%5D%5Blt%5D=100", expect.any(Object));
  });

  it("stacks the trace detail panel below the list at ≤900px widths", async () => {
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

    expect(layoutStyles.flexDirection).toBe("column");
    expect(panelStyles.position).toBe("static");
    expect(panelStyles.borderTopWidth).toBe("1px");
    expect(panelStyles.borderTopStyle).toBe("solid");
    expect(panelStyles.borderLeftWidth).toBe("0px");
    expect(contentStyles.minHeight).toBe("0");

    // Exiting panel must not collapse horizontally — width stays auto, only height collapses
    window.document.body.innerHTML =
      "<div class=\"signal-view signal-view--trace-detail signal-view--with-panel\"><div class=\"signal-view__content\"></div><div class=\"signal-view__panel signal-view__panel--exiting\"></div></div>";
    const exitingPanel = window.document.querySelector(".signal-view__panel--exiting");
    if (!exitingPanel) throw new Error("expected exiting panel");
    const exitingStyles = window.getComputedStyle(exitingPanel);
    expect(exitingStyles.width).not.toBe("0px");
  });

  it("stacks the trace detail panel below the list at 640px", async () => {
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
