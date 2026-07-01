// @vitest-environment happy-dom

import React from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DashboardGrid, clampLayout } from "./DashboardGrid";
import { makePanel } from "./testFixtures";

afterEach(cleanup);

describe("clampLayout", () => {
  it("keeps a valid layout unchanged", () => {
    expect(clampLayout({ column: 0, row: 0, width: 6, height: 3 })).toEqual({ column: 0, row: 0, width: 6, height: 3 });
  });

  it("clamps width so column + width never exceeds 12", () => {
    // column 8 + width 20 would overflow → width clamps to 4 (12 - 8).
    expect(clampLayout({ column: 8, row: 0, width: 20, height: 1 })).toEqual({ column: 8, row: 0, width: 4, height: 1 });
  });

  it("clamps column into 0-11", () => {
    expect(clampLayout({ column: 99, row: 0, width: 4, height: 1 }).column).toBe(11);
    expect(clampLayout({ column: -5, row: 0, width: 4, height: 1 }).column).toBe(0);
  });

  it("floors row at 0 and height at 1", () => {
    const out = clampLayout({ column: 0, row: -3, width: 4, height: 0 });
    expect(out.row).toBe(0);
    expect(out.height).toBe(1);
  });

  it("falls back to safe minimums for NaN", () => {
    const out = clampLayout({ column: NaN, row: NaN, width: NaN, height: NaN });
    expect(out.column).toBe(0);
    expect(out.row).toBe(0);
    expect(out.width).toBe(1);
    expect(out.height).toBe(1);
  });
});

const noExpand = () => undefined;

describe("DashboardGrid", () => {
  it("places each panel cell with the correct grid-column / grid-row", () => {
    const { container } = render(
      <DashboardGrid
        windowMs={0}
        onExpand={noExpand}
        panels={[
          makePanel({ label: "a", layout: { column: 0, row: 0, width: 6, height: 3 } }),
          makePanel({ label: "b", layout: { column: 6, row: 1, width: 6, height: 2 } }),
        ]}
      />,
    );

    const cells = container.querySelectorAll<HTMLElement>(".dashboard-grid__cell");
    expect(cells).toHaveLength(2);
    // CSS grid is 1-based; column 0 → line 1.
    expect(cells[0].style.gridColumn).toBe("1 / span 6");
    expect(cells[0].style.gridRow).toBe("1 / span 3");
    expect(cells[1].style.gridColumn).toBe("7 / span 6");
    expect(cells[1].style.gridRow).toBe("2 / span 2");
  });

  it("clamps an overflowing width down to fit the 12-column grid", () => {
    const { container } = render(
      <DashboardGrid windowMs={0} onExpand={noExpand} panels={[makePanel({ layout: { column: 0, row: 0, width: 20, height: 1 } })]} />,
    );
    const cell = container.querySelector<HTMLElement>(".dashboard-grid__cell");
    expect(cell?.style.gridColumn).toBe("1 / span 12");
  });

  it("F1: stacks two same-column panels height-aware without overlap (KPI above chart)", () => {
    // Canonical template: KPI at row=0 h=2 directly above a chart at row=2 h=3,
    // same column. The old ordinal packing collapsed rows 0 and 2 to start
    // lines 0 and 1, overlapping on grid line 2. The lower panel's start line
    // must be strictly past the upper panel's last occupied line.
    const { container } = render(
      <DashboardGrid
        windowMs={0}
        onExpand={noExpand}
        panels={[
          makePanel({ label: "kpi", chartType: "single_value", layout: { column: 0, row: 0, width: 6, height: 2 } }),
          makePanel({ label: "chart", layout: { column: 0, row: 2, width: 6, height: 3 } }),
        ]}
      />,
    );

    const cells = container.querySelectorAll<HTMLElement>(".dashboard-grid__cell");
    expect(cells).toHaveLength(2);

    // Parse "<start> / span <span>" for each panel.
    const parse = (gridRow: string) => {
      const [start, , , span] = gridRow.split(" ");
      return { start: Number(start), span: Number(span) };
    };
    const upper = parse(cells[0].style.gridRow);
    const lower = parse(cells[1].style.gridRow);

    // Upper KPI: start line 1, spans 2 → occupies grid lines [1, 3).
    expect(upper.start).toBe(1);
    expect(upper.span).toBe(2);

    // Lower chart's start line must be at or past the upper panel's last
    // occupied line (upper.start + upper.span), so the spans never overlap.
    expect(lower.start).toBeGreaterThanOrEqual(upper.start + upper.span);
  });

  it("exposes list semantics for assistive tech", () => {
    const { container } = render(<DashboardGrid windowMs={0} onExpand={noExpand} panels={[makePanel()]} />);
    expect(container.querySelector('[role="list"]')).toBeTruthy();
    expect(container.querySelector('[role="listitem"]')).toBeTruthy();
  });
});
