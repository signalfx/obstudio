// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FilterDefinition } from "./FilterBar";
import { FilterBar } from "./FilterBar";

const DEFS: FilterDefinition[] = [
  { key: "serviceName", label: "Service", kind: "text", supportsNot: true },
  { key: "bodyContains", label: "Message", kind: "text" },
];

function setup(onSuggestValues?: FilterDefinition["key"] extends string ? (key: string, prefix: string, signal: AbortSignal) => Promise<string[]> : never) {
  const onChange = vi.fn();
  const { container } = render(
    <FilterBar
      definitions={DEFS}
      clauses={[]}
      onChange={onChange}
      onSuggestValues={onSuggestValues}
    />,
  );
  return { container, onChange };
}

describe("FilterBar field-picker menu", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); cleanup(); });

  it("opens on trigger click", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    expect(document.querySelector(".filter-builder__menu")).toBeTruthy();
  });

  it("closes when focus moves to an element outside the wrapper via Tab", () => {
    setup();
    const trigger = screen.getByRole("button", { name: "Add filter" });
    fireEvent.click(trigger);
    expect(document.querySelector(".filter-builder__menu")).toBeTruthy();

    // Blur the trigger with a relatedTarget outside the wrapper
    const outsideEl = document.createElement("button");
    document.body.appendChild(outsideEl);
    fireEvent.blur(trigger, { relatedTarget: outsideEl });
    act(() => { vi.advanceTimersByTime(200); });

    expect(document.querySelector(".filter-builder__menu")).toBeNull();
    outsideEl.remove();
  });

  it("closes when focus leaves a menu item to an element outside the wrapper", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));

    const menuItems = document.querySelectorAll<HTMLElement>(".filter-builder__menu-item");
    const outsideEl = document.createElement("button");
    document.body.appendChild(outsideEl);
    fireEvent.blur(menuItems[0], { relatedTarget: outsideEl });
    act(() => { vi.advanceTimersByTime(200); });

    expect(document.querySelector(".filter-builder__menu")).toBeNull();
    outsideEl.remove();
  });

  it("stays open when focus moves from trigger to a menu item", () => {
    setup();
    const trigger = screen.getByRole("button", { name: "Add filter" });
    fireEvent.click(trigger);

    const menuItem = document.querySelector<HTMLElement>(".filter-builder__menu-item")!;
    fireEvent.blur(trigger, { relatedTarget: menuItem });
    act(() => { vi.advanceTimersByTime(200); });

    expect(document.querySelector(".filter-builder__menu")).toBeTruthy();
  });
});

describe("FilterBar suggestion menu keyboard navigation", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); cleanup(); });

  function openValueInput(): HTMLInputElement {
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    const serviceItem = Array.from(
      document.querySelectorAll<HTMLElement>(".filter-builder__menu-item"),
    ).find((el) => el.textContent?.includes("Service"))!;
    fireEvent.mouseDown(serviceItem);
    return document.querySelector<HTMLInputElement>('[aria-label="serviceName value"]')!;
  }

  it("ArrowDown moves focus to the first suggestion and the blur timer does not close the menu", async () => {
    const suggest = vi.fn().mockResolvedValue(["checkout", "payments"]);
    setup(suggest);

    const input = openValueInput();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "c" } });
    await act(async () => { await Promise.resolve(); });

    expect(document.querySelector('[role="menu"][aria-label="serviceName suggestions"]')).toBeTruthy();

    fireEvent.keyDown(input, { key: "ArrowDown" });

    const firstItem = document.querySelector<HTMLElement>(
      '[role="menu"][aria-label="serviceName suggestions"] [role="menuitem"]',
    )!;
    expect(document.activeElement).toBe(firstItem);

    // Input blur fires when ArrowDown moves focus; advance past the 100 ms timer to prove the menu survives
    act(() => { vi.advanceTimersByTime(200); });
    expect(document.querySelector('[role="menu"][aria-label="serviceName suggestions"]')).toBeTruthy();
  });

  it("Escape in suggestions closes the menu without clearing the input value", async () => {
    const suggest = vi.fn().mockResolvedValue(["checkout", "payments"]);
    setup(suggest);

    const input = openValueInput();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "che" } });

    await act(async () => { await Promise.resolve(); });

    expect(document.querySelector(".filter-builder__menu")).toBeTruthy();

    fireEvent.keyDown(input, { key: "Escape" });

    act(() => { vi.advanceTimersByTime(200); });

    expect(document.querySelector(".filter-builder__menu")).toBeNull();
    expect((input as HTMLInputElement).value).toBe("che");
  });

  it("Escape in suggestions menu refocuses the value input", async () => {
    const suggest = vi.fn().mockResolvedValue(["checkout"]);
    setup(suggest);

    const input = openValueInput();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "c" } });

    await act(async () => { await Promise.resolve(); });

    const menu = document.querySelector<HTMLElement>('[role="menu"][aria-label="serviceName suggestions"]')!;
    fireEvent.keyDown(menu, { key: "Escape" });

    expect(document.activeElement).toBe(input);
  });

  it("suggestions reopen when the input is focused again after Escape closes them", async () => {
    const suggest = vi.fn().mockResolvedValue(["checkout"]);
    setup(suggest);

    const input = openValueInput();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "c" } });

    await act(async () => { await Promise.resolve(); });
    expect(document.querySelector('[role="menu"][aria-label="serviceName suggestions"]')).toBeTruthy();

    fireEvent.keyDown(input, { key: "Escape" });
    act(() => { vi.advanceTimersByTime(200); });
    expect(document.querySelector('[role="menu"][aria-label="serviceName suggestions"]')).toBeNull();

    // Natural re-focus (e.g. user tabs away and back)
    input.blur();
    await act(async () => { input.focus(); await Promise.resolve(); });

    expect(document.querySelector('[role="menu"][aria-label="serviceName suggestions"]')).toBeTruthy();
  });

  it("Escape does not reopen the suggestions menu after closing it", async () => {
    const suggest = vi.fn().mockResolvedValue(["checkout", "payments"]);
    setup(suggest);

    const input = openValueInput();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "c" } });

    await act(async () => { await Promise.resolve(); });
    expect(document.querySelector('[role="menu"][aria-label="serviceName suggestions"]')).toBeTruthy();

    fireEvent.keyDown(input, { key: "Escape" });

    act(() => { vi.advanceTimersByTime(200); });

    expect(document.querySelector('[role="menu"][aria-label="serviceName suggestions"]')).toBeNull();
    expect((input as HTMLInputElement).value).toBe("c");
  });

  it("selecting a suggestion via mouse click applies the value and closes the menu", async () => {
    const suggest = vi.fn().mockResolvedValue(["checkout", "payments"]);
    setup(suggest);

    const input = openValueInput();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "c" } });

    await act(async () => { await Promise.resolve(); });

    const firstItem = document.querySelector<HTMLElement>('[role="menu"][aria-label="serviceName suggestions"] [role="menuitem"]')!;

    await act(async () => { fireEvent.click(firstItem); await Promise.resolve(); });

    expect((input as HTMLInputElement).value).toBe("checkout");
    expect(document.querySelector('[role="menu"][aria-label="serviceName suggestions"]')).toBeNull();
  });

  it("selecting a suggestion via keyboard Enter applies the value, refocuses the input, and closes the menu", async () => {
    const suggest = vi.fn().mockResolvedValue(["checkout", "payments"]);
    setup(suggest);

    const input = openValueInput();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "c" } });
    await act(async () => { await Promise.resolve(); });

    // Simulate ArrowDown navigation to the first item
    const firstItem = document.querySelector<HTMLElement>(
      '[role="menu"][aria-label="serviceName suggestions"] [role="menuitem"]',
    )!;
    firstItem.focus();
    expect(document.activeElement).toBe(firstItem);

    // Simulate Enter (fires click on the focused button)
    await act(async () => { fireEvent.click(firstItem); await Promise.resolve(); });

    expect((input as HTMLInputElement).value).toBe("checkout");
    expect(document.activeElement).toBe(input);
    expect(document.querySelector('[role="menu"][aria-label="serviceName suggestions"]')).toBeNull();
  });
});
