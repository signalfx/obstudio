// @vitest-environment happy-dom

import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  afterEach(() => cleanup());

  beforeEach(() => {
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

  it("filters logs from the compact explorer toolbar", () => {
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
    expect(screen.getByRole("option", { name: "TRACE" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "FATAL" })).toBeTruthy();
    expect(container.querySelector(".data-table__td--timestamp .explorer-row__secondary")).toBeTruthy();
    expect(container.querySelector(".data-table__td--service .explorer-row__secondary")).toBeTruthy();
    expect(container.querySelector(".data-table__td--message .explorer-row__primary")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("Search message, service, or trace ID"), {
      target: { value: "does-not-match" },
    });

    expect(screen.getByText("No logs match the current filters.")).toBeTruthy();
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
      />,
    );

    fireEvent.click(container.querySelector(".data-table__row--logs") as HTMLElement);

    expect(screen.getByRole("heading", { name: "Message" })).toBeTruthy();
    expect(screen.queryByText("Validation")).toBeNull();
    expect(screen.getByRole("button", { name: "Close panel" })).toBeTruthy();
    expect(screen.getAllByRole("combobox", { name: "Filter logs by severity" }).length).toBeGreaterThan(0);
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

    fireEvent.change(container.querySelector('select[aria-label="Filter logs by severity"]') as HTMLElement, {
      target: { value: "error" },
    });

    expect(screen.getByText("persistence operation failed")).toBeTruthy();
    expect(screen.queryByText("checkout started")).toBeNull();
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

    fireEvent.change(container.querySelector('select[aria-label="Filter logs by severity"]') as HTMLElement, {
      target: { value: "trace" },
    });

    expect(screen.getByText("persistence operation failed")).toBeTruthy();
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

    fireEvent.change(container.querySelector('select[aria-label="Filter logs by severity"]') as HTMLElement, {
      target: { value: "info" },
    });

    expect(screen.getByText("informational text")).toBeTruthy();
    expect(screen.queryByText("warning text")).toBeNull();
  });
});
