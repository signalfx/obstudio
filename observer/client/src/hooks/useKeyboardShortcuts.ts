import { useEffect } from "react";

/** Register webview-local shortcuts while preserving host modifier commands. */
export function useKeyboardShortcuts(shortcuts: Record<string, () => void>): void {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      // Leave modified shortcuts (such as VS Code's Cmd/Ctrl+P) to the host.
      if (event.altKey || event.ctrlKey || event.metaKey) return;

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
