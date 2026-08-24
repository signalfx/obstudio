// @vitest-environment happy-dom

import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Span } from "../api/types";
import { SpanDetailsPanel } from "./SpanDetailsPanel";

function makeSpan(overrides: Partial<Span> = {}): Span {
  return {
    traceId: "trace-1",
    spanId: "span-1",
    parentSpanId: "",
    name: "GET /orders",
    kind: "SERVER",
    startTimeUnixNano: "2026-04-09T00:00:00Z",
    endTimeUnixNano: "2026-04-09T00:00:00.012Z",
    durationMs: 12.3,
    status: { code: "OK", message: "" },
    attributes: {},
    events: [],
    links: [],
    resource: { serviceName: "checkout", attributes: {} },
    scope: { name: "otel", version: "1.0.0" },
    ...overrides,
  };
}

describe("SpanDetailsPanel keyboard navigation", () => {
  afterEach(cleanup);

  it("starts on Info tab with roving tabIndex", () => {
    const { container } = render(<SpanDetailsPanel span={makeSpan()} validationFindings={[]} />);
    const tablist = container.querySelector('[role="tablist"]') as HTMLElement;
    const [infoTab, attrTab] = Array.from(tablist.querySelectorAll<HTMLElement>('[role="tab"]'));

    expect(infoTab.getAttribute("aria-selected")).toBe("true");
    expect(infoTab.getAttribute("tabindex")).toBe("0");
    expect(attrTab.getAttribute("tabindex")).toBe("-1");
  });

  it("ArrowRight moves to Attributes tab", () => {
    const { container } = render(<SpanDetailsPanel span={makeSpan()} validationFindings={[]} />);
    const tablist = container.querySelector('[role="tablist"]') as HTMLElement;

    fireEvent.keyDown(tablist, { key: "ArrowRight" });

    const attrTab = screen.getByRole("tab", { name: /Attributes/ });
    expect(attrTab.getAttribute("aria-selected")).toBe("true");
    expect(attrTab.getAttribute("tabindex")).toBe("0");
    expect(screen.getByRole("tab", { name: "Info" }).getAttribute("tabindex")).toBe("-1");
  });

  it("ArrowLeft from Info wraps to Links tab", () => {
    const { container } = render(<SpanDetailsPanel span={makeSpan()} validationFindings={[]} />);
    const tablist = container.querySelector('[role="tablist"]') as HTMLElement;

    fireEvent.keyDown(tablist, { key: "ArrowLeft" });

    expect(screen.getByRole("tab", { name: "Links" }).getAttribute("aria-selected")).toBe("true");
  });

  it("ArrowRight from Links tab wraps back to Info", () => {
    const { container } = render(<SpanDetailsPanel span={makeSpan()} validationFindings={[]} />);
    const tablist = container.querySelector('[role="tablist"]') as HTMLElement;

    fireEvent.keyDown(tablist, { key: "End" });
    fireEvent.keyDown(tablist, { key: "ArrowRight" });

    expect(screen.getByRole("tab", { name: "Info" }).getAttribute("aria-selected")).toBe("true");
  });

  it("End key moves to last tab (Links)", () => {
    const { container } = render(<SpanDetailsPanel span={makeSpan()} validationFindings={[]} />);
    const tablist = container.querySelector('[role="tablist"]') as HTMLElement;

    fireEvent.keyDown(tablist, { key: "End" });

    const linksTab = screen.getByRole("tab", { name: "Links" });
    expect(linksTab.getAttribute("aria-selected")).toBe("true");
    expect(linksTab.getAttribute("tabindex")).toBe("0");
  });

  it("Home key returns to Info from any tab", () => {
    const { container } = render(<SpanDetailsPanel span={makeSpan()} validationFindings={[]} />);
    const tablist = container.querySelector('[role="tablist"]') as HTMLElement;

    fireEvent.keyDown(tablist, { key: "End" });
    fireEvent.keyDown(tablist, { key: "Home" });

    const infoTab = screen.getByRole("tab", { name: "Info" });
    expect(infoTab.getAttribute("aria-selected")).toBe("true");
    expect(infoTab.getAttribute("tabindex")).toBe("0");
  });

  it("active tab controls a mounted tabpanel", () => {
    const { container } = render(
      <SpanDetailsPanel
        span={makeSpan({ attributes: { "http.method": "GET" } })}
        validationFindings={[]}
      />,
    );
    const tablist = container.querySelector('[role="tablist"]') as HTMLElement;

    fireEvent.keyDown(tablist, { key: "ArrowRight" });

    const panel = container.querySelector('[role="tabpanel"]') as HTMLElement;
    expect(panel.id).toBe("span-panel-attributes");
    expect(panel.getAttribute("aria-labelledby")).toBe("span-tab-attributes");
  });

  it("only the active tab has aria-controls; inactive tabs omit it", () => {
    const { container } = render(<SpanDetailsPanel span={makeSpan()} validationFindings={[]} />);
    const tabs = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'));
    const activeTab = tabs.find((t) => t.getAttribute("aria-selected") === "true")!;
    const inactiveTabs = tabs.filter((t) => t.getAttribute("aria-selected") === "false");

    expect(activeTab.getAttribute("aria-controls")).toBeTruthy();
    expect(document.getElementById(activeTab.getAttribute("aria-controls")!)).toBeTruthy();
    for (const tab of inactiveTabs) {
      expect(tab.getAttribute("aria-controls")).toBeNull();
    }
  });
});
