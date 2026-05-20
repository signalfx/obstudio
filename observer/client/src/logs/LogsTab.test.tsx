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

  it("filters by displayed severity labels such as WARN2", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          id: "2",
          timeUnixNano: "1712700000000000001",
          severityNumber: 14,
          body: "number only: WARN2",
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
            severityNumber: 14,
            body: "number only: WARN2",
            attributes: {},
            resource: { serviceName: "payments", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
        onInteract={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), {
      target: { value: "Severity" },
    });
    fireEvent.change(screen.getByLabelText("severityDisplay value"), {
      target: { value: "WARN2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/logs?filter%5BseverityDisplay%5D%5Beq%5D=WARN2", expect.any(Object));
    expect(screen.getByText("number only: WARN2")).toBeTruthy();
    expect(screen.queryByText("checkout started")).toBeNull();
  });

  it("does not show severity number in the log filter menu", () => {
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

    expect(screen.queryByText("Severity Number")).toBeNull();
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

  it("falls back to severityNumber for number-only log badges and detail titles", () => {
    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityNumber: 14,
            body: "number only: WARN2",
            attributes: {},
            resource: { serviceName: "severity-demo", attributes: {} },
            scope: { name: "demo.logger" },
          },
        ]}
        onInteract={vi.fn()}
      />,
    );

    const badge = container.querySelector(".data-table__td--severity") as HTMLElement;

    expect(badge.textContent).toContain("WARN2");
    expect(badge.classList.contains("sev-badge--warn")).toBe(true);

    fireEvent.click(container.querySelector(".data-table__row--logs") as HTMLElement);

    // Panel title shows the log message body (better UX than severity level).
    expect(container.querySelector(".detail-panel__title")?.textContent).toBe("number only: WARN2");
  });

  it("prefers severityText over conflicting severityNumber values", () => {
    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityNumber: 3,
            severityText: "SEVERE",
            body: "both fields: ERROR (SEVERE)",
            attributes: {},
            resource: { serviceName: "severity-demo", attributes: {} },
            scope: { name: "demo.logger" },
          },
        ]}
        onInteract={vi.fn()}
      />,
    );

    const badge = container.querySelector(".data-table__td--severity") as HTMLElement;

    expect(badge.textContent).toContain("SEVERE");
    expect(badge.textContent).not.toContain("TRACE3");
    expect(badge.classList.contains("sev-badge--error")).toBe(true);

    fireEvent.click(container.querySelector(".data-table__row--logs") as HTMLElement);

    // Panel title shows the log message body (better UX than severity level).
    expect(container.querySelector(".detail-panel__title")?.textContent).toBe("both fields: ERROR (SEVERE)");
  });

  it("uses blue severity styling for info-level badges", () => {
    const { readFileSync } = require("fs");
    const { resolve } = require("path");
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toContain(".sev-badge--info {\n  background: rgba(97, 202, 250, 0.18);\n  color: #61cafa;\n}");
  });

  it("severity badges use pill shape with no border-left accent", () => {
    const { readFileSync } = require("fs");
    const { resolve } = require("path");
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toContain("border-radius: 999px;");
    // No border-left on sev-badge base rule
    const badgeBlock = css.slice(css.indexOf(".sev-badge {"), css.indexOf(".sev-badge--error {"));
    expect(badgeBlock).not.toContain("border-left");
  });

  it("renders JSON tab with syntax-highlighted spans for key, string, number, and keyword tokens", () => {
    const { container } = render(
      <LogsTab
        logs={[
          {
            id: "1",
            timeUnixNano: "1712700000000000000",
            severityText: "INFO",
            body: "checkout started",
            attributes: { count: 3, active: true },
            resource: { serviceName: "checkout", attributes: {} },
            scope: { name: "otel" },
          },
        ]}
        onInteract={vi.fn()}
      />,
    );

    fireEvent.click(container.querySelector(".data-table__row--logs") as HTMLElement);

    const jsonTab = screen.getByRole("button", { name: "JSON" });
    fireEvent.click(jsonTab);

    // Highlighted keys
    expect(container.querySelector(".json-hl__key")).toBeTruthy();
    // Highlighted string values
    expect(container.querySelector(".json-hl__string")).toBeTruthy();
    // Highlighted numbers
    expect(container.querySelector(".json-hl__number")).toBeTruthy();
    // Highlighted keywords (true/false/null)
    expect(container.querySelector(".json-hl__keyword")).toBeTruthy();
  });

  it("JSON tab copy button copies raw JSON not highlighted markup", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    const log = {
      id: "1",
      timeUnixNano: "1712700000000000000",
      severityText: "INFO",
      body: "checkout started",
      attributes: {},
      resource: { serviceName: "checkout", attributes: {} },
      scope: { name: "otel" },
    };

    const { container } = render(<LogsTab logs={[log]} onInteract={vi.fn()} />);

    fireEvent.click(container.querySelector(".data-table__row--logs") as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "JSON" }));
    fireEvent.click(screen.getByRole("button", { name: "Copy JSON" }));

    expect(writeText).toHaveBeenCalledWith(JSON.stringify(log, null, 2));
  });
});
