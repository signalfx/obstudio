import React, { useEffect, useMemo, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { Switch } from "../components/Switch";
import type { ConfigEditsState, FieldValue } from "../cloud/configEdits";
import { saveErrorText, type SendOutcome, useConfigEdits } from "../cloud/useConfigEdits";
import { observerFetch } from "../host/transport";
import {
  type ConfigDefinition,
  type ConfigSection,
  displayDescription,
  displayTitle,
  editFields,
  hasChoices,
  parseDefinitions,
  parseText,
  toText,
} from "./model";

const SAVED_INDICATOR_MS = 1500;

/** Settings generated from the observer's config definitions, saved as they are edited. */
export function ConfigTab(): React.ReactElement {
  const [sections, setSections] = useState<ConfigSection[] | null>(null);
  const [definitionsFailed, setDefinitionsFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (sections !== null) return undefined;
    let active = true;
    observerFetch("/api/config/definitions")
      .then(async (response) => (response.ok ? parseDefinitions(await response.json()) : null))
      .catch(() => null)
      .then((parsed) => {
        if (!active) return;
        if (parsed !== null) setSections(parsed);
        setDefinitionsFailed(parsed === null);
      });
    return () => {
      active = false;
    };
    // Only a retry asks again; once the definitions are loaded they stay.
  }, [attempt]);

  const fields = useMemo(() => (sections === null ? null : editFields(sections)), [sections]);
  const { edit, outcomes, refresh, state } = useConfigEdits(fields);

  const loadFailed = definitionsFailed || state?.loadFailed === true;
  const ready = sections !== null && state !== null && state.server !== null;
  const retry = (): void => {
    if (sections === null) setAttempt((count) => count + 1);
    refresh();
  };

  return (
    <section id="panel-config" aria-label="Config" className="tab-panel config-tab" role="tabpanel">
      <div className="config-tab__content">
        <header className="config-tab__header">
          <h2>Configuration</h2>
          <p>Changes are saved automatically.</p>
        </header>

        {!ready && !loadFailed ? (
          <p className="explorer__status" role="status">Loading configuration…</p>
        ) : null}

        {loadFailed ? (
          <div className="cloud-alert cloud-alert--error config-alert" role="alert">
            <span>Could not load the configuration.</span>
            <button className="cloud-button" onClick={retry} type="button">Retry</button>
          </div>
        ) : null}

        {ready && sections.length === 0 ? (
          <EmptyState title="No settings available" hint="Splunk Observability Studio did not report any settings." />
        ) : null}

        {ready ? sections.map((section) => (
          <section aria-labelledby={`config-section-${section.name}`} className="config-section" key={section.name}>
            <h3 className="config-section__title" id={`config-section-${section.name}`}>{section.title}</h3>
            {section.definitions.map((definition) => (
              <ConfigField
                definition={definition}
                error={outcomes[definition.path]?.ok === false ? state.error : null}
                inFlight={state.inFlight.has(definition.path)}
                key={definition.path}
                onEdit={edit}
                outcome={outcomes[definition.path]}
                value={state.values[definition.path]}
              />
            ))}
          </section>
        )) : null}
      </div>
    </section>
  );
}

interface ConfigFieldProps {
  definition: ConfigDefinition;
  /** What configEdits says the field displays. */
  value: FieldValue | undefined;
  inFlight: boolean;
  outcome: SendOutcome | undefined;
  /** The send error, when the latest send carrying this field failed. */
  error: ConfigEditsState["error"];
  onEdit: (path: string, value: FieldValue) => void;
}

function rangeHint(definition: ConfigDefinition): string | null {
  const { minimum, maximum } = definition;
  if (minimum !== undefined && maximum !== undefined) return `Whole number from ${minimum} to ${maximum}`;
  if (minimum !== undefined) return `Whole number, at least ${minimum}`;
  if (maximum !== undefined) return `Whole number, at most ${maximum}`;
  return null;
}

/** "Saved" for a moment after a send carrying the field succeeds. */
function useSavedIndicator(outcome: SendOutcome | undefined): boolean {
  const [shownFor, setShownFor] = useState<number | null>(null);
  useEffect(() => {
    if (outcome === undefined || !outcome.ok) {
      setShownFor(null);
      return undefined;
    }
    setShownFor(outcome.seq);
    const timer = setTimeout(() => setShownFor(null), SAVED_INDICATOR_MS);
    return () => clearTimeout(timer);
  }, [outcome]);
  return shownFor !== null && shownFor === outcome?.seq;
}

function ConfigField({ definition, value, inFlight, outcome, error, onEdit }: ConfigFieldProps): React.ReactElement {
  // Text the user typed. Kept while it does not parse, or while it still
  // matches the displayed value; dropped when the server's value replaces it.
  const [draft, setDraft] = useState<{ text: string; error: string | null } | null>(null);
  const saved = useSavedIndicator(outcome);

  useEffect(() => {
    setDraft((current) => {
      if (current === null || current.error !== null) return current;
      const parsed = parseText(definition, current.text);
      return parsed.ok && parsed.value === value ? current : null;
    });
  }, [definition, value]);

  const id = `config-field-${definition.path.replace(/[^A-Za-z0-9_-]/g, "-")}`;
  const titleId = `${id}-title`;
  const descriptionId = `${id}-description`;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const title = displayTitle(definition);
  const description = displayDescription(definition);
  const choices = hasChoices(definition) ? (definition.enum ?? []).map(String) : null;
  const hints = [
    definition.type === "integer" && choices === null ? rangeHint(definition) : null,
    definition.apply === "restart" ? "Takes effect after a restart." : null,
  ].filter((hint): hint is string => hint !== null);
  const hint = hints.length > 0 ? hints.join(" ") : null;
  const errorText = draft?.error ?? (error ? saveErrorText(error) : null);
  const describedBy = [
    description !== null ? descriptionId : null,
    hint !== null ? hintId : null,
    errorText !== null ? errorId : null,
  ]
    .filter((part): part is string => part !== null)
    .join(" ") || undefined;
  const status = inFlight ? "saving" : saved ? "saved" : "idle";
  const statusText = status === "saving" ? "Saving…" : status === "saved" ? "Saved" : "";

  let control: React.ReactElement;
  if (definition.type === "boolean") {
    control = (
      <Switch
        aria-describedby={describedBy}
        aria-labelledby={titleId}
        busy={inFlight}
        checked={value === true}
        id={id}
        onToggle={(next) => onEdit(definition.path, next)}
      />
    );
  } else if (choices !== null) {
    const text = toText(value);
    control = (
      <select
        aria-describedby={describedBy}
        aria-disabled={inFlight || undefined}
        aria-invalid={errorText !== null}
        className="config-select"
        id={id}
        onChange={(event) => {
          const parsed = parseText(definition, event.target.value);
          if (parsed.ok && !inFlight) onEdit(definition.path, parsed.value);
        }}
        value={text}
      >
        {choices.includes(text) ? null : <option value={text}>{text === "" ? "(not set)" : `${text} (not allowed)`}</option>}
        {choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
      </select>
    );
  } else {
    control = (
      <input
        aria-describedby={describedBy}
        aria-invalid={errorText !== null}
        autoComplete="off"
        className="config-input"
        id={id}
        inputMode={definition.type === "integer" ? "numeric" : undefined}
        onChange={(event) => {
          const text = event.target.value;
          const parsed = parseText(definition, text);
          setDraft({ error: parsed.ok ? null : parsed.error, text });
          if (parsed.ok) onEdit(definition.path, parsed.value);
        }}
        spellCheck={false}
        type="text"
        value={draft?.text ?? toText(value)}
      />
    );
  }

  return (
    <div className="config-field" data-status={status}>
      <div className="config-field__text">
        <label className="config-field__label" htmlFor={id} id={titleId}>{title}</label>
        {description !== null ? <p className="config-field__description" id={descriptionId}>{description}</p> : null}
        {title !== definition.path ? <code className="config-field__key">{definition.path}</code> : null}
        {hint !== null ? <p className="config-field__hint" id={hintId}>{hint}</p> : null}
      </div>
      <div className="config-field__control">
        {control}
        <span className="config-field__status" role="status">{statusText}</span>
      </div>
      {errorText !== null ? (
        <p className="config-field__error" id={errorId} role="alert">{errorText}</p>
      ) : null}
    </div>
  );
}
