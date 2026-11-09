import { useCallback } from "react";
import {
  callObserverHostCloud,
  isObserverIDEHost,
  isObserverHostCloudTimeoutError,
  isSplunkExportStatus,
  observerHostCloudActions,
  observerHostSkillIds,
  type ObserverHostCloudAction,
  type ObserverHostCloudPayload,
  type ObserverHostCloudResponse,
  type ObserverHostSkillId,
} from "../host/transport";

export { isObserverHostCloudTimeoutError, isSplunkExportStatus };

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
 * bridge and call the same-origin local API directly.
 */
export function useCloudBridge(): UseCloudBridgeResult {
  const bridge = isObserverIDEHost() ? ideBridge : null;
  const callBridge = useCallback((
    action: CloudBridgeAction,
    payload?: CloudBridgePayload,
  ) => callObserverHostCloud(action, payload), []);
  return { bridge, callBridge };
}
