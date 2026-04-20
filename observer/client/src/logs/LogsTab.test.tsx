// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LogsTab } from "./LogsTab";

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

describe("LogsTab", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      value: 400,
    });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      value: 1200,
    });
    HTMLElement.prototype.getBoundingClientRect = () =>
      ({
        width: 1200,
        height: 400,
        top: 0,
        left: 0,
        right: 1200,
        bottom: 400,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect;
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("filters logs from the compact explorer toolbar via the REST query endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          id: "2",
          timeUnixNano: "1712700000000000001",
          severityText: "ERROR",
          body: "payment failed",
          attributes: {},
          resource: { serviceName: "payments", attributes: {} },
          scope: { name: "otel" },
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityText: "INFO",
            body: "checkout started",
            attributes: {},
            resource: { serviceName: "checkout", attributes: {} },
            scope: { name: "otel" },
          },
          {
            id: "2",
            timeUnixNano: "1712700000000000001",
            severityText: "ERROR",
            body: "payment failed",
            attributes: {},
            resource: { serviceName: "payments", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
        onInteract={vi.fn()}
      />,
    );

    expect(container.querySelector(".data-table__head--left-cluster-logs")).toBeTruthy();
    expect(container.querySelector(".data-table__body-inner--logs")).toBeTruthy();
    expect(container.querySelector(".data-table__td--timestamp .explorer-row__secondary")).toBeTruthy();
    expect(container.querySelector(".data-table__td--service .explorer-row__secondary")).toBeTruthy();
    expect(container.querySelector(".data-table__td--message .explorer-row__primary")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "bodyContains" },
    });
    expect((screen.getByRole("button", { name: "=" }) as HTMLButtonElement).classList.contains("filter-builder__operator--active")).toBe(true);
    fireEvent.change(screen.getByLabelText("bodyContains value"), {
      target: { value: "payment" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/logs?filter%5BbodyContains%5D%5Beq%5D=payment", expect.any(Object));
    expect(screen.getByText("payment failed")).toBeTruthy();
    expect(screen.queryByText("checkout started")).toBeNull();
  });

  it("encodes negated exact filters with neq operators", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          id: "2",
          timeUnixNano: "1712700000000000001",
          severityText: "ERROR",
          body: "payment failed",
          attributes: {},
          resource: { serviceName: "payments", attributes: {} },
          scope: { name: "otel" },
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityText: "INFO",
            body: "checkout started",
            attributes: {},
            resource: { serviceName: "checkout", attributes: {} },
            scope: { name: "otel" },
          },
          {
            id: "2",
            timeUnixNano: "1712700000000000001",
            severityText: "ERROR",
            body: "payment failed",
            attributes: {},
            resource: { serviceName: "payments", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
        onInteract={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "serviceName" },
    });
    fireEvent.click(screen.getByRole("button", { name: "!=" }));
    fireEvent.change(screen.getByLabelText("serviceName value"), {
      target: { value: "checkout" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/logs?filter%5BserviceName%5D%5Bneq%5D=checkout", expect.any(Object));
    expect(screen.getByText("payment failed")).toBeTruthy();
    expect(screen.queryByText("checkout started")).toBeNull();
  });

  it("uses whole-number inputs for severity number filters", () => {
    render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityText: "INFO",
            body: "checkout started",
            attributes: {},
            resource: { serviceName: "checkout", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
        onInteract={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "Severity Number" },
    });
    const input = screen.getByLabelText("severityNumber value") as HTMLInputElement;

    expect(input.getAttribute("step")).toBe("1");

    fireEvent.change(input, { target: { value: "1.5" } });
    expect(input.value).toBe("");
  });

  it("does not show time range fields in the log filter menu", () => {
    render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityText: "INFO",
            body: "checkout started",
            attributes: {},
            resource: { serviceName: "checkout", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
        onInteract={vi.fn()}
      />,
    );

    fireEvent.focus(screen.getByLabelText("Filter field"));

    expect(screen.queryByText("Time From")).toBeNull();
    expect(screen.queryByText("Time To")).toBeNull();
  });

  it("renders the selected log detail without validation overlays", () => {
    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityText: "INFO",
            body: "checkout started",
            attributes: {},
            resource: { serviceName: "checkout", attributes: {} },
            scope: { name: "otel" },
            traceId: "trace-1",
            spanId: "span-1",
          },
        ]}
        onInteract={vi.fn()}
      />,
    );

    fireEvent.click(container.querySelector(".data-table__row--logs") as HTMLElement);

    expect(screen.getByRole("heading", { name: "Message" })).toBeTruthy();
    expect(screen.queryByText("Validation")).toBeNull();
    expect(screen.getByRole("button", { name: "Close panel" })).toBeTruthy();
    expect(screen.getByLabelText("Filter field")).toBeTruthy();
  });
});
