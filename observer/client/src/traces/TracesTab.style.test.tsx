// @vitest-environment happy-dom

import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TracesTab, traceStatusLabel } from "./TracesTab";
import { SpanDetailsPanel } from "./SpanDetailsPanel";

declare const require: (id: string) => any;
declare const process: { cwd(): string };

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

afterEach(() => cleanup());

describe("TracesTab row layout", () => {
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

  it("renders trace id as a dedicated table column", () => {
    const { container } = render(
      <TracesTab
        traces={[
          { traceId: "trace-1234567890ab", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 3, durationMs: 42, status: "error" },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    expect(screen.getByText("1 traces")).toBeTruthy();
    expect(screen.getByText("Trace ID")).toBeTruthy();
    expect(screen.getByText("Service")).toBeTruthy();
    expect(screen.getByText("Status")).toBeTruthy();
    expect(screen.getByText("Duration")).toBeTruthy();
    expect(screen.getByPlaceholderText("Search operation, trace ID, service, or status")).toBeTruthy();
    expect(container.querySelector(".status-dot")).toBeNull();
    expect(container.querySelector(".data-table__head--left-cluster")).toBeTruthy();
    expect(container.querySelector(".data-table__body-inner--traces")).toBeTruthy();
    expect(container.querySelector(".trace-row__stack")).toBeNull();
    expect(container.querySelector(".trace-row__operation")?.classList.contains("explorer-row__primary")).toBe(true);
    expect(container.querySelector(".data-table__td--trace-id .trace-row__trace-id")?.classList.contains("explorer-row__secondary")).toBe(true);
    expect(container.querySelector(".trace-row__trace-id")?.classList.contains("mono")).toBe(false);
    expect(container.querySelector(".trace-row__trace-id")?.textContent).toBe("trace-1234567890ab");
    expect(container.querySelector(".trace-row__service")?.classList.contains("explorer-row__secondary")).toBe(true);
    expect(container.querySelector(".data-table__td--service")?.textContent).toBe("checkout");
    expect(container.querySelector(".validation-badge")).toBeNull();
    expect(container.querySelector(".data-table__td--status")?.textContent).toContain("error");
    expect(container.querySelector(".data-table__td--duration .explorer-row__numeric")).toBeTruthy();
  });

  it("filters traces by the dedicated status and trace id columns", () => {
    const view = render(
      <TracesTab
        traces={[
          { traceId: "trace-error-123", rootSpanName: "POST /payments", serviceName: "api-gateway", spanCount: 2, durationMs: 42, status: "error" },
          { traceId: "trace-ok-456", rootSpanName: "GET /health", serviceName: "api-gateway", spanCount: 1, durationMs: 5, status: "ok" },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
        validationFindings={[]}
        validationIndex={{ trace: new Map(), span: new Map(), metric: new Map(), log: new Map() }}
      />,
    );

    const input = view.getByPlaceholderText("Search operation, trace ID, service, or status");
    expect(view.getByText("2 traces")).toBeTruthy();

    fireEvent.change(input, { target: { value: "error" } });
    expect(view.getByText("1 traces")).toBeTruthy();
    expect(view.getByText("POST /payments")).toBeTruthy();
    expect(view.queryByText("GET /health")).toBeNull();

    fireEvent.change(input, { target: { value: "trace-ok-456" } });
    expect(view.getByText("1 traces")).toBeTruthy();
    expect(view.getByText("GET /health")).toBeTruthy();
    expect(view.queryByText("POST /payments")).toBeNull();
  });

  it("shows explicit labels for all trace statuses", () => {
    expect(traceStatusLabel("ok")).toBe("ok");
    expect(traceStatusLabel("error")).toBe("error");
    expect(traceStatusLabel("mixed")).toBe("mixed");
    expect(traceStatusLabel("unset")).toBe("unset");
    expect(traceStatusLabel("weird")).toBe("unknown");
  });

  it("does not render validation rule ids in the span detail panel", () => {
    render(
      <SpanDetailsPanel
        span={{
          traceId: "trace-1",
          spanId: "span-1",
          parentSpanId: "",
          name: "GET /orders",
          kind: "SERVER",
          startTimeUnixNano: "2026-04-11T12:00:00Z",
          endTimeUnixNano: "2026-04-11T12:00:01Z",
          durationMs: 1,
          status: { code: "ERROR", message: "" },
          attributes: {},
          events: [],
          links: [],
          resource: { serviceName: "checkout", attributes: {} },
          scope: { name: "otel", version: "" },
        }}
        validationFindings={[
          {
            entityKey: "span:trace-1:span-1",
            source: "weaver",
            ruleId: "invalid_format",
            severity: "violation",
            message: "Attribute 'traceId' does not match name formatting rules.",
            signal: {
              type: "span",
              serviceName: "checkout",
              traceId: "trace-1",
              spanId: "span-1",
              spanName: "GET /orders",
            },
            updatedAt: "2026-04-11T12:00:00Z",
          },
        ]}
      />,
    );

    expect(screen.getByText("Attribute 'traceId' does not match name formatting rules.")).toBeTruthy();
    expect(screen.queryByText("invalid_format")).toBeNull();
  });

  it("uses bounded per-tab column caps with trailing spacer tracks", () => {
    const { readFileSync } = require("fs");
    const { resolve } = require("path");
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toContain(".data-table__head--metrics,\n.data-table__row--metrics {\n  --table-columns: 220px 220px 140px 1fr;\n}");
    expect(css).toContain("--table-columns: 220px 240px 140px 96px 88px 56px 1fr;");
    expect(css).toContain("--findings-tab-grid: 220px 140px 88px 88px 88px 1fr;");
    expect(css).toContain("--findings-tab-grid: 220px 140px 88px 88px 88px 1fr;");
    expect(css).toContain("--table-columns: 220px 240px 88px 1fr;");
    expect(css).toContain(".data-table__head--metrics,\n  .data-table__row--metrics {\n    --table-columns: 220px 100px 1fr;\n  }");
  });

  it("uses the same compact row shell height as logs for master rows", () => {
    const { readFileSync } = require("fs");
    const { resolve } = require("path");
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toContain(".data-table__head--traces,\n.data-table__row--traces {\n  --table-columns: 220px 240px 140px 96px 88px 56px 1fr;\n}");
    expect(css).toContain(".data-table__row--traces {\n  align-items: center;\n  min-height: 34px;\n}");
    expect(css).toContain(".data-table__row--traces .data-table__td {\n  padding-top: 3px;\n  padding-bottom: 3px;\n}");
  });

  it("left-aligns stacked trace and metric values so content does not stretch across the cell", () => {
    const { readFileSync } = require("fs");
    const { resolve } = require("path");
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toContain(".data-table__td--operation {\n  min-width: 0;\n}");
    expect(css).toContain(".trace-row__operation {\n  display: inline-block;\n  max-width: 100%;\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}");
    expect(css).toContain(".data-table__td--trace-id {\n  min-width: 0;\n}");
    expect(css).toContain(".trace-row__trace-id {\n  display: inline-block;\n  max-width: 100%;\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}");
    expect(css).toContain(".metric-card__description {\n  display: block;\n  min-width: 0;\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}");
  });

  it("constrains table headers so narrow count columns do not bleed into neighbors", () => {
    const { readFileSync } = require("fs");
    const { resolve } = require("path");
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toContain(".data-table__th {\n  display: flex;\n  align-items: center;\n  justify-content: flex-start;\n  font-size: var(--font-label);");
    expect(css).toContain(".data-table__td {\n  display: flex;\n  align-items: center;\n  justify-content: flex-start;\n  padding: 3px 6px;");
    expect(css).toContain(".data-table__th--numeric,\n.data-table__td--numeric {\n  justify-self: stretch;\n  text-align: right;\n  justify-content: flex-end;\n}");
    expect(css).toContain(".findings-tab__head .data-table__th {\n  padding: 0 6px;\n  min-width: 0;\n  overflow: hidden;\n  text-overflow: ellipsis;\n}");
  });

  it("uses the same vertical centering model for metric and validation master cells", () => {
    const { readFileSync } = require("fs");
    const { resolve } = require("path");
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toContain(".data-table__cell-content {\n  display: flex;\n  align-items: center;\n  justify-content: flex-start;\n  width: 100%;\n  min-width: 0;\n}");
    expect(css).toContain(".data-table__cell-content--meta {\n  gap: 8px;\n}");
    expect(css).toContain(".data-table__td--metric-meta {\n  display: flex;\n  align-items: center;\n  justify-content: flex-start;\n  min-width: 0;\n}");
    expect(css).toContain(".findings-tab__item-title {\n  display: flex;\n  align-items: center;");
    expect(css).toContain(".findings-tab__item-rule {\n  display: flex;\n  align-items: center;");
    expect(css).toContain(".findings-tab__item-count {\n  display: flex;\n  align-items: center;\n  justify-content: flex-end;");
  });
});
