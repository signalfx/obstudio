import { useCallback, useEffect, useRef, useState } from "react";
import type { SplunkExportSignalStatus, SplunkExportStatus } from "../api/types";

const cloudBridgeVerificationWindowMs = 15_000;
const cloudBridgeVerificationIntervalMs = 100;
export const maxCloudClipboardTextBytes = 4096;

export const cloudBridgeActions = [
  "connect",
  "forget",
  "initialize",
  "open-audit-report",
  "open-free-edition",
  "open-ingest-token-help",
  "open-skill-docs",
  "read-clipboard",
  "set-enabled",
] as const;

export type CloudBridgeAction = typeof cloudBridgeActions[number];

/**
 * Skills whose docs the IDE may be asked to open. The webview names a skill,
 * never a URL — the extension owns the URL mapping, so this side can never
 * steer the IDE to an arbitrary page.
 */
export const skillDocsIds = [
  "otel-audit",
  "otel-instrument",
  "otel-verify",
  "splunk-configure",
  "splunk-detector-publish",
  "splunk-dashboard-publish",
] as const;

export type SkillDocsId = typeof skillDocsIds[number];

export interface CloudBridgePayload {
  accessToken?: string;
  enabled?: boolean;
  realm?: string;
  skill?: SkillDocsId;
}

export interface CloudBridgeConfig {
  parentOrigin: string;
  supportedActions: readonly string[];
  token: string;
}

export interface CloudBridgeHandshake {
  bridgeToken: string;
  supportedActions?: readonly string[];
  type: "obstudio.cloud.bridge";
}

export interface CloudBridgeResponse {
  bridgeToken: string;
  clipboardText?: string;
  error?: string;
  ok: boolean;
  requestId: string;
  status?: SplunkExportStatus;
  type: "obstudio.cloud.response";
}

interface PendingBridgeRequest {
  reject: (error: Error) => void;
  resolve: (response: CloudBridgeResponse) => void;
  timeoutId: number;
}

export interface UseCloudBridgeResult {
  bridge: CloudBridgeConfig | null;
  callBridge: (action: CloudBridgeAction, payload?: CloudBridgePayload) => Promise<CloudBridgeResponse>;
  /** True when the expected IDE handshake is missing or fails server-side verification. */
  verificationFailed: boolean;
}

/**
 * Establishes the postMessage bridge to the hosting IDE webview, if any.
 *
 * Outside the IDE `window.parent === window`, no handshake is sent, and
 * `bridge` stays null — callers should fall back to plain web behavior.
 */
export function useCloudBridge(): UseCloudBridgeResult {
  const [bridge, setBridge] = useState<CloudBridgeConfig | null>(null);
  const [verificationFailed, setVerificationFailed] = useState(false);
  const pendingRequests = useRef(new Map<string, PendingBridgeRequest>());
  const verificationSequence = useRef(0);

  const callBridge = useCallback((
    action: CloudBridgeAction,
    payload?: CloudBridgePayload,
  ): Promise<CloudBridgeResponse> => {
    if (!bridge) {
      return Promise.reject(new Error("Cloud connection changes are available in the IDE."));
    }
    const requestId = bridgeRequestId();
    return new Promise((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        pendingRequests.current.delete(requestId);
        reject(new Error("The IDE did not respond. Try again."));
      }, 15_000);
      pendingRequests.current.set(requestId, { reject, resolve, timeoutId });
      window.parent.postMessage({
        action,
        bridgeToken: bridge.token,
        payload,
        requestId,
        type: "obstudio.cloud.request",
      }, bridge.parentOrigin);
    });
  }, [bridge]);

  useEffect(() => {
    let active = true;
    let handshakeTimeoutId: number | undefined;
    const receiveBridgeConfig = (event: MessageEvent<unknown>) => {
      if (
        event.source !== window.parent
        || !isCloudBridgeHandshake(event.data)
        || !isTrustedCloudBridgeOrigin(event.origin)
      ) {
        return;
      }
      if (handshakeTimeoutId !== undefined) {
        window.clearTimeout(handshakeTimeoutId);
        handshakeTimeoutId = undefined;
      }
      const { bridgeToken, supportedActions = [] } = event.data;
      const { origin } = event;
      const sequence = ++verificationSequence.current;
      void verifyCloudBridgeToken(bridgeToken).then((verified) => {
        if (!active || sequence !== verificationSequence.current) return;
        if (!verified) {
          setBridge(null);
          setVerificationFailed(true);
          return;
        }
        setVerificationFailed(false);
        setBridge((current) => {
          if (
            current?.parentOrigin === origin
            && current.token === bridgeToken
            && sameStringValues(current.supportedActions, supportedActions)
          ) {
            return current;
          }
          return {
            parentOrigin: origin,
            supportedActions,
            token: bridgeToken,
          };
        });
      });
    };
    window.addEventListener("message", receiveBridgeConfig);
    if (window.parent !== window) {
      window.parent.postMessage({ type: "obstudio.cloud.ready" }, "*");
      handshakeTimeoutId = window.setTimeout(() => {
        handshakeTimeoutId = undefined;
        if (active) setVerificationFailed(true);
      }, cloudBridgeVerificationWindowMs);
    }
    return () => {
      active = false;
      if (handshakeTimeoutId !== undefined) window.clearTimeout(handshakeTimeoutId);
      window.removeEventListener("message", receiveBridgeConfig);
    };
  }, []);

  useEffect(() => {
    if (!bridge) return undefined;
    const pending = pendingRequests.current;
    const receiveBridgeResponse = (event: MessageEvent<unknown>) => {
      if (
        event.source !== window.parent
        || event.origin !== bridge.parentOrigin
        || !isCloudBridgeResponse(event.data)
        || event.data.bridgeToken !== bridge.token
      ) {
        return;
      }
      const request = pending.get(event.data.requestId);
      if (!request) return;
      pending.delete(event.data.requestId);
      window.clearTimeout(request.timeoutId);
      if (event.data.ok) {
        request.resolve(event.data);
      } else {
        request.reject(new Error(event.data.error ?? "The cloud connection request failed."));
      }
    };
    window.addEventListener("message", receiveBridgeResponse);
    return () => {
      window.removeEventListener("message", receiveBridgeResponse);
      for (const request of pending.values()) {
        window.clearTimeout(request.timeoutId);
        request.reject(new Error("The cloud connection request was cancelled."));
      }
      pending.clear();
    };
  }, [bridge]);

  return { bridge, callBridge, verificationFailed };
}

export function isCloudBridgeHandshake(value: unknown): value is CloudBridgeHandshake {
  if (typeof value !== "object" || value === null) return false;
  const handshake = value as Record<string, unknown>;
  return handshake.type === "obstudio.cloud.bridge"
    && typeof handshake.bridgeToken === "string"
    && /^[A-Za-z0-9_-]{24,128}$/.test(handshake.bridgeToken)
    && (handshake.supportedActions === undefined
      || (Array.isArray(handshake.supportedActions)
        && handshake.supportedActions.length <= 64
        && handshake.supportedActions.every((action) => (
          typeof action === "string" && /^[a-z][a-z0-9-]{0,63}$/.test(action)
        ))));
}

function sameStringValues(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

export function isTrustedCloudBridgeOrigin(origin: string): boolean {
  if (origin.startsWith("vscode-webview://")) return true;
  try {
    const url = new URL(origin);
    return url.protocol === "https:"
      && (url.hostname.endsWith(".vscode-webview.net") || url.hostname.endsWith(".vscode-cdn.net"));
  } catch {
    return false;
  }
}

export async function verifyCloudBridgeToken(bridgeToken: string): Promise<boolean> {
  const expiresAt = Date.now() + cloudBridgeVerificationWindowMs;
  for (;;) {
    try {
      const response = await fetch("/api/splunk/export/bridge/verify", {
        body: JSON.stringify({ bridgeToken }),
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
      if (response.ok) {
        const body: unknown = await response.json();
        return isBridgeVerificationResponse(body);
      }
      if (response.status === 400) {
        return false;
      }
    } catch {
      // The extension can race the iframe load while registering the token.
    }
    const remaining = expiresAt - Date.now();
    if (remaining <= 0) {
      return false;
    }
    await new Promise((resolve) => window.setTimeout(
      resolve,
      Math.min(cloudBridgeVerificationIntervalMs, remaining),
    ));
  }
}

function isBridgeVerificationResponse(value: unknown): boolean {
  return typeof value === "object"
    && value !== null
    && (value as Record<string, unknown>).ok === true;
}

export function isCloudBridgeResponse(value: unknown): value is CloudBridgeResponse {
  if (typeof value !== "object" || value === null) return false;
  const response = value as Record<string, unknown>;
  return response.type === "obstudio.cloud.response"
    && typeof response.bridgeToken === "string"
    && typeof response.requestId === "string"
    && typeof response.ok === "boolean"
    && (response.clipboardText === undefined
      || (typeof response.clipboardText === "string"
        && utf8ByteLength(response.clipboardText) <= maxCloudClipboardTextBytes))
    && (response.error === undefined || typeof response.error === "string")
    && (response.status === undefined || isSplunkExportStatus(response.status));
}

export function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

export function isSplunkExportStatus(value: unknown): value is SplunkExportStatus {
  if (typeof value !== "object" || value === null) return false;
  const status = value as Record<string, unknown>;
  return typeof status.connected === "boolean"
    && typeof status.enabled === "boolean"
    && (status.realm === undefined || typeof status.realm === "string")
    && isSplunkExportSignalStatus(status.metrics)
    && isSplunkExportSignalStatus(status.traces);
}

function isSplunkExportSignalStatus(value: unknown): value is SplunkExportSignalStatus {
  if (typeof value !== "object" || value === null) return false;
  const status = value as Record<string, unknown>;
  return typeof status.configured === "boolean"
    && typeof status.enabled === "boolean"
    && typeof status.exportedBatches === "number"
    && typeof status.exportedItems === "number"
    && typeof status.failedBatches === "number";
}

export function bridgeRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `cloud-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
