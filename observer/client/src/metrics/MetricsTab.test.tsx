// @vitest-environment happy-dom

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MetricsTab } from "./MetricsTab";

afterEach(() => cleanup());

describe("MetricsTab", () => {
  it("filters metrics from the compact explorer toolbar using the visible columns", () => {
    render(
      <MetricsTab
        metrics={[
          {
            name: "http.server.request.count",
            description: "Request count",
            unit: "requests",
            type: "sum",
            serviceName: "checkout",
            scopeName: "otel",
            dataPointCount: 1,
            dataPoints: [],
          },
          {
            name: "http.server.duration",
            description: "Request duration",
            unit: "ms",
            type: "histogram",
            serviceName: "checkout",
            scopeName: "otel",
            dataPointCount: 1,
            dataPoints: [],
          },
          {
            name: "db.client.connections.usage",
            description: "Open connections",
            unit: "connections",
            type: "gauge",
            serviceName: "db",
            scopeName: "otel",
            dataPointCount: 1,
            dataPoints: [],
          },
        ]}
        telemetryError={null}
      />,
    );

    expect(screen.getByText("Type / Unit")).toBeTruthy();
    expect(screen.getByText("Description")).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByText("Type")).toBeNull();
    expect(screen.queryByText("Unit")).toBeNull();

    fireEvent.change(screen.getByPlaceholderText("Search metric, description, type, unit, or service"), {
      target: { value: "duration" },
    });

    expect(screen.queryByText("http.server.request.count")).toBeNull();
    expect(screen.getByText("http.server.duration")).toBeTruthy();
    expect(screen.queryByText("db.client.connections.usage")).toBeNull();
  });

  it("renders metrics in alphabetical order", () => {
    const { container } = render(
      <MetricsTab
        metrics={[
          {
            name: "zeta.metric",
            description: "Zeta metric",
            unit: "ms",
            type: "gauge",
            serviceName: "checkout",
            scopeName: "otel",
            dataPointCount: 1,
            dataPoints: [],
          },
          {
            name: "alpha.metric",
            description: "Alpha metric",
            unit: "ms",
            type: "gauge",
            serviceName: "checkout",
            scopeName: "otel",
            dataPointCount: 1,
            dataPoints: [],
          },
        ]}
        telemetryError={null}
      />,
    );

    const names = Array.from(container.querySelectorAll(".metric-card__name")).map((node) => node.textContent);
    expect(names).toEqual(["alpha.metric", "zeta.metric"]);
    expect(container.querySelector(".metric-card__header")?.classList.contains("data-table__row--metrics")).toBe(true);
    expect(container.querySelector(".metric-card__name")?.classList.contains("explorer-row__primary")).toBe(true);
    expect(container.querySelector(".metric-card__description")?.textContent).toBe("Alpha metric");
    expect(container.querySelector(".metric-card__glyph")).toBeNull();
    expect(container.querySelector(".metric-card__meta")).toBeTruthy();
    expect(container.querySelector(".metric-card__meta")?.classList.contains("data-table__cell-content")).toBe(true);
    expect(container.querySelector(".data-table__td--metric-description")).toBeTruthy();
    expect(container.querySelector(".data-table__td--metric-meta")).toBeTruthy();
    expect(container.querySelector(".metric-card__meta-separator")?.textContent).toBe("/");
    expect(container.querySelector(".validation-badge")).toBeNull();
    expect(container.querySelector(".metric-card__disclosure")).toBeNull();
    expect(container.textContent).toContain("gauge/ms");
    expect(container.textContent).not.toContain("svc");
  });

  it("opens the full metric view in a side panel with series rows", () => {
    const { container } = render(
      <MetricsTab
        metrics={[
          {
            name: "http.server.duration",
            description: "Request duration",
            unit: "ms",
            type: "histogram",
            serviceName: "api-gateway",
            scopeName: "otel",
            dataPointCount: 1,
            dataPoints: [
              {
                name: "http.server.duration",
                type: "histogram",
                unit: "ms",
                timeUnixNano: "1",
                attributes: { "http.route": "/api/orders/{id}" },
                resource: { serviceName: "api-gateway", attributes: {} },
                scope: { name: "otel" },
                value: 8.18,
              },
            ],
          },
        ]}
        telemetryError={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /http\.server\.duration/i }));

    expect(screen.getByRole("heading", { name: "http.server.duration" })).toBeTruthy();
    expect(screen.getByText("Series (1)")).toBeTruthy();
    expect(container.querySelector(".ts-chart")).toBeTruthy();
    expect(container.querySelector(".metrics-explorer__series-service")?.textContent).toBe("api-gateway");
    expect(container.querySelector(".metrics-explorer__series-attr")?.textContent).toBe("http.route=/api/orders/{id}");
    expect(container.querySelector(".metrics-explorer__series-value")?.textContent).toBe("8.18");
    expect(container.querySelector(".metrics-explorer__series-points")?.textContent).toBe("1 pts");
    expect(container.querySelector(".metric-card__description")?.classList.contains("explorer-row__secondary")).toBe(true);
  });

  it("shows selected series detail inside the metric side panel", () => {
    render(
      <MetricsTab
        metrics={[
          {
            name: "http.server.duration",
            description: "Request duration",
            unit: "ms",
            type: "histogram",
            serviceName: "api-gateway",
            scopeName: "otel",
            dataPointCount: 2,
            dataPoints: [
              {
                name: "http.server.duration",
                type: "histogram",
                unit: "ms",
                timeUnixNano: "1",
                attributes: { "http.route": "/api/orders/{id}" },
                resource: { serviceName: "api-gateway", attributes: { "service.instance.id": "instance-1" } },
                scope: { name: "otel", version: "1.0.0" },
                value: 8.18,
              },
              {
                name: "http.server.duration",
                type: "histogram",
                unit: "ms",
                timeUnixNano: "2",
                attributes: { "http.route": "/api/orders/{id}" },
                resource: { serviceName: "api-gateway", attributes: { "service.instance.id": "instance-1" } },
                scope: { name: "otel", version: "1.0.0" },
                value: 10.25,
              },
            ],
          },
        ]}
        telemetryError={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /http\.server\.duration/i }));
    fireEvent.click(screen.getAllByRole("button", { name: /api-gateway/i })[0] as HTMLElement);

    expect(screen.getByRole("heading", { name: "http.server.duration" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Close panel" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Clear series selection" })).toBeTruthy();
    expect(screen.getByText("Scope")).toBeTruthy();
    expect(screen.getByText("Resource")).toBeTruthy();
    expect(screen.getByText("service.instance.id:")).toBeTruthy();
  });

  it("keeps metric series order stable across live value updates and appends new series at the end", () => {
    const initialMetrics = [
      {
        name: "http.server.duration",
        description: "Request duration",
        unit: "ms",
        type: "histogram",
        serviceName: "api-gateway",
        scopeName: "otel",
        dataPointCount: 2,
        dataPoints: [
          {
            name: "http.server.duration",
            type: "histogram",
            unit: "ms",
            timeUnixNano: "1",
            attributes: { "http.route": "/api/orders" },
            resource: { serviceName: "checkout", attributes: {} },
            scope: { name: "otel" },
            value: 8.18,
          },
          {
            name: "http.server.duration",
            type: "histogram",
            unit: "ms",
            timeUnixNano: "2",
            attributes: { "http.route": "/api/orders/{id}" },
            resource: { serviceName: "payments", attributes: {} },
            scope: { name: "otel" },
            value: 10.25,
          },
        ],
      },
    ];
    const { container, rerender } = render(<MetricsTab metrics={initialMetrics} telemetryError={null} />);

    fireEvent.click(screen.getByRole("button", { name: /http\.server\.duration/i }));

    const initialRows = Array.from(container.querySelectorAll(".metrics-explorer__series-row"))
      .map((node) => ({
        service: node.querySelector(".metrics-explorer__series-service")?.textContent,
        dimension: node.querySelector(".metrics-explorer__series-attr")?.textContent,
        value: node.querySelector(".metrics-explorer__series-value")?.textContent,
      }));
    expect(initialRows).toEqual([
      { service: "checkout", dimension: "http.route=/api/orders", value: "8.18" },
      { service: "payments", dimension: "http.route=/api/orders/{id}", value: "10.25" },
    ]);

    rerender(
      <MetricsTab
        metrics={[
          {
            name: "http.server.duration",
            description: "Request duration",
            unit: "ms",
            type: "histogram",
            serviceName: "api-gateway",
            scopeName: "otel",
            dataPointCount: 3,
            dataPoints: [
              {
                name: "http.server.duration",
                type: "histogram",
                unit: "ms",
                timeUnixNano: "3",
                attributes: { "http.route": "/api/orders/{id}" },
                resource: { serviceName: "payments", attributes: {} },
                scope: { name: "otel" },
                value: 100.25,
              },
              {
                name: "http.server.duration",
                type: "histogram",
                unit: "ms",
                timeUnixNano: "4",
                attributes: { "http.route": "/api/orders" },
                resource: { serviceName: "checkout", attributes: {} },
                scope: { name: "otel" },
                value: 18.18,
              },
              {
                name: "http.server.duration",
                type: "histogram",
                unit: "ms",
                timeUnixNano: "5",
                attributes: { "http.route": "/api/inventory" },
                resource: { serviceName: "inventory", attributes: {} },
                scope: { name: "otel" },
                value: 3.5,
              },
            ],
          },
        ]}
        telemetryError={null}
      />,
    );

    const updatedRows = Array.from(container.querySelectorAll(".metrics-explorer__series-row"))
      .map((node) => ({
        service: node.querySelector(".metrics-explorer__series-service")?.textContent,
        dimension: node.querySelector(".metrics-explorer__series-attr")?.textContent,
        value: node.querySelector(".metrics-explorer__series-value")?.textContent,
      }));
    expect(updatedRows).toEqual([
      { service: "checkout", dimension: "http.route=/api/orders", value: "18.18" },
      { service: "payments", dimension: "http.route=/api/orders/{id}", value: "100.25" },
      { service: "inventory", dimension: "http.route=/api/inventory", value: "3.50" },
    ]);
  });

  it("keeps the shared row separator on metric rows", async () => {
    const css = await readFile(resolve(process.cwd(), "src/styles.css"), "utf8");
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    const { container } = render(
      <MetricsTab
        metrics={[
          {
            name: "http.server.request.count",
            description: "Request count",
            unit: "requests",
            type: "sum",
            serviceName: "checkout",
            scopeName: "otel",
            dataPointCount: 1,
            dataPoints: [],
          },
        ]}
        telemetryError={null}
      />,
    );

    const row = container.querySelector(".metric-card__header");
    expect(row).toBeTruthy();

    const rowStyles = window.getComputedStyle(row as Element);
    expect(rowStyles.borderBottomStyle).toBe("solid");
    expect(rowStyles.borderBottomWidth).not.toBe("0px");

    style.remove();
  });
});
