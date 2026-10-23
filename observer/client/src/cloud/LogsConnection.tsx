import React, { useEffect, useRef, useState } from "react";
import { configureSplunkLogs, fetchSplunkLogsStatus } from "../api/client";
import type { SplunkLogsStatus } from "../api/types";

export type LogsConnectionState = "connected" | "configured" | "disconnected";

export function LogsConnection({
  onConnectionChange,
}: {
  onConnectionChange?: (state: LogsConnectionState) => void;
}): React.ReactElement {
  const [status, setStatus] = useState<SplunkLogsStatus | null>(null);
  const [endpoint, setEndpoint] = useState("");
  const [index, setIndex] = useState("");
  const [source, setSource] = useState("otel");
  const [token, setToken] = useState("");
  const [insecure, setInsecure] = useState(false);
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
    setSource(next.source || "otel");
    setInsecure(next.insecureSkipVerify);
  }

  async function refresh(signal?: AbortSignal) {
    const sequence = ++requestSequence.current;
    try {
      const next = await fetchSplunkLogsStatus(signal);
      if (
        !mounted.current ||
        signal?.aborted ||
        inFlight.current ||
        dirty.current ||
        sequence !== requestSequence.current
      )
        return;
      hydrate(next);
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
        setError("Logs settings are unavailable. Refresh to try again.");
      }
    }
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = window.setInterval(() => {
      if (!dirty.current && !inFlight.current) void refresh(controller.signal);
    }, 5000);
    return () => {
      mounted.current = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

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

  async function save(enabled: boolean) {
    if (!status || inFlight.current) return;
    if (enabled && !endpoint.trim()) {
      setError("Enter the HEC endpoint.");
      endpointRef.current?.focus();
      return;
    }
    if (enabled && !index.trim()) {
      setError("Enter the destination index.");
      indexRef.current?.focus();
      return;
    }
    if (
      enabled &&
      !token.trim() &&
      (!status.tokenConfigured || endpoint.trim() !== status.endpoint)
    ) {
      setError("Paste the complete HEC token for this endpoint.");
      tokenRef.current?.focus();
      return;
    }
    const hadEdits = dirty.current;
    const settings = enabled
      ? { endpoint, token, index, source, insecureSkipVerify: insecure }
      : {
          endpoint: status.endpoint,
          token: "",
          index: status.index,
          source: status.source,
          insecureSkipVerify: status.insecureSkipVerify,
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
        enabled,
        expectedVersion: status.version,
      });
      if (!mounted.current) return;
      setStatus(next);
      setStatusUnavailable(false);
      if (enabled || !hadEdits) {
        hydrate(next);
        setToken("");
      }
      dirty.current = enabled ? false : hadEdits;
      setNotice(
        enabled
          ? "Test log accepted. Logs forwarding is on and settings are saved."
          : "Logs forwarding paused. Settings are saved.",
      );
    } catch (reason) {
      if (mounted.current)
        setError(
          reason instanceof Error
            ? reason.message
            : "Could not save logs settings.",
        );
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
          void save(true);
        }}
        noValidate
      >
        <div aria-live="polite" className="cloud-logs__status">
          <strong>{state}</strong>
          {status ? (
            <span>
              {status.exportedRecords}{" "}
              {status.exportedRecords === 1 ? "record" : "records"} accepted ·{" "}
              {status.failedBatches} failed batches
            </span>
          ) : null}
          {status?.lastExportSuccess ? (
            <small>
              Last accepted:{" "}
              {new Date(status.lastExportSuccess).toLocaleString()}
            </small>
          ) : null}
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
        <fieldset disabled={!status || busy}>
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
          <div className="cloud-logs__destinations">
            <div>
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
            </div>
            <div>
              <label htmlFor="cloud-logs-source">Logs source</label>
              <input
                id="cloud-logs-source"
                value={source}
                onChange={(e) => {
                  edit();
                  setSource(e.target.value);
                }}
                placeholder="otel"
              />
            </div>
          </div>
          <label className="cloud-logs__tls">
            <input
              type="checkbox"
              checked={insecure}
              onChange={(e) => {
                edit();
                setInsecure(e.target.checked);
              }}
            />
            Skip TLS certificate verification
          </label>
          <small>
            Leave off for trusted certificates. Enabling this disables server
            certificate verification.
          </small>
          <p>
            Saving sends one test log to this endpoint and index, then enables
            forwarding. Settings are saved locally.
          </p>
          <div className="cloud-logs__actions">
            <button
              className="cloud-button cloud-button--primary"
              type="submit"
            >
              {busy ? "Saving…" : "Save and enable logs"}
            </button>
            {status?.enabled ? (
              <button
                className="cloud-button"
                type="button"
                onClick={() => void save(false)}
              >
                Pause logs
              </button>
            ) : null}
          </div>
        </fieldset>
        <button
          className="cloud-button"
          type="button"
          disabled={busy}
          onClick={() => {
            dirty.current = false;
            setToken("");
            setNotice(null);
            void refresh();
          }}
        >
          Refresh logs status
        </button>
      </form>
    </section>
  );
}
