import React, { useEffect, useId, useMemo, useRef, useState } from "react";

export type FilterFieldKind = "text" | "number" | "enum" | "datetime";

export interface FilterDefinition {
  key: string;
  label?: string;
  kind: FilterFieldKind;
  chipLabel?: string;
  placeholder?: string;
  operatorLabels?: OperatorLabels;
  options?: Array<{ label: string; value: string }>;
  supportsNot?: boolean;
  step?: number;
}

export interface FilterClause {
  key: string;
  op: "eq" | "neq";
  value: string;
}

interface FilterBarProps {
  definitions: FilterDefinition[];
  clauses: FilterClause[];
  onChange: (nextClauses: FilterClause[]) => void;
  fieldPlaceholder?: string;
  onSuggestValues?: (fieldKey: string, prefix: string, signal: AbortSignal) => Promise<string[]>;
}

interface OperatorLabels {
  eq: string;
  neq: string;
}

const DEFAULT_OPERATOR_LABELS: OperatorLabels = { eq: "=", neq: "!=" };

function resolveOperatorLabels(definition: FilterDefinition): OperatorLabels {
  return definition.operatorLabels ?? DEFAULT_OPERATOR_LABELS;
}

function normalizeClauseValue(definition: FilterDefinition, value: string): string {
  if (definition.kind === "datetime") {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString();
    }
  }
  return value.trim();
}

function nextDraftValue(definition: FilterDefinition, rawValue: string, currentValue: string): string {
  if (definition.kind !== "number") {
    return rawValue;
  }
  if (rawValue === "") {
    return "";
  }
  const parsed = Number(rawValue);
  if (!Number.isNaN(parsed) && parsed < 0) {
    return currentValue;
  }
  if (!Number.isNaN(parsed) && definition.step === 1 && !Number.isInteger(parsed)) {
    return currentValue;
  }
  return rawValue;
}

function chipText(definition: FilterDefinition | undefined, clause: FilterClause): string {
  const base = definition?.chipLabel ?? definition?.label ?? definition?.key ?? "filter";
  const labels = definition ? resolveOperatorLabels(definition) : DEFAULT_OPERATOR_LABELS;
  const op = clause.op === "neq" ? labels.neq : labels.eq;
  return `${base} ${op} ${clause.value}`;
}

function valuePlaceholder(definition: FilterDefinition): string {
  if (definition.placeholder) {
    return `Enter ${definition.placeholder}`;
  }
  const label = definition.label ?? definition.chipLabel ?? definition.key;
  if (definition.kind === "datetime") {
    return `Select ${label}`;
  }
  if (definition.kind === "enum") {
    return `Select ${label}`;
  }
  return `Enter ${label}`;
}

function findExactDefinition(definitions: FilterDefinition[], query: string): FilterDefinition | null {
  const normalizedQuery = query.trim().toLowerCase();
  if (normalizedQuery === "") {
    return null;
  }
  return definitions.find((definition) => {
    const label = definition.label?.toLowerCase() ?? "";
    return definition.key.toLowerCase() === normalizedQuery || label === normalizedQuery;
  }) ?? null;
}

function FilterIcon(): React.ReactElement {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d="M1.5 2.5h9L7.5 6v3.5l-3-1V6L1.5 2.5z" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Lightweight explicit-filter builder with inline field suggestions and eq/neq operators. */
export function FilterBar({ definitions, clauses, onChange, fieldPlaceholder, onSuggestValues }: FilterBarProps): React.ReactElement {
  const [draftQuery, setDraftQuery] = useState("");
  const [draftKey, setDraftKey] = useState("");
  const [draftValue, setDraftValue] = useState("");
  const [draftOp, setDraftOp] = useState<FilterClause["op"] | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [valueFocused, setValueFocused] = useState(false);
  const [valueSuggestions, setValueSuggestions] = useState<string[]>([]);
  const inputId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const fieldMenuRef = useRef<HTMLDivElement>(null);
  const valueInputRef = useRef<HTMLInputElement>(null);
  const suggestionsMenuRef = useRef<HTMLDivElement>(null);

  const selectedDefinition = definitions.find((definition) => definition.key === draftKey) ?? null;
  const canAdd = selectedDefinition !== null && draftOp !== null && draftValue.trim() !== "";
  const filteredDefinitions = useMemo(() => {
    if (selectedDefinition) {
      return [];
    }
    const query = draftQuery.trim().toLowerCase();
    if (query === "") {
      return definitions;
    }
    return definitions
      .filter((definition) => {
        const label = definition.label?.toLowerCase() ?? "";
        return definition.key.toLowerCase().includes(query) || label.includes(query);
      })
      .sort((left, right) => {
        const leftStarts = left.key.toLowerCase().startsWith(query) || (left.label?.toLowerCase().startsWith(query) ?? false);
        const rightStarts = right.key.toLowerCase().startsWith(query) || (right.label?.toLowerCase().startsWith(query) ?? false);
        if (leftStarts !== rightStarts) {
          return leftStarts ? -1 : 1;
        }
        return (left.label ?? left.key).localeCompare(right.label ?? right.key);
      });
  }, [definitions, draftQuery, selectedDefinition]);

  useEffect(() => {
    if (!selectedDefinition || selectedDefinition.kind !== "text" || !onSuggestValues || !valueFocused) {
      setValueSuggestions([]);
      return;
    }

    const controller = new AbortController();
    onSuggestValues(selectedDefinition.key, draftValue, controller.signal)
      .then((values) => {
        if (!controller.signal.aborted) {
          setValueSuggestions(values);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setValueSuggestions([]);
        }
      });

    return () => controller.abort();
  }, [draftValue, onSuggestValues, selectedDefinition, valueFocused]);

  function resetDraft(): void {
    setDraftQuery("");
    setDraftKey("");
    setDraftValue("");
    setDraftOp(null);
    setMenuOpen(false);
    setValueFocused(false);
    setValueSuggestions([]);
  }

  function selectDefinition(definition: FilterDefinition): void {
    setDraftKey(definition.key);
    setDraftQuery(definition.key);
    setDraftValue("");
    setDraftOp("eq");
    setMenuOpen(false);
  }

  function addClause(): void {
    if (!selectedDefinition || !draftOp) {
      return;
    }
    const normalizedValue = normalizeClauseValue(selectedDefinition, draftValue);
    if (normalizedValue === "") {
      return;
    }
    const nextClause: FilterClause = { key: selectedDefinition.key, op: draftOp, value: normalizedValue };
    onChange([...clauses.filter((clause) => clause.key !== nextClause.key), nextClause]);
    resetDraft();
  }

  function removeClause(key: string): void {
    onChange(clauses.filter((clause) => clause.key !== key));
  }

  const labels = selectedDefinition ? resolveOperatorLabels(selectedDefinition) : DEFAULT_OPERATOR_LABELS;

  const supportsNot = selectedDefinition?.supportsNot !== false;

  function renderConditionCreator(): React.ReactNode {
    if (!selectedDefinition) return null;

    const valueInput = selectedDefinition.kind === "enum" ? (
      <select
        className="explorer__select filter-builder__value"
        value={draftValue}
        onChange={(event) => setDraftValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") { event.preventDefault(); addClause(); }
          if (event.key === "Backspace" && draftValue === "") resetDraft();
        }}
        aria-label={`${selectedDefinition.key} value`}
      >
        <option value="">Select value</option>
        {selectedDefinition.options?.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    ) : (
      <input
        ref={valueInputRef}
        className="explorer__input filter-builder__value"
        type={selectedDefinition.kind === "number" ? "number" : selectedDefinition.kind === "datetime" ? "datetime-local" : "text"}
        value={draftValue}
        min={selectedDefinition.kind === "number" ? 0 : undefined}
        step={selectedDefinition.kind === "number" ? selectedDefinition.step ?? "any" : undefined}
        onChange={(event) => setDraftValue(nextDraftValue(selectedDefinition, event.target.value, draftValue))}
        onFocus={() => setValueFocused(true)}
        onBlur={() => { window.setTimeout(() => setValueFocused(false), 100); }}
        onKeyDown={(event) => {
          if (selectedDefinition.kind === "number" && (event.key === "-" || (selectedDefinition.step === 1 && event.key === "."))) {
            event.preventDefault();
            return;
          }
          if (event.key === "ArrowDown" && valueSuggestions.length > 0) {
            event.preventDefault();
            suggestionsMenuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
            return;
          }
          if (event.key === "Escape" && valueSuggestions.length > 0) {
            setValueFocused(false);
            return;
          }
          if (event.key === "Enter") { event.preventDefault(); addClause(); }
          if (event.key === "Backspace" && draftValue === "") resetDraft();
        }}
        placeholder={valuePlaceholder(selectedDefinition)}
        aria-label={`${selectedDefinition.key} value`}
      />
    );

    return (
      <div className="filter-builder__composer filter-builder__composer--selected">
        <span className="filter-builder__token">{selectedDefinition.label ?? selectedDefinition.key}</span>
        <div
          className="filter-builder__operators"
          role="radiogroup"
          aria-label="Filter operator"
          onKeyDown={(event) => {
            if (!supportsNot) return;
            if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
              event.preventDefault();
              const next = draftOp === "eq" ? "neq" : "eq";
              setDraftOp(next);
              const btn = event.currentTarget.querySelector<HTMLElement>(`[aria-checked="false"]`);
              btn?.focus();
            }
          }}
        >
          <button
            className={`filter-builder__operator${draftOp === "eq" ? " filter-builder__operator--active" : ""}`}
            onClick={() => setDraftOp("eq")}
            type="button"
            role="radio"
            aria-checked={draftOp === "eq"}
            aria-label={labels.eq}
            tabIndex={draftOp === "eq" ? 0 : -1}
          >
            {labels.eq}
          </button>
          {supportsNot ? (
            <button
              className={`filter-builder__operator${draftOp === "neq" ? " filter-builder__operator--active" : ""}`}
              onClick={() => setDraftOp("neq")}
              type="button"
              role="radio"
              aria-checked={draftOp === "neq"}
              aria-label={labels.neq}
              tabIndex={draftOp === "neq" ? 0 : -1}
            >
              {labels.neq}
            </button>
          ) : null}
        </div>
        <div className="filter-builder__value-wrapper">
          {valueInput}
          {valueFocused && valueSuggestions.length > 0 ? (
            <div
              ref={suggestionsMenuRef}
              className="filter-builder__menu"
              role="menu"
              aria-label={`${selectedDefinition.key} suggestions`}
              onKeyDown={(e) => {
                const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
                const idx = items.indexOf(document.activeElement as HTMLElement);
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  items[(idx + 1) % items.length]?.focus();
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  if (idx <= 0) valueInputRef.current?.focus();
                  else items[idx - 1]?.focus();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  setValueFocused(false);
                  valueInputRef.current?.focus();
                }
              }}
            >
              <div className="filter-builder__menu-section">Suggested Values</div>
              {valueSuggestions.slice(0, 10).map((value) => (
                <button
                  key={value}
                  className="filter-builder__menu-item"
                  role="menuitem"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    setDraftValue(value);
                    setValueFocused(false);
                  }}
                  onClick={() => {
                    setDraftValue(value);
                    setValueFocused(false);
                    valueInputRef.current?.focus();
                  }}
                  type="button"
                >
                  <span className="filter-builder__menu-key">{value}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <button
          className="filter-builder__apply"
          onClick={addClause}
          type="button"
          disabled={!canAdd}
          aria-label="Apply filter"
        >
          Apply
        </button>
        <button
          className="filter-builder__clear"
          onClick={resetDraft}
          type="button"
          aria-label="Reset filter draft"
        >
          ×
        </button>
      </div>
    );
  }

  return (
    <div className="filter-builder">
      {selectedDefinition ? renderConditionCreator() : (
        <div className="filter-builder__trigger-wrapper">
          <button
            ref={triggerRef}
            id={inputId}
            className="filter-builder__trigger"
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            onBlur={(e) => {
              const next = e.relatedTarget as Element | null;
              if (next && e.currentTarget.parentElement?.contains(next)) return;
              window.setTimeout(() => setMenuOpen(false), 150);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                if (!menuOpen) setMenuOpen(true);
                window.requestAnimationFrame(() => {
                  fieldMenuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
                });
              } else if (e.key === "Escape") {
                setMenuOpen(false);
              }
            }}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label={fieldPlaceholder ?? "Add filter"}
          >
            <FilterIcon />
            {fieldPlaceholder ?? "Add filter"}
          </button>
          {menuOpen && filteredDefinitions.length > 0 ? (
            <div
              ref={fieldMenuRef}
              className="filter-builder__menu"
              role="menu"
              aria-labelledby={inputId}
              onKeyDown={(e) => {
                const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
                const idx = items.indexOf(document.activeElement as HTMLElement);
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  items[(idx + 1) % items.length]?.focus();
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  if (idx <= 0) triggerRef.current?.focus();
                  else items[idx - 1]?.focus();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  setMenuOpen(false);
                  triggerRef.current?.focus();
                }
              }}
            >
              <div className="filter-builder__menu-section">Indexed Tags</div>
              {filteredDefinitions.slice(0, 10).map((definition) => (
                <button
                  key={definition.key}
                  className="filter-builder__menu-item"
                  role="menuitem"
                  onMouseDown={(event) => { event.preventDefault(); selectDefinition(definition); }}
                  onClick={() => selectDefinition(definition)}
                  type="button"
                >
                  <span className="filter-builder__menu-key">{definition.label ?? definition.key}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      )}

      {clauses.map((clause) => {
        const definition = definitions.find((candidate) => candidate.key === clause.key);
        return (
          <button
            key={clause.key}
            className="filter-builder__chip"
            onClick={() => removeClause(clause.key)}
            type="button"
            aria-label={`Remove filter ${clause.key}`}
            title="Remove filter"
          >
            <span>{chipText(definition, clause)}</span>
            <span className="filter-builder__chip-remove" aria-hidden="true">×</span>
          </button>
        );
      })}
    </div>
  );
}
