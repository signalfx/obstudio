import { useCallback, useEffect, useRef, useState } from "react";
import type { TraceSummary, MetricGroup, LogRecord, Stats } from "../api/types";

/** Snapshot of all telemetry signals received from the server. */
export interface TelemetryState {
  error: string | null;
  traces: TraceSummary[];
  metrics: MetricGroup[];
  logs: LogRecord[];
  stats: Stats | null;
}

/** Controls returned by {@link useTelemetry} for reading and managing live telemetry. */
export interface TelemetryHandle {
  /** Current telemetry snapshot. */
  state: TelemetryState;
  /** Whether the WebSocket stream is paused. */
  paused: boolean;
  /** True when updates arrived while paused. */
  hasNewUpdates: boolean;
  /** Pause the live stream; updates are buffered until resumed. */
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
};

const RECONNECT_MS = 1000;

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
        // Clear stale state on reconnect so the UI refreshes immediately.
        setTelemetry(emptyState);
        bufferRef.current = null;
        setHasNewUpdates(false);
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
        setTelemetry({ ...emptyState, error: "Disconnected. Reconnecting..." });
        bufferRef.current = null;
        reconnectTimer = setTimeout(connect, RECONNECT_MS);
      };
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
          default:
            return current;
        }
      };

      if (pausedRef.current) {
        const base = bufferRef.current ?? telemetryRef.current;
        bufferRef.current = apply(base);
        setHasNewUpdates(true);
      } else {
        setTelemetry(apply);
      }
    }

    connect();

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
