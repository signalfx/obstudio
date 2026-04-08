import type { Span } from "../api/types";

/** A span enriched with tree depth and child references for waterfall rendering. */
export type WaterfallSpan = Span & {
  depth: number;
  children: WaterfallSpan[];
};

/** Build a parent-child tree from a flat list of spans. */
export function buildWaterfallTree(spans: Span[]): WaterfallSpan[] {
  const map = new Map<string, WaterfallSpan>();
  const roots: WaterfallSpan[] = [];

  for (const s of spans) {
    map.set(s.spanId, { ...s, depth: 0, children: [] });
  }

  for (const ws of map.values()) {
    if (ws.parentSpanId && map.has(ws.parentSpanId)) {
      const parent = map.get(ws.parentSpanId)!;
      ws.depth = parent.depth + 1;
      parent.children.push(ws);
    } else {
      roots.push(ws);
    }
  }

  // Recursively set depths.
  function setDepths(node: WaterfallSpan, depth: number): void {
    node.depth = depth;
    for (const c of node.children) setDepths(c, depth + 1);
  }
  for (const r of roots) setDepths(r, 0);

  return roots;
}

/** Flatten a waterfall tree into a depth-first ordered list. */
export function flattenTree(roots: WaterfallSpan[]): WaterfallSpan[] {
  const out: WaterfallSpan[] = [];
  function walk(node: WaterfallSpan): void {
    out.push(node);
    for (const c of node.children) walk(c);
  }
  for (const r of roots) walk(r);
  return out;
}
