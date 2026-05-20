import React, { useEffect } from "react";

interface KeyboardHelpProps {
  onClose: () => void;
}

const shortcuts = [
  { key: "?", description: "Toggle keyboard shortcuts" },
  { key: "p", description: "Pause / resume live updates" },
  { key: "Escape", description: "Close help or deselect trace (Traces tab)" },
  { key: "1", description: "Switch to Metrics tab" },
  { key: "2", description: "Switch to Traces tab" },
  { key: "3", description: "Switch to Logs tab" },
  { key: "4", description: "Switch to Services tab" },
  { key: "5", description: "Switch to Validation tab" },
];

/** Modal overlay listing available keyboard shortcuts. */
export function KeyboardHelp({ onClose }: KeyboardHelpProps): React.ReactElement {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      onClose();
    };

    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [onClose]);

  return (
    <div className="keyboard-help__overlay" onClick={onClose}>
      <div
        className="keyboard-help"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="keyboard-help-title"
      >
        <div className="keyboard-help__header">
          <h2 className="keyboard-help__title" id="keyboard-help-title">Keyboard Shortcuts</h2>
          <button className="keyboard-help__close" onClick={onClose} type="button" aria-label="Close">
            &times;
          </button>
        </div>
        <div className="keyboard-help__body">
          {shortcuts.map((s) => (
            <div key={s.key} className="keyboard-help__row">
              <span className="keyboard-help__key">{s.key}</span>
              <span className="keyboard-help__desc">{s.description}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
