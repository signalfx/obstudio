// @vitest-environment happy-dom

import React from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
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
