import { useEffect } from "react";

type KeyboardModifierEvent = Pick<KeyboardEvent, "altKey" | "ctrlKey" | "metaKey">;

/** Whether a key event belongs to a host-level Alt, Ctrl, or Cmd shortcut. */
export function hasHostCommandModifier(event: KeyboardModifierEvent): boolean {
  return event.altKey || event.ctrlKey || event.metaKey;
}

/** Register webview-local shortcuts while preserving host modifier commands. */
export function useKeyboardShortcuts(shortcuts: Record<string, () => void>): void {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (hasHostCommandModifier(event)) return;

      // Ignore when typing in an input.
      const tag = (event.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
      const fn = shortcuts[key];
      if (fn) {
        event.preventDefault();
        fn();
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [shortcuts]);
}
