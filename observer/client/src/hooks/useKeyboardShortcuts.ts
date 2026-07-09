import { useEffect } from "react";

type KeyboardModifierEvent = Pick<KeyboardEvent, "altKey" | "ctrlKey" | "metaKey">;

export const hostKeyboardEventMessageType = "obstudio:host-keyboard-event";

export interface HostKeyboardEventMessage {
  type: typeof hostKeyboardEventMessageType;
  event: {
    altKey: boolean;
    code: string;
    ctrlKey: boolean;
    key: string;
    keyCode: number;
    location: number;
    metaKey: boolean;
    repeat: boolean;
    shiftKey: boolean;
    type: "keydown" | "keyup";
  };
}

const suppressedBrowserShortcutKeyCodes = new Set(
  ["P", "S"].map((key) => key.charCodeAt(0)),
);

/** Whether a key event belongs to a host-level Alt, Ctrl, or Cmd shortcut. */
export function hasHostCommandModifier(event: KeyboardModifierEvent): boolean {
  return event.altKey || event.ctrlKey || event.metaKey;
}

function eventCode(event: KeyboardEvent): string {
  return event.code || event.key;
}

function isHostModifierKey(event: KeyboardEvent): boolean {
  return event.key === "Alt" || event.key === "Control" || event.key === "Meta";
}

function shouldPreventBrowserDefault(event: KeyboardEvent): boolean {
  if (!event.ctrlKey && !event.metaKey) return false;
  return suppressedBrowserShortcutKeyCodes.has(event.keyCode);
}

/** Forward a host shortcut out of the nested Observer iframe. */
export function forwardHostKeyboardEvent(
  event: KeyboardEvent,
  forwardedCodes: Set<string>,
  parentWindow: Window = window.parent,
  currentWindow: Window = window,
): boolean {
  if (parentWindow === currentWindow) return false;

  const code = eventCode(event);
  if (event.type === "keydown") {
    if (!hasHostCommandModifier(event)) return false;
    forwardedCodes.add(code);
  } else if (event.type === "keyup") {
    const wasForwarded = forwardedCodes.delete(code);
    if (!wasForwarded && !hasHostCommandModifier(event) && !isHostModifierKey(event)) return false;
  } else {
    return false;
  }

  const message: HostKeyboardEventMessage = {
    type: hostKeyboardEventMessageType,
    event: {
      type: event.type,
      key: event.key,
      code: event.code,
      keyCode: event.keyCode,
      location: event.location,
      altKey: event.altKey,
      ctrlKey: event.ctrlKey,
      metaKey: event.metaKey,
      shiftKey: event.shiftKey,
      repeat: event.repeat,
    },
  };

  parentWindow.postMessage(message, "*");
  if (event.type === "keydown" && shouldPreventBrowserDefault(event)) {
    event.preventDefault();
  }
  return true;
}

/** Bridge host modifier commands out of the nested iframe once at the app root. */
export function useHostKeyboardForwarding(): void {
  useEffect(() => {
    const forwardedCodes = new Set<string>();
    const handler = (event: KeyboardEvent) => {
      forwardHostKeyboardEvent(event, forwardedCodes);
    };

    window.addEventListener("keydown", handler);
    window.addEventListener("keyup", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("keyup", handler);
      forwardedCodes.clear();
    };
  }, []);
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
