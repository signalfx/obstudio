import React, { useMemo } from "react";
import { EmptyState } from "../components/EmptyState";
import type { ConfigKeySpec } from "../api/types";
import { type DraftValue, displayDescription, displayLabel, fieldKind, groupSections } from "./model";
import { type FieldState, useConfig } from "./useConfig";

/** Settings generated from the server's config schema, saved automatically as they are edited. */
export function ConfigTab(): React.ReactElement {
  const { edit, fields, flush, loadError, loadState, reset, retry, specs } = useConfig();
  const sections = useMemo(() => groupSections(specs), [specs]);

  return (
    <section id="panel-config" aria-label="Config" className="tab-panel config-tab" role="tabpanel">
      <div className="config-tab__content">
        <header className="config-tab__header">
          <h2>Configuration</h2>
          <p>Changes are saved automatically.</p>
        </header>

        {loadState === "loading" ? (
          <p className="explorer__status" role="status">Loading configuration…</p>
        ) : null}

        {loadState === "error" ? (
          <div className="cloud-alert cloud-alert--error config-alert" role="alert">
            <span>{loadError ?? "Could not load the configuration."}</span>
            <button className="cloud-button" onClick={retry} type="button">Retry</button>
          </div>
        ) : null}

        {loadState === "ready" && specs.length === 0 ? (
          <EmptyState title="No settings available" hint="The server did not report any configurable settings." />
        ) : null}

        {loadState === "ready" ? sections.map((section) => (
          <section aria-labelledby={`config-section-${section.id}`} className="config-section" key={section.id}>
            <h3 className="config-section__title" id={`config-section-${section.id}`}>{section.title}</h3>
            {section.specs.map((spec) => {
              const state = fields[spec.key];
              if (state === undefined) return null;
              return (
                <ConfigField
                  key={spec.key}
                  onEdit={edit}
                  onFlush={flush}
                  onReset={reset}
                  spec={spec}
                  state={state}
                />
              );
            })}
          </section>
        )) : null}
      </div>
    </section>
  );
}

interface ConfigFieldProps {
  spec: ConfigKeySpec;
  state: FieldState;
  onEdit: (key: string, draft: DraftValue, immediate?: boolean) => void;
  onFlush: (key: string) => void;
  onReset: (key: string) => void;
}

function rangeHint(spec: ConfigKeySpec): string | null {
  const { minimum, maximum } = spec;
  if (minimum !== undefined && maximum !== undefined) return `Whole number from ${minimum} to ${maximum}`;
  if (minimum !== undefined) return `Whole number, at least ${minimum}`;
  if (maximum !== undefined) return `Whole number, at most ${maximum}`;
  return null;
}

function ConfigField({ spec, state, onEdit, onFlush, onReset }: ConfigFieldProps): React.ReactElement {
  const kind = fieldKind(spec);
  const id = `config-field-${spec.key.replace(/[^A-Za-z0-9_-]/g, "-")}`;
  const labelId = `${id}-label`;
  const descriptionId = `${id}-description`;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const label = displayLabel(spec);
  const description = displayDescription(spec);
  const hint = kind === "integer" && !(spec.allowedValues?.length) ? rangeHint(spec) : null;
  const describedBy = [
    description !== null ? descriptionId : null,
    hint !== null ? hintId : null,
    state.error !== null ? errorId : null,
  ]
    .filter((value): value is string => value !== null)
    .join(" ") || undefined;
  const invalid = state.error !== null;
  const statusText = state.status === "saving" ? "Saving…" : state.status === "saved" ? "Saved" : "";
  const draftText = typeof state.draft === "string" ? state.draft : "";
  const choices = spec.allowedValues !== undefined && spec.allowedValues.length > 0 && kind !== "boolean"
    ? spec.allowedValues.map(String)
    : null;

  let control: React.ReactElement;
  if (kind === "boolean") {
    const on = state.draft === true;
    control = (
      <button
        aria-checked={on}
        aria-describedby={describedBy}
        aria-labelledby={labelId}
        className={on ? "cloud-switch cloud-switch--on" : "cloud-switch"}
        id={id}
        onClick={() => onEdit(spec.key, !on, true)}
        role="switch"
        type="button"
      >
        <span aria-hidden="true" className="cloud-switch__track"><span /></span>
        <span aria-hidden="true">{on ? "On" : "Off"}</span>
      </button>
    );
  } else if (kind === "unsupported") {
    control = <code className="config-field__readonly" id={id}>{draftText === "" ? "—" : draftText}</code>;
  } else if (choices !== null) {
    const known = choices.includes(draftText);
    control = (
      <select
        aria-describedby={describedBy}
        aria-invalid={invalid}
        className="config-select"
        id={id}
        onChange={(event) => onEdit(spec.key, event.target.value, true)}
        value={draftText}
      >
        {known ? null : <option value={draftText}>{draftText === "" ? "(not set)" : `${draftText} (not allowed)`}</option>}
        {choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
      </select>
    );
  } else {
    control = (
      <input
        aria-describedby={describedBy}
        aria-invalid={invalid}
        autoComplete="off"
        className="config-input"
        id={id}
        inputMode={kind === "integer" ? "numeric" : undefined}
        onBlur={() => onFlush(spec.key)}
        onChange={(event) => onEdit(spec.key, event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") onFlush(spec.key);
        }}
        spellCheck={false}
        type="text"
        value={draftText}
      />
    );
  }

  return (
    <div className="config-field" data-status={state.status}>
      <div className="config-field__text">
        <label className="config-field__label" htmlFor={id} id={labelId}>{label}</label>
        {description !== null ? <p className="config-field__description" id={descriptionId}>{description}</p> : null}
        {label !== spec.key ? <code className="config-field__key">{spec.key}</code> : null}
        {hint !== null ? <p className="config-field__hint" id={hintId}>{hint}</p> : null}
      </div>
      <div className="config-field__control">
        {control}
        <span className="config-field__status" role="status">{statusText}</span>
      </div>
      {state.error !== null ? (
        <p className="config-field__error" id={errorId} role="alert">
          <span>{state.error}</span>
          {state.status === "error" ? (
            <button
              aria-label={`Reset ${label} to its saved value`}
              className="config-field__reset"
              onClick={() => onReset(spec.key)}
              type="button"
            >
              Reset to saved
            </button>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}
