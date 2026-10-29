import React, { useEffect, useRef, useState } from "react";
import { configureSplunkLogs, disconnectSplunkLogs, fetchSplunkLogsStatus, refreshSplunkLogs, setSplunkLogsEnabled, SplunkExportBrowserActionError } from "../api/client";
import type { SplunkLogsStatus } from "../api/types";
import { ConnectionBadge, EditingBadge, ExportControls, ExportToggle, SavedTokenBadge } from "./ExportControls";
import { useCloudBridge, type CloudBridgeAction } from "./bridge";

export interface LogsConnectionDetails {
  status: SplunkLogsStatus | null;
  editing: boolean;
  unavailable: boolean;
  failed: boolean;
}

export function LogsConnection({
  onSaved,
  refreshKey,
  disabled = false,
  onDetailsChange,
}: {
  onSaved?: () => void;
  refreshKey?: string;
  disabled?: boolean;
  onDetailsChange?: (details: LogsConnectionDetails) => void;
}): React.ReactElement {
  const [status, setStatus] = useState<SplunkLogsStatus | null>(null);
  const [endpoint, setEndpoint] = useState("");
  const [index, setIndex] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [reloadNeeded, setReloadNeeded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [connectionFailed, setConnectionFailed] = useState(false);
  const [editToken, setEditToken] = useState(false);
  const { bridge, callBridge } = useCloudBridge();
  const editRef = useRef<HTMLButtonElement>(null);
  const restoreEditFocus = useRef(false);
  const [statusUnavailable, setStatusUnavailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<"endpoint" | "token" | "index" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const dirty = useRef(false);
  const inFlight = useRef(false);
  const requestSequence = useRef(0);
  const statusRetry = useRef(false);
  const mounted = useRef(false);
  const endpointRef = useRef<HTMLInputElement>(null);
  const tokenRef = useRef<HTMLInputElement>(null);
  const indexRef = useRef<HTMLInputElement>(null);
  const exportRef = useRef<HTMLButtonElement>(null);
  const cleanupRef = useRef<HTMLButtonElement>(null);
  const connected = status?.connected ?? Boolean(status?.lastExportSuccess);
  const cleanupPending = status?.cleanupPending ?? false;
  const canDisconnect = status?.canDisconnect ?? status?.tokenConfigured ?? false;
  const rejected = isLogsRejected(status);

  useEffect(() => { onDetailsChange?.({ status, editing, unavailable: statusUnavailable, failed: connectionFailed || fieldError !== null || cleanupPending }); }, [status, editing, statusUnavailable, connectionFailed, fieldError, cleanupPending, onDetailsChange]);
  useEffect(() => {
    if (editing && ![endpointRef.current, tokenRef.current, indexRef.current].some((field) => field === document.activeElement)) (editToken ? tokenRef : endpointRef).current?.focus();
    else if (restoreEditFocus.current) { restoreEditFocus.current = false; editRef.current?.focus(); }
  }, [editing, editToken]);

  useEffect(() => { if (cleanupPending && !connected && !busy) cleanupRef.current?.focus(); }, [cleanupPending, connected, busy]);

  useEffect(() => {
    if (notice === "Logs connected." || notice === "Logs connection updated.") exportRef.current?.focus();
    if (notice === "Logs disconnected.") endpointRef.current?.focus();
  }, [notice]);

  function reconcileStatus(next: SplunkLogsStatus) {
    setStatus(next);
    if (dirty.current && (next.connected ?? Boolean(next.lastExportSuccess))) setEditing(true);
  }

  function hydrate(next: SplunkLogsStatus) {
    setEndpoint(next.endpoint ?? "");
    setIndex(next.index || "studio");
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
      reconcileStatus(next);
      statusRetry.current = false;
      setStatusUnavailable(false);
    } catch {
      if (
        mounted.current &&
        !signal?.aborted &&
        sequence === requestSequence.current
      ) {
        setStatusUnavailable(true);
        statusRetry.current = true;
      }
    }
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    let timer: number | undefined;
    async function poll(reconcile = false) {
      const reconcileStatus = reconcile || statusRetry.current;
      if (!inFlight.current && (reconcileStatus || !dirty.current)) await refresh(controller.signal, reconcileStatus);
      if (!controller.signal.aborted) timer = window.setTimeout(() => { void poll(); }, 5000);
    }
    void poll(true);
    return () => {
      mounted.current = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [refreshKey]);

  function edit() {
    dirty.current = true;
    requestSequence.current += 1;
    setNotice(null);
    setError(null);
    setFieldError(null);
  }

  function beginEdit(tokenOnly = false) {
    if (!status) return;
    hydrate(status);
    setToken("");
    dirty.current = true;
    setError(null);
    setFieldError(null);
    setNotice(null);
    setEditToken(tokenOnly);
    setEditing(true);
  }

  function cancelEdit() {
    if (status) hydrate(status);
    setToken("");
    dirty.current = false;
    setError(null);
    setFieldError(null);
    setNotice(null);
    setConnectionFailed(false);
    restoreEditFocus.current = true;
    setEditing(false);
  }

  async function connect() {
    if (!status || inFlight.current) return;
    setFieldError(null);
    if (!endpoint.trim()) {
      setFieldError("endpoint");
      setError("Enter the HEC endpoint.");
      endpointRef.current?.focus();
      return;
    }
    if (!index.trim()) {
      setFieldError("index");
      setError("Enter the destination index.");
      indexRef.current?.focus();
      return;
    }
    if (
      !token.trim() &&
      (!status.tokenConfigured || endpoint.trim() !== status.endpoint)
    ) {
      setFieldError("token");
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
    setConnectionFailed(false);
    try {
      const next = await configureSplunkLogs({
        ...settings,
        enabled: editing ? status.enabled : true,
        ...(editing ? { preserveEnabled: true } : {}),
        verifyConnection: true,
        expectedVersion: status.version,
      });
      if (!mounted.current) return;
      reconcileStatus(next);
      setStatusUnavailable(false);
      hydrate(next);
      setToken("");
      setReloadNeeded(false);
      dirty.current = false;
      setNotice(editing ? "Logs connection updated." : "Logs connected.");
      setEditing(false);
      onSaved?.();
    } catch (reason) {
      if (reason instanceof SplunkExportBrowserActionError && reason.statusCode === 409) setReloadNeeded(true);
      setConnectionFailed(true);
      if (mounted.current)
        setError(
          reason instanceof Error
            ? reason.message
            : "Could not connect logs.",
        );
      try {
        const next = await fetchSplunkLogsStatus();
        if (mounted.current) {
          reconcileStatus(next);
          const nextConnected = next.connected ?? Boolean(next.lastExportSuccess);
          setStatusUnavailable(false);
          if (!(reason instanceof SplunkExportBrowserActionError)) {
            setError("Could not confirm that the connection was saved. Your changes are kept; try again.");
          }
          if (!editing && nextConnected) setEditing(true);
        }
      } catch {
        // Preserve edits so Connect can retry when the collector becomes available.
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function toggleExport() {
    if (!status || inFlight.current || (dirty.current && !status.enabled)) return;
    inFlight.current = true;
    requestSequence.current += 1;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await setSplunkLogsEnabled(!status.enabled, status.version);
      if (!mounted.current) return;
      reconcileStatus(next);
      setStatusUnavailable(false);
      onSaved?.();
    } catch (reason) {
      if (reason instanceof SplunkExportBrowserActionError && reason.statusCode === 409) setReloadNeeded(true);
      if (mounted.current) setError(reason instanceof Error ? reason.message : "Could not update logs export.");
      try {
        const next = await fetchSplunkLogsStatus();
        if (mounted.current) reconcileStatus(next);
      } catch {
        // Normal polling retries when the collector is available again.
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function disconnect() {
    if (!status || inFlight.current) return;
    inFlight.current = true;
    requestSequence.current += 1;
    setBusy(true);
    setDisconnecting(true);
    setError(null);
    setFieldError(null);
    setNotice(null);
    try {
      const next = await disconnectSplunkLogs(status.version);
      if (!mounted.current) return;
      reconcileStatus(next);
      setStatusUnavailable(false);
      hydrate(next);
      setToken("");
      setReloadNeeded(false);
      dirty.current = false;
      setEditing(false);
      setNotice("Logs disconnected.");
      setConnectionFailed(false);
      onSaved?.();
    } catch (reason) {
      if (reason instanceof SplunkExportBrowserActionError && reason.statusCode === 409) setReloadNeeded(true);
      if (mounted.current) setError(reason instanceof Error ? reason.message : "Could not disconnect logs.");
      try {
        const next = await fetchSplunkLogsStatus();
        if (mounted.current) {
          reconcileStatus(next);
          if (!next.enabled && !next.tokenConfigured && !(next.connected ?? Boolean(next.lastExportSuccess))) {
            setStatusUnavailable(false);
            hydrate(next);
            setToken("");
            dirty.current = false;
            setEditing(false);
            setConnectionFailed(false);
            const pending = next.cleanupPending === true;
            if (!pending) {
              setError(null);
              setNotice("Logs disconnected.");
            }
            onSaved?.();
          }
        }
      } catch {
        // Keep the connection visible until its state can be confirmed.
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setBusy(false);
        setDisconnecting(false);
      }
    }
  }

  async function reload() {
    if (inFlight.current) return;
    inFlight.current = true;
    requestSequence.current += 1;
    setBusy(true);
    setError(null);
    try {
      const next = await refreshSplunkLogs();
      if (!mounted.current) return;
      reconcileStatus(next);
      if (!dirty.current) hydrate(next);
      setStatusUnavailable(false);
      setReloadNeeded(false);
      setConnectionFailed(false);
      onSaved?.();
      window.requestAnimationFrame(() => {
        if (next.connected && !dirty.current && !editing) exportRef.current?.focus();
        else endpointRef.current?.focus();
      });
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : "Could not reload saved logs settings.");
      try {
        const next = await fetchSplunkLogsStatus();
        if (mounted.current) reconcileStatus(next);
      } catch {
        // Retain the recovery action until saved settings can be read.
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const badge = statusUnavailable ? "Unavailable" : !status ? "Loading" : rejected ? "Rejected"
    : status?.lastExportError ? "Connection failed" : connected ? "Connected" : connectionFailed ? "Connection failed" : "Not connected";
  const queued = status?.queuedRecords ?? 0;
  const dropped = status?.droppedRecords ?? 0;
  const showForm = !connected || editing;
  const savedToken = Boolean(status?.tokenConfigured && endpoint.trim() === status.endpoint && !token);
  const displayedError = error ?? (statusUnavailable ? "Logs connection is unavailable. Retrying…" : null);
  const searchURL = status?.searchURL;
  let host = status?.endpoint ?? "";
  try { host = new URL(host).hostname; if (host.endsWith(".splunkcloud.com")) host = host.split(".")[0]; } catch { /* An empty destination has no host label. */ }

  function openExternal(event: React.MouseEvent<HTMLAnchorElement>, action: CloudBridgeAction) {
    if (!bridge) return;
    event.preventDefault();
    void callBridge(action).catch((reason) => setError(reason instanceof Error ? reason.message : "Could not open the destination."));
  }

  return (
    <section aria-labelledby="cloud-logs-title" className={`cloud-panel cloud-logs cloud-destination cloud-destination--logs${connected ? " cloud-destination--connected" : ""}${editing ? " cloud-destination--editing" : ""}${rejected ? " cloud-destination--rejected" : ""}`}>
      <header className="cloud-panel__header">
        <h2 id="cloud-logs-title">Splunk Platform</h2>
        {connected ? <code className="destination-identifier" title={status?.endpoint}>{host} · {status?.index}</code> : <>
          <span className="destination-chip">Logs</span><span className="destination-protocol">HTTP Event Collector</span>
        </>}
        <ConnectionBadge state={badge} />
        {editing ? <EditingBadge /> : connected && status && !statusUnavailable ? (
          <ExportToggle enabled={status.enabled} busy={busy} disabled={disabled} onToggle={() => void toggleExport()} switchLabel="Logs export" buttonRef={exportRef} />
        ) : null}
      </header>
      {editing ? <p className="destination-editing-note">Saved settings stay in use until you save.</p> : null}
      {!showForm && status ? <>
        <ExportControls id="cloud-logs-export-title" title="Logs export" activityLabel="Logs export activity" signals={[{
            label: "Logs", signal: {
              configured: status.configured, enabled: status.enabled, exportedItems: status.exportedRecords,
              exportedBatches: status.exportedBatches ?? 0, failedBatches: status.failedBatches,
              lastExport: status.lastExportSuccess || status.lastExportError ? {
                success: !status.lastExportError, error: status.lastExportError, time: status.lastExportSuccess ?? "",
              } : undefined,
            },
            ...(rejected ? { tone: "error" as const, statusText: status.lastHTTPStatus === 401 || status.lastHECCode === 4
              ? `HEC token refused${status.lastHTTPStatus ? ` — ${status.lastHTTPStatus} from the endpoint` : ""}.`
              : status.lastExportError } : {}),
          }]} />
        <div className="destination-actions">
          <button className={`cloud-button${rejected ? " cloud-button--primary" : ""}`} disabled={busy || disabled || statusUnavailable}
            aria-label={rejected ? "Update HEC token" : "Edit Splunk Platform"} onClick={() => beginEdit(rejected)} ref={editRef} type="button">{rejected ? "Update token" : "Edit"}</button>
          <button aria-label="Disconnect Splunk Platform" className="cloud-button cloud-button--danger" disabled={busy || disabled || statusUnavailable}
            onClick={() => void disconnect()} type="button">{disconnecting ? "Disconnecting..." : "Disconnect"}</button>
          {searchURL && !rejected ? <a className="destination-open-link" href={bridge ? "#" : searchURL} target={bridge ? undefined : "_blank"} rel={bridge ? undefined : "noopener noreferrer"}
            onClick={(event) => openExternal(event, "open-splunk-search")}>Search index {status.index}</a> : null}
          {rejected ? <span className="destination-footnote">Queued logs send once the token is accepted.</span> : null}
        </div>
      </> : null}
      <div className={showForm ? "cloud-logs__form destination-body" : "destination-feedback"} aria-busy={busy}>
        <span className="visually-hidden">{!status ? "Loading" : !status.configured ? "Not configured" : status.enabled ? "Forwarding on" : connected ? "Paused" : ""}</span>
        {displayedError ? <p className="cloud-field__error" role="alert" id="cloud-logs-error">{displayedError}</p> : null}
        {notice ? <p className="visually-hidden" role="status">{notice}</p> : null}
        {cleanupPending ? <p className="destination-buffered" role="status">Credential cleanup is pending. Unlock secure storage, then retry.</p> : null}
        {cleanupPending || reloadNeeded || canDisconnect && !status?.tokenConfigured ? <div className="destination-actions destination-actions--form">
          <button className="cloud-button" disabled={busy || disabled || statusUnavailable} ref={cleanupRef} onClick={() => void reload()} type="button">{cleanupPending ? "Retry credential cleanup" : "Reload saved logs settings"}</button>
        </div> : null}
        {dropped > 0 ? <p role="alert" className="cloud-field__error">{dropped.toLocaleString()} {dropped === 1 ? "log was" : "logs were"} dropped from export. Local copies remain available.</p> : null}
        {showForm ? <form aria-label="Logs connection" noValidate onSubmit={(event) => { event.preventDefault(); void connect(); }}>
          <fieldset disabled={!status || busy || disabled}>
            {!connected && queued > 0 ? <p className="destination-buffered">Logs are buffered locally until this connects.</p> : null}
            <div className="destination-field">
              <label htmlFor="cloud-logs-endpoint">HEC endpoint</label>
              <input id="cloud-logs-endpoint" type="url" autoComplete="off" spellCheck={false}
                aria-invalid={fieldError === "endpoint"} aria-describedby={fieldError === "endpoint" ? "cloud-logs-error" : undefined}
                placeholder="https://your-stack.splunkcloud.com:8088/services/collector" value={endpoint} ref={endpointRef}
                onChange={(event) => { edit(); setEndpoint(event.target.value); }} />
            </div>
            <div className="destination-field">
              <div className="destination-label-row"><label htmlFor="cloud-logs-token">HEC token</label>
                <a href={bridge ? "#" : hecTokenHelpURL} target={bridge ? undefined : "_blank"} rel={bridge ? undefined : "noopener noreferrer"}
                  onClick={(event) => openExternal(event, "open-hec-token-help")}>Find your HEC token</a>
              </div>
              <div className="destination-token">
                <input id="cloud-logs-token" type="password" autoComplete="new-password" spellCheck={false}
                  aria-invalid={fieldError === "token"}
                  placeholder={status?.tokenConfigured ? "Paste a new token to replace" : "Paste token"} value={token} ref={tokenRef}
                  onChange={(event) => { edit(); setToken(event.target.value); }} aria-describedby={fieldError === "token" ? "cloud-logs-error" : savedToken ? "cloud-logs-token-help" : undefined} />
                {savedToken ? <SavedTokenBadge /> : null}
              </div>
              {savedToken ? <small id="cloud-logs-token-help">Leave blank to keep the saved token.</small> : null}
            </div>
            <div className="destination-field destination-field--short">
              <label htmlFor="cloud-logs-index">Logs index</label>
              <input id="cloud-logs-index" value={index} ref={indexRef} onChange={(event) => { edit(); setIndex(event.target.value); }} placeholder="studio"
                aria-invalid={fieldError === "index"} aria-describedby={fieldError === "index" ? "cloud-logs-error" : undefined} />
              <small>Must already accept events from this token.</small>
            </div>
            <div className="destination-actions destination-actions--form">
              <button aria-label={editing ? "Save Splunk Platform changes" : "Connect Splunk Platform"} className="cloud-button cloud-button--primary" type="submit">
                {busy ? editing ? "Saving..." : "Connecting..." : editing ? "Save changes" : "Connect"}
              </button>
              {editing ? <button className="cloud-button" onClick={cancelEdit} type="button">Cancel</button> : queued === 0 ? <span className="destination-inline-help">Logs stay local until this connects.</span> : null}
              {editing || canDisconnect ? <button aria-label="Disconnect Splunk Platform" className="cloud-button cloud-button--danger destination-disconnect" disabled={statusUnavailable} onClick={() => void disconnect()} type="button">Disconnect</button> : null}
            </div>
          </fieldset>
        </form> : null}
      </div>
    </section>
  );
}

const hecTokenHelpURL = "https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-enterprise/set-up-and-use-http-event-collector-in-splunk-web";

export function isLogsRejected(status: SplunkLogsStatus | null): boolean {
  return Boolean(status?.lastExportError && (status.lastHTTPStatus === 401 || status.lastHTTPStatus === 403 || status.lastHECCode === 4));
}
