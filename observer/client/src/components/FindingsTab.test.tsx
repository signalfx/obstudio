// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ValidationFinding, ValidationSummary } from "../api/types";
import { buildValidationIssues } from "../validation/utils";
import { FindingsTab } from "./FindingsTab";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
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
    const metricsTab = within(tablist).getByRole("tab", { name: /^Metrics/ });
    const spansTab = within(tablist).getByRole("tab", { name: /^Spans/ });
    expect(metricsTab.getAttribute("aria-selected")).toBe("true");
    expect(spansTab.getAttribute("aria-selected")).toBe("false");

    // Signal tabs show issue counts
    expect(metricsTab.querySelector(".findings-tab__signal-count")?.textContent).toBe("1");
    expect(spansTab.querySelector(".findings-tab__signal-count")?.textContent).toBe("1");
    expect(metricsTab.getAttribute("aria-label")).toBe("Metrics, 1 issue");
    expect(spansTab.getAttribute("aria-label")).toBe("Spans, 1 issue");

    const head = view.container.querySelector(".findings-tab__head");
    expect(head).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Metric")).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Rule")).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Viol.")).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Impr.")).toBeTruthy();
    expect(within(head as HTMLElement).getByText("Info")).toBeTruthy();

    const master = view.container.querySelector(".findings-tab__master");
    expect(master?.classList.contains("findings-tab__master--metric")).toBe(true);
    const rowButton = within(master as HTMLElement).getByText("http.server.duration").closest("button");
    expect(rowButton).toBeTruthy();
    expect(within(rowButton as HTMLElement).getByText("unit_mismatch +2 more")).toBeTruthy();
    const counts = Array.from((rowButton as HTMLElement).querySelectorAll(".findings-tab__item-count")).map((node) => node.textContent?.trim());
    expect(counts).toEqual(["1", "1", "1"]);
    expect((rowButton as HTMLElement).getAttribute("aria-label")).toBe("http.server.duration, unit_mismatch +2 more, 1 violation, 1 improvement, 1 information finding");
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

  it("refreshes relative validation timestamps as time passes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-09T00:01:45Z"));

    const summary: ValidationSummary = {
      ...makeSummary(),
      lastRunCompletedAt: "2026-04-09T00:01:30Z",
    };

    const view = render(
      <FindingsTab
        issues={buildValidationIssues([makeFinding({})])}
        summary={summary}
      />,
    );

    expect(view.getByText("Validated just now")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(45_000);
    });

    expect(view.getByText("Validated 1 minute ago")).toBeTruthy();
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

    fireEvent.click(within(tablist).getByRole("tab", { name: /^Spans/ }));
    let head = view.container.querySelector(".findings-tab__head");
    expect(within(head as HTMLElement).getByText("Span")).toBeTruthy();
    let master = view.container.querySelector(".findings-tab__master");
    expect(master?.classList.contains("findings-tab__master--span")).toBe(true);
    expect(within(master as HTMLElement).getByText("GET /orders")).toBeTruthy();

    fireEvent.click(within(tablist).getByRole("tab", { name: /^Logs/ }));
    head = view.container.querySelector(".findings-tab__head");
    expect(within(head as HTMLElement).getByText("Example")).toBeTruthy();
    master = view.container.querySelector(".findings-tab__master");
    expect(master?.classList.contains("findings-tab__master--log")).toBe(true);
    expect(within(master as HTMLElement).getByText("Cache hit for order ORD-1781")).toBeTruthy();
    expect(within(master as HTMLElement).getByText("missing_attribute")).toBeTruthy();

    fireEvent.click(within(tablist).getByRole("tab", { name: /^Resources/ }));
    head = view.container.querySelector(".findings-tab__head");
    expect(within(head as HTMLElement).getByText("Attribute")).toBeTruthy();
    master = view.container.querySelector(".findings-tab__master");
    expect(master?.classList.contains("findings-tab__master--resource")).toBe(true);
    expect(within(master as HTMLElement).getByText("deployment.environment.name")).toBeTruthy();
    expect(within(master as HTMLElement).getByText("not_stable")).toBeTruthy();
  });

  it("shows per-tab counts for the currently filtered rows and keeps span rows reachable", () => {
    const view = render(
      <FindingsTab
        issues={buildValidationIssues([
          makeFinding({
            entityKey: "metric:checkout:http.server.duration",
            ruleId: "unit_mismatch",
            severity: "violation",
            message: "Unit should be s.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "otel",
              metricName: "http.server.duration",
            },
          }),
          makeFinding({
            entityKey: "span:trace-2:span-2",
            ruleId: "missing_http_method",
            severity: "information",
            message: "missing http.method",
            signal: {
              type: "span",
              serviceName: "checkout",
              traceId: "trace-2",
              spanId: "span-2",
              spanName: "POST /orders",
            },
          }),
        ])}
        summary={makeSummary()}
      />,
    );

    fireEvent.change(view.container.querySelector(".validation-panel__select") as HTMLSelectElement, {
      target: { value: "information" },
    });

    const tablist = view.getByRole("tablist", { name: "Validation signals" });
    const metricsTab = within(tablist).getByRole("tab", { name: /^Metrics/ });
    const spansTab = within(tablist).getByRole("tab", { name: /^Spans/ });

    expect(metricsTab.querySelector(".findings-tab__signal-count")).toBeNull();
    expect(metricsTab.getAttribute("aria-label")).toBe("Metrics");
    expect(spansTab.querySelector(".findings-tab__signal-count")?.textContent).toBe("1");
    expect(spansTab.getAttribute("aria-label")).toBe("Spans, 1 issue");
    expect(spansTab.getAttribute("aria-selected")).toBe("true");
    expect(view.queryByText("No metrics validation issues match the current filters.")).toBeNull();

    const master = view.container.querySelector(".findings-tab__master");
    expect(master?.classList.contains("findings-tab__master--span")).toBe(true);
    const rowButton = within(master as HTMLElement).getByText("POST /orders").closest("button");
    expect(rowButton).toBeTruthy();
    const rowCounts = Array.from((rowButton as HTMLElement).querySelectorAll(".findings-tab__item-count")).map((node) => node.textContent?.trim());
    expect(rowCounts).toEqual(["", "", "1"]);
    expect((rowButton as HTMLElement).getAttribute("aria-label")).toBe("POST /orders, missing_http_method, 1 information finding");
  });

  it("auto-selects the first non-empty tab when results arrive before any explicit tab choice", () => {
    const view = render(<FindingsTab issues={[]} summary={makeSummary()} />);

    let tablist = view.getByRole("tablist", { name: "Validation signals" });
    expect(within(tablist).getByRole("tab", { name: /^Metrics/ }).getAttribute("aria-selected")).toBe("true");
    expect(view.getByText("No metrics validation issues match the current filters.")).toBeTruthy();

    view.rerender(
      <FindingsTab
        issues={buildValidationIssues([
          makeFinding({
            entityKey: "span:trace-2:span-2",
            signal: {
              type: "span",
              serviceName: "checkout",
              traceId: "trace-2",
              spanId: "span-2",
              spanName: "POST /orders",
            },
          }),
        ])}
        summary={makeSummary()}
      />,
    );

    tablist = view.getByRole("tablist", { name: "Validation signals" });
    const spansTab = within(tablist).getByRole("tab", { name: /^Spans/ });
    expect(spansTab.getAttribute("aria-selected")).toBe("true");
    expect(within(view.container.querySelector(".findings-tab__master") as HTMLElement).getByText("POST /orders")).toBeTruthy();
  });

  it("keeps an empty validation tab selected and shows its empty state", () => {
    const view = render(
      <FindingsTab
        issues={buildValidationIssues([
          makeFinding({
            entityKey: "metric:checkout:http.server.duration",
            ruleId: "unit_mismatch",
            severity: "violation",
            message: "Unit should be s.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "otel",
              metricName: "http.server.duration",
            },
          }),
        ])}
        summary={makeSummary()}
      />,
    );

    const tablist = view.getByRole("tablist", { name: "Validation signals" });
    const resourcesTab = within(tablist).getByRole("tab", { name: /^Resources/ });

    expect(resourcesTab.querySelector(".findings-tab__signal-count")).toBeNull();
    expect(resourcesTab.getAttribute("aria-label")).toBe("Resources");

    fireEvent.click(resourcesTab);

    expect(resourcesTab.getAttribute("aria-selected")).toBe("true");
    expect(view.getByText("No resources validation issues match the current filters.")).toBeTruthy();
    expect(view.container.querySelector(".findings-tab__master")).toBeNull();
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
    expect(detailPanel.querySelector(".detail-panel__title")?.textContent).toBe("GET /orders");
    expect(detailPanel.querySelector(".detail-panel__subtitle")?.textContent).toContain("Span");

    const tablist = view.getByRole("tablist", { name: "Validation signals" });
    fireEvent.click(within(tablist).getByRole("tab", { name: /^Logs/ }));
    master = view.container.querySelector(".findings-tab__master");
    fireEvent.click(within(master as HTMLElement).getByText("Cache hit for order ORD-1781").closest("button") as HTMLElement);
    detailPanel = view.container.querySelector("#validation-issue-detail") as HTMLElement;
    expect(detailPanel.querySelector(".detail-panel__title")?.textContent).toBe("Cache hit for order ORD-1781");
    expect(detailPanel.querySelector(".detail-panel__subtitle")?.textContent).toContain("Log");

    fireEvent.click(within(tablist).getByRole("tab", { name: /^Resources/ }));
    master = view.container.querySelector(".findings-tab__master");
    fireEvent.click(within(master as HTMLElement).getByText("deployment.environment.name").closest("button") as HTMLElement);
    detailPanel = view.container.querySelector("#validation-issue-detail") as HTMLElement;
    expect(detailPanel.querySelector(".detail-panel__title")?.textContent).toBe("deployment.environment.name");
    expect(detailPanel.querySelector(".detail-panel__subtitle")?.textContent).toContain("Resource");
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
    expect((detailPanel as HTMLElement).querySelector(".detail-panel__title")?.textContent).toBe("jvm.thread.count");
    expect((detailPanel as HTMLElement).querySelector(".detail-panel__subtitle")?.textContent).toContain("Metric");
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
    fireEvent.click(within(tablist).getByRole("tab", { name: /^Resources/ }));

    const master = view.container.querySelector(".findings-tab__master");
    fireEvent.click(within(master as HTMLElement).getByText("deployment.environment.name").closest("button") as HTMLElement);

    const detailPanel = view.container.querySelector("#validation-issue-detail");
    expect(within(detailPanel as HTMLElement).getByText("Stability")).toBeTruthy();
    expect(within(detailPanel as HTMLElement).getByText("development")).toBeTruthy();
    expect(within(detailPanel as HTMLElement).queryByText("Service")).toBeNull();
    expect(within(detailPanel as HTMLElement).queryByText("Scope")).toBeNull();
    expect(within(detailPanel as HTMLElement).getByText("Resource attributes apply across traces, metrics, and logs emitted by the same service.")).toBeTruthy();
  });

  it("groups detail findings by severity without a summary-card strip", () => {
    const view = render(
      <FindingsTab
        issues={buildValidationIssues([
          makeFinding({
            entityKey: "metric:checkout:http.server.request.duration",
            ruleId: "unit_mismatch",
            severity: "violation",
            message: "Unit should be 's', but found 'ms'.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "otel",
              metricName: "http.server.request.duration",
            },
            updatedAt: "2026-04-09T00:00:00Z",
          }),
          makeFinding({
            entityKey: "metric:checkout:http.server.request.duration",
            ruleId: "recommended_attribute_not_present",
            severity: "improvement",
            message: "Recommended attribute 'network.protocol.version' is not present.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "otel",
              metricName: "http.server.request.duration",
            },
            updatedAt: "2026-04-09T00:01:00Z",
          }),
          makeFinding({
            entityKey: "metric:checkout:http.server.request.duration",
            ruleId: "conditionally_required_attribute_not_present",
            severity: "information",
            message: "Conditionally required attribute 'http.route' is not present.",
            signal: {
              type: "metric",
              serviceName: "checkout",
              scopeName: "otel",
              metricName: "http.server.request.duration",
            },
            updatedAt: "2026-04-09T00:02:00Z",
          }),
        ])}
        summary={makeSummary()}
      />,
    );

    const row = view.getByText("http.server.request.duration").closest("button");
    fireEvent.click(row as HTMLElement);

    const detailPanel = view.container.querySelector("#validation-issue-detail") as HTMLElement;
    expect(within(detailPanel).getAllByText("1 finding")).toHaveLength(3);
    expect(within(detailPanel).queryByText("Violations")).toBeNull();
    expect(within(detailPanel).queryByText("Improvements")).toBeNull();
    expect(within(detailPanel).queryByText("Information")).toBeNull();
    expect(within(detailPanel).getByText("unit_mismatch")).toBeTruthy();
    expect(within(detailPanel).getByText("recommended_attribute_not_present")).toBeTruthy();
    expect(within(detailPanel).getByText("conditionally_required_attribute_not_present")).toBeTruthy();
    expect(within(detailPanel).getAllByText("Rule")).toHaveLength(3);
    expect(within(detailPanel).queryByText("Suggested fix")).toBeNull();
    expect(within(detailPanel).queryByText("Emit this metric with the semantic-convention unit expected by the validator.")).toBeNull();
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
    expect(detailPanel?.querySelector(".detail-panel__header--close-only")).toBeNull();
    expect(detailPanel?.querySelector(".detail-panel__header .detail-panel__close")).toBeTruthy();
    expect(selected).toBe(item);
    expect(detailPanel?.querySelector(".detail-panel__title")?.textContent).toBe("jvm.thread.count");
    expect((detailPanel?.closest(".resizable-panel") as HTMLElement | null)?.style.getPropertyValue("--panel-width")).toBe("560px");
  });
});
