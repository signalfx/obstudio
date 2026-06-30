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
  const rowMap = buildRowMap(clamped.map((c) => c.layout));
  return (
    <div className="dashboard-grid" role="list">
      {clamped.map(({ panel, layout }, i) => {
        const packedRow = rowMap.get(layout.row) ?? layout.row;
        return (
          <div
            key={`${panel.label}-${i}`}
            role="listitem"
            className="dashboard-grid__cell"
            style={{
              gridColumn: `${layout.column + 1} / span ${layout.width}`,
              gridRow: `${packedRow + 1} / span ${layout.height}`,
            }}
          >
            <DashboardPanel panel={panel} windowMs={windowMs} onExpand={onExpand} />
          </div>
        );
      })}
    </div>
  );
}

/**
 * Build a mapping from original row index → packed row index. Splunk packs
 * rows so the first used row maps to 0; each distinct original row maps to the
 * next consecutive packed row. Non-contiguous rows (e.g. rows 0, 5, 10) are
 * remapped to 0, 1, 2 so no blank vertical space appears in the local preview.
 */
function buildRowMap(layouts: Array<{ row: number }>): Map<number, number> {
  const distinctRows = [...new Set(layouts.map((l) => l.row))].sort((a, b) => a - b);
  const map = new Map<number, number>();
  distinctRows.forEach((orig, packed) => map.set(orig, packed));
  return map;
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
