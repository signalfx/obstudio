import React from "react";
import { useOtlpEndpoint } from "../hooks/useOtlpEndpoint";
import { CopyTextButton } from "../layout";

/** One column of the placeholder table drawn behind an empty data tab. */
export interface EmptyStateColumn {
  label: string;
  /** Column modifiers, e.g. `service` becomes `data-table__th--service` on the
   *  header and `data-table__td--service` on each cell, so the real table's
   *  column widths and narrow-viewport rules carry over. */
  modifiers?: string[];
  /** Extra class for both the header and the cells. */
  className?: string;
}

function columnClass(base: "data-table__th" | "data-table__td", column: EmptyStateColumn): string {
  return [base, ...(column.modifiers ?? []).map((m) => `${base}--${m}`), column.className]
    .filter(Boolean)
    .join(" ");
}

export interface EmptyStateSkeleton {
  columns: EmptyStateColumn[];
  /** Class of the header row, e.g. `data-table__head data-table__head--traces`. */
  headClassName: string;
  /** Class of each placeholder row, e.g. `data-table__row data-table__row--traces`. */
  rowClassName: string;
  /** Class of the element wrapping the header and rows, for grid-based tables. */
  tableClassName?: string;
}

interface EmptyStateProps {
  title: string;
  hint: React.ReactNode;
  /** Next steps shown under the hint, e.g. a primary button or a copyable command. */
  actions?: React.ReactNode;
  /** Draws the table's structure behind the message instead of a blank page. */
  skeleton?: EmptyStateSkeleton;
  /** `card` sits inline with other content instead of filling the view. */
  variant?: "page" | "card";
}

const SKELETON_ROW_COUNT = 8;

export function EmptyState({ title, hint, actions, skeleton, variant = "page" }: EmptyStateProps): React.ReactElement {
  const message = (
    <div className="empty-state__message">
      <p className="empty-state__title">{title}</p>
      <p className="empty-state__hint">{hint}</p>
      {actions ? <div className="empty-state__actions">{actions}</div> : null}
    </div>
  );

  if (variant === "card") {
    return <section className="empty-state-card" aria-label={title}>{message}</section>;
  }

  if (!skeleton) {
    return <div className="explorer__status explorer__status--empty">{message}</div>;
  }

  return (
    <div className="empty-state empty-state--skeleton">
      {/* Decorative: the column names are visible structure, the message
          carries the meaning, so assistive tech only reads the message. */}
      <div className={`empty-state__skeleton ${skeleton.tableClassName ?? ""}`} aria-hidden="true">
        <div className={skeleton.headClassName}>
          {skeleton.columns.map((column) => (
            <span key={column.label} className={columnClass("data-table__th", column)}>{column.label}</span>
          ))}
        </div>
        {Array.from({ length: SKELETON_ROW_COUNT }, (_, row) => (
          <div key={row} className={`${skeleton.rowClassName} empty-state__skeleton-row`}>
            {skeleton.columns.map((column, col) => (
              <span key={column.label} className={columnClass("data-table__td", column)}>
                <span className={`empty-state__bar empty-state__bar--${(row + col) % 3}`} />
              </span>
            ))}
          </div>
        ))}
      </div>
      <div className="empty-state__overlay">{message}</div>
    </div>
  );
}

const OTEL_INSTRUMENT_COMMAND = "$otel-instrument";

/** Copyable command with the shared command-chip styling. */
export function CommandChip({ text, label }: { text: string; label: string }): React.ReactElement {
  // `NAME=value` wraps after the `=` in narrow panels rather than mid-value.
  const split = text.indexOf("=") + 1;
  return (
    <span className="command-chip empty-state__command">
      <code className="overview-checklist__command">
        {split > 0 ? <>{text.slice(0, split)}<wbr />{text.slice(split)}</> : text}
      </code>
      <CopyTextButton text={text} label={label} />
    </span>
  );
}

/**
 * Next steps for sending telemetry: the real OTLP/HTTP receiver from
 * /api/health as an exporter environment variable, plus the skill that
 * instruments the app. The port is never hardcoded because obstudio can
 * listen elsewhere (`OTLP_HTTP_PORT`).
 */
export function useSendTelemetryHelp(includeSkill = true): { hint: string; actions: React.ReactElement } {
  const endpoint = useOtlpEndpoint();
  const hint = endpoint
    ? `Point your app's OTLP exporter at ${endpoint}, or ask your coding agent to instrument it.`
    : "Point your app's OTLP exporter at this collector's OTLP/HTTP endpoint, or ask your coding agent to instrument it.";
  const actions = (
    <>
      {endpoint ? (
        <CommandChip
          text={`OTEL_EXPORTER_OTLP_ENDPOINT=${endpoint}`}
          label="OTLP endpoint environment variable"
        />
      ) : null}
      {includeSkill ? (
        <CommandChip text={OTEL_INSTRUMENT_COMMAND} label={`${OTEL_INSTRUMENT_COMMAND} command`} />
      ) : null}
    </>
  );
  return { hint, actions };
}

interface TelemetryEmptyStateProps {
  title: string;
  skeleton?: EmptyStateSkeleton;
  variant?: EmptyStateProps["variant"];
  /** Off where the view already lists the instrumentation skill, e.g. Overview. */
  includeSkill?: boolean;
}

/** Empty state for a view that has received no telemetry yet. */
export function TelemetryEmptyState({ title, skeleton, variant, includeSkill }: TelemetryEmptyStateProps): React.ReactElement {
  const { hint, actions } = useSendTelemetryHelp(includeSkill);
  return <EmptyState title={title} hint={hint} actions={actions} skeleton={skeleton} variant={variant} />;
}
