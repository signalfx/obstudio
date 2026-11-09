import React from "react";
import type { SplunkExportSignalStatus } from "../api/types";

export function ExportControls({ id, title, activityLabel, signals }: {
  id: string;
  title: string;
  activityLabel: string;
  signals: { label: string; signal: SplunkExportSignalStatus | undefined; statusText?: string; tone?: "error" | "idle" | "success" | "warning" }[];
}): React.ReactElement {
  return (
    <section aria-labelledby={id} className="cloud-export">
      <h3 id={id} className="visually-hidden">{title}</h3>
      <div aria-label={activityLabel} className="cloud-signal-list" role="list">
        {signals.map(({ label, signal, statusText, tone }) => {
          const row = signalRow(label, signal);
          return (
            <div className={`cloud-signal-row cloud-signal-row--${tone ?? row.tone}`} key={label} role="listitem">
              <span aria-hidden="true" className="cloud-signal-row__dot" />
              <div><p>{label}</p><small>{statusText ?? row.status}</small></div>
              <span className="cloud-signal-row__count">{row.detail}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function ExportToggle({ enabled, partial = false, busy = false, disabled = false, onToggle, switchLabel, buttonRef }: {
  enabled: boolean; partial?: boolean; busy?: boolean; disabled?: boolean;
  onToggle: () => void; switchLabel: string; buttonRef?: React.RefObject<HTMLButtonElement | null>;
}): React.ReactElement {
  const state = enabled ? "on" : partial ? "partially on" : "off";
  return <button aria-checked={enabled} aria-label={`${switchLabel} is ${state}`}
    className={enabled ? "cloud-switch cloud-switch--on" : "cloud-switch"}
    disabled={disabled || busy} onClick={onToggle} role="switch" ref={buttonRef} type="button">
    <span aria-hidden="true" className="cloud-switch__track"><span /></span>
    <span>{busy ? "Updating" : enabled ? "On" : partial ? "Partial" : "Off"}</span>
  </button>;
}

export function ConnectionBadge({ state }: { state: "Connected" | "Not connected" | "Rejected" | "Connection failed" | "Loading" | "Unavailable" | "Secure storage unavailable" }): React.ReactElement {
  const tone = state === "Connected" ? "connected" : state === "Secure storage unavailable" ? "warning" : state === "Rejected" || state === "Connection failed" || state === "Unavailable" ? "error" : "idle";
  return <span className={`destination-badge destination-badge--${tone}`}><span aria-hidden="true" />{state}</span>;
}

function signalRow(label: string, signal: SplunkExportSignalStatus | undefined): {
  detail: string; status: string; tone: "error" | "idle" | "success" | "warning";
} {
  if (!signal) return { detail: "No activity", status: "Waiting for Splunk Observability Studio", tone: "idle" };
  const detail = `${formatCount(signal.exportedItems, label === "Metrics" ? "point" : label === "Logs" ? "log" : "span")} exported · ${formatCount(signal.exportedBatches, "batch", "batches")}`;
  if (!signal.enabled) return { detail, status: "Paused — export is off. Telemetry stays local.", tone: "idle" };
  if (signal.lastExport && !signal.lastExport.success) {
    return { detail, status: signal.lastExport.error ? `Failed: ${signal.lastExport.error}` : "Last export failed", tone: "error" };
  }
  if (signal.lastExport?.success) {
    const elapsed = Math.max(0, Date.now() - new Date(signal.lastExport.time).getTime());
    const seconds = Math.floor(elapsed / 1000);
    const age = seconds < 60 ? `${seconds}s` : seconds < 3600 ? `${Math.floor(seconds / 60)}m` : `${Math.floor(seconds / 3600)}h`;
    return { detail, status: Number.isFinite(elapsed) ? `Last batch accepted ${age} ago.` : "Last batch accepted.", tone: signal.failedBatches > 0 ? "warning" : "success" };
  }
  return { detail, status: "Waiting for telemetry", tone: "idle" };
}

function formatCount(value: number, singular: string, plural = `${singular}s`): string {
  return `${value.toLocaleString()} ${value === 1 ? singular : plural}`;
}

export function EditingBadge(): React.ReactElement {
  return <span className="destination-editing-label">
    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false"><path d="M11.2 2.8 13.2 4.8 5.6 12.4 2.8 13.2l0.8-2.8 7.6-7.6Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" /></svg>
    Editing
  </span>;
}

export function SavedTokenBadge(): React.ReactElement {
  return <span className="destination-saved">
    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden="true" focusable="false"><path d="M2.5 6.4 5 8.8l4.5-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
    Saved
  </span>;
}
