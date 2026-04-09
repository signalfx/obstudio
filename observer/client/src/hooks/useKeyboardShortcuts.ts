import { useEffect } from "react";

/** Register global keyboard shortcuts; ignores events from input elements. */
export function useKeyboardShortcuts(shortcuts: Record<string, () => void>): void {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      // Ignore when typing in an input.
      const tag = (event.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      const fn = shortcuts[event.key];
      if (fn) {
        event.preventDefault();
        fn();
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [shortcuts]);
}
