import { useState, useRef, useEffect, useCallback } from "react";

/**
 * Delays state-clearing callbacks so a slide-out CSS animation can complete
 * before the panel is removed from the DOM.
 *
 * Usage:
 *   const { exiting, triggerExit, cancelExit } = useAnimatedPanel();
 *   // Call triggerExit(clearStateFn) instead of clearStateFn() directly.
 *   // Call cancelExit() when opening a new item while one is closing.
 */
export function useAnimatedPanel(durationMs = 300) {
  const [exiting, setExiting] = useState(false);
  const timerRef = useRef<number | null>(null);

  const triggerExit = useCallback(
    (onComplete: () => void) => {
      if (timerRef.current !== null) return; // already exiting — ignore duplicate calls
      setExiting(true);
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        setExiting(false);
        onComplete();
      }, durationMs);
    },
    [durationMs],
  );

  const cancelExit = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
      setExiting(false);
    }
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  return { exiting, triggerExit, cancelExit };
}
