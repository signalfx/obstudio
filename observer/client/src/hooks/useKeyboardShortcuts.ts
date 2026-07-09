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

const forwardedEvents = new WeakSet<KeyboardEvent>();
const forwardedCodes = new Set<string>();

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
  return [67, 70, 80, 83, 86, 88, 89, 90].includes(event.keyCode);
}

/** Forward a host shortcut out of the nested Observer iframe. */
export function forwardHostKeyboardEvent(
  event: KeyboardEvent,
  parentWindow: Window = window.parent,
  currentWindow: Window = window,
): boolean {
  if (forwardedEvents.has(event)) return true;
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

  forwardedEvents.add(event);
  parentWindow.postMessage(message, "*");
  if (event.type === "keydown" && shouldPreventBrowserDefault(event)) {
    event.preventDefault();
  }
  return true;
}

/** Register webview-local shortcuts and bridge host modifier commands out of the nested iframe. */
export function useKeyboardShortcuts(shortcuts: Record<string, () => void>): void {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (hasHostCommandModifier(event)) {
        forwardHostKeyboardEvent(event);
        return;
      }

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

    const keyupHandler = (event: KeyboardEvent) => {
      forwardHostKeyboardEvent(event);
    };

    window.addEventListener("keydown", handler);
    window.addEventListener("keyup", keyupHandler);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("keyup", keyupHandler);
    };
  }, [shortcuts]);
}
