// WebSocket handler using Bun's native WebSocket support.
// Protocol matches observer-go/internal/web/websocket.go exactly.

import type { Server, ServerWebSocket } from "bun";
import type { Store } from "../store/store.ts";
import type { Signal } from "../store/types.ts";
import { queryTraces, getTrace, queryMetrics, queryLogs, stats, queryServiceMap } from "../store/query.ts";

const THROTTLE_MS = 100;
const PING_INTERVAL_MS = 30_000;

// --- Filter types matching Go ---

type TraceSubFilters = {
  limit?: number;
  spanPreviewCount?: number;
  serviceName?: string;
  status?: string;
  spanName?: string;
  search?: string;
};

type MetricSubFilters = {
  limit?: number;
  dataPointLimit?: number;
  metricName?: string;
  serviceName?: string;
  type?: string;
  search?: string;
};

type LogSubFilters = {
  limit?: number;
  serviceName?: string;
  severityText?: string;
  body?: string;
  traceId?: string;
};

type ClientMessage = {
  type: "subscribe" | "pause" | "resume";
  signals?: Record<string, unknown>;
};

type ServerMessage = {
  type: "connected" | "update" | "paused-update";
  signal?: string;
  data?: unknown;
};

// --- Per-connection state ---

type ConnData = {
  store: Store;
  paused: boolean;
  traceSub: TraceSubFilters | null;
  metricSub: MetricSubFilters | null;
  logSub: LogSubFilters | null;
  statsSub: boolean;
  serviceMapSub: boolean;
  pending: Record<string, boolean>;
  timers: Record<string, ReturnType<typeof setTimeout>>;
  pingInterval: ReturnType<typeof setInterval> | null;
  // Whether a paused-update notification has already been sent (reset on resume).
  pausedNotified: boolean;
};

// --- Global connection registry ---

const connections = new Set<ServerWebSocket<ConnData>>();

export function broadcastSignal(store: Store, sig: Signal): void {
  for (const ws of connections) {
    onStoreSignal(ws, sig);
  }
}

export function setupStoreSubscription(store: Store): void {
  store.subscribe((sig) => broadcastSignal(store, sig));
}

// --- Bun WebSocket handlers ---

export const websocketHandlers = {
  open(ws: ServerWebSocket<ConnData>) {
    connections.add(ws);
    ws.data.pingInterval = setInterval(() => {
      ws.ping();
    }, PING_INTERVAL_MS);
    sendMsg(ws, { type: "connected" });
  },

  message(ws: ServerWebSocket<ConnData>, message: string | Buffer) {
    const raw = typeof message === "string" ? message : message.toString();
    let msg: ClientMessage;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }

    switch (msg.type) {
      case "subscribe":
        handleSubscribe(ws, msg.signals ?? {});
        break;
      case "pause":
        ws.data.paused = true;
        ws.data.pausedNotified = false;
        break;
      case "resume":
        ws.data.paused = false;
        ws.data.pausedNotified = false;
        pushAll(ws);
        break;
    }
  },

  close(ws: ServerWebSocket<ConnData>) {
    cleanup(ws);
  },
};

function cleanup(ws: ServerWebSocket<ConnData>) {
  connections.delete(ws);
  if (ws.data.pingInterval) clearInterval(ws.data.pingInterval);
  for (const timer of Object.values(ws.data.timers)) {
    clearTimeout(timer);
  }
}

// --- Subscribe ---

function handleSubscribe(ws: ServerWebSocket<ConnData>, signals: Record<string, unknown>) {
  const d = ws.data;
  d.traceSub = null;
  d.metricSub = null;
  d.logSub = null;
  d.statsSub = false;
  d.serviceMapSub = false;

  for (const [sig, raw] of Object.entries(signals)) {
    switch (sig) {
      case "traces": {
        const f = (raw ?? {}) as TraceSubFilters;
        d.traceSub = { limit: f.limit ?? 50, spanPreviewCount: f.spanPreviewCount ?? 8, ...f };
        break;
      }
      case "metrics": {
        const f = (raw ?? {}) as MetricSubFilters;
        d.metricSub = { limit: f.limit ?? 50, dataPointLimit: f.dataPointLimit ?? 5, ...f };
        break;
      }
      case "logs": {
        const f = (raw ?? {}) as LogSubFilters;
        d.logSub = { limit: f.limit ?? 100, ...f };
        break;
      }
      case "stats":
        d.statsSub = true;
        break;
      case "service-map":
        d.serviceMapSub = true;
        break;
    }
  }

  pushAll(ws);
}

// --- Push data ---

function pushAll(ws: ServerWebSocket<ConnData>) {
  const d = ws.data;
  if (d.traceSub) queryAndSend(ws, "traces", d.traceSub);
  if (d.metricSub) queryAndSend(ws, "metrics", d.metricSub);
  if (d.logSub) queryAndSend(ws, "logs", d.logSub);
  if (d.statsSub) queryAndSend(ws, "stats", null);
  if (d.serviceMapSub) queryAndSend(ws, "service-map", null);
}

function queryAndSend(ws: ServerWebSocket<ConnData>, signal: string, filters: unknown) {
  const store = ws.data.store;
  let data: unknown;

  switch (signal) {
    case "traces": {
      const f = filters as TraceSubFilters;
      data = queryTraces(store, {
        serviceName: f.serviceName,
        spanName: f.spanName,
        status: f.status,
        traceIdPrefix: f.search,
        limit: f.limit,
        spanPreviewCount: f.spanPreviewCount,
      });
      break;
    }
    case "metrics": {
      const f = filters as MetricSubFilters;
      data = queryMetrics(store, {
        metricName: f.metricName,
        serviceName: f.serviceName,
        type: f.type,
        limit: f.limit,
        dataPointLimit: f.dataPointLimit,
      });
      break;
    }
    case "logs": {
      const f = filters as LogSubFilters;
      data = queryLogs(store, {
        serviceName: f.serviceName,
        severityText: f.severityText,
        body: f.body,
        traceId: f.traceId,
        limit: f.limit,
      });
      break;
    }
    case "stats":
      data = stats(store);
      break;
    case "service-map":
      data = queryServiceMap(store);
      break;
  }

  sendMsg(ws, { type: "update", signal, data });
}

// --- Store signal → throttled push ---

function onStoreSignal(ws: ServerWebSocket<ConnData>, sig: Signal) {
  const d = ws.data;

  const signals = [sig as string];
  if (d.statsSub) signals.push("stats");
  if (d.serviceMapSub && sig === "traces") signals.push("service-map");

  if (d.paused) {
    // Send a single lightweight notification so the client knows updates are available.
    if (!d.pausedNotified) {
      d.pausedNotified = true;
      sendMsg(ws, { type: "paused-update" });
    }
    return;
  }

  for (const s of signals) {
    throttledPush(ws, s);
  }
}

function throttledPush(ws: ServerWebSocket<ConnData>, signal: string) {
  const d = ws.data;

  // Check subscription.
  let filters: unknown = null;
  switch (signal) {
    case "traces":
      if (!d.traceSub) return;
      filters = { ...d.traceSub };
      break;
    case "metrics":
      if (!d.metricSub) return;
      filters = { ...d.metricSub };
      break;
    case "logs":
      if (!d.logSub) return;
      filters = { ...d.logSub };
      break;
    case "stats":
      if (!d.statsSub) return;
      break;
    case "service-map":
      if (!d.serviceMapSub) return;
      break;
  }

  // Throttle: if timer active, mark pending.
  if (d.timers[signal]) {
    d.pending[signal] = true;
    return;
  }

  // Start cooldown timer.
  d.timers[signal] = setTimeout(() => {
    delete d.timers[signal];
    if (d.pending[signal]) {
      d.pending[signal] = false;
      throttledPush(ws, signal);
    }
  }, THROTTLE_MS);

  queryAndSend(ws, signal, filters);
}

// --- Send ---

function sendMsg(ws: ServerWebSocket<ConnData>, msg: ServerMessage) {
  try {
    ws.sendText(JSON.stringify(msg));
  } catch {
    // Connection closed — remove from broadcast set and clean up timers.
    cleanup(ws);
  }
}

// --- Upgrade helper ---

export function upgradeWebSocket(req: Request, server: Server<ConnData>, store: Store): Response | undefined {
  const data: ConnData = {
    store,
    paused: false,
    traceSub: null,
    metricSub: null,
    logSub: null,
    statsSub: false,
    serviceMapSub: false,
    pending: {},
    timers: {},
    pingInterval: null,
    pausedNotified: false,
  };

  const success = server.upgrade(req, { data });
  if (success) return undefined; // Bun handles the upgrade.
  return new Response("WebSocket upgrade failed", { status: 400 });
}
