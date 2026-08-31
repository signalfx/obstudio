import { useCallback } from "react";
import type { SplunkExportSignalStatus, SplunkExportStatus } from "../api/types";
import {
  callObserverHostCloud,
  isObserverIDEHost,
  isObserverHostCloudTimeoutError,
  observerHostCloudActions,
  observerHostSkillIds,
  type ObserverHostCloudAction,
  type ObserverHostCloudPayload,
  type ObserverHostCloudResponse,
  type ObserverHostSkillId,
} from "../host/transport";

export { isObserverHostCloudTimeoutError };

export const cloudBridgeActions = observerHostCloudActions;
export const skillDocsIds = observerHostSkillIds;

export type CloudBridgeAction = ObserverHostCloudAction;
export type CloudBridgePayload = ObserverHostCloudPayload;
export type CloudBridgeResponse = ObserverHostCloudResponse;
export type SkillDocsId = ObserverHostSkillId;

export interface CloudBridgeConfig {
  kind: "ide";
}

const ideBridge: CloudBridgeConfig = Object.freeze({ kind: "ide" });

export interface UseCloudBridgeResult {
  bridge: CloudBridgeConfig | null;
  callBridge: (
    action: CloudBridgeAction,
    payload?: CloudBridgePayload,
  ) => Promise<CloudBridgeResponse>;
}

/**
 * Exposes the VS Code/Kiro cloud command channel when the same React client is
 * running as a top-level IDE webview. Standalone localhost pages return no
 * bridge and continue to use the browser-session API.
 */
export function useCloudBridge(): UseCloudBridgeResult {
  const bridge = isObserverIDEHost() ? ideBridge : null;
  const callBridge = useCallback((
    action: CloudBridgeAction,
    payload?: CloudBridgePayload,
  ) => callObserverHostCloud(action, payload), []);
  return { bridge, callBridge };
}

export function isSplunkExportStatus(value: unknown): value is SplunkExportStatus {
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

function isSplunkExportSignalStatus(value: unknown): value is SplunkExportSignalStatus {
  if (typeof value !== "object" || value === null) return false;
  const status = value as Record<string, unknown>;
  return typeof status.configured === "boolean"
    && typeof status.enabled === "boolean"
    && typeof status.exportedBatches === "number"
    && typeof status.exportedItems === "number"
    && typeof status.failedBatches === "number";
}
