// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  callObserverHostCloud,
  observerFetch,
  subscribeObserverHostTelemetry,
} from "./transport";

type PostedMessage = {
  request?: {
    action?: string;
    body?: string;
    kind?: string;
    method?: string;
    path?: string;
    payload?: Record<string, unknown>;
  };
  requestId?: string;
  type?: string;
};

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Observer host transport", () => {
  it("keeps native fetch for the standalone browser", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("browser", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await observerFetch("/api/health");

    expect(await response.text()).toBe("browser");
    expect(fetchMock).toHaveBeenCalledWith("/api/health", undefined);
  });

  it("routes IDE HTTP through the extension host and reconstructs a Response", async () => {
    const { posted } = installHost();
    const pending = observerFetch("/api/validation/run", {
      body: JSON.stringify({ ignored: false }),
      method: "POST",
    });
    const request = posted.at(-1);
    expect(request).toMatchObject({
      request: {
        body: '{"ignored":false}',
        kind: "http",
        method: "POST",
        path: "/api/validation/run",
      },
      type: "obstudio.host.request",
    });

    respond(request, true, {
      body: JSON.stringify({ ok: true }),
      headers: { "content-type": "application/json" },
      status: 202,
      statusText: "Accepted",
    });

    const response = await pending;
    expect(response.status).toBe(202);
    expect(response.statusText).toBe("Accepted");
    await expect(response.json()).resolves.toEqual({ ok: true });
  });

  it("sends bounded cloud actions and validates the host status", async () => {
    const { posted } = installHost();
    const pending = callObserverHostCloud("connect", {
      accessToken: "opaque-token",
      realm: "us1",
    });
    const request = posted.at(-1);
    expect(request).toMatchObject({
      request: {
        action: "connect",
        kind: "cloud",
        payload: { accessToken: "opaque-token", realm: "us1" },
      },
    });
    respond(request, true, { status: disconnectedStatus() });
    await expect(pending).resolves.toEqual({ status: disconnectedStatus() });

    const invalid = callObserverHostCloud("initialize");
    respond(posted.at(-1), true, { status: { connected: "yes" } });
    await expect(invalid).rejects.toThrow("invalid cloud response");
  });

  it("cancels the host request when its AbortSignal is aborted", async () => {
    const { posted } = installHost();
    const controller = new AbortController();
    const pending = observerFetch("/api/query/stats", { signal: controller.signal });
    const request = posted.at(-1);

    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(posted.at(-1)).toEqual({
      requestId: request?.requestId,
      type: "obstudio.host.cancel",
    });
  });

  it("bounds the cloud wait without sending a cancellation or permitting an uncertain retry", async () => {
    vi.useFakeTimers();
    const { posted } = installHost();
    const pending = callObserverHostCloud("connect", {
      accessToken: "opaque-token",
      realm: "us1",
    });
    const request = posted.at(-1);
    const timedOut = expect(pending).rejects
      .toThrow(/Reload the window to reconcile its final state/);

    await vi.advanceTimersByTimeAsync(60_000);

    await timedOut;
    expect(posted.some((message) => message.type === "obstudio.host.cancel")).toBe(false);

    // A late completion is ignored because the caller must reload and reconcile.
    respond(request, true, { status: disconnectedStatus() });
  });

  it("subscribes to host telemetry and forwards pause, resume, and dispose", () => {
    const { posted } = installHost();
    const listener = vi.fn();
    const subscription = subscribeObserverHostTelemetry(listener);
    expect(subscription).not.toBeNull();
    expect(posted.at(-1)).toEqual({ command: "subscribe", type: "obstudio.host.telemetry" });

    window.dispatchEvent(new MessageEvent("message", {
      data: {
        message: { data: [], signal: "traces", type: "update" },
        type: "obstudio.host.telemetry-message",
      },
    }));
    expect(listener).toHaveBeenCalledWith({ data: [], signal: "traces", type: "update" });

    subscription?.pause();
    subscription?.resume();
    subscription?.dispose();
    expect(posted.slice(-3)).toEqual([
      { command: "pause", type: "obstudio.host.telemetry" },
      { command: "resume", type: "obstudio.host.telemetry" },
      { command: "unsubscribe", type: "obstudio.host.telemetry" },
    ]);
  });
});

function installHost(): { posted: PostedMessage[] } {
  const posted: PostedMessage[] = [];
  const acquire = vi.fn(() => ({
    postMessage(message: PostedMessage) {
      posted.push(message);
    },
  }));
  vi.stubGlobal("acquireVsCodeApi", acquire);
  return { posted };
}

function respond(request: PostedMessage | undefined, ok: boolean, result?: unknown): void {
  if (!request?.requestId) throw new Error("host request was not posted");
  window.dispatchEvent(new MessageEvent("message", {
    data: {
      ok,
      requestId: request.requestId,
      result,
      type: "obstudio.host.response",
    },
  }));
}

function disconnectedStatus() {
  return {
    connected: false,
    enabled: false,
    version: "V".repeat(43),
    metrics: {
      configured: false,
      enabled: false,
      exportedBatches: 0,
      exportedItems: 0,
      failedBatches: 0,
    },
    traces: {
      configured: false,
      enabled: false,
      exportedBatches: 0,
      exportedItems: 0,
      failedBatches: 0,
    },
  };
}
