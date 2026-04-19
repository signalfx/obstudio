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
      />,
    );

    expect(container.querySelector(".data-table__head--left-cluster-logs")).toBeTruthy();
    expect(container.querySelector(".data-table__body-inner--logs")).toBeTruthy();
    expect(screen.getByText("Severity")).toBeTruthy();
    expect(container.querySelector(".data-table__td--timestamp .explorer-row__secondary")).toBeTruthy();
    expect(container.querySelector(".data-table__td--service .explorer-row__secondary")).toBeTruthy();
    expect(container.querySelector(".data-table__td--message .explorer-row__primary")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "serviceName" },
    });
    expect((screen.getByRole("button", { name: "=" }) as HTMLButtonElement).classList.contains("filter-builder__operator--active")).toBe(true);
    fireEvent.change(screen.getByLabelText("serviceName value"), {
      target: { value: "payments" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/logs?filter%5BserviceName%5D%5Beq%5D=payments", expect.any(Object));
    expect(screen.getByText("payment failed")).toBeTruthy();
    expect(screen.queryByText("checkout started")).toBeNull();
  });

  it("maps the Message filter to bodyContains in the REST query endpoint", async () => {
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
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "Message" },
    });
    fireEvent.change(screen.getByLabelText("message value"), {
      target: { value: "failed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/logs?filter%5BbodyContains%5D%5Beq%5D=failed", expect.any(Object));
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
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "Severity Number" },
    });
    const input = screen.getByLabelText("severityNumber value") as HTMLInputElement;

    expect(input.getAttribute("step")).toBe("1");
  });

  it("renders the selected log detail without validation overlays", () => {
    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "2024-04-09T22:00:00.000000019Z",
            severityNumber: 10,
            severityText: "Informational",
            body: "checkout started",
            attributes: {
              "demo.case": "checkout started",
            },
            resource: {
              serviceName: "checkout",
              attributes: {
                "service.name": "checkout",
                "deployment.environment": "prod",
              },
            },
            scope: { name: "otel" },
            traceId: "trace-1",
            spanId: "span-1",
          },
        ]}
      />,
    );

    fireEvent.click(container.querySelector(".data-table__row--logs") as HTMLElement);

    expect(screen.getByRole("heading", { name: "Summary" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Message" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Attributes" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Resource Attributes" })).toBeTruthy();
    expect(screen.getByText("2024-04-09T22:00:00.000000019Z")).toBeTruthy();
    expect(screen.getAllByText("INFO2 (Informational)")).toHaveLength(2);
    expect(screen.getByText("Severity Number")).toBeTruthy();
    expect(screen.getByText("Severity Text")).toBeTruthy();
    expect(screen.getByText("demo.case")).toBeTruthy();
    expect(screen.queryByText("service.name")).toBeNull();
    expect(screen.getByText("deployment.environment")).toBeTruthy();
    expect(screen.queryByText("Validation")).toBeNull();
    expect(screen.getByRole("button", { name: "Close panel" })).toBeTruthy();
    expect(screen.getByLabelText("Filter field")).toBeTruthy();

    const headings = Array.from(container.querySelectorAll(".log-detail__heading")).map((node) => node.textContent);
    expect(headings).toEqual(["Summary", "Message", "Trace Correlation", "Attributes", "Resource Attributes", "Scope"]);
  });

  it("falls back to severityNumber when severityText is missing", () => {
    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityNumber: 19,
            body: "persistence operation failed",
            attributes: {},
            resource: { serviceName: "kvstore", attributes: {} },
            scope: { name: "otel" },
          },
          {
            id: "2",
            timeUnixNano: "1712700000000000001",
            severityText: "INFO",
            body: "checkout started",
            attributes: {},
            resource: { serviceName: "checkout", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
      />,
    );

    const severityCells = Array.from(container.querySelectorAll(".data-table__td--severity .sev-badge"));
    const severities = severityCells.map((node) => node.textContent);
    expect(severities).toContain("ERROR3");
    expect(severityCells[0]?.classList.contains("sev-badge--error")).toBe(true);
    expect(severityCells[1]?.classList.contains("sev-badge--info")).toBe(true);
  });

  it("shows both severityNumber and severityText when both are present", () => {
    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityNumber: 3,
            severityText: "ERROR",
            body: "persistence operation failed",
            attributes: {},
            resource: { serviceName: "kvstore", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
      />,
    );

    expect(container.querySelector(".data-table__td--severity .sev-badge")?.textContent).toBe("TRACE3 (ERROR)");
    expect(container.querySelector(".data-table__td--severity .sev-badge")?.classList.contains("sev-badge--default")).toBe(true);
  });

  it("deduplicates identical normalized and text severities", () => {
    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityNumber: 17,
            severityText: "ERROR",
            body: "payment failed",
            attributes: {},
            resource: { serviceName: "payments", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
      />,
    );

    expect(container.querySelector(".data-table__td--severity .sev-badge")?.textContent).toBe("ERROR");
  });

  it("uses text-only fallback when severityNumber is absent", () => {
    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityText: "SEVERE",
            body: "severe text",
            attributes: {},
            resource: { serviceName: "alpha", attributes: {} },
            scope: { name: "otel" },
          },
          {
            id: "2",
            timeUnixNano: "1712700000000000001",
            severityText: "WARNING",
            body: "warning text",
            attributes: {},
            resource: { serviceName: "beta", attributes: {} },
            scope: { name: "otel" },
          },
          {
            id: "3",
            timeUnixNano: "1712700000000000002",
            severityText: "Informational",
            body: "informational text",
            attributes: {},
            resource: { serviceName: "gamma", attributes: {} },
            scope: { name: "otel" },
          },
          {
            id: "4",
            timeUnixNano: "1712700000000000003",
            severityText: "TRACE",
            body: "trace text",
            attributes: {},
            resource: { serviceName: "delta", attributes: {} },
            scope: { name: "otel" },
          },
          {
            id: "5",
            timeUnixNano: "1712700000000000004",
            severityText: "AUDIT",
            body: "audit text",
            attributes: {},
            resource: { serviceName: "epsilon", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
      />,
    );

    const severityCells = Array.from(container.querySelectorAll(".data-table__td--severity .sev-badge"));
    expect(severityCells[0]?.classList.contains("sev-badge--error")).toBe(true);
    expect(severityCells[1]?.classList.contains("sev-badge--warn")).toBe(true);
    expect(severityCells[2]?.classList.contains("sev-badge--info")).toBe(true);
    expect(severityCells[3]?.classList.contains("sev-badge--default")).toBe(true);
    expect(severityCells[4]?.classList.contains("sev-badge--default")).toBe(true);
  });
});
