// @vitest-environment happy-dom

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAnimatedPanel } from "./useAnimatedPanel";

describe("useAnimatedPanel", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("starts with exiting=false", () => {
    const { result } = renderHook(() => useAnimatedPanel());
    expect(result.current.exiting).toBe(false);
  });

  it("triggerExit sets exiting=true immediately and calls onComplete after duration", () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useAnimatedPanel(200));

    act(() => { result.current.triggerExit(onComplete); });
    expect(result.current.exiting).toBe(true);
    expect(onComplete).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(200); });
    expect(result.current.exiting).toBe(false);
    expect(onComplete).toHaveBeenCalledOnce();
  });

  it("second triggerExit call while exiting completes immediately, cancelling the first", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { result } = renderHook(() => useAnimatedPanel(200));

    act(() => { result.current.triggerExit(first); });
    act(() => { result.current.triggerExit(second); });

    // second call fires immediately and resets exiting; first timer was cleared
    expect(second).toHaveBeenCalledOnce();
    expect(first).not.toHaveBeenCalled();
    expect(result.current.exiting).toBe(false);

    // no stale timer fires after duration
    act(() => { vi.advanceTimersByTime(200); });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
  });

  it("cancelExit resets exiting to false and prevents the callback", () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useAnimatedPanel(200));

    act(() => { result.current.triggerExit(onComplete); });
    expect(result.current.exiting).toBe(true);

    act(() => { result.current.cancelExit(); });
    expect(result.current.exiting).toBe(false);

    act(() => { vi.advanceTimersByTime(200); });
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("allows triggerExit again after cancelExit", () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useAnimatedPanel(200));

    act(() => { result.current.triggerExit(vi.fn()); });
    act(() => { result.current.cancelExit(); });
    act(() => { result.current.triggerExit(onComplete); });

    act(() => { vi.advanceTimersByTime(200); });
    expect(onComplete).toHaveBeenCalledOnce();
  });

  it("skips the animation and calls onComplete synchronously when prefers-reduced-motion is reduce", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));

    const onComplete = vi.fn();
    const { result } = renderHook(() => useAnimatedPanel(200));

    act(() => { result.current.triggerExit(onComplete); });

    expect(onComplete).toHaveBeenCalledOnce();
    expect(result.current.exiting).toBe(false);
  });

  it("unmount while a timer is pending clears the timer so onComplete never fires", () => {
    const onComplete = vi.fn();
    const { result, unmount } = renderHook(() => useAnimatedPanel(200));

    act(() => { result.current.triggerExit(onComplete); });
    expect(result.current.exiting).toBe(true);

    unmount();

    act(() => { vi.advanceTimersByTime(200); });
    expect(onComplete).not.toHaveBeenCalled();
  });
});
