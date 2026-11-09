import React, { useEffect, useState } from "react";
import { observerFetch } from "../host/transport";
import { CopyTextButton } from "../layout";

export interface EmptyStateSkeleton {
  headClassName: string;
  rowClassName: string;
  /** Wraps the head and rows, for grid tables like Services. */
  tableClassName?: string;
  /** Header classes, e.g. `data-table__th--service`. Cells get the `__td` version. */
  columns: Array<{ label: string; className?: string }>;
}

interface EmptyStateProps {
  title: string;
  hint: React.ReactNode;
  actions?: React.ReactNode;
  /** Shows the table's columns behind the message. */
  skeleton?: EmptyStateSkeleton;
  /** `card` sits inline with other content instead of filling the view. */
  variant?: "page" | "card";
}

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
      <div className={`empty-state__skeleton ${skeleton.tableClassName ?? ""}`} aria-hidden="true">
        <div className={skeleton.headClassName}>
          {skeleton.columns.map((c) => (
            <span key={c.label} className={`data-table__th ${c.className ?? ""}`}>{c.label}</span>
          ))}
        </div>
        {Array.from({ length: 8 }, (_, row) => (
          <div key={row} className={skeleton.rowClassName}>
            {skeleton.columns.map((c) => (
              <span key={c.label} className={`data-table__td ${c.className?.replaceAll("__th", "__td") ?? ""}`}>
                <span className="empty-state__bar" />
              </span>
            ))}
          </div>
        ))}
      </div>
      <div className="empty-state__overlay">{message}</div>
    </div>
  );
}

export function CommandChip({ text, label }: { text: string; label: string }): React.ReactElement {
  // Long `NAME=value` commands wrap after the `=`.
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

/** The OTLP/HTTP receiver from /api/health, or null until it loads or if it fails. */
export function useOtlpEndpoint(): string | null {
  const [endpoint, setEndpoint] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    observerFetch("/api/health", { signal: controller.signal })
      .then((r) => (r.ok ? (r.json() as Promise<{ endpoints?: { otlpHttp?: string } }>) : null))
      .then((health) => {
        const otlpHttp = health?.endpoints?.otlpHttp?.trim();
        if (otlpHttp) setEndpoint(otlpHttp);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return endpoint;
}

interface TelemetryEmptyStateProps {
  title: string;
  skeleton?: EmptyStateSkeleton;
  variant?: EmptyStateProps["variant"];
  /** Overview already lists $otel-instrument, so it turns this off. */
  includeSkill?: boolean;
}

/** Empty state for when no telemetry has arrived, with how to send some. */
export function TelemetryEmptyState({ title, skeleton, variant, includeSkill = true }: TelemetryEmptyStateProps): React.ReactElement {
  const endpoint = useOtlpEndpoint();
  const target = endpoint ?? "this collector's OTLP/HTTP endpoint";
  const actions = (
    <>
      {endpoint ? (
        <CommandChip text={`OTEL_EXPORTER_OTLP_ENDPOINT=${endpoint}`} label="OTLP endpoint environment variable" />
      ) : null}
      {includeSkill ? <CommandChip text="$otel-instrument" label="$otel-instrument command" /> : null}
    </>
  );
  return (
    <EmptyState
      title={title}
      hint={`Point your app's OTLP exporter at ${target}, or ask your coding agent to instrument it.`}
      actions={actions}
      skeleton={skeleton}
      variant={variant}
    />
  );
}
