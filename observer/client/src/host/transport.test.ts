// @vitest-environment happy-dom

import { cloudInitializeHostRequestTimeoutMs, cloudHostRequestTimeoutMs, logsHostRequestTimeoutMs } from "../../../../shared/connection-limits.cjs";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  callObserverHostCloud,
  ObserverHostCloudRequestError,
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

describe("Splunk Observability Studio host transport", () => {
  it("allows initialization to finish its refresh and credential-import budget", async () => {
    vi.useFakeTimers();
    const { posted } = installHost();
    const pending = callObserverHostCloud("initialize");
    const request = posted.at(-1);
    await vi.advanceTimersByTimeAsync(cloudInitializeHostRequestTimeoutMs - 1);
    respond(request, true, { status: disconnectedStatus() });
    expect(await pending).toEqual({ status: disconnectedStatus() });
    expect(posted.some((message) => message.type === "obstudio.host.cancel")).toBe(false);
  });

  it("routes logs settings through the IDE adapter without affecting unrelated requests after failure", async () => {
    const { posted } = installHost();
    const settings = observerFetch("/api/splunk/logs", {method:"POST",body:JSON.stringify({token:"synthetic-token",index:"studio"})});
    const request=posted.at(-1);
    expect(request?.request).toMatchObject({kind:"http",method:"POST",path:"/api/splunk/logs"});
    respond(request,true,{body:JSON.stringify({error:"HEC rejected token"}),status:502,statusText:"Bad Gateway"});
    expect((await settings).status).toBe(502);
    const health=observerFetch("/api/health");
    respond(posted.at(-1),true,{body:JSON.stringify({kind:"obstudio"}),status:200,statusText:"OK"});
    await expect((await health).json()).resolves.toEqual({kind:"obstudio"});
  });
  it.each(["", "/enabled", "/disconnect", "/refresh"])("waits for logs storage and reports an uncertain outcome without cancellation (%s)", async (suffix) => {
    vi.useFakeTimers();
    const { posted } = installHost();
    const pending = observerFetch(`/api/splunk/logs${suffix}`, { method: "POST", body: "{}" });
    const timedOut = expect(pending).rejects.toThrow(/Reload saved logs settings/);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(posted).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(logsHostRequestTimeoutMs - 15_000);
    await timedOut;
    expect(posted.some((message) => message.type === "obstudio.host.cancel")).toBe(false);
    const health = observerFetch("/api/health");
    respond(posted.at(-1), true, { body: "{}", status: 200, statusText: "OK" });
    expect((await health).status).toBe(200);
  });

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

  it("refuses HTTP methods the host does not forward", async () => {
    const { posted } = installHost();
    for (const method of ["PUT", "PATCH", "DELETE"]) {
      await expect(observerFetch("/api/config", { body: "{}", method })).rejects.toThrow(
        `Splunk Observability Studio host transport does not support ${method} requests.`,
      );
    }
    expect(posted).toHaveLength(0);
  });

  it("serves the Config tab's API calls through the host", async () => {
    const { posted } = installHost();

    const definitions = observerFetch("/api/config/definitions");
    expect(posted.at(-1)).toMatchObject({ request: { kind: "http", method: "GET", path: "/api/config/definitions" } });
    respond(posted.at(-1), true, {
      body: JSON.stringify({ type: "object", properties: {} }),
      headers: { "content-type": "application/json" },
      status: 200,
      statusText: "OK",
    });
    await expect((await definitions).json()).resolves.toEqual({ type: "object", properties: {} });

    const values = observerFetch("/api/config");
    expect(posted.at(-1)).toMatchObject({ request: { kind: "http", method: "GET", path: "/api/config" } });
    respond(posted.at(-1), true, {
      body: JSON.stringify({ telemetry: { enabled: true } }),
      headers: { "content-type": "application/json" },
      status: 200,
      statusText: "OK",
    });
    await expect((await values).json()).resolves.toEqual({ telemetry: { enabled: true } });

    const rejected = observerFetch("/api/config", {
      body: '{"telemetry":{"enabled":null}}',
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
    expect(posted.at(-1)).toMatchObject({
      request: { body: '{"telemetry":{"enabled":null}}', kind: "http", method: "POST", path: "/api/config" },
    });
    respond(posted.at(-1), true, {
      body: JSON.stringify({ error: "telemetry.enabled: null is not a valid value" }),
      headers: { "content-type": "application/json" },
      status: 400,
      statusText: "Bad Request",
    });
    const response = await rejected;
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: "telemetry.enabled: null is not a valid value" });
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

    const legacy = callObserverHostCloud("initialize");
    respond(posted.at(-1), true, { status: legacyDisconnectedStatus() });
    await expect(legacy).resolves.toEqual({ status: legacyDisconnectedStatus() });

    const logsStatus = { ...disconnectedStatus(), logs: { ...disconnectedStatus().metrics, configured: true, exportedItems: 4 } };
    const logs = callObserverHostCloud("initialize");
    respond(posted.at(-1), true, { status: logsStatus });
    await expect(logs).resolves.toEqual({ status: logsStatus });

    const invalidLogs = callObserverHostCloud("initialize");
    respond(posted.at(-1), true, { status: { ...logsStatus, logs: { exportedItems: "four" } } });
    await expect(invalidLogs).rejects.toThrow("invalid cloud response");

    for (const cloudVersion of [17, null, "invalid"]) {
      const invalidVersion = callObserverHostCloud("initialize");
      respond(posted.at(-1), true, { status: { ...disconnectedStatus(), cloudVersion } });
      await expect(invalidVersion).rejects.toThrow("invalid cloud response");
    }

    const invalid = callObserverHostCloud("initialize");
    respond(posted.at(-1), true, { status: { connected: "yes" } });
    await expect(invalid).rejects.toThrow("invalid cloud response");

    // An unrecognized value must not pass validation and end up truthy in the UI.
    const invalidProtocol = callObserverHostCloud("initialize");
    respond(posted.at(-1), true, {
      status: { ...disconnectedStatus(), registrationAndAuthProtocol: "cimd" },
    });
    await expect(invalidProtocol).rejects.toThrow("invalid cloud response");
  });

  it.each(["yes", "false", 1, null])("rejects malformed credential cleanup status from host mutations (%s)", async (cleanupPending) => {
    const { posted } = installHost();
    const pending = callObserverHostCloud("refresh");
    respond(posted.at(-1), true, { status: { ...disconnectedStatus(), cleanupPending } });
    await expect(pending).rejects.toThrow("invalid cloud response");
  });

  it("preserves allowlisted cloud failure metadata for outcome handling", async () => {
    const { posted } = installHost();
    const pending = callObserverHostCloud("create-free-account", {
      email: "person@example.com",
      firstName: "Example",
      lastName: "Person",
      region: "us",
      termsAccepted: true,
    });
    const request = posted.at(-1);
    if (!request?.requestId) throw new Error("host request was not posted");

    window.dispatchEvent(new MessageEvent("message", {
      data: {
        code: "outcome_unknown",
        error: "The upstream result could not be confirmed.",
        ok: false,
        requestId: request.requestId,
        retrySafe: false,
        type: "obstudio.host.response",
      },
    }));

    await expect(pending).rejects.toEqual(expect.objectContaining({
      code: "outcome_unknown",
      message: "The upstream result could not be confirmed.",
      name: "ObserverHostCloudRequestError",
      retrySafe: false,
    } satisfies Partial<ObserverHostCloudRequestError>));
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
      .toThrow(/Reload saved connection/);

    await vi.advanceTimersByTimeAsync(cloudHostRequestTimeoutMs);

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
    registrationAndAuthProtocol: "NONE",
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

function legacyDisconnectedStatus() {
  const { registrationAndAuthProtocol: _registrationAndAuthProtocol, ...status } = disconnectedStatus();
  return status;
}
