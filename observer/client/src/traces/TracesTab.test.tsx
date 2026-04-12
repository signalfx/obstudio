// @vitest-environment happy-dom

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TracesTab } from "./TracesTab";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 36,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: index,
        start: index * 36,
        end: (index + 1) * 36,
        size: 36,
      })),
    measureElement: () => undefined,
  }),
}));

describe("TracesTab", () => {
  it("filters traces from the compact explorer toolbar", () => {
    render(
      <TracesTab
        traces={[
          { traceId: "trace-1", rootSpanName: "GET /orders", serviceName: "checkout", spanCount: 3, durationMs: 42, status: "ok" },
          { traceId: "trace-2", rootSpanName: "POST /charge", serviceName: "payments", spanCount: 5, durationMs: 88, status: "error" },
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
      />,
    );

    expect(screen.getByText("2 traces")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("Search operation, trace ID, service, or status"), {
      target: { value: "missing-service" },
    });

    expect(screen.getByText("No traces match the current search.")).toBeTruthy();
  });

  it("renders zero-duration traces as 0.0ms instead of dashes", () => {
    render(
      <TracesTab
        traces={[
          { traceId: "trace-0", rootSpanName: "GET /health", serviceName: "api", spanCount: 1, durationMs: 0, status: "ok" },
          { traceId: "trace-missing", rootSpanName: "GET /ready", serviceName: "api", spanCount: 1, status: "ok" } as any,
        ]}
        telemetryError={null}
        onInteract={vi.fn()}
      />,
    );

    expect(screen.getAllByText("0.0ms")).toHaveLength(2);
    expect(screen.queryByText("--")).toBeNull();
  });

  it("stacks the detail panel below the list on narrow widths", async () => {
    const [{ Window }, { readFile }, { resolve }] = await Promise.all([
      import("happy-dom"),
      import("node:fs/promises"),
      import("node:path"),
    ]);
    const css = await readFile(resolve(process.cwd(), "src/styles.css"), "utf8");
    const window = new Window({ width: 800, height: 700, url: "http://localhost" });
    const style = window.document.createElement("style");
    style.textContent = css;
    window.document.head.appendChild(style);
    window.document.body.innerHTML =
      "<div class=\"signal-view signal-view--with-panel\"><div class=\"signal-view__content\"></div><div class=\"signal-view__panel\"></div></div>";

    const layout = window.document.querySelector(".signal-view");
    const panel = window.document.querySelector(".signal-view__panel");
    const content = window.document.querySelector(".signal-view__content");
    expect(layout).toBeTruthy();
    expect(panel).toBeTruthy();
    expect(content).toBeTruthy();
    if (!layout || !panel || !content) {
      throw new Error("expected responsive layout shell");
    }

    const layoutStyles = window.getComputedStyle(layout);
    const panelStyles = window.getComputedStyle(panel);
    const contentStyles = window.getComputedStyle(content);

    expect(layoutStyles.flexDirection).toBe("column");
    expect(panelStyles.position).toBe("static");
    expect(panelStyles.borderTopWidth).toBe("1px");
    expect(panelStyles.borderTopStyle).toBe("solid");
    expect(panelStyles.borderLeftWidth).toBe("0px");
    expect(contentStyles.minHeight).toBe("0");
  });
});
