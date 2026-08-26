import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSplunkExportStatus } from "../api/client";
import type { SplunkExportSignalStatus, SplunkExportStatus } from "../api/types";
import {
  isSplunkExportStatus,
  useCloudBridge,
  type CloudBridgeAction,
  type CloudBridgeResponse,
} from "./bridge";

const maxSplunkRealmLength = 32;
const splunkRealmPattern = /^[a-z]{2,12}[0-9]+$/;
const freeEditionURL = "https://www.splunk.com/en_us/download/observability-cloud-free-edition.html";
const ingestTokenHelpURL = "https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens";

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
  const { bridge, callBridge, verificationFailed } = useCloudBridge();
  const [status, setStatus] = useState<SplunkExportStatus | null>(null);
  const [region, setRegion] = useState("us0");
  const [accessToken, setAccessToken] = useState("");
  const [busyAction, setBusyAction] = useState<CloudBridgeAction | null>("initialize");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [forgetOpen, setForgetOpen] = useState(false);
  const forgetCancelRef = useRef<HTMLButtonElement>(null);
  const forgetConfirmRef = useRef<HTMLButtonElement>(null);
  const forgetTriggerRef = useRef<HTMLButtonElement>(null);
  const regionInputRef = useRef<HTMLInputElement>(null);
  const tokenInputRef = useRef<HTMLInputElement>(null);

  const closeForgetDialog = useCallback(() => {
    setForgetOpen(false);
    window.setTimeout(() => forgetTriggerRef.current?.focus(), 0);
  }, []);

  useEffect(() => {
    if (!verificationFailed) return;
    setBusyAction(null);
    setError("Cloud connection changes are not available in this IDE session.");
  }, [verificationFailed]);

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

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() !== "" ? error.message : fallback;
}
