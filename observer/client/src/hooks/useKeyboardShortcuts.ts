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

// Block only browser UI that competes with host commands. Editing defaults must
// stay available to focused controls inside the cross-origin Observer iframe.
const suppressedBrowserShortcutKeyCodes = new Set(
  ["P", "S"].map((key) => key.charCodeAt(0)),
);
const editablePrimaryShortcutKeys = new Set(["a", "c", "v", "x", "y", "z"]);
const editableNavigationKeys = new Set([
  "arrowdown",
  "arrowleft",
  "arrowright",
  "arrowup",
  "backspace",
  "delete",
  "end",
  "home",
  "insert",
]);

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

function isModifierCode(code: string): boolean {
  return ["Alt", "Control", "Meta", "Shift"].some(
    (modifier) => code === modifier || code.startsWith(modifier),
  );
}

function shouldPreventBrowserDefault(event: KeyboardEvent): boolean {
  if (!event.ctrlKey && !event.metaKey) return false;
  return suppressedBrowserShortcutKeyCodes.has(event.keyCode);
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!target || typeof target !== "object") return false;
  const element = target as HTMLElement;
  const tagName = element.tagName?.toUpperCase();
  return tagName === "INPUT"
    || tagName === "TEXTAREA"
    || tagName === "SELECT"
    || element.isContentEditable === true;
}

function isEditableEditingShortcut(event: KeyboardEvent): boolean {
  if (!isEditableTarget(event.target)) return false;
  const key = event.key.toLowerCase();
  const primaryModifier = event.ctrlKey || event.metaKey;
  if (primaryModifier) {
    return editablePrimaryShortcutKeys.has(key) || editableNavigationKeys.has(key);
  }
  return event.altKey && editableNavigationKeys.has(key);
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
    if (isEditableEditingShortcut(event)) return false;
    forwardedCodes.add(code);
  } else if (event.type === "keyup") {
    const wasForwarded = forwardedCodes.delete(code);
    const isReleasedHostModifier = isHostModifierKey(event);
    if (isReleasedHostModifier) {
      // macOS may omit a non-modifier keyup while Cmd is held. Drop those stale
      // entries when the host modifier is released, while retaining any Shift
      // key that still needs its own forwarded keyup.
      for (const forwardedCode of forwardedCodes) {
        if (!isModifierCode(forwardedCode)) forwardedCodes.delete(forwardedCode);
      }
    }
    if (!wasForwarded && !isReleasedHostModifier) return false;
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

  // VS Code webview origins are opaque to the nested iframe. The parent still
  // validates both this window as the source and the Observer origin.
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
    const reset = () => forwardedCodes.clear();

    window.addEventListener("keydown", handler);
    window.addEventListener("keyup", handler);
    window.addEventListener("blur", reset);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("keyup", handler);
      window.removeEventListener("blur", reset);
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
