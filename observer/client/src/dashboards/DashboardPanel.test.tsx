// @vitest-environment happy-dom

import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DashboardPanel } from "./DashboardPanel";
import { makePanel } from "./testFixtures";
import type { MetricGroup, MetricDataPoint } from "../api/types";

afterEach(cleanup);

describe("DashboardPanel", () => {
  it("renders an SVG chart for a matched time-series panel", () => {
    const { container } = render(<DashboardPanel panel={makePanel()} />);
    // The shared TimeSeriesChart draws a <path> when series have points.
    expect(container.querySelector("svg")).toBeTruthy();
    expect(container.querySelector("path")).toBeTruthy();
    expect(screen.getByText("P99 Latency")).toBeTruthy();
  });

  it("shows an honest empty card naming the metric + filter chips when unmatched", () => {
    const panel = makePanel({
      matched: false,
      metrics: [],
      query: { metricName: "http.server.request.duration", filters: { "service.name": ["checkout"] } },
    });
    render(<DashboardPanel panel={panel} />);

    expect(screen.getByText(/No local series matches/i)).toBeTruthy();
    expect(screen.getByText("http.server.request.duration")).toBeTruthy();
    expect(screen.getByText("service.name=checkout")).toBeTruthy();
    expect(screen.getByText(/emit it to localhost:4318/i)).toBeTruthy();
  });

  it("shows a distinct parse-error card", () => {
    const panel = makePanel({
      matched: false,
      metrics: [],
      query: { parseError: "no data('<metric>') call found in program_text" },
    });
    render(<DashboardPanel panel={panel} />);

    expect(screen.getByText(/Couldn't parse SignalFlow/i)).toBeTruthy();
    expect(screen.getByText(/no data/i)).toBeTruthy();
  });

  it("passes markdown through for a text panel", () => {
    const panel = makePanel({
      chartType: "text",
      text: "## Runbook notes",
      query: undefined,
      metrics: [],
      matched: false,
    });
    render(<DashboardPanel panel={panel} />);

    expect(screen.getByText("## Runbook notes")).toBeTruthy();
  });

  it("renders the latest value for a single_value panel", () => {
    const panel = makePanel({ chartType: "single_value" });
    const { container } = render(<DashboardPanel panel={panel} />);

    const number = container.querySelector(".dashboard-panel__single-value-number");
    expect(number).toBeTruthy();
    // Latest of the two seeded points (10, 20) is 20.
    expect(number?.textContent).toBe("20");
  });

  it("F12: a monotonic-counter single_value panel with one data point shows the raw latest value (not 0)", () => {
    // One cumulative counter point cannot form a rate (the rate loop starts at
    // i=1 → zero points → the group would be dropped and the panel rendered 0).
    // Latest-value renderings must fall back to the raw latest value instead.
    const onePoint: MetricGroup = {
      name: "messages.processed",
      description: "messages processed",
      unit: "1",
      type: "sum",
      serviceName: "checkout",
      scopeName: "otel.app",
      dataPointCount: 1,
      dataPoints: [
        {
          name: "messages.processed",
          type: "sum",
          unit: "1",
          timeUnixNano: "2026-01-01T00:00:00Z",
          attributes: {},
          resource: { serviceName: "checkout", attributes: {} },
          scope: { name: "otel.app" },
          value: 42,
          isMonotonic: true,
        },
      ],
    };
    const panel = makePanel({
      chartType: "single_value",
      query: { metricName: "messages.processed" },
      metrics: [onePoint],
    });
    const { container } = render(<DashboardPanel panel={panel} />);

    const number = container.querySelector(".dashboard-panel__single-value-number");
    expect(number).toBeTruthy();
    expect(number?.textContent).toBe("42");
  });

  it("R2: a multi-series monotonic counter in one group computes rate per-series (no cross-series interleaving)", () => {
    // The backend groups only by (name, service, scope), so a counter with an
    // `endpoint` dimension lands TWO series in one MetricGroup.dataPoints. The
    // rate math must diff consecutive points of the SAME series, never across
    // the two cumulative counters.
    const cp = (value: number, endpoint: string, ts: string): MetricDataPoint => ({
      name: "messages.processed",
      type: "sum",
      unit: "1",
      timeUnixNano: ts,
      attributes: { endpoint },
      resource: { serviceName: "checkout", attributes: {} },
      scope: { name: "otel.app" },
      value,
      isMonotonic: true,
    });
    // Series A (/a): 100 @ t0 → 110 @ t2s ⇒ 10 / 2s = 5/s
    // Series B (/b): 5000 @ t1 → 5060 @ t3s ⇒ 60 / 2s = 30/s
    // Points are interleaved by timestamp as the backend / sort delivers them.
    const group: MetricGroup = {
      name: "messages.processed",
      description: "messages processed",
      unit: "1",
      type: "sum",
      serviceName: "checkout",
      scopeName: "otel.app",
      dataPointCount: 4,
      dataPoints: [
        cp(100, "/a", "2026-01-01T00:00:00Z"),
        cp(5000, "/b", "2026-01-01T00:00:01Z"),
        cp(110, "/a", "2026-01-01T00:00:02Z"),
        cp(5060, "/b", "2026-01-01T00:00:03Z"),
      ],
    };
    const panel = makePanel({
      chartType: "list",
      query: { metricName: "messages.processed" },
      metrics: [group],
    });
    const { container } = render(<DashboardPanel panel={panel} />);

    const values = Array.from(container.querySelectorAll(".dashboard-panel__list-value")).map((el) => el.textContent);
    // Per-series rates: A=5/s, B=30/s. If interleaved, A would show a huge
    // (5000-100)/1 spike clamped/garbage and B a wrong value.
    expect(values).toContain("5");
    expect(values).toContain("30");
    // Two series, two rows — no bogus extra values.
    expect(values).toHaveLength(2);
  });

  it("R2: a multi-series histogram in one group computes percentile deltas per-series", () => {
    // Two histogram series (endpoint=/a,/b) in one group. Bucket deltas must be
    // taken within each series; crossing them yields negative garbage bucket
    // counts and a wrong percentile.
    const hp = (
      endpoint: string,
      ts: string,
      count: number,
      sum: number,
      bucketCounts: number[],
    ): MetricDataPoint => ({
      name: "http.server.duration",
      type: "histogram",
      unit: "ms",
      timeUnixNano: ts,
      attributes: { endpoint },
      resource: { serviceName: "checkout", attributes: {} },
      scope: { name: "otel.http" },
      count,
      sum,
      bucketCounts,
      explicitBounds: [10, 20],
    });
    // Series A: delta all in bucket [10,20] ⇒ P99 interpolates to 20.
    // Series B: delta all in bucket [0,10] ⇒ P99 interpolates to 10.
    const group: MetricGroup = {
      name: "http.server.duration",
      description: "server duration",
      unit: "ms",
      type: "histogram",
      serviceName: "checkout",
      scopeName: "otel.http",
      dataPointCount: 4,
      dataPoints: [
        hp("/a", "2026-01-01T00:00:00Z", 0, 0, [0, 0, 0]),
        hp("/b", "2026-01-01T00:00:01Z", 0, 0, [0, 0, 0]),
        hp("/a", "2026-01-01T00:00:02Z", 10, 150, [0, 10, 0]),
        hp("/b", "2026-01-01T00:00:03Z", 10, 50, [10, 0, 0]),
      ],
    };
    const panel = makePanel({
      chartType: "list",
      query: { metricName: "http.server.duration", aggregation: "percentile", percentile: 99 },
      metrics: [group],
    });
    const { container } = render(<DashboardPanel panel={panel} />);

    const values = Array.from(container.querySelectorAll(".dashboard-panel__list-value")).map((el) => el.textContent);
    expect(values).toHaveLength(2);
    // A's P99 lands in bucket [10,20] → 19.9; B's in [0,10] → 9.9. Interleaving
    // the two series would yield negative bucket deltas and garbage percentiles.
    expect(values).toContain("19.90");
    expect(values).toContain("9.90");
    for (const v of values) {
      expect(Number(v)).toBeGreaterThanOrEqual(0);
    }
  });

  it("R3: a single-bucket histogram (empty explicitBounds) with percentile agg falls back to the mean (no NaN)", () => {
    // A valid OTLP explicit-bucket histogram can carry a single (-Inf,+Inf)
    // bucket: bucketCounts:[n], explicitBounds:[]. The empty [] is truthy, so
    // the percentile branch used to run interpolatePercentile with bounds=[],
    // where the +Inf bucket bound computed bounds[-1]*2 = NaN and the panel
    // rendered the literal text "NaN". It must fall back to the mean instead.
    const hp = (ts: string, count: number, sum: number, bucketCounts: number[]): MetricDataPoint => ({
      name: "http.server.duration",
      type: "histogram",
      unit: "ms",
      timeUnixNano: ts,
      attributes: {},
      resource: { serviceName: "checkout", attributes: {} },
      scope: { name: "otel.http" },
      count,
      sum,
      bucketCounts,
      explicitBounds: [],
    });
    const group: MetricGroup = {
      name: "http.server.duration",
      description: "server duration",
      unit: "ms",
      type: "histogram",
      serviceName: "checkout",
      scopeName: "otel.http",
      dataPointCount: 2,
      dataPoints: [
        hp("2026-01-01T00:00:00Z", 0, 0, [0]),
        // Δcount=10, Δsum=150 ⇒ mean fallback = 150/10 = 15.
        hp("2026-01-01T00:00:01Z", 10, 150, [10]),
      ],
    };
    const panel = makePanel({
      chartType: "single_value",
      query: { metricName: "http.server.duration", aggregation: "percentile", percentile: 99 },
      metrics: [group],
    });
    const { container } = render(<DashboardPanel panel={panel} />);

    const number = container.querySelector(".dashboard-panel__single-value-number");
    expect(number).toBeTruthy();
    expect(number?.textContent).not.toBe("NaN");
    expect(number?.textContent).toBe("15");
  });

  it("renders the chart type chip in the panel head", () => {
    const { container } = render(<DashboardPanel panel={makePanel()} />);
    expect(container.querySelector(".dashboard-panel__type")?.textContent).toBe("Time series");
  });

  it("F8: renders a table for chartType:table (not the SVG line chart) with a friendly type badge", () => {
    const panel = makePanel({ chartType: "table" });
    const { container } = render(<DashboardPanel panel={panel} />);

    // A real <table> body row with the latest value, not the time_series SVG.
    expect(container.querySelector(".dashboard-panel__table")).toBeTruthy();
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("20")).toBeTruthy();

    // The type badge shows the friendly label, not the raw "table" string.
    expect(container.querySelector(".dashboard-panel__type")?.textContent).toBe("Table");
  });
});
