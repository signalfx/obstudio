import { useCallback, useEffect, useRef, useState } from "react";
import type { TraceSummary, MetricGroup, LogRecord, Stats, ValidationSnapshot } from "../api/types";

/** Snapshot of all telemetry signals received from the server. */
export interface TelemetryState {
  error: string | null;
  traces: TraceSummary[];
  metrics: MetricGroup[];
  logs: LogRecord[];
  stats: Stats | null;
  validation: ValidationSnapshot | null;
}

/** Controls returned by {@link useTelemetry} for reading and managing live telemetry. */
export interface TelemetryHandle {
  /** Current telemetry snapshot. */
  state: TelemetryState;
  /** Whether live telemetry updates are paused. Validation stays live. */
  paused: boolean;
  /** True when updates arrived while paused. */
  hasNewUpdates: boolean;
  /** Pause live telemetry updates; traces, metrics, logs, and stats are buffered until resumed. */
  pause: () => void;
  /** Resume the live stream and apply any buffered updates. */
  resume: () => void;
  /** Toggle between paused and live. */
  toggle: () => void;
  /** Apply buffered updates without resuming the stream. */
  flush: () => void;
}

interface ServerMessage {
  type: "connected" | "update" | "paused-update";
  signal?: string;
  data?: unknown;
}

const emptyState: TelemetryState = {
  error: null,
  traces: [],
  metrics: [],
  logs: [],
  stats: null,
  validation: null,
};

const RECONNECT_MS = 1000;

async function fetchJSON<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function fetchValidationSnapshot(): Promise<ValidationSnapshot | null> {
  try {
    const summary = await fetchJSON<ValidationSnapshot["summary"]>("/api/query/validation/summary");
    if (!summary.hasResult) {
      return { summary, findings: [], issues: [] };
    }
    try {
      return await fetchJSON<ValidationSnapshot>("/api/query/validation/latest");
    } catch {
      return { summary, findings: [], issues: [] };
    }
  } catch {
    return null;
  }
}

function normalizeValidationSnapshot(validation: ValidationSnapshot | null): ValidationSnapshot | null {
  if (!validation) {
    return null;
  }

  return {
    summary: {
      ...validation.summary,
      severityCounts: validation.summary?.severityCounts ?? {},
      highestSeverityCounts: validation.summary?.highestSeverityCounts ?? {},
      signalCounts: validation.summary?.signalCounts ?? {},
    },
    findings: validation.findings ?? [],
    issues: (validation.issues ?? []).map((issue) => ({
      ...issue,
      targetLabel: issue.targetLabel ?? "",
      serviceName: issue.serviceName ?? "",
      scopeName: issue.scopeName ?? "",
      count: issue.count ?? 0,
      violationCount: issue.violationCount ?? countIssueSeverity(issue.findings ?? [], "violation"),
      improvementCount: issue.improvementCount ?? countIssueSeverity(issue.findings ?? [], "improvement"),
      informationCount: issue.informationCount ?? countIssueSeverity(issue.findings ?? [], "information"),
      affectedEntityCount: issue.affectedEntityCount ?? 0,
      firstSeen: issue.firstSeen ?? "",
      lastSeen: issue.lastSeen ?? "",
      findings: issue.findings ?? [],
    })),
  };
}

function countIssueSeverity(findings: ValidationSnapshot["findings"], severity: "violation" | "improvement" | "information"): number {
  let count = 0;
  for (const finding of findings) {
    if (finding.severity === severity) {
      count += 1;
    }
  }
  return count;
}

function mergeValidationSnapshot(
  current: ValidationSnapshot | null,
  incoming: ValidationSnapshot | null,
): ValidationSnapshot | null {
  const normalized = normalizeValidationSnapshot(incoming);
  if (!normalized) {
    return null;
  }
  if (!current) {
    return normalized;
  }

  const currentRunID = current.summary.resultRunId ?? "";
  const nextRunID = normalized.summary.resultRunId ?? "";
  const preservePinnedResult = current.summary.hasResult
    && normalized.summary.hasResult
    && currentRunID !== ""
    && currentRunID === nextRunID;

  if (!preservePinnedResult) {
    return normalized;
  }

  return {
    ...normalized,
    findings: current.findings,
    issues: current.issues,
  };
}

async function fetchInitialTelemetryState(): Promise<TelemetryState> {
  const [tracesResult, metricsResult, logsResult, statsResult, validation] = await Promise.all([
    fetchJSON<TraceSummary[]>("/api/query/traces").catch(() => []),
    fetchJSON<MetricGroup[]>("/api/query/metrics").catch(() => []),
    fetchJSON<LogRecord[]>("/api/query/logs").catch(() => []),
    fetchJSON<Stats | null>("/api/query/stats").catch(() => null),
    fetchValidationSnapshot(),
  ]);

  return {
    error: null,
    traces: tracesResult ?? [],
    metrics: metricsResult ?? [],
    logs: logsResult ?? [],
    stats: statsResult ? { ...statsResult, serviceNames: statsResult.serviceNames ?? [] } : null,
    validation: normalizeValidationSnapshot(validation),
  };
}

/**
 * Manages a WebSocket connection to the observer backend and exposes
 * live telemetry state with pause/resume controls.
 */
export function useTelemetry(): TelemetryHandle {
  // Note: JSON.parse casts (as ServerMessage, as TraceSummary[], etc.) are safe
  // because the data comes from our own server WebSocket connection (trusted boundary)
  const [telemetry, setTelemetry] = useState<TelemetryState>(emptyState);
  const [paused, setPaused] = useState(false);
  const [hasNewUpdates, setHasNewUpdates] = useState(false);

  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  const bufferRef = useRef<TelemetryState | null>(null);
  const telemetryRef = useRef(telemetry);
  telemetryRef.current = telemetry;

  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let active = true;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (!active) return;

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/api/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!active) return;
        // Restore the previous stream mode after reconnect.
        ws.send(JSON.stringify({ type: "subscribe" }));
        if (pausedRef.current) {
          setPaused(true);
          ws.send(JSON.stringify({ type: "pause" }));
        }
      };

      ws.onmessage = (event) => {
        if (!active) return;
        let msg: ServerMessage;
        try {
          msg = JSON.parse(event.data) as ServerMessage;
        } catch {
          return;
        }

        if (msg.type === "paused-update") {
          setHasNewUpdates(true);
        } else if (msg.type === "update" && msg.signal && msg.data !== undefined) {
          applyUpdate(msg.signal, msg.data);
        }
      };

      ws.onerror = () => {
        // Will trigger onclose.
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (!active) return;
        setTelemetry((current) => ({ ...current, error: "Disconnected. Reconnecting..." }));
        bufferRef.current = null;
        reconnectTimer = setTimeout(() => {
          void start();
        }, RECONNECT_MS);
      };
    }

    async function start() {
      const snapshot = await fetchInitialTelemetryState();
      if (!active) return;
      setTelemetry(snapshot);
      telemetryRef.current = snapshot;
      bufferRef.current = null;
      setHasNewUpdates(false);
      connect();
    }

    function applyUpdate(signal: string, data: unknown) {
      const apply = (current: TelemetryState): TelemetryState => {
        switch (signal) {
          case "traces":
            return { ...current, error: null, traces: (data as TraceSummary[]) ?? [] };
          case "metrics":
            return { ...current, error: null, metrics: (data as MetricGroup[]) ?? [] };
          case "logs":
            return { ...current, error: null, logs: (data as LogRecord[]) ?? [] };
          case "stats": {
            const s = data as Stats;
            return { ...current, stats: s ? { ...s, serviceNames: s.serviceNames ?? [] } : null };
          }
          case "validation": {
            const validation = mergeValidationSnapshot(current.validation, data as ValidationSnapshot);
            return {
              ...current,
              validation,
            };
          }
          default:
            return current;
        }
      };

      if (pausedRef.current) {
        if (signal === "validation") {
          setTelemetry((current) => {
            const next = apply(current);
            telemetryRef.current = next;
            return next;
          });
          if (bufferRef.current) {
            bufferRef.current = apply(bufferRef.current);
          }
          return;
        }
        const base = bufferRef.current ?? telemetryRef.current;
        bufferRef.current = apply(base);
        setHasNewUpdates(true);
      } else {
        setTelemetry((current) => {
          const next = apply(current);
          telemetryRef.current = next;
          return next;
        });
      }
    }

    void start();

    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      const ws = wsRef.current;
      if (ws) {
        ws.onclose = null; // Prevent reconnect on intentional close.
        ws.close();
      }
      wsRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const flush = useCallback(() => {
    if (bufferRef.current) {
      setTelemetry(bufferRef.current);
      bufferRef.current = null;
    }
    setHasNewUpdates(false);
  }, []);

  const pause = useCallback(() => {
    if (pausedRef.current) return;
    pausedRef.current = true;
    setPaused(true);
    bufferRef.current = null;
    setHasNewUpdates(false);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "pause" }));
    }
  }, []);

  const resume = useCallback(() => {
    pausedRef.current = false;
    setPaused(false);
    if (bufferRef.current) {
      setTelemetry(bufferRef.current);
    }
    bufferRef.current = null;
    setHasNewUpdates(false);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "resume" }));
    }
  }, []);

  const toggle = useCallback(() => {
    if (pausedRef.current) {
      resume();
    } else {
      pause();
    }
  }, [pause, resume]);

  return { state: telemetry, paused, hasNewUpdates, pause, resume, toggle, flush };
}
