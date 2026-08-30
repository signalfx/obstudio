import type { SplunkExportStatus } from "../api/types";

export const observerHostCloudActions = [
  "connect",
  "forget",
  "initialize",
  "open-audit-report",
  "open-free-edition",
  "open-ingest-token-help",
  "open-skill-docs",
  "set-enabled",
] as const;

export type ObserverHostCloudAction = typeof observerHostCloudActions[number];

export const observerHostSkillIds = [
  "otel-audit",
  "otel-instrument",
  "otel-verify",
  "splunk-configure",
  "splunk-detector-publish",
  "splunk-dashboard-publish",
] as const;

export type ObserverHostSkillId = typeof observerHostSkillIds[number];

export interface ObserverHostCloudPayload {
  accessToken?: string;
  enabled?: boolean;
  expectedVersion?: string;
  realm?: string;
  skill?: ObserverHostSkillId;
}

export interface ObserverHostCloudResponse {
  status?: SplunkExportStatus;
  warning?: string;
}

export interface ObserverHostTelemetryMessage {
  data?: unknown;
  signal?: string;
  type: "connected" | "disconnected" | "paused-update" | "reload" | "update";
}

interface VSCodeWebviewAPI {
  postMessage(message: unknown): void;
}

type ObserverHostRequest =
  | {
    body?: string;
    kind: "http";
    method: "GET" | "POST";
    path: string;
  }
  | {
    action: ObserverHostCloudAction;
    kind: "cloud";
    payload?: ObserverHostCloudPayload;
  };

interface ObserverHostRequestEnvelope {
  request: ObserverHostRequest;
  requestId: string;
  type: "obstudio.host.request";
}

interface ObserverHostCancelEnvelope {
  requestId: string;
  type: "obstudio.host.cancel";
}

interface ObserverHostResponseEnvelope {
  error?: string;
  ok: boolean;
  requestId: string;
  result?: unknown;
  type: "obstudio.host.response";
}

interface ObserverHostTelemetryEnvelope {
  message: ObserverHostTelemetryMessage;
  type: "obstudio.host.telemetry-message";
}

interface PendingHostRequest {
  cleanup?: () => void;
  reject: (error: Error) => void;
  resolve: (result: unknown) => void;
  timeoutId?: number;
}

const hostRequestTimeoutMs = 15_000;
const hostCloudRequestTimeoutMs = 60_000;
const pendingHostRequests = new Map<string, PendingHostRequest>();
const telemetryListeners = new Set<(message: ObserverHostTelemetryMessage) => void>();
let acquiredFrom: (() => VSCodeWebviewAPI) | undefined;
let hostAPI: VSCodeWebviewAPI | null = null;
let messageListenerInstalled = false;

export class ObserverHostCloudTimeoutError extends Error {
  constructor() {
    super("The IDE did not confirm the cloud request. Reload the window to reconcile its final state before trying again.");
    this.name = "ObserverHostCloudTimeoutError";
  }
}

export function isObserverHostCloudTimeoutError(error: unknown): error is ObserverHostCloudTimeoutError {
  return error instanceof ObserverHostCloudTimeoutError;
}

export function isObserverIDEHost(): boolean {
  return observerHostAPI() !== null;
}

export async function observerFetch(path: string, init?: RequestInit): Promise<Response> {
  const api = observerHostAPI();
  if (!api) return fetch(path, init);

  const method = (init?.method ?? "GET").toUpperCase();
  if (method !== "GET" && method !== "POST") {
    throw new Error(`Observer host transport does not support ${method} requests.`);
  }
  if (init?.body !== undefined && typeof init.body !== "string") {
    throw new Error("Observer host transport accepts only string request bodies.");
  }

  const result = await callObserverHost({
    body: init?.body,
    kind: "http",
    method,
    path,
  }, init?.signal ?? undefined);
  if (!isObserverHostHTTPResult(result)) {
    throw new Error("The IDE returned an invalid Observer response.");
  }
  const body = result.status === 204 || result.status === 205 || result.status === 304
    ? null
    : result.body;
  return new Response(body, {
    headers: result.headers,
    status: result.status,
    statusText: result.statusText,
  });
}

export async function callObserverHostCloud(
  action: ObserverHostCloudAction,
  payload?: ObserverHostCloudPayload,
): Promise<ObserverHostCloudResponse> {
  if (!observerHostAPI()) {
    throw new Error("Cloud connection changes are not available in the IDE.");
  }
  const result = await callObserverHost({ action, kind: "cloud", payload });
  if (!isObserverHostCloudResponse(result)) {
    throw new Error("The IDE returned an invalid cloud response.");
  }
  return result;
}

export interface ObserverHostTelemetrySubscription {
  pause(): void;
  resume(): void;
  dispose(): void;
}

export function subscribeObserverHostTelemetry(
  listener: (message: ObserverHostTelemetryMessage) => void,
): ObserverHostTelemetrySubscription | null {
  const api = observerHostAPI();
  if (!api) return null;
  const firstListener = telemetryListeners.size === 0;
  telemetryListeners.add(listener);
  if (firstListener) {
    api.postMessage({ command: "subscribe", type: "obstudio.host.telemetry" });
  }
  let disposed = false;
  return {
    pause() {
      if (!disposed) api.postMessage({ command: "pause", type: "obstudio.host.telemetry" });
    },
    resume() {
      if (!disposed) api.postMessage({ command: "resume", type: "obstudio.host.telemetry" });
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      telemetryListeners.delete(listener);
      if (telemetryListeners.size === 0) {
        api.postMessage({ command: "unsubscribe", type: "obstudio.host.telemetry" });
      }
    },
  };
}

function observerHostAPI(): VSCodeWebviewAPI | null {
  const acquire = (
    globalThis as typeof globalThis & { acquireVsCodeApi?: () => VSCodeWebviewAPI }
  ).acquireVsCodeApi;
  if (typeof acquire !== "function") {
    return null;
  }
  if (acquiredFrom !== acquire) {
    rejectPendingHostRequests("The IDE host changed before responding.");
    acquiredFrom = acquire;
    hostAPI = acquire();
  }
  installMessageListener();
  return hostAPI;
}

function installMessageListener(): void {
  if (messageListenerInstalled) return;
  messageListenerInstalled = true;
  window.addEventListener("message", (event: MessageEvent<unknown>) => {
    if (isObserverHostResponseEnvelope(event.data)) {
      const pending = pendingHostRequests.get(event.data.requestId);
      if (!pending) return;
      pendingHostRequests.delete(event.data.requestId);
      if (pending.timeoutId !== undefined) window.clearTimeout(pending.timeoutId);
      pending.cleanup?.();
      if (event.data.ok) {
        pending.resolve(event.data.result);
      } else {
        pending.reject(new Error(event.data.error ?? "The IDE request failed."));
      }
      return;
    }
    if (isObserverHostTelemetryEnvelope(event.data)) {
      for (const listener of telemetryListeners) listener(event.data.message);
    }
  });
}

function callObserverHost(request: ObserverHostRequest, signal?: AbortSignal): Promise<unknown> {
  const api = observerHostAPI();
  if (!api) return Promise.reject(new Error("The IDE host is not available."));
  if (signal?.aborted) return Promise.reject(abortError());

  const requestId = hostRequestId();
  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
        const pending = pendingHostRequests.get(requestId);
        if (!pending) return;
        pendingHostRequests.delete(requestId);
        pending.cleanup?.();
        if (request.kind === "http") {
          api.postMessage({ requestId, type: "obstudio.host.cancel" } satisfies ObserverHostCancelEnvelope);
          reject(new Error("The IDE did not respond. Try again."));
          return;
        }
        // Do not cancel an accepted cloud mutation: the extension must finish
        // synchronizing Observer state and secure storage. The caller fails
        // closed until reload instead of permitting an uncertain retry.
        reject(new ObserverHostCloudTimeoutError());
      }, request.kind === "http" ? hostRequestTimeoutMs : hostCloudRequestTimeoutMs);
    const abort = signal
      ? () => {
        const pending = pendingHostRequests.get(requestId);
        if (!pending) return;
        pendingHostRequests.delete(requestId);
        window.clearTimeout(timeoutId);
        api.postMessage({ requestId, type: "obstudio.host.cancel" } satisfies ObserverHostCancelEnvelope);
        reject(abortError());
      }
      : undefined;
    if (abort) signal?.addEventListener("abort", abort, { once: true });
    pendingHostRequests.set(requestId, {
      cleanup: abort ? () => signal?.removeEventListener("abort", abort) : undefined,
      reject,
      resolve,
      timeoutId,
    });
    api.postMessage({ request, requestId, type: "obstudio.host.request" } satisfies ObserverHostRequestEnvelope);
  });
}

function rejectPendingHostRequests(message: string): void {
  for (const pending of pendingHostRequests.values()) {
    if (pending.timeoutId !== undefined) window.clearTimeout(pending.timeoutId);
    pending.cleanup?.();
    pending.reject(new Error(message));
  }
  pendingHostRequests.clear();
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function hostRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `host-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function isObserverHostHTTPResult(value: unknown): value is {
  body: string;
  headers?: Record<string, string>;
  status: number;
  statusText: string;
} {
  if (typeof value !== "object" || value === null) return false;
  const result = value as Record<string, unknown>;
  return typeof result.body === "string"
    && typeof result.status === "number"
    && Number.isInteger(result.status)
    && result.status >= 100
    && result.status <= 599
    && typeof result.statusText === "string"
    && (result.headers === undefined || isStringRecord(result.headers));
}

function isObserverHostCloudResponse(value: unknown): value is ObserverHostCloudResponse {
  if (typeof value !== "object" || value === null) return false;
  const response = value as Record<string, unknown>;
  return (response.status === undefined || isSplunkExportStatus(response.status))
    && (response.warning === undefined || typeof response.warning === "string");
}

function isSplunkExportStatus(value: unknown): value is SplunkExportStatus {
  if (typeof value !== "object" || value === null) return false;
  const status = value as Record<string, unknown>;
  return typeof status.connected === "boolean"
    && typeof status.enabled === "boolean"
    && (status.realm === undefined || typeof status.realm === "string")
    && typeof status.version === "string"
    && /^[A-Za-z0-9_-]{43}$/.test(status.version)
    && isSplunkExportSignalStatus(status.metrics)
    && isSplunkExportSignalStatus(status.traces);
}

function isSplunkExportSignalStatus(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false;
  const status = value as Record<string, unknown>;
  return typeof status.configured === "boolean"
    && typeof status.enabled === "boolean"
    && typeof status.exportedBatches === "number"
    && typeof status.exportedItems === "number"
    && typeof status.failedBatches === "number";
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return typeof value === "object"
    && value !== null
    && Object.values(value).every((entry) => typeof entry === "string");
}

function isObserverHostResponseEnvelope(value: unknown): value is ObserverHostResponseEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const response = value as Record<string, unknown>;
  return response.type === "obstudio.host.response"
    && typeof response.requestId === "string"
    && /^[A-Za-z0-9_-]{8,128}$/.test(response.requestId)
    && typeof response.ok === "boolean"
    && (response.error === undefined || typeof response.error === "string");
}

function isObserverHostTelemetryEnvelope(value: unknown): value is ObserverHostTelemetryEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const envelope = value as Record<string, unknown>;
  if (envelope.type !== "obstudio.host.telemetry-message") return false;
  if (typeof envelope.message !== "object" || envelope.message === null) return false;
  const message = envelope.message as Record<string, unknown>;
  return typeof message.type === "string"
    && ["connected", "disconnected", "paused-update", "reload", "update"].includes(message.type)
    && (message.signal === undefined || typeof message.signal === "string");
}
