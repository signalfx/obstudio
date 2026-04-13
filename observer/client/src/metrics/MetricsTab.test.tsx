// @vitest-environment happy-dom

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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
        onInteract={vi.fn()}
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

  it("renders metrics in alphabetical order and pauses live updates on interaction", () => {
    const onInteract = vi.fn();
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
        onInteract={onInteract}
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

    fireEvent.pointerDown(screen.getByRole("button", { name: /alpha\.metric/i }));
    expect(onInteract).toHaveBeenCalled();
  });

  it("renders expanded series rows with separate service and dimension text", () => {
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
        onInteract={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /http\.server\.duration/i }));

    expect(container.querySelector(".metrics-explorer__series-service")?.textContent).toBe("api-gateway");
    expect(container.querySelector(".metrics-explorer__series-attr")?.textContent).toBe("http.route=/api/orders/{id}");
    expect(container.querySelector(".metrics-explorer__series-value")?.textContent).toBe("8.18");
    expect(container.querySelector(".metrics-explorer__series-points")?.textContent).toBe("1 pts");
    expect(container.querySelector(".metric-card__description")?.classList.contains("explorer-row__secondary")).toBe(true);
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
        onInteract={vi.fn()}
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
