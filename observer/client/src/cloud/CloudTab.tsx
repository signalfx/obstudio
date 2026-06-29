import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchSplunkExportStatus, forgetSplunkExportDestination, setSplunkExportEnabled } from "../api/client";
import type { SplunkExportSignalStatus, SplunkExportStatus } from "../api/types";

const statusRefreshMs = 3000;

interface CloudStatusState {
  error: string | null;
  loading: boolean;
  status: SplunkExportStatus | null;
}

interface SignalRow {
  endpoint: string;
  label: string;
  stats: string;
  status: string;
  tone: "error" | "idle" | "success" | "warning";
}

export function CloudTab(): React.ReactElement {
  const [state, setState] = useState<CloudStatusState>({
    error: null,
    loading: true,
    status: null,
  });
  const [forgetBusy, setForgetBusy] = useState(false);
  const [forgetConfirmOpen, setForgetConfirmOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [toggleBusy, setToggleBusy] = useState(false);
  const forgetCancelRef = useRef<HTMLButtonElement>(null);
  const forgetDialogRef = useRef<HTMLElement>(null);
  const forgetTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let active = true;
    let timeoutId: number | undefined;
    const controller = new AbortController();

    const load = async () => {
      try {
        const status = await fetchSplunkExportStatus(controller.signal);
        if (!active) return;
        setState({ error: null, loading: false, status });
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        setState((current) => ({
          error: err instanceof Error ? err.message : "Could not load cloud status",
          loading: false,
          status: current.status,
        }));
      } finally {
        if (active) {
          timeoutId = window.setTimeout(load, statusRefreshMs);
        }
      }
    };

    void load();

    return () => {
      active = false;
      controller.abort();
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, []);

  const model = useMemo(() => buildCloudModel(state.status), [state.status]);

  useEffect(() => {
    if (forgetConfirmOpen) {
      forgetCancelRef.current?.focus();
    }
  }, [forgetConfirmOpen]);

  useEffect(() => {
    if (!model.connected && forgetConfirmOpen) {
      setForgetConfirmOpen(false);
    }
  }, [forgetConfirmOpen, model.connected]);

  useEffect(() => {
    if (!notice) return undefined;
    const timeoutId = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  const closeForgetConfirmation = () => {
    if (forgetBusy) return;
    setForgetConfirmOpen(false);
    forgetTriggerRef.current?.focus();
  };

  const forgetKey = async () => {
    if (!model.connected || forgetBusy) return;
    const controller = new AbortController();
    setForgetBusy(true);
    setNotice(null);
    try {
      const status = await forgetSplunkExportDestination(controller.signal);
      setState({ error: null, loading: false, status });
      setNotice("Destination key forgotten.");
      setForgetConfirmOpen(false);
    } catch (err) {
      setState((current) => ({
        ...current,
        error: err instanceof Error ? err.message : "Could not forget destination key",
      }));
    } finally {
      setForgetBusy(false);
    }
  };

  const handleForgetDialogKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeForgetConfirmation();
      return;
    }
    if (event.key !== "Tab") return;

    const buttons = Array.from(
      forgetDialogRef.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [],
    );
    if (buttons.length < 2) return;
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const toggleExport = async () => {
    if (!model.connected || toggleBusy) return;
    const nextEnabled = !model.exportEnabled;
    const controller = new AbortController();
    setToggleBusy(true);
    setNotice(null);
    try {
      const status = await setSplunkExportEnabled(nextEnabled, controller.signal);
      setState({ error: null, loading: false, status });
      setNotice(nextEnabled ? "Telemetry export enabled." : "Telemetry export disabled.");
    } catch (err) {
      setState((current) => ({
        ...current,
        error: err instanceof Error ? err.message : "Could not update telemetry export",
      }));
    } finally {
      setToggleBusy(false);
    }
  };

  return (
    <section className="tab-panel cloud-tab" role="tabpanel" aria-label="Cloud">
      <div className="cloud-tab__content">
        {state.error ? <div className="cloud-alert cloud-alert--error" role="alert">{state.error}</div> : null}
        <div className="cloud-notice-region" aria-live="polite" aria-atomic="true">
          {notice ? <div className="cloud-alert cloud-alert--success" role="status">{notice}</div> : null}
        </div>
        <section className="cloud-panel" aria-busy={state.loading ? "true" : "false"}>
          <header className="cloud-panel__header">
            <div className="cloud-panel__intro">
              <span
                className={model.connected
                  ? "cloud-connection-state cloud-connection-state--connected"
                  : "cloud-connection-state"}
              >
                <span aria-hidden="true" />
                {model.connectionLabel}
              </span>
              <h2 className="cloud-panel__title">{model.destination}</h2>
              <p className="cloud-panel__subtitle">{model.connectionCopy}</p>
            </div>
            {model.connected ? (
              <button
                className="cloud-button cloud-button--danger"
                disabled={forgetBusy}
                onClick={() => setForgetConfirmOpen(true)}
                ref={forgetTriggerRef}
                type="button"
              >
                {forgetBusy ? "Forgetting..." : "Forget key"}
              </button>
            ) : null}
          </header>

          <section className="cloud-export" aria-labelledby="cloud-export-title">
            <div className="cloud-export__header">
              <div className="cloud-export__copy">
                <div className="cloud-export__title-row">
                  <h3 className="cloud-export__title" id="cloud-export-title">Cloud export</h3>
                </div>
                <p className="cloud-export__subtitle">{model.exportCopy}</p>
                <p className="cloud-local-state">
                  <span aria-hidden="true" />
                  Local collection always on
                </p>
              </div>
              <button
                aria-checked={model.exportEnabled}
                aria-label="Cloud export"
                className={model.exportEnabled ? "cloud-switch cloud-switch--on" : "cloud-switch"}
                disabled={!model.connected || toggleBusy}
                onClick={() => void toggleExport()}
                role="switch"
                type="button"
              >
                <span aria-hidden="true" />
                <span className="cloud-switch__text">{toggleBusy ? "Updating" : model.exportEnabled ? "On" : "Off"}</span>
              </button>
            </div>

            {model.exportEnabled ? (
              <section className="cloud-activity" aria-labelledby="cloud-activity-title">
                <header className="cloud-activity__header">
                  <div>
                    <h3 id="cloud-activity-title">Export activity</h3>
                    <p>Latest delivery state for each signal.</p>
                  </div>
                </header>
                <div className="cloud-signal-list" role="list" aria-label="Cloud export activity">
                  {model.signals.map((signal) => (
                    <div className={`cloud-signal-row cloud-signal-row--${signal.tone}`} key={signal.label} role="listitem">
                      <div className="cloud-signal-row__identity">
                        <span className="cloud-signal-row__indicator" aria-hidden="true" />
                        <div>
                          <p className="cloud-signal-row__label">{signal.label}</p>
                          <p className="cloud-signal-row__status">{signal.status}</p>
                        </div>
                      </div>
                      <p className="cloud-signal-row__stats">{signal.stats}</p>
                      <div className="cloud-signal-row__destination">
                        <span>Endpoint</span>
                        <code className="cloud-signal-row__endpoint">{signal.endpoint}</code>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ) : (
              <div className="cloud-export-placeholder">
                <span className="cloud-export-placeholder__indicator" aria-hidden="true" />
                <div>
                  <strong>{model.connected ? "Remote export is off" : "Cloud destination not connected"}</strong>
                  <p>{model.exportPlaceholderCopy}</p>
                </div>
              </div>
            )}
          </section>
        </section>
      </div>
      {forgetConfirmOpen ? (
        <div
          className="cloud-dialog-backdrop"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) closeForgetConfirmation();
          }}
        >
          <section
            aria-describedby="forget-cloud-key-description"
            aria-labelledby="forget-cloud-key-title"
            aria-modal="true"
            className="cloud-dialog"
            onKeyDown={handleForgetDialogKeyDown}
            ref={forgetDialogRef}
            role="dialog"
          >
            <h2 id="forget-cloud-key-title">Forget cloud key?</h2>
            <p id="forget-cloud-key-description">
              Remote export will turn off. Telemetry already stored locally will remain available.
            </p>
            {state.error ? <p className="cloud-dialog__error" role="alert">{state.error}</p> : null}
            <div className="cloud-dialog__actions">
              <button
                className="cloud-button"
                disabled={forgetBusy}
                onClick={closeForgetConfirmation}
                ref={forgetCancelRef}
                type="button"
              >
                Cancel
              </button>
              <button
                className="cloud-button cloud-button--danger"
                disabled={forgetBusy}
                onClick={() => void forgetKey()}
                type="button"
              >
                {forgetBusy ? "Forgetting..." : "Forget key"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function buildCloudModel(status: SplunkExportStatus | null) {
  const metrics = status?.metrics;
  const traces = status?.traces;
  const signalStatuses = [metrics, traces].filter((item): item is SplunkExportSignalStatus => Boolean(item));
  const hasSignals = signalStatuses.length > 0;
  const exportEnabled = hasSignals && signalStatuses.every((item) => item.enabled);
  const tokenReady = hasSignals && signalStatuses.every((item) => item.accessTokenConfigured);
  const partialTokenReady = !tokenReady && signalStatuses.some((item) => item.accessTokenConfigured);
  const connected = tokenReady;
  const realm = firstValue(signalStatuses.map((item) => item.realm)) ?? "Not connected";
  const destination = connected ? "Splunk Observability Cloud" : "Local telemetry";
  const storageState = connected ? "Secure storage" : "Session only";
  const signals: SignalRow[] = [
    signalRow("Metrics", metrics),
    signalRow("Traces", traces),
  ];

  return {
    connected,
    connectionCopy: connected
      ? `${realm} realm / token in ${storageState.toLowerCase()}`
      : partialTokenReady
      ? "Token setup is incomplete. Configure both metrics and traces before enabling cloud export."
      : "Connect from VS Code to enable remote export. Local telemetry remains available.",
    connectionLabel: connected ? "Connected" : partialTokenReady ? "Setup incomplete" : "Not connected",
    destination,
    exportCopy: partialTokenReady
      ? "Telemetry export needs both metrics and traces tokens before it can be enabled."
      : exportEnabled
      ? `Telemetry is retained locally and forwarded to ${realm}.`
      : "Telemetry stays local until cloud export is enabled.",
    exportEnabled,
    exportPlaceholderCopy: connected
      ? "Turn it on when you are ready to forward metrics and traces. Local telemetry remains available."
      : "Use the VS Code connection flow to add a destination. Local collection continues without one.",
    realm,
    signals,
    storageState,
  };
}

function signalRow(label: string, status: SplunkExportSignalStatus | undefined): SignalRow {
  const endpoint = firstValue(status?.endpoints ?? []) ?? "Local store";
  let state = "Local only";
  let stats = "No export attempts yet";
  let tone: SignalRow["tone"] = "idle";
  if (status?.enabled && status.configured) {
    stats = signalStats(label, status);
    if (status.lastExport) {
      state = lastExportText(status);
      tone = status.lastExport.success ? "success" : "error";
    } else {
      state = "Waiting for telemetry";
    }
    if ((status.failedBatches ?? 0) > 0 && tone !== "error") {
      tone = "warning";
    }
  } else if (status?.accessTokenConfigured) {
    state = "Token ready";
    stats = "Export is off";
  }
  return { endpoint, label, stats, status: state, tone };
}

function signalStats(label: string, status: SplunkExportSignalStatus): string {
  const failed = status.failedBatches ?? 0;
  if (label === "Metrics") {
    const points = status.metricPoints ?? 0;
    const batches = status.metricBatches ?? 0;
    return `${formatCount(points, "point")} / ${formatCount(batches, "batch")}${failed > 0 ? ` / ${formatCount(failed, "failed batch")}` : ""}`;
  }
  const spans = status.traceSpans ?? 0;
  const batches = status.traceBatches ?? 0;
  return `${formatCount(spans, "span")} / ${formatCount(batches, "batch")}${failed > 0 ? ` / ${formatCount(failed, "failed batch")}` : ""}`;
}

function formatCount(value: number, singular: string): string {
  const safeValue = Number.isFinite(value) ? value : 0;
  return `${safeValue.toLocaleString()} ${singular}${safeValue === 1 ? "" : "s"}`;
}

function lastExportText(status: SplunkExportSignalStatus): string {
  if (!status.lastExport) {
    return "Ready";
  }
  if (status.lastExport.success) {
    return `Last export ${formatTime(status.lastExport.time)}`;
  }
  return status.lastExport.error ? `Failed: ${status.lastExport.error}` : "Last export failed";
}

function firstValue(values: Array<string | undefined>): string | undefined {
  return values.find((value) => value !== undefined && value.trim() !== "");
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
