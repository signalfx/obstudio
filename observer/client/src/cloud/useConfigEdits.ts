import { useCallback, useEffect, useRef, useState } from "react";
import { observerFetch } from "../host/transport";
import { onConfigRefresh } from "../telemetry/configSignal";
import { createConfigEdits, type ConfigEdits, type ConfigEditsState, type FieldKind, type FieldValue } from "./configEdits";

export interface UseConfigEditsOptions {
  /** Runs at the start of every value refresh, before GET /api/config is sent. */
  onRefresh?: () => void;
}

/** How the latest settled send carrying a path ended. `seq` grows with every settlement. */
export interface SendOutcome {
  ok: boolean;
  seq: number;
}

export interface UseConfigEdits {
  /** The instance's latest state, or null before it reports one. */
  state: ConfigEditsState | null;
  /** Per path, the outcome of the latest send that carried it and has settled. */
  outcomes: Readonly<Record<string, SendOutcome>>;
  edit(path: string, value: FieldValue): void;
  refresh(): void;
}

/** What to show for a failed send: the server's message, or a generic one. */
export function saveErrorText(error: NonNullable<ConfigEditsState["error"]>): string {
  if (error.message) return error.message;
  if (error.status !== undefined) return `This setting could not be saved (HTTP ${error.status}).`;
  return "This setting could not be saved.";
}

/**
 * Owns one configEdits instance for the given fields, wired to the observer's
 * /api/config endpoints. It refreshes on mount and on every config signal,
 * and disposes (flushing pending edits) on unmount or when the fields change.
 * Pass null while the fields are not known yet.
 */
export function useConfigEdits(
  fields: Readonly<Record<string, FieldKind>> | null,
  options: UseConfigEditsOptions = {},
): UseConfigEdits {
  const [state, setState] = useState<ConfigEditsState | null>(null);
  const [outcomes, setOutcomes] = useState<Readonly<Record<string, SendOutcome>>>({});
  const editsRef = useRef<ConfigEdits | null>(null);
  const onRefreshRef = useRef(options.onRefresh);
  onRefreshRef.current = options.onRefresh;
  const fieldsKey = fields === null ? null : JSON.stringify(fields);

  useEffect(() => {
    if (fieldsKey === null) return undefined;
    let active = true;
    // Outcomes are derived from every state the instance reports, not from
    // rendered states: a send can start and settle within one render batch.
    let previous: ConfigEditsState | null = null;
    let settled: Record<string, SendOutcome> = {};
    let seq = 0;
    const edits = createConfigEdits(JSON.parse(fieldsKey) as Record<string, FieldKind>, {
      fetchConfig: () => {
        onRefreshRef.current?.();
        return observerFetch("/api/config");
      },
      postConfig: (body) => observerFetch("/api/config", {
        body,
        headers: { "Content-Type": "application/json", "X-Obstudio-Browser-Request": "1" },
        method: "POST",
      }),
      onChange: (next) => {
        if (!active) return;
        const before = previous;
        previous = next;
        const done = before === null ? [] : [...before.inFlight].filter((path) => !next.inFlight.has(path));
        if (done.length > 0) {
          const ok = !(next.error !== null && next.error !== before?.error);
          seq += 1;
          settled = { ...settled };
          for (const path of done) settled[path] = { ok, seq };
          setOutcomes(settled);
        }
        setState(next);
      },
    });
    editsRef.current = edits;
    const unsubscribe = onConfigRefresh(() => edits.refresh());
    edits.refresh();

    return () => {
      active = false;
      unsubscribe();
      edits.dispose();
      editsRef.current = null;
      setState(null);
      setOutcomes({});
    };
  }, [fieldsKey]);

  const edit = useCallback((path: string, value: FieldValue) => editsRef.current?.edit(path, value), []);
  const refresh = useCallback(() => editsRef.current?.refresh(), []);
  return { edit, outcomes, refresh, state };
}
