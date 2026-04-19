// @vitest-environment happy-dom

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MetricsTab } from "./MetricsTab";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("MetricsTab", () => {
  it("filters metrics from the compact explorer toolbar via the REST query endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
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
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

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
    expect(screen.getByLabelText("Filter field")).toBeTruthy();
    expect(screen.queryByText("Type")).toBeNull();
    expect(screen.queryByText("Unit")).toBeNull();

    const fieldInput = screen.getByLabelText("Filter field");
    expect(fieldInput.getAttribute("placeholder")).toBe("Add filter");
    fireEvent.change(fieldInput, { target: { value: "metricName" } });
    expect((screen.getByRole("button", { name: "=" }) as HTMLButtonElement).classList.contains("filter-builder__operator--active")).toBe(true);
    fireEvent.change(screen.getByLabelText("metricName value"), {
      target: { value: "http.server.duration" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/query/metrics?filter%5BmetricName%5D%5Beq%5D=http.server.duration", expect.any(Object));
    expect(screen.queryByText("http.server.request.count")).toBeNull();
    expect(screen.getByText("http.server.duration")).toBeTruthy();
    expect(screen.queryByText("db.client.connections.usage")).toBeNull();
  });

  it("shows server-backed value suggestions for low-cardinality fields", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.startsWith("/api/query/metrics/filter-values")) {
        return {
          ok: true,
          json: async () => ["checkout"],
        };
      }
      return {
        ok: true,
        json: async () => [],
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MetricsTab
        metrics={[
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
        ]}
        telemetryError={null}
      />,
    );

    fireEvent.change(screen.getByLabelText("Filter field"), { target: { value: "serviceName" } });
    fireEvent.focus(screen.getByLabelText("serviceName value"));
    fireEvent.change(screen.getByLabelText("serviceName value"), { target: { value: "che" } });

    await act(async () => {});

    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/query/metrics/filter-values?field=serviceName"))).toBe(true);
    expect(screen.getByText("checkout")).toBeTruthy();
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

  it("renders selected metric details in the side panel", () => {
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

    expect(container.querySelector(".signal-view__panel")).toBeTruthy();
    expect(container.querySelector(".metrics-explorer__series-service")?.textContent).toBe("api-gateway");
    expect(container.querySelector(".metrics-explorer__series-attr")?.textContent).toBe("http.route=/api/orders/{id}");
    expect(container.querySelector(".metrics-explorer__series-value")?.textContent).toBe("8.18");
    expect(container.querySelector(".metrics-explorer__series-points")?.textContent).toBe("1 pts");
    expect(container.querySelector(".metric-card__description")?.classList.contains("explorer-row__secondary")).toBe(true);
    expect(container.querySelector(".metric-card__body")).toBeNull();
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
