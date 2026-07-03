import React from "react";
import { DashboardPanel } from "./DashboardPanel";
import type { PreviewPanel } from "./types";

interface DashboardGridProps {
  panels: PreviewPanel[];
  windowMs: number;
  onExpand: (panel: PreviewPanel) => void;
}

export function DashboardGrid({ panels, windowMs, onExpand }: DashboardGridProps): React.ReactElement {
  const clamped = panels.map((p) => ({ panel: p, layout: clampLayout(p.layout) }));
  // Splunk `row` is an absolute y-coordinate, so pass it through unchanged as the
  // grid-row START line and let `height` drive the span. Combined with the
  // grid's `grid-auto-rows`, this keeps stacked panels (e.g. a KPI at row=0 h=2
  // ABOVE a chart at row=2 h=3 in the same column) from overlapping — the KPI
  // occupies lines 1-2 and the chart lines 3-5. Remapping distinct rows to
  // consecutive ordinals (the old behaviour) ignored height and made a height-2
  // panel above a row=2 panel collide on grid line 2.
  return (
    <div className="dashboard-grid" role="list">
      {clamped.map(({ panel, layout }, i) => {
        return (
          <div
            key={`${panel.label}-${i}`}
            role="listitem"
            className="dashboard-grid__cell"
            style={{
              gridColumn: `${layout.column + 1} / span ${layout.width}`,
              gridRow: `${layout.row + 1} / span ${layout.height}`,
            }}
          >
            <DashboardPanel panel={panel} windowMs={windowMs} onExpand={onExpand} />
          </div>
        );
      })}
    </div>
  );
}

/** Clamp a layout into the valid 12-column grid: column 0-11, width 1-12 without overflow, row ≥0, height ≥1. */
export function clampLayout(layout: PreviewPanel["layout"]): { column: number; row: number; width: number; height: number } {
  const column = clamp(layout?.column ?? 0, 0, 11);
  const row = atLeast(layout?.row ?? 0, 0);
  const rawWidth = layout?.width ?? 12;
  const width = clamp(rawWidth, 1, 12 - column);
  const height = atLeast(layout?.height ?? 1, 1);
  return { column, row, width, height };
}

function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(Math.max(value, min), max);
}

/** Like Math.max(value, min) but maps NaN to the minimum (Math.max(NaN, n) is NaN). */
function atLeast(value: number, min: number): number {
  if (Number.isNaN(value)) return min;
  return Math.max(value, min);
}
