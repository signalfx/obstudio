import React from "react";

interface KeyboardHelpProps {
  onClose: () => void;
}

const shortcuts = [
  { key: "?", description: "Toggle keyboard shortcuts" },
  { key: "p", description: "Pause / resume live updates" },
  { key: "Escape", description: "Deselect trace (Traces tab)" },
  { key: "1", description: "Switch to Metrics tab" },
  { key: "2", description: "Switch to Traces tab" },
  { key: "3", description: "Switch to Logs tab" },
];

/** Modal overlay listing available keyboard shortcuts. */
export function KeyboardHelp({ onClose }: KeyboardHelpProps): React.ReactElement {
  return (
    <div className="keyboard-help__overlay" onClick={onClose}>
      <div className="keyboard-help" onClick={(e) => e.stopPropagation()}>
        <div className="keyboard-help__header">
          <h2 className="keyboard-help__title">Keyboard Shortcuts</h2>
          <button className="keyboard-help__close" onClick={onClose} type="button">
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
