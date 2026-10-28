import { useEffect, useState } from "react";
import { observerFetch } from "../host/transport";
import { onConfigRefresh } from "../telemetry/configSignal";

/** One problem the observer found in the config file. */
export interface ConfigStatusDiagnostic {
  /** 1-based line in the file; 0 when the entry is absent. */
  line: number;
  message: string;
}

/** The observer's report on the config file, as the webview shows it. */
export interface ConfigStatus {
  /** The observer's state name; shown nowhere and not interpreted here. */
  state: string;
  /** True when what the file says is not in force. */
  problem: boolean;
  message: string;
  diagnostics: readonly ConfigStatusDiagnostic[];
}

export const CONFIG_PROBLEM_PILL_TEXT = "Config problem";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Reads a config status body; null unless every field the webview uses is well-formed. */
export function parseConfigStatus(body: unknown): ConfigStatus | null {
  if (!isRecord(body)) return null;
  const { state, problem, message, diagnostics } = body;
  if (typeof state !== "string" || typeof problem !== "boolean" || typeof message !== "string" || !Array.isArray(diagnostics)) {
    return null;
  }
  const out: ConfigStatusDiagnostic[] = [];
  for (const d of diagnostics) {
    if (!isRecord(d) || typeof d.line !== "number" || !Number.isInteger(d.line) || d.line < 0 || typeof d.message !== "string") {
      return null;
    }
    out.push({ line: d.line, message: d.message });
  }
  return { state, problem, message, diagnostics: out };
}

async function fetchConfigStatus(): Promise<ConfigStatus | null> {
  try {
    const response = await observerFetch("/api/config/status");
    if (!response.ok) return null;
    return parseConfigStatus(await response.json());
  } catch {
    return null;
  }
}

/**
 * The current config status: read on mount and on every config refresh
 * notice, with only the latest request applied. Null until the first answer,
 * and whenever the answer is not a usable status.
 */
export function useConfigStatus(): ConfigStatus | null {
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  useEffect(() => {
    let latest = 0;
    let disposed = false;
    const load = (): void => {
      const id = ++latest;
      void fetchConfigStatus().then((next) => {
        if (!disposed && id === latest) setStatus(next);
      });
    };
    load();
    const unsubscribe = onConfigRefresh(load);
    return () => {
      disposed = true;
      unsubscribe();
    };
  }, []);
  return status;
}
