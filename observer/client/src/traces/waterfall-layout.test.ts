import { describe, it, expect } from "vitest";
import { buildWaterfallTree, flattenTree } from "./waterfall-layout";
import type { Span } from "../api/types";

function makeSpan(overrides: Partial<Span> & { spanId: string }): Span {
  return {
    traceId: "abc123",
    spanId: overrides.spanId,
    parentSpanId: overrides.parentSpanId ?? "",
    name: overrides.name ?? `span-${overrides.spanId}`,
    kind: "INTERNAL",
    startTimeUnixNano: "1000000000",
    endTimeUnixNano: "2000000000",
    durationMs: 1,
    status: { code: "UNSET" },
    attributes: {},
    events: [],
    links: [],
    resource: { attributes: {} },
    scope: { name: "test" },
    ...overrides,
  };
}

describe("buildWaterfallTree", () => {
  it("groups children under their parent", () => {
    const spans: Span[] = [
      makeSpan({ spanId: "root" }),
      makeSpan({ spanId: "child1", parentSpanId: "root" }),
      makeSpan({ spanId: "child2", parentSpanId: "root" }),
    ];

    const roots = buildWaterfallTree(spans);
    expect(roots).toHaveLength(1);
    expect(roots[0].spanId).toBe("root");
    expect(roots[0].children).toHaveLength(2);
    expect(roots[0].children.map((c) => c.spanId).sort()).toEqual(["child1", "child2"]);
  });

  it("computes depth correctly", () => {
    const spans: Span[] = [
      makeSpan({ spanId: "root" }),
      makeSpan({ spanId: "child", parentSpanId: "root" }),
      makeSpan({ spanId: "grandchild", parentSpanId: "child" }),
    ];

    const roots = buildWaterfallTree(spans);
    expect(roots[0].depth).toBe(0);
    expect(roots[0].children[0].depth).toBe(1);
    expect(roots[0].children[0].children[0].depth).toBe(2);
  });

  it("treats spans with missing parents as roots", () => {
    const spans: Span[] = [
      makeSpan({ spanId: "root" }),
      makeSpan({ spanId: "orphan", parentSpanId: "nonexistent" }),
    ];

    const roots = buildWaterfallTree(spans);
    expect(roots).toHaveLength(2);
    expect(roots.map((r) => r.spanId).sort()).toEqual(["orphan", "root"]);
  });

  it("handles multiple root spans", () => {
    const spans: Span[] = [
      makeSpan({ spanId: "root1" }),
      makeSpan({ spanId: "root2" }),
      makeSpan({ spanId: "child-of-1", parentSpanId: "root1" }),
    ];

    const roots = buildWaterfallTree(spans);
    expect(roots).toHaveLength(2);
  });

  it("returns empty array for empty input", () => {
    const roots = buildWaterfallTree([]);
    expect(roots).toEqual([]);
  });
});

describe("flattenTree", () => {
  it("returns depth-first order", () => {
    const spans: Span[] = [
      makeSpan({ spanId: "root" }),
      makeSpan({ spanId: "child1", parentSpanId: "root" }),
      makeSpan({ spanId: "grandchild", parentSpanId: "child1" }),
      makeSpan({ spanId: "child2", parentSpanId: "root" }),
    ];

    const roots = buildWaterfallTree(spans);
    const flat = flattenTree(roots);

    expect(flat.map((s) => s.spanId)).toEqual(["root", "child1", "grandchild", "child2"]);
  });

  it("returns empty array for empty roots", () => {
    expect(flattenTree([])).toEqual([]);
  });

  it("preserves depth values through flattening", () => {
    const spans: Span[] = [
      makeSpan({ spanId: "root" }),
      makeSpan({ spanId: "child", parentSpanId: "root" }),
      makeSpan({ spanId: "grandchild", parentSpanId: "child" }),
    ];

    const roots = buildWaterfallTree(spans);
    const flat = flattenTree(roots);

    expect(flat.map((s) => s.depth)).toEqual([0, 1, 2]);
  });
});
