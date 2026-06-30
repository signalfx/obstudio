import type { MetricGroup, MetricDataPoint } from "../api/types";
import type { PreviewPanel, PreviewResponse } from "./types";

/** A metric data point with two values so the SVG chart draws a real path. */
export function makeDataPoint(value: number, attributes: Record<string, unknown> = {}): MetricDataPoint {
  return {
    name: "http.server.request.duration",
    type: "gauge",
    unit: "ms",
    timeUnixNano: "2026-01-01T00:00:00Z",
    attributes,
    resource: { serviceName: "checkout", attributes: {} },
    scope: { name: "otel.http" },
    value,
  };
}

export function makeMetricGroup(name = "http.server.request.duration"): MetricGroup {
  return {
    name,
    description: `${name} description`,
    unit: "ms",
    type: "gauge",
    serviceName: "checkout",
    scopeName: "otel.http",
    dataPointCount: 2,
    dataPoints: [makeDataPoint(10), makeDataPoint(20)],
  };
}

export function makePanel(overrides: Partial<PreviewPanel> = {}): PreviewPanel {
  return {
    label: "p99_latency",
    title: "P99 Latency",
    chartType: "time_series",
    layout: { column: 0, row: 0, width: 6, height: 3 },
    matched: true,
    query: { metricName: "http.server.request.duration", filters: { "service.name": "checkout" }, aggregation: "percentile", percentile: 99 },
    metrics: [makeMetricGroup()],
    ...overrides,
  };
}

export function makePreviewResponse(overrides: Partial<PreviewResponse> = {}): PreviewResponse {
  return {
    available: true,
    approximate: true,
    source: "/repo/.observe/dashboards.preview.json",
    generatedAt: "2026-01-01T00:00:00Z",
    groups: [
      {
        name: "checkout",
        description: "checkout service",
        dashboards: [
          {
            name: "Checkout RED",
            description: "RED metrics",
            panels: [makePanel()],
          },
        ],
      },
    ],
    ...overrides,
  };
}
