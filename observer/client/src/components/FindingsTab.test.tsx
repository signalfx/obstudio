// @vitest-environment happy-dom

import React from "react";
import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ValidationFinding, ValidationSummary } from "../api/types";
import { buildValidationIssues } from "../validation/utils";
import { FindingsTab } from "./FindingsTab";

afterEach(() => {
  cleanup();
});

function makeFinding(overrides: Partial<ValidationFinding>): ValidationFinding {
  return {
    entityKey: "span:trace-1:span-1",
    source: "weaver",
    ruleId: "missing_http_method",
    severity: "violation",
    message: "missing http.method",
    signal: {
      type: "span",
      serviceName: "checkout",
      traceId: "trace-1",
      spanId: "span-1",
      spanName: "GET /orders",
    },
    updatedAt: "2026-04-09T00:00:00Z",
    ...overrides,
  };
}

function makeSummary(): ValidationSummary {
  return {
    enabled: true,
    ready: true,
    status: "ready",
    message: "Weaver validator connected",
    hasResult: true,
    stale: false,
    needsRun: false,
    totalEntities: 3,
    totalAdvisories: 3,
    noAdviceCount: 0,
    severityCounts: { violation: 3, improvement: 0, information: 0 },
    highestSeverityCounts: { violation: 3, improvement: 0, information: 0 },
    signalCounts: { span: 2, metric: 1 },
    updatedAt: "2026-04-09T00:01:00Z",
  };
}

describe("FindingsTab", () => {
  it("renders signal mini-tabs and defaults to the first available signal with no detail selection", () => {
    const view = render(
      <FindingsTab
        issues={buildValidationIssues([
          makeFinding({
            entityKey: "metric:checkout:http.server.duration",
            ruleId: "unit_mismatch",
            message: "Unit should be s.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "otel",
              metricName: "http.server.duration",
            },
          }),
          makeFinding({
            entityKey: "metric:checkout:http.server.duration",
            severity: "improvement",
            ruleId: "missing_description",
            message: "Metric needs a description.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "otel",
              metricName: "http.server.duration",
            },
            updatedAt: "2026-04-09T00:01:00Z",
          }),
          makeFinding({
            entityKey: "metric:checkout:http.server.duration",
            severity: "information",
            ruleId: "naming",
            message: "Metric naming can be tightened.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "otel",
              metricName: "http.server.duration",
            },
            updatedAt: "2026-04-09T00:02:00Z",
          }),
          makeFinding({}),
        ])}
        summary={makeSummary()}
      />,
    );

    const tablist = view.getByRole("tablist", { name: "Validation signals" });
    expect(within(tablist).getByRole("tab", { name: "Metrics" }).getAttribute("aria-selected")).toBe("true");
    expect(within(tablist).getByRole("tab", { name: "Spans" }).getAttribute("aria-selected")).toBe("false");

    const head = view.container.querySelector(".findings-tab__head");
    expect(head).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Metric")).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Rule")).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Violations")).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Improvements")).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Information")).toBeTruthy();

    const master = view.container.querySelector(".findings-tab__master");
    expect(master?.classList.contains("findings-tab__master--metric")).toBe(true);
    const rowButton = within(master as HTMLElement).getByText("http.server.duration").closest("button");
    expect(rowButton).toBeTruthy();
    expect(within(rowButton as HTMLElement).getByText("unit_mismatch +2 more")).toBeTruthy();
    const counts = Array.from((rowButton as HTMLElement).querySelectorAll(".findings-tab__item-count")).map((node) => node.textContent?.trim());
    expect(counts).toEqual(["1", "1", "1"]);
    expect((rowButton as HTMLElement).querySelector(".findings-tab__item-title")?.classList.contains("explorer-row__primary")).toBe(true);
    expect((rowButton as HTMLElement).querySelector(".findings-tab__item-rule")?.classList.contains("explorer-row__secondary")).toBe(true);
    expect((rowButton as HTMLElement).querySelector(".findings-tab__item-rule")?.classList.contains("mono")).toBe(false);
    expect(Array.from((rowButton as HTMLElement).querySelectorAll(".findings-tab__item-count")).every((node) => node.classList.contains("explorer-row__numeric"))).toBe(true);
    expect(view.container.querySelector("#validation-issue-detail")).toBeNull();
  });

  it("does not show a validated timestamp before validation has produced a real result", () => {
    const idleSummary: ValidationSummary = {
      ...makeSummary(),
      hasResult: false,
      status: "idle",
      lastRunCompletedAt: "0001-01-01T00:00:00Z",
    };

    const view = render(
      <FindingsTab
        issues={[]}
        summary={idleSummary}
      />,
    );

    expect(view.queryByText(/Validated /)).toBeNull();
    expect(view.getByText("Validation has not been run yet. Run validation to analyze the current telemetry snapshot.")).toBeTruthy();
  });

  it("switches tabs and uses signal-specific fields for spans, logs, and resources", () => {
    const view = render(
      <FindingsTab
        issues={buildValidationIssues([
          makeFinding({
            entityKey: "span:trace-1:span-1",
            signal: {
              type: "span",
              serviceName: "checkout",
              traceId: "trace-1",
              spanId: "span-1",
              spanName: "GET /orders",
            },
          }),
          makeFinding({
            entityKey: "log:1",
            ruleId: "missing_attribute",
            message: "Attribute 'traceId' does not exist in the registry.",
            signal: {
              type: "log",
              serviceName: "order-service",
              logBody: "Cache hit for order ORD-1781",
            },
          }),
          makeFinding({
            entityKey: "resource:1",
            ruleId: "not_stable",
            message: "Attribute 'deployment.environment.name' is not stable; stability = development.",
            signal: { type: "resource", serviceName: "order-service" },
            context: {
              attribute_name: "deployment.environment.name",
              stability: "development",
            },
          }),
        ])}
        summary={makeSummary()}
      />,
    );

    const tablist = view.getByRole("tablist", { name: "Validation signals" });

    fireEvent.click(within(tablist).getByRole("tab", { name: "Spans" }));
    let head = view.container.querySelector(".findings-tab__head");
    expect(within(head as HTMLElement).getByText("Span")).toBeTruthy();
    let master = view.container.querySelector(".findings-tab__master");
    expect(master?.classList.contains("findings-tab__master--span")).toBe(true);
    expect(within(master as HTMLElement).getByText("GET /orders")).toBeTruthy();

    fireEvent.click(within(tablist).getByRole("tab", { name: "Logs" }));
    head = view.container.querySelector(".findings-tab__head");
    expect(within(head as HTMLElement).getByText("Example")).toBeTruthy();
    master = view.container.querySelector(".findings-tab__master");
    expect(master?.classList.contains("findings-tab__master--log")).toBe(true);
    expect(within(master as HTMLElement).getByText("Cache hit for order ORD-1781")).toBeTruthy();
    expect(within(master as HTMLElement).getByText("missing_attribute")).toBeTruthy();

    fireEvent.click(within(tablist).getByRole("tab", { name: "Resources" }));
    head = view.container.querySelector(".findings-tab__head");
    expect(within(head as HTMLElement).getByText("Attribute")).toBeTruthy();
    master = view.container.querySelector(".findings-tab__master");
    expect(master?.classList.contains("findings-tab__master--resource")).toBe(true);
    expect(within(master as HTMLElement).getByText("deployment.environment.name")).toBeTruthy();
    expect(within(master as HTMLElement).getByText("not_stable")).toBeTruthy();
  });

  it("does not render generic detail titles or subtitles in any validation subtab", () => {
    const view = render(
      <FindingsTab
        issues={buildValidationIssues([
          makeFinding({
            entityKey: "span:trace-1:span-1",
            signal: {
              type: "span",
              serviceName: "checkout",
              traceId: "trace-1",
              spanId: "span-1",
              spanName: "GET /orders",
            },
          }),
          makeFinding({
            entityKey: "log:1",
            ruleId: "missing_attribute",
            message: "Attribute 'traceId' does not exist in the registry.",
            signal: {
              type: "log",
              serviceName: "order-service",
              logBody: "Cache hit for order ORD-1781",
            },
          }),
          makeFinding({
            entityKey: "resource:1",
            ruleId: "not_stable",
            message: "Attribute 'deployment.environment.name' is not stable; stability = development.",
            signal: { type: "resource", serviceName: "order-service" },
            context: {
              attribute_name: "deployment.environment.name",
              stability: "development",
            },
          }),
        ])}
        summary={makeSummary()}
      />,
    );

    let master = view.container.querySelector(".findings-tab__master");
    fireEvent.click(within(master as HTMLElement).getByText("GET /orders").closest("button") as HTMLElement);
    let detailPanel = view.container.querySelector("#validation-issue-detail") as HTMLElement;
    expect(detailPanel.querySelector(".detail-panel__title")).toBeNull();
    expect(detailPanel.querySelector(".detail-panel__subtitle")).toBeNull();
    expect(detailPanel.querySelector(".findings-tab__detail-heading")?.textContent).toBe("GET /orders");

    const tablist = view.getByRole("tablist", { name: "Validation signals" });
    fireEvent.click(within(tablist).getByRole("tab", { name: "Logs" }));
    master = view.container.querySelector(".findings-tab__master");
    fireEvent.click(within(master as HTMLElement).getByText("Cache hit for order ORD-1781").closest("button") as HTMLElement);
    detailPanel = view.container.querySelector("#validation-issue-detail") as HTMLElement;
    expect(detailPanel.querySelector(".detail-panel__title")).toBeNull();
    expect(detailPanel.querySelector(".detail-panel__subtitle")).toBeNull();
    expect(detailPanel.querySelector(".findings-tab__detail-heading")?.textContent).toBe("Cache hit for order ORD-1781");

    fireEvent.click(within(tablist).getByRole("tab", { name: "Resources" }));
    master = view.container.querySelector(".findings-tab__master");
    fireEvent.click(within(master as HTMLElement).getByText("deployment.environment.name").closest("button") as HTMLElement);
    detailPanel = view.container.querySelector("#validation-issue-detail") as HTMLElement;
    expect(detailPanel.querySelector(".detail-panel__title")).toBeNull();
    expect(detailPanel.querySelector(".detail-panel__subtitle")).toBeNull();
    expect(detailPanel.querySelector(".findings-tab__detail-heading")?.textContent).toBe("deployment.environment.name");
  });

  it("shows the clicked row in the shared side detail panel", () => {
    const view = render(
      <FindingsTab
        issues={buildValidationIssues([
          makeFinding({
            entityKey: "metric:checkout:jvm.thread.count",
            ruleId: "unexpected_instrument",
            message: "Instrument should be 'updowncounter', but found 'gauge'.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "",
              metricName: "jvm.thread.count",
            },
          }),
          makeFinding({
            entityKey: "metric:checkout:jvm.thread.count",
            ruleId: "unit_mismatch",
            message: "Unit should be '{thread}', but found ''.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "",
              metricName: "jvm.thread.count",
            },
            updatedAt: "2026-04-09T00:01:00Z",
          }),
        ])}
        summary={makeSummary()}
      />,
    );

    const layout = view.container.querySelector(".findings-tab__layout");
    expect(layout?.classList.contains("findings-tab__layout--with-panel")).toBe(false);

    const master = view.container.querySelector(".findings-tab__master");
    const rowButton = within(master as HTMLElement).getByText("jvm.thread.count").closest("button");
    expect(view.container.querySelector("#validation-issue-detail")).toBeNull();

    fireEvent.click(rowButton as HTMLElement);

    const detailPanel = view.container.querySelector("#validation-issue-detail");
    expect(detailPanel).toBeTruthy();
    expect(view.container.querySelector(".findings-tab__layout--with-panel")).toBeTruthy();
    expect((detailPanel as HTMLElement).querySelector(".detail-panel__title")).toBeNull();
    expect((detailPanel as HTMLElement).querySelector(".detail-panel__subtitle")).toBeNull();
    expect((detailPanel as HTMLElement).querySelector(".findings-tab__detail-heading")?.textContent).toBe("jvm.thread.count");
    expect((detailPanel as HTMLElement).querySelector(".findings-tab__detail-grid")).toBeNull();
    expect(within(detailPanel as HTMLElement).queryByText("Target")).toBeNull();
    expect(within(detailPanel as HTMLElement).queryByText("Signal")).toBeNull();
    expect(within(detailPanel as HTMLElement).queryByText("Service")).toBeNull();
    expect(within(detailPanel as HTMLElement).queryByText("Entities")).toBeNull();
    expect(within(detailPanel as HTMLElement).queryByText("Last Seen")).toBeNull();
    expect(within(detailPanel as HTMLElement).getByText("Findings")).toBeTruthy();
    expect(within(detailPanel as HTMLElement).getAllByText("unexpected_instrument").length).toBeGreaterThan(0);
    expect(within(detailPanel as HTMLElement).getAllByText("unit_mismatch").length).toBeGreaterThan(0);
  });

  it("shows resource context and hides empty service metadata in the detail panel", () => {
    const view = render(
      <FindingsTab
        issues={[
          {
            key: "resource:not_stable",
            severity: "violation",
            message: "Attribute 'deployment.environment.name' is not stable; stability = development.",
            signalType: "resource",
            targetLabel: "deployment.environment.name",
            serviceName: "",
            scopeName: "",
            count: 1,
            violationCount: 1,
            improvementCount: 0,
            informationCount: 0,
            affectedEntityCount: 1,
            firstSeen: "2026-04-10T00:00:00Z",
            lastSeen: "2026-04-10T00:00:00Z",
            findings: [
              makeFinding({
                entityKey: "resource:",
                ruleId: "not_stable",
                message: "Attribute 'deployment.environment.name' is not stable; stability = development.",
                signal: { type: "resource" },
                context: {
                  attribute_name: "deployment.environment.name",
                  stability: "development",
                },
              }),
            ],
          },
        ]}
        summary={makeSummary()}
      />,
    );

    const tablist = view.getByRole("tablist", { name: "Validation signals" });
    fireEvent.click(within(tablist).getByRole("tab", { name: "Resources" }));

    const master = view.container.querySelector(".findings-tab__master");
    fireEvent.click(within(master as HTMLElement).getByText("deployment.environment.name").closest("button") as HTMLElement);

    const detailPanel = view.container.querySelector("#validation-issue-detail");
    expect(within(detailPanel as HTMLElement).getByText("Stability")).toBeTruthy();
    expect(within(detailPanel as HTMLElement).getByText("development")).toBeTruthy();
    expect(within(detailPanel as HTMLElement).queryByText("Service")).toBeNull();
    expect(within(detailPanel as HTMLElement).queryByText("Scope")).toBeNull();
    expect(within(detailPanel as HTMLElement).getByText("Resource attributes apply across traces, metrics, and logs emitted by the same service.")).toBeTruthy();
  });

  it("renders the selected issue in a split view with the compact close-only detail header", () => {
    const view = render(
      <FindingsTab
        issues={buildValidationIssues([
          makeFinding({
            entityKey: "metric:checkout:jvm.thread.count",
            ruleId: "unit_mismatch",
            message: "Metric unit should be {thread}.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "otel",
              metricName: "jvm.thread.count",
            },
          }),
        ])}
        summary={makeSummary()}
      />,
    );

    const row = view.getByText("jvm.thread.count").closest("button");
    const item = row?.closest(".findings-tab__item");
    fireEvent.click(row as HTMLElement);

    const layout = view.container.querySelector(".findings-tab__layout");
    const detailPanel = view.container.querySelector("#validation-issue-detail");
    const selected = view.container.querySelector(".findings-tab__item.is-selected");

    expect(layout?.classList.contains("findings-tab__layout--with-panel")).toBe(true);
    expect(detailPanel).toBeTruthy();
    expect(detailPanel?.querySelector(".detail-panel__header--close-only")).toBeTruthy();
    expect(selected).toBe(item);
    expect(detailPanel?.querySelector(".findings-tab__detail-heading")?.textContent).toBe("jvm.thread.count");
  });
});
