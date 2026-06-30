import React from "react";
import { DashboardPanel } from "./DashboardPanel";
import type { PreviewPanel } from "./types";

interface DashboardGridProps {
  panels: PreviewPanel[];
  windowMs: number;
  onExpand: (panel: PreviewPanel) => void;
}

export function DashboardGrid({ panels, windowMs, onExpand }: DashboardGridProps): React.ReactElement {
  return (
    <div className="dashboard-grid" role="list">
      {panels.map((panel, i) => {
        const { column, row, width, height } = clampLayout(panel.layout);
        return (
          <div
            key={`${panel.label}-${i}`}
            role="listitem"
            className="dashboard-grid__cell"
            style={{
              gridColumn: `${column + 1} / span ${width}`,
              gridRow: `${row + 1} / span ${height}`,
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
