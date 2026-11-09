import React from "react";

export interface SwitchProps {
  checked: boolean;
  /** A write is in flight: toggles are ignored, and the switch keeps keyboard focus. */
  busy: boolean;
  onToggle(next: boolean): void;
  id?: string;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
}

/**
 * An on/off switch for a setting, named by an external label. While busy it
 * is aria-disabled, not disabled: a disabled button drops keyboard focus.
 */
export function Switch({
  checked,
  busy,
  onToggle,
  id,
  "aria-labelledby": labelledBy,
  "aria-describedby": describedBy,
}: SwitchProps): React.ReactElement {
  return (
    <button
      aria-checked={checked}
      aria-describedby={describedBy}
      aria-disabled={busy || undefined}
      aria-labelledby={labelledBy}
      className={checked ? "cloud-switch cloud-switch--on" : "cloud-switch"}
      id={id}
      onClick={() => {
        if (!busy) onToggle(!checked);
      }}
      role="switch"
      type="button"
    >
      <span aria-hidden="true" className="cloud-switch__track"><span /></span>
      <span aria-hidden="true">{checked ? "On" : "Off"}</span>
    </button>
  );
}
