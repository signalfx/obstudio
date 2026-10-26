import { useCallback, useEffect, useRef, useState } from "react";
import { fetchConfigSchema, fetchConfigValues, putConfigValue } from "../api/client";
import type { ConfigKeySpec } from "../api/types";
import { type DraftValue, lookupValue, parseDraft, toDraft } from "./model";

export const AUTOSAVE_DEBOUNCE_MS = 500;
const SAVED_INDICATOR_MS = 1500;

export type FieldStatus = "idle" | "saving" | "saved" | "error";
export type ConfigLoadState = "loading" | "ready" | "error";

export interface FieldState {
  draft: DraftValue;
  status: FieldStatus;
  error: string | null;
}

// Per-key bookkeeping that must not trigger renders.
interface Controller {
  spec: ConfigKeySpec;
  /** Last value the server confirmed. */
  saved: unknown;
  /** Latest value shown in the control. */
  draft: DraftValue;
  /** Bumped by every user edit and reset, so a late response can tell whether it is stale. */
  generation: number;
  timer: ReturnType<typeof setTimeout> | null;
  savedTimer: ReturnType<typeof setTimeout> | null;
  inFlight: boolean;
  /** Newest value waiting for the in-flight request to finish; only the latest is kept. */
  queued: { value: unknown; generation: number } | null;
}

export interface UseConfig {
  loadState: ConfigLoadState;
  loadError: string | null;
  specs: ConfigKeySpec[];
  fields: Record<string, FieldState>;
  retry: () => void;
  /** Update a control. Discrete controls pass `immediate`; typed ones are debounced. */
  edit: (key: string, draft: DraftValue, immediate?: boolean) => void;
  /** Save a debounced edit now (on blur or Enter). */
  flush: (key: string) => void;
  /** Drop a failed edit and show the last saved value again. */
  reset: (key: string) => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message !== "" ? error.message : "Could not save this setting.";
}

/**
 * Loads the config schema and values, and autosaves each field independently:
 * one PUT per key, debounced for typed input, one request in flight per key, and
 * only the newest pending value is sent after it.
 */
export function useConfig(): UseConfig {
  const [loadState, setLoadState] = useState<ConfigLoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [specs, setSpecs] = useState<ConfigKeySpec[]>([]);
  const [fields, setFields] = useState<Record<string, FieldState>>({});
  const [attempt, setAttempt] = useState(0);
  const controllers = useRef(new Map<string, Controller>());
  const mounted = useRef(true);

  const patchField = useCallback((key: string, patch: Partial<FieldState> | ((current: FieldState) => FieldState)) => {
    if (!mounted.current) return;
    setFields((previous) => {
      const current = previous[key];
      if (current === undefined) return previous;
      const next = typeof patch === "function" ? patch(current) : { ...current, ...patch };
      return next === current ? previous : { ...previous, [key]: next };
    });
  }, []);

  const send = useCallback((key: string, value: unknown, generation: number) => {
    const controller = controllers.current.get(key);
    if (controller === undefined) return;
    controller.inFlight = true;
    // A request for an edit the user has since replaced must not clear the newer edit's error.
    if (generation === controller.generation) patchField(key, { error: null, status: "saving" });

    putConfigValue(key, value).then(
      (stored) => {
        controller.inFlight = false;
        controller.saved = stored;
        const queued = controller.queued;
        controller.queued = null;
        if (queued !== null) {
          send(key, queued.value, queued.generation);
          return;
        }
        if (controller.generation === generation) {
          controller.draft = toDraft(controller.spec, stored);
          patchField(key, { draft: controller.draft, error: null, status: "saved" });
          if (controller.savedTimer !== null) clearTimeout(controller.savedTimer);
          controller.savedTimer = setTimeout(() => {
            controller.savedTimer = null;
            patchField(key, (current) => (current.status === "saved" ? { ...current, status: "idle" } : current));
          }, SAVED_INDICATOR_MS);
        } else {
          // A newer edit is still debouncing; leave its text alone.
          patchField(key, (current) => (current.status === "saving" ? { ...current, status: "idle" } : current));
        }
      },
      (error: unknown) => {
        controller.inFlight = false;
        const queued = controller.queued;
        controller.queued = null;
        if (queued !== null) {
          send(key, queued.value, queued.generation);
          return;
        }
        if (controller.generation === generation) {
          patchField(key, { error: errorMessage(error), status: "error" });
        } else {
          patchField(key, (current) => (current.status === "saving" ? { ...current, status: "idle" } : current));
        }
      },
    );
  }, [patchField]);

  const commit = useCallback((key: string) => {
    const controller = controllers.current.get(key);
    if (controller === undefined) return;
    const result = parseDraft(controller.spec, controller.draft);
    if (!result.ok) {
      patchField(key, { error: result.error, status: "error" });
      return;
    }
    if (controller.inFlight) {
      controller.queued = { generation: controller.generation, value: result.value };
      patchField(key, { error: null, status: "saving" });
      return;
    }
    if (result.value === controller.saved) {
      patchField(key, { error: null, status: "idle" });
      return;
    }
    send(key, result.value, controller.generation);
  }, [patchField, send]);

  const edit = useCallback((key: string, draft: DraftValue, immediate = false) => {
    const controller = controllers.current.get(key);
    if (controller === undefined) return;
    controller.generation += 1;
    controller.draft = draft;
    if (controller.timer !== null) clearTimeout(controller.timer);
    controller.timer = null;
    if (controller.savedTimer !== null) clearTimeout(controller.savedTimer);
    controller.savedTimer = null;
    patchField(key, { draft, error: null, status: controller.inFlight ? "saving" : "idle" });
    if (immediate) {
      commit(key);
    } else {
      controller.timer = setTimeout(() => {
        controller.timer = null;
        commit(key);
      }, AUTOSAVE_DEBOUNCE_MS);
    }
  }, [commit, patchField]);

  const flush = useCallback((key: string) => {
    const controller = controllers.current.get(key);
    if (controller === undefined || controller.timer === null) return;
    clearTimeout(controller.timer);
    controller.timer = null;
    commit(key);
  }, [commit]);

  const reset = useCallback((key: string) => {
    const controller = controllers.current.get(key);
    if (controller === undefined || controller.inFlight) return;
    if (controller.timer !== null) clearTimeout(controller.timer);
    controller.timer = null;
    controller.generation += 1;
    controller.queued = null;
    controller.draft = toDraft(controller.spec, controller.saved);
    patchField(key, { draft: controller.draft, error: null, status: "idle" });
  }, [patchField]);

  const retry = useCallback(() => setAttempt((count) => count + 1), []);

  useEffect(() => {
    const abort = new AbortController();
    setLoadState("loading");
    setLoadError(null);
    Promise.all([fetchConfigSchema(abort.signal), fetchConfigValues(abort.signal)]).then(
      ([schema, values]) => {
        if (abort.signal.aborted) return;
        for (const controller of controllers.current.values()) {
          if (controller.timer !== null) clearTimeout(controller.timer);
          if (controller.savedTimer !== null) clearTimeout(controller.savedTimer);
        }
        controllers.current = new Map();
        const initial: Record<string, FieldState> = {};
        for (const spec of schema) {
          const saved = lookupValue(values, spec.key);
          const draft = toDraft(spec, saved);
          controllers.current.set(spec.key, {
            draft,
            generation: 0,
            inFlight: false,
            queued: null,
            saved,
            savedTimer: null,
            spec,
            timer: null,
          });
          initial[spec.key] = { draft, error: null, status: "idle" };
        }
        setSpecs(schema);
        setFields(initial);
        setLoadState("ready");
      },
      (error: unknown) => {
        if (abort.signal.aborted) return;
        setLoadError(error instanceof Error && error.message !== "" ? error.message : "Could not load the configuration.");
        setLoadState("error");
      },
    );
    return () => abort.abort();
  }, [attempt]);

  // Leaving the tab must not drop an edit that is still debouncing.
  useEffect(() => {
    mounted.current = true;
    const map = controllers;
    return () => {
      mounted.current = false;
      for (const [key, controller] of map.current) {
        if (controller.savedTimer !== null) clearTimeout(controller.savedTimer);
        controller.savedTimer = null;
        if (controller.timer !== null) {
          clearTimeout(controller.timer);
          controller.timer = null;
          commit(key);
        }
      }
    };
  }, [commit]);

  return { edit, fields, flush, loadError, loadState, reset, retry, specs };
}
