// @vitest-environment happy-dom

import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MetricSeries } from "./useMetricTimeSeries";
import { TimeSeriesChart } from "./TimeSeriesChart";

afterEach(() => {
  cleanup();
});

function makeSeries(): MetricSeries[] {
  return [
    {
      key: "checkout|otel|resource:|point:",
      metricKey: "http.server.request.duration",
      metricName: "http.server.request.duration",
      type: "histogram",
      unit: "ms",
      description: "Request duration",
      attributes: {},
      scope: { name: "otel" },
      resource: { serviceName: "checkout", attributes: {} },
      points: [
        { value: 10, timestamp: "2026-06-30T12:00:00.000Z" },
        { value: 20, timestamp: "2026-06-30T12:01:00.000Z" },
      ],
      latest: 20,
    },
  ];
}

describe("TimeSeriesChart", () => {
  // Regression: preserveAspectRatio must stay uniform ("meet"). A non-uniform
  // "none" value stretches the fixed 800x240 viewBox to fill the flex container,
  // which distorts every <text> axis label (Y values + X time ticks) because SVG
  // text is scaled non-uniformly along with the geometry.
  it("scales the SVG uniformly so axis text labels are not distorted", () => {
    const { container } = render(
      <TimeSeriesChart
        series={makeSeries()}
        displayType="lines"
        selectedKey={null}
        onSelectSeries={() => {}}
      />,
    );

    const svg = container.querySelector("svg.ts-chart__svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("preserveAspectRatio")).toBe("xMidYMid meet");
    // Axis labels must render inside the same scaled SVG.
    expect(container.querySelectorAll(".ts-chart__axis-label").length).toBeGreaterThan(0);
  });
});

describe("TimeSeriesChart annotation aria-pressed", () => {
  it("annotation button has aria-pressed=false when no series is selected", () => {
    render(
      <TimeSeriesChart
        series={makeSeries()}
        displayType="lines"
        selectedKey={null}
        onSelectSeries={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: /checkout/i }).getAttribute("aria-pressed")).toBe("false");
  });

  it("annotation button has aria-pressed=true when its series key is the selected key", () => {
    const series = makeSeries();
    render(
      <TimeSeriesChart
        series={series}
        displayType="lines"
        selectedKey={series[0].key}
        onSelectSeries={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: /checkout/i }).getAttribute("aria-pressed")).toBe("true");
  });

  it("clicking inactive annotation calls onSelectSeries with the key; aria-pressed transitions false → true → false", () => {
    const series = makeSeries();
    const onSelectSeries = vi.fn();
    const { rerender } = render(
      <TimeSeriesChart
        series={series}
        displayType="lines"
        selectedKey={null}
        onSelectSeries={onSelectSeries}
      />,
    );

    const btn = screen.getByRole("button", { name: /checkout/i });
    expect(btn.getAttribute("aria-pressed")).toBe("false");

    // Activate — transitions to pressed
    fireEvent.click(btn);
    expect(onSelectSeries).toHaveBeenCalledWith(series[0].key);

    rerender(
      <TimeSeriesChart
        series={series}
        displayType="lines"
        selectedKey={series[0].key}
        onSelectSeries={onSelectSeries}
      />,
    );
    expect(btn.getAttribute("aria-pressed")).toBe("true");

    // Deactivate — transitions back to unpressed
    fireEvent.click(btn);
    expect(onSelectSeries).toHaveBeenCalledWith(null);

    rerender(
      <TimeSeriesChart
        series={series}
        displayType="lines"
        selectedKey={null}
        onSelectSeries={onSelectSeries}
      />,
    );
    expect(btn.getAttribute("aria-pressed")).toBe("false");
  });
});
