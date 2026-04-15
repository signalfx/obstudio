// @vitest-environment happy-dom

import React from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DetailPanel } from "./DetailPanel";

afterEach(() => cleanup());

describe("DetailPanel", () => {
  it("does not reset scroll when only the panel body rerenders", () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });

    const view = render(
      <DetailPanel title="Metric" subtitle="checkout" onClose={() => undefined}>
        <div>first</div>
      </DetailPanel>,
    );

    expect(scrollTo).toHaveBeenCalledTimes(1);

    view.rerender(
      <DetailPanel title="Metric" subtitle="checkout" onClose={() => undefined}>
        <div>second</div>
      </DetailPanel>,
    );

    expect(scrollTo).toHaveBeenCalledTimes(1);
  });

  it("resets scroll when the panel target changes", () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });

    const view = render(
      <DetailPanel title="Metric A" subtitle="checkout" onClose={() => undefined}>
        <div>first</div>
      </DetailPanel>,
    );

    expect(scrollTo).toHaveBeenCalledTimes(1);

    view.rerender(
      <DetailPanel title="Metric B" subtitle="checkout" onClose={() => undefined}>
        <div>second</div>
      </DetailPanel>,
    );

    expect(scrollTo).toHaveBeenCalledTimes(2);
  });
});
