import { test, expect, describe, beforeAll, afterAll } from "bun:test";
import { Store } from "../../src/store/store.ts";
import { startWebServer } from "../../src/web/server.ts";
import type { Span } from "../../src/store/types.ts";

const WEB_PORT = 43000;
const WS_URL = `ws://127.0.0.1:${WEB_PORT}/api/ws`;

const store = new Store({ sessionGap: 0 });
let webServer: { stop: () => void };

function makeSpan(overrides: Partial<Span> = {}): Span {
  return {
    traceId: "ws-test-trace",
    spanId: "ws-test-span",
    name: "ws-test",
    kind: "SERVER",
    startTimeUnixNano: "0",
    endTimeUnixNano: "0",
    durationMs: 0,
    status: { code: "OK" },
    attributes: {},
    events: [],
    links: [],
    resource: { serviceName: "ws-svc", attributes: {} },
    scope: { name: "ws-scope" },
    ...overrides,
  };
}

function waitForMessage(ws: WebSocket, timeout = 2000): Promise<string> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), timeout);
    ws.onmessage = (event) => {
      clearTimeout(timer);
      resolve(typeof event.data === "string" ? event.data : event.data.toString());
    };
  });
}

function waitForOpen(ws: WebSocket, timeout = 2000): Promise<void> {
  return new Promise((resolve, reject) => {
    if (ws.readyState === WebSocket.OPEN) return resolve();
    const timer = setTimeout(() => reject(new Error("timeout")), timeout);
    ws.onopen = () => { clearTimeout(timer); resolve(); };
    ws.onerror = (e) => { clearTimeout(timer); reject(e); };
  });
}

describe("WebSocket handler", () => {
  beforeAll(() => {
    const ws = startWebServer(store, "127.0.0.1", WEB_PORT);
    webServer = ws;
  });

  afterAll(() => {
    webServer.stop();
  });

  test("receives connected message on open", async () => {
    store.clear();
    const ws = new WebSocket(WS_URL);
    await waitForOpen(ws);
    const msg = await waitForMessage(ws);
    const data = JSON.parse(msg);
    expect(data.type).toBe("connected");
    ws.close();
  });

  test("subscribe and receive updates on data change", async () => {
    store.clear();
    const ws = new WebSocket(WS_URL);
    await waitForOpen(ws);

    // Skip connected message.
    await waitForMessage(ws);

    // Subscribe to stats.
    ws.send(JSON.stringify({ type: "subscribe", signals: { stats: {} } }));

    // Should get initial stats push.
    const statsMsg = await waitForMessage(ws);
    const statsData = JSON.parse(statsMsg);
    expect(statsData.type).toBe("update");
    expect(statsData.signal).toBe("stats");
    expect(statsData.data.spanCount).toBe(0);

    ws.close();
  });

  test("subscribe to traces and receive data", async () => {
    store.clear();
    const ws = new WebSocket(WS_URL);
    await waitForOpen(ws);
    await waitForMessage(ws); // connected

    ws.send(JSON.stringify({ type: "subscribe", signals: { traces: { limit: 10 } } }));

    // Should get initial traces push (empty).
    const initMsg = await waitForMessage(ws);
    const initData = JSON.parse(initMsg);
    expect(initData.type).toBe("update");
    expect(initData.signal).toBe("traces");

    // Now add a span and wait for update.
    store.addSpans([makeSpan()]);

    const updateMsg = await waitForMessage(ws);
    const updateData = JSON.parse(updateMsg);
    expect(updateData.type).toBe("update");
    expect(updateData.signal).toBe("traces");
    expect(updateData.data.length).toBe(1);

    ws.close();
  });

  test("pause stops updates, resume pushes latest", async () => {
    store.clear();
    const ws = new WebSocket(WS_URL);
    await waitForOpen(ws);
    await waitForMessage(ws); // connected

    ws.send(JSON.stringify({ type: "subscribe", signals: { stats: {} } }));
    await waitForMessage(ws); // initial stats

    // Pause — give server time to process.
    ws.send(JSON.stringify({ type: "pause" }));
    await new Promise((r) => setTimeout(r, 50));

    // Add data — should receive paused-update notification, NOT a full update.
    store.addSpans([makeSpan({ traceId: "paused-1" })]);

    const pausedMsg = await waitForMessage(ws);
    const pausedData = JSON.parse(pausedMsg);
    expect(pausedData.type).toBe("paused-update");

    // Resume.
    ws.send(JSON.stringify({ type: "resume" }));

    // Should receive updated stats.
    const resumeMsg = await waitForMessage(ws);
    const resumeData = JSON.parse(resumeMsg);
    expect(resumeData.type).toBe("update");
    expect(resumeData.signal).toBe("stats");
    expect(resumeData.data.spanCount).toBe(1);

    ws.close();
  });

  test("multiple signal subscriptions", async () => {
    store.clear();
    const ws = new WebSocket(WS_URL);
    await waitForOpen(ws);
    await waitForMessage(ws); // connected

    ws.send(JSON.stringify({
      type: "subscribe",
      signals: { traces: { limit: 5 }, stats: {}, "service-map": {} },
    }));

    // Should receive initial pushes for all 3 signals.
    const messages: string[] = [];
    for (let i = 0; i < 3; i++) {
      messages.push(await waitForMessage(ws));
    }

    const signals = messages.map((m) => JSON.parse(m).signal).sort();
    expect(signals).toContain("traces");
    expect(signals).toContain("stats");
    expect(signals).toContain("service-map");

    ws.close();
  });
});
