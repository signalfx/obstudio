import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSplunkExportStatus } from "../api/client";
import type { SplunkExportSignalStatus, SplunkExportStatus } from "../api/types";

const maxSplunkRealmLength = 32;
const splunkRealmPattern = /^[a-z]{2,12}[0-9]+$/;
const cloudBridgeVerificationWindowMs = 15_000;
const cloudBridgeVerificationIntervalMs = 100;
const freeEditionURL = "https://www.splunk.com/en_us/download/observability-cloud-free-edition.html";
const ingestTokenHelpURL = "https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens";

type CloudBridgeAction =
  | "connect"
  | "forget"
  | "initialize"
  | "open-free-edition"
  | "open-ingest-token-help"
  | "set-enabled";

interface CloudBridgeConfig {
  parentOrigin: string;
  token: string;
}

interface CloudBridgeHandshake {
  bridgeToken: string;
  type: "obstudio.cloud.bridge";
}

interface CloudBridgeResponse {
  bridgeToken: string;
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

interface SignalRow {
  detail: string;
  label: string;
  status: string;
  tone: "error" | "idle" | "success" | "warning";
}

export type CloudConnectionState = "connected" | "configured" | "disconnected";

interface CloudTabProps {
  onConnectionChange?: (state: CloudConnectionState) => void;
}

export function CloudTab({ onConnectionChange }: CloudTabProps): React.ReactElement {
  const [bridge, setBridge] = useState<CloudBridgeConfig | null>(null);
  const [status, setStatus] = useState<SplunkExportStatus | null>(null);
  const [region, setRegion] = useState("us0");
  const [accessToken, setAccessToken] = useState("");
  const [busyAction, setBusyAction] = useState<CloudBridgeAction | null>("initialize");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [forgetOpen, setForgetOpen] = useState(false);
  const pendingRequests = useRef(new Map<string, PendingBridgeRequest>());
  const forgetCancelRef = useRef<HTMLButtonElement>(null);
  const forgetConfirmRef = useRef<HTMLButtonElement>(null);
  const forgetTriggerRef = useRef<HTMLButtonElement>(null);
  const regionInputRef = useRef<HTMLInputElement>(null);
  const tokenInputRef = useRef<HTMLInputElement>(null);

  const closeForgetDialog = useCallback(() => {
    setForgetOpen(false);
    window.setTimeout(() => forgetTriggerRef.current?.focus(), 0);
  }, []);

  const callBridge = useCallback((
    action: CloudBridgeAction,
    payload?: { accessToken?: string; enabled?: boolean; realm?: string },
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
    const receiveBridgeConfig = (event: MessageEvent<unknown>) => {
      if (
        event.source !== window.parent
        || !isCloudBridgeHandshake(event.data)
        || !isTrustedCloudBridgeOrigin(event.origin)
      ) {
        return;
      }
      const { bridgeToken } = event.data;
      const { origin } = event;
      void verifyCloudBridgeToken(bridgeToken).then((verified) => {
        if (!active) return;
        if (!verified) {
          setBusyAction(null);
          setError("Cloud connection changes are not available in this IDE session.");
          return;
        }
        setBridge({
          parentOrigin: origin,
          token: bridgeToken,
        });
      });
    };
    window.addEventListener("message", receiveBridgeConfig);
    if (window.parent !== window) {
      window.parent.postMessage({ type: "obstudio.cloud.ready" }, "*");
    }
    return () => {
      active = false;
      window.removeEventListener("message", receiveBridgeConfig);
    };
  }, []);

  useEffect(() => {
    if (!bridge) return undefined;
    const receiveBridgeResponse = (event: MessageEvent<unknown>) => {
      if (
        event.source !== window.parent
        || event.origin !== bridge.parentOrigin
        || !isCloudBridgeResponse(event.data)
        || event.data.bridgeToken !== bridge.token
      ) {
        return;
      }
      const pending = pendingRequests.current.get(event.data.requestId);
      if (!pending) return;
      pendingRequests.current.delete(event.data.requestId);
      window.clearTimeout(pending.timeoutId);
      if (event.data.ok) {
        pending.resolve(event.data);
      } else {
        pending.reject(new Error(event.data.error ?? "The cloud connection request failed."));
      }
    };
    window.addEventListener("message", receiveBridgeResponse);
    return () => {
      window.removeEventListener("message", receiveBridgeResponse);
      for (const pending of pendingRequests.current.values()) {
        window.clearTimeout(pending.timeoutId);
        pending.reject(new Error("The cloud connection request was cancelled."));
      }
      pendingRequests.current.clear();
    };
  }, [bridge]);

  useEffect(() => {
    if (!bridge && window.parent !== window) return undefined;
    let active = true;
    const controller = new AbortController();
    const initialize = async () => {
      try {
        let nextStatus: unknown;
        let bridgeInitializationError: unknown;
        if (bridge) {
          try {
            nextStatus = (await callBridge("initialize")).status;
          } catch (initializationError) {
            bridgeInitializationError = initializationError;
            nextStatus = await fetchSplunkExportStatus(controller.signal);
          }
        } else {
          nextStatus = await fetchSplunkExportStatus(controller.signal);
        }
        if (!active) return;
        if (!nextStatus || !isSplunkExportStatus(nextStatus)) {
          throw new Error("Observer returned an invalid cloud status.");
        }
        setStatus(nextStatus);
        if (nextStatus.realm?.trim()) {
          setRegion(nextStatus.realm.trim().toLowerCase());
        }
        setError(bridgeInitializationError
          ? errorMessage(bridgeInitializationError, "Could not restore cloud connection status.")
          : null);
      } catch (initializationError) {
        if (!active || controller.signal.aborted) return;
        setError(errorMessage(initializationError, "Could not load cloud connection status."));
        onConnectionChange?.("disconnected");
      } finally {
        if (active) setBusyAction(null);
      }
    };
    void initialize();
    return () => {
      active = false;
      controller.abort();
    };
  }, [bridge, callBridge, onConnectionChange]);

  useEffect(() => {
    if (forgetOpen) forgetCancelRef.current?.focus();
  }, [forgetOpen]);

  useEffect(() => {
    if (!notice) return undefined;
    const timeoutId = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  const connected = status?.connected === true;

  useEffect(() => {
    if (status === null) return;
    const isConfigured = status.connected
      || status.metrics.configured
      || status.traces.configured;
    const state: CloudConnectionState = status.connected ? "connected" : isConfigured ? "configured" : "disconnected";
    onConnectionChange?.(state);
  }, [onConnectionChange, status]);

  const exportEnabled = status?.enabled === true;
  const metricsConfigured = status?.metrics.configured === true;
  const tracesConfigured = status?.traces.configured === true;
  const cloudConfigured = connected || metricsConfigured || tracesConfigured;
  const exportPartiallyEnabled = !exportEnabled
    && (status?.metrics.enabled === true || status?.traces.enabled === true);
  const exportActive = exportEnabled || exportPartiallyEnabled;
  const exportStateLabel = exportEnabled ? "on" : exportPartiallyEnabled ? "partially on" : "off";
  const connectionStateLabel = connected ? "Connected" : cloudConfigured ? "Partially configured" : "Not connected";
  const destinationLabel = cloudConfigured
    ? status?.realm?.trim()
      ? status.realm.toUpperCase()
      : "configured destination"
    : "";
  const connectionSummary = connected
    ? `${destinationLabel} · Access token configured`
    : cloudConfigured
      ? status?.realm?.trim()
        ? `${destinationLabel} · Connection details incomplete`
        : "Connection details incomplete"
      : "Connect to export metrics and traces.";
  const signals = useMemo(() => [
    signalRow("Metrics", status?.metrics),
    signalRow("Traces", status?.traces),
  ], [status]);

  useEffect(() => {
    if (!exportActive) return undefined;
    let active = true;
    let controller: AbortController | undefined;
    let timeoutId: number | undefined;

    const poll = async () => {
      controller = new AbortController();
      try {
        const nextStatus = await fetchSplunkExportStatus(controller.signal);
        if (active && isSplunkExportStatus(nextStatus)) {
          setStatus(nextStatus);
        }
      } catch {
        // Keep the last known status if a background status request fails.
      } finally {
        if (active) timeoutId = window.setTimeout(() => void poll(), 5000);
      }
    };

    timeoutId = window.setTimeout(() => void poll(), 5000);
    return () => {
      active = false;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      controller?.abort();
    };
  }, [exportActive]);

  const runAction = async (
    action: CloudBridgeAction,
    payload?: { accessToken?: string; enabled?: boolean; realm?: string },
  ): Promise<CloudBridgeResponse | null> => {
    if (busyAction) return null;
    setBusyAction(action);
    setError(null);
    setNotice(null);
    try {
      const response = await callBridge(action, payload);
      if (response.status) setStatus(response.status);
      return response;
    } catch (actionError) {
      setError(errorMessage(actionError, "The cloud connection request failed."));
      return null;
    } finally {
      setBusyAction(null);
    }
  };

  const connect = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const token = accessToken.trim();
    const realm = region.trim().toLowerCase();
    if (realm.length > maxSplunkRealmLength || !splunkRealmPattern.test(realm)) {
      setError("Enter a valid Splunk Observability Cloud region.");
      regionInputRef.current?.focus();
      return;
    }
    if (token.length < 16) {
      setError("Paste the access token secret.");
      tokenInputRef.current?.focus();
      return;
    }
    const response = await runAction("connect", {
      accessToken: token,
      realm,
    });
    if (!response) return;
    setAccessToken("");
    setNotice("Cloud destination connected.");
  };

  const openExternalLink = (
    event: React.MouseEvent<HTMLAnchorElement>,
    action: "open-free-edition" | "open-ingest-token-help",
  ) => {
    if (!bridge) return;
    event.preventDefault();
    void callBridge(action).catch((openError) => {
      setError(errorMessage(openError, "Could not open the external page."));
    });
  };

  const toggleExport = async () => {
    const response = await runAction("set-enabled", { enabled: !exportEnabled });
    if (response) {
      setNotice(exportEnabled ? "Remote export disabled." : "Remote export enabled.");
    }
  };

  const forget = async () => {
    const response = await runAction("forget");
    if (!response) return;
    closeForgetDialog();
    setAccessToken("");
    setNotice("Cloud key forgotten.");
  };

  return (
    <section id="panel-cloud" aria-label="Cloud" className="tab-panel cloud-tab" role="tabpanel">
      <div className="cloud-tab__content">
        <div aria-atomic="true" aria-live="polite" className="cloud-alert-region">
          {error ? <div className="cloud-alert cloud-alert--error" role="alert">{error}</div> : null}
          {!error && notice ? <div className="cloud-alert cloud-alert--success" role="status">{notice}</div> : null}
        </div>

        <section
          aria-busy={busyAction ? "true" : "false"}
          className={cloudConfigured ? "cloud-panel" : "cloud-panel cloud-panel--setup"}
        >
          <header className="cloud-panel__header">
            <div>
              <h2>Splunk Observability Cloud</h2>
              <p>{connectionSummary}</p>
            </div>
            {cloudConfigured ? (
              <div className="cloud-panel__actions">
                <button
                  className="cloud-button cloud-button--danger"
                  disabled={busyAction !== null || !bridge}
                  onClick={() => setForgetOpen(true)}
                  ref={forgetTriggerRef}
                  type="button"
                >
                  Forget key
                </button>
              </div>
            ) : null}
          </header>

          {!cloudConfigured ? (
            <form aria-label="Cloud connection" className="cloud-connect-form" onSubmit={connect}>
              <div className="cloud-field cloud-field--region">
                <label htmlFor="cloud-region">Region</label>
                <input
                  autoCapitalize="none"
                  autoComplete="off"
                  autoCorrect="off"
                  disabled={busyAction !== null || !bridge}
                  id="cloud-region"
                  onChange={(event) => {
                    setRegion(event.target.value.trim().toLowerCase());
                    setError(null);
                  }}
                  placeholder="US0"
                  ref={regionInputRef}
                  spellCheck={false}
                  value={region.toUpperCase()}
                />
              </div>
              <div className="cloud-field cloud-field--token">
                <label htmlFor="cloud-access-token">Access token</label>
                <input
                  autoCapitalize="none"
                  autoComplete="new-password"
                  autoCorrect="off"
                  disabled={busyAction !== null || !bridge}
                  id="cloud-access-token"
                  maxLength={4096}
                  onChange={(event) => {
                    setAccessToken(event.target.value);
                    setError(null);
                  }}
                  placeholder="Paste Ingest token"
                  ref={tokenInputRef}
                  spellCheck={false}
                  type="password"
                  value={accessToken}
                />
                <a
                  className="cloud-field__help-link"
                  href={ingestTokenHelpURL}
                  onClick={(event) => openExternalLink(event, "open-ingest-token-help")}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  More on access tokens
                </a>
              </div>
              <div className="cloud-connect-form__action">
                <button
                  className="cloud-button cloud-button--primary"
                  disabled={busyAction !== null || !bridge || accessToken.trim().length < 16}
                  type="submit"
                >
                  {busyAction === "connect" ? "Connecting..." : "Connect"}
                </button>
              </div>
            </form>
          ) : (
            <section aria-labelledby="cloud-export-title" className="cloud-export">
              <div className="cloud-export__header">
                <div>
                  <h3 id="cloud-export-title">Remote export</h3>
                  <p>Send metrics and traces to {destinationLabel}.</p>
                </div>
                <button
                  aria-checked={exportEnabled}
                  aria-label={`Remote telemetry export is ${exportStateLabel}`}
                  className={exportEnabled ? "cloud-switch cloud-switch--on" : "cloud-switch"}
                  disabled={busyAction !== null || !bridge}
                  onClick={() => void toggleExport()}
                  role="switch"
                  type="button"
                >
                  <span aria-hidden="true" className="cloud-switch__track"><span /></span>
                  <span>
                    {busyAction === "set-enabled"
                      ? "Updating"
                      : exportEnabled
                        ? "On"
                        : exportPartiallyEnabled
                          ? "Partial"
                          : "Off"}
                  </span>
                </button>
              </div>

              {exportActive ? (
                <div aria-label="Telemetry export activity" className="cloud-signal-list" role="list">
                  {signals.map((signal) => (
                    <div className={`cloud-signal-row cloud-signal-row--${signal.tone}`} key={signal.label} role="listitem">
                      <div>
                        <p><span aria-hidden="true" />{signal.label}</p>
                        <small>{signal.status}</small>
                      </div>
                      <span>{signal.detail}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
          )}
          {!cloudConfigured ? (
            <section aria-labelledby="cloud-free-account-title" className="cloud-free-account">
              <div>
                <h3 id="cloud-free-account-title">Don't have an Observability Cloud account?</h3>
                <p>Create a free account with your own organization, then connect it here.</p>
              </div>
              <a
                className="cloud-button cloud-free-account__link"
                href={freeEditionURL}
                onClick={(event) => openExternalLink(event, "open-free-edition")}
                rel="noopener noreferrer"
                target="_blank"
              >
                Create free account
                <span aria-hidden="true" />
              </a>
            </section>
          ) : null}
        </section>
      </div>

      {forgetOpen ? (
        <div
          className="cloud-dialog-backdrop"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target && busyAction !== "forget") closeForgetDialog();
          }}
        >
          <section
            aria-describedby="cloud-forget-description"
            aria-labelledby="cloud-forget-title"
            aria-modal="true"
            className="cloud-dialog"
            onKeyDown={(event) => {
              if (event.key === "Escape" && busyAction !== "forget") {
                event.preventDefault();
                closeForgetDialog();
                return;
              }
              if (event.key !== "Tab") return;
              const first = forgetCancelRef.current;
              const last = forgetConfirmRef.current;
              if (!first || !last) return;
              if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
              } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
              }
            }}
            role="dialog"
          >
            <h2 id="cloud-forget-title">Forget cloud key?</h2>
            <p id="cloud-forget-description">This removes the stored key and turns off remote export.</p>
            <div>
              <button
                className="cloud-button"
                disabled={busyAction === "forget"}
                onClick={closeForgetDialog}
                ref={forgetCancelRef}
                type="button"
              >
                Cancel
              </button>
              <button
                className="cloud-button cloud-button--danger"
                disabled={busyAction === "forget"}
                onClick={() => void forget()}
                ref={forgetConfirmRef}
                type="button"
              >
                {busyAction === "forget" ? "Forgetting..." : "Forget key"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function signalRow(label: string, signal: SplunkExportSignalStatus | undefined): SignalRow {
  if (!signal) {
    return { detail: "No activity", label, status: "Waiting for Observer", tone: "idle" };
  }
  const detail = `${formatCount(signal.exportedItems, label === "Metrics" ? "point" : "span")} · ${formatCount(signal.exportedBatches, "batch", "batches")}`;
  if (!signal.enabled) {
    return { detail, label, status: "Remote export off", tone: "idle" };
  }
  if (signal.lastExport && !signal.lastExport.success) {
    return {
      detail,
      label,
      status: signal.lastExport.error ? `Failed: ${signal.lastExport.error}` : "Last export failed",
      tone: "error",
    };
  }
  if (signal.lastExport?.success) {
    return {
      detail,
      label,
      status: `Last export ${formatTime(signal.lastExport.time)}`,
      tone: signal.failedBatches > 0 ? "warning" : "success",
    };
  }
  return { detail, label, status: "Waiting for telemetry", tone: "idle" };
}

function formatCount(value: number, singular: string, plural = `${singular}s`): string {
  return `${value.toLocaleString()} ${value === 1 ? singular : plural}`;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function isCloudBridgeHandshake(value: unknown): value is CloudBridgeHandshake {
  if (typeof value !== "object" || value === null) return false;
  const handshake = value as Record<string, unknown>;
  return handshake.type === "obstudio.cloud.bridge"
    && typeof handshake.bridgeToken === "string"
    && /^[A-Za-z0-9_-]{24,128}$/.test(handshake.bridgeToken);
}

function isTrustedCloudBridgeOrigin(origin: string): boolean {
  if (origin.startsWith("vscode-webview://")) return true;
  try {
    const url = new URL(origin);
    return url.protocol === "https:"
      && (url.hostname.endsWith(".vscode-webview.net") || url.hostname.endsWith(".vscode-cdn.net"));
  } catch {
    return false;
  }
}

async function verifyCloudBridgeToken(bridgeToken: string): Promise<boolean> {
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

function isCloudBridgeResponse(value: unknown): value is CloudBridgeResponse {
  if (typeof value !== "object" || value === null) return false;
  const response = value as Record<string, unknown>;
  return response.type === "obstudio.cloud.response"
    && typeof response.bridgeToken === "string"
    && typeof response.requestId === "string"
    && typeof response.ok === "boolean"
    && (response.error === undefined || typeof response.error === "string")
    && (response.status === undefined || isSplunkExportStatus(response.status));
}

function isSplunkExportStatus(value: unknown): value is SplunkExportStatus {
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

function bridgeRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `cloud-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() !== "" ? error.message : fallback;
}
