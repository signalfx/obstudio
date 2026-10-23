import React, { useEffect, useRef, useState } from "react";
import { configureSplunkLogs, fetchSplunkLogsStatus } from "../api/client";
import type { SplunkLogsStatus } from "../api/types";

export type LogsConnectionState = "connected" | "configured" | "disconnected";

export function LogsConnection({
  onConnectionChange,
  onSaved,
  refreshKey,
  disabled = false,
}: {
  onConnectionChange?: (state: LogsConnectionState) => void;
  onSaved?: () => void;
  refreshKey?: string;
  disabled?: boolean;
}): React.ReactElement {
  const [status, setStatus] = useState<SplunkLogsStatus | null>(null);
  const [endpoint, setEndpoint] = useState("");
  const [index, setIndex] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusUnavailable, setStatusUnavailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const dirty = useRef(false);
  const inFlight = useRef(false);
  const requestSequence = useRef(0);
  const mounted = useRef(false);
  const endpointRef = useRef<HTMLInputElement>(null);
  const tokenRef = useRef<HTMLInputElement>(null);
  const indexRef = useRef<HTMLInputElement>(null);

  function hydrate(next: SplunkLogsStatus) {
    setEndpoint(next.endpoint ?? "");
    setIndex(next.index ?? "");
  }

  async function refresh(signal?: AbortSignal, reconcile = false) {
    const sequence = ++requestSequence.current;
    try {
      const next = await fetchSplunkLogsStatus(signal);
      if (
        !mounted.current ||
        signal?.aborted ||
        inFlight.current ||
        (dirty.current && !reconcile) ||
        sequence !== requestSequence.current
      )
        return;
      if (!dirty.current) hydrate(next);
      setStatus(next);
      setStatusUnavailable(false);
      setError(null);
    } catch {
      if (
        mounted.current &&
        !signal?.aborted &&
        sequence === requestSequence.current
      ) {
        setStatusUnavailable(true);
        setError("Logs settings are unavailable. Retrying…");
      }
    }
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void refresh(controller.signal, true);
    const timer = window.setInterval(() => {
      if (!dirty.current && !inFlight.current) void refresh(controller.signal);
    }, 5000);
    return () => {
      mounted.current = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refreshKey]);

  useEffect(() => {
    if (!status) return;
    onConnectionChange?.(
      status.enabled && !status.lastExportError && !statusUnavailable
        ? "connected"
        : status.configured
          ? "configured"
          : "disconnected",
    );
  }, [status, onConnectionChange, statusUnavailable]);

  function edit() {
    dirty.current = true;
    requestSequence.current += 1;
    setNotice(null);
    setError(null);
  }

  async function save() {
    if (!status || inFlight.current) return;
    if (!endpoint.trim()) {
      setError("Enter the HEC endpoint.");
      endpointRef.current?.focus();
      return;
    }
    if (!index.trim()) {
      setError("Enter the destination index.");
      indexRef.current?.focus();
      return;
    }
    if (
      !token.trim() &&
      (!status.tokenConfigured || endpoint.trim() !== status.endpoint)
    ) {
      setError("Paste the complete HEC token for this endpoint.");
      tokenRef.current?.focus();
      return;
    }
    const settings = {
      endpoint,
      token,
      index,
      source: status.source || "otel",
      insecureSkipVerify:
        endpoint.trim() === status.endpoint && status.insecureSkipVerify,
    };
    inFlight.current = true;
    dirty.current = true;
    requestSequence.current += 1;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await configureSplunkLogs({
        ...settings,
        expectedVersion: status.version,
      });
      if (!mounted.current) return;
      setStatus(next);
      setStatusUnavailable(false);
      hydrate(next);
      setToken("");
      dirty.current = false;
      setNotice("Logs settings saved.");
      onSaved?.();
    } catch (reason) {
      if (mounted.current)
        setError(
          reason instanceof Error
            ? reason.message
            : "Could not save logs settings.",
        );
      try {
        const next = await fetchSplunkLogsStatus();
        if (mounted.current) setStatus(next);
      } catch {
        // Preserve edits so Save can retry when the collector becomes available.
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const state = statusUnavailable
    ? "Status unavailable"
    : !status
      ? error
        ? "Unavailable"
        : "Loading"
      : !status.configured
        ? "Not configured"
        : status.lastExportError
          ? "Export error"
          : status.enabled
            ? "Forwarding on"
            : "Paused";
  return (
    <section
      aria-labelledby="cloud-logs-title"
      className="cloud-panel cloud-logs"
    >
      <header className="cloud-panel__header">
        <div>
          <h2 id="cloud-logs-title">Splunk Platform logs</h2>
          <p>
            Send logs to Splunk Cloud Platform or Splunk Enterprise using HTTP
            Event Collector.
          </p>
        </div>
      </header>
      <form
        aria-label="Logs connection"
        aria-busy={busy}
        className="cloud-logs__form"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
        noValidate
      >
        <div aria-live="polite" className="cloud-logs__status">
          <strong>{state}</strong>
          {status?.lastExportError ? (
            <p role="alert">{status.lastExportError}</p>
          ) : null}
        </div>
        {error ? (
          <p className="cloud-field__error" role="alert">
            {error}
          </p>
        ) : null}
        {notice ? <p role="status">{notice}</p> : null}
        <fieldset disabled={!status || busy || disabled}>
          <label htmlFor="cloud-logs-endpoint">HEC endpoint</label>
          <input
            id="cloud-logs-endpoint"
            autoComplete="off"
            spellCheck={false}
            placeholder="https://your-host:8088/services/collector"
            value={endpoint}
            ref={endpointRef}
            onChange={(e) => {
              edit();
              setEndpoint(e.target.value);
            }}
          />
          <label htmlFor="cloud-logs-token">HEC token</label>
          <input
            id="cloud-logs-token"
            type="password"
            autoComplete="new-password"
            spellCheck={false}
            placeholder={
              status?.tokenConfigured
                ? "Token saved — paste to replace"
                : "Paste the complete HEC token"
            }
            value={token}
            ref={tokenRef}
            onChange={(e) => {
              edit();
              setToken(e.target.value);
            }}
            aria-describedby={
              status?.tokenConfigured ? "cloud-logs-token-help" : undefined
            }
          />
          {status?.tokenConfigured ? (
            <small id="cloud-logs-token-help">
              A token is saved. Leave blank to keep it for the same endpoint.
            </small>
          ) : null}
          <label htmlFor="cloud-logs-index">Logs index</label>
          <input
            id="cloud-logs-index"
            value={index}
            ref={indexRef}
            onChange={(e) => {
              edit();
              setIndex(e.target.value);
            }}
            placeholder="studio"
          />
          <div className="cloud-logs__actions">
            <button
              className="cloud-button cloud-button--primary"
              type="submit"
            >
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </fieldset>
      </form>
    </section>
  );
}
