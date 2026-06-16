// @vitest-environment happy-dom

import React from "react";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DetailPanel, ResizablePanel } from "./DetailPanel";

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

describe("ResizablePanel", () => {
  it("preserves user width when the default width prop changes after a resize", () => {
    const view = render(
      <ResizablePanel defaultWidth={500} minWidth={300} maxWidth={900}>
        <div>panel body</div>
      </ResizablePanel>,
    );
    const panel = view.container.querySelector<HTMLElement>(".resizable-panel");
    const handle = view.container.querySelector<HTMLElement>(".resizable-panel__handle");
    expect(panel?.style.getPropertyValue("--panel-width")).toBe("500px");

    view.rerender(
      <ResizablePanel defaultWidth={600} minWidth={300} maxWidth={900}>
        <div>panel body</div>
      </ResizablePanel>,
    );
    expect(panel?.style.getPropertyValue("--panel-width")).toBe("600px");

    fireEvent.mouseDown(handle as HTMLElement, { clientX: 0 });
    fireEvent.mouseMove(window, { clientX: -120 });
    fireEvent.mouseUp(window);
    expect(panel?.style.getPropertyValue("--panel-width")).toBe("720px");

    view.rerender(
      <ResizablePanel defaultWidth={650} minWidth={300} maxWidth={900}>
        <div>panel body</div>
      </ResizablePanel>,
    );
    expect(panel?.style.getPropertyValue("--panel-width")).toBe("720px");
  });
});
