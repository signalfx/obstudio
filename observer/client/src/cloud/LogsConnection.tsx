import React, { useEffect, useRef, useState } from "react";
import { hecEndpointHelpURL, hecTokenHelpURL } from "../../../../shared/hec-help.cjs";
import { configureSplunkLogs, disconnectSplunkLogs, fetchSplunkLogsStatus, refreshSplunkLogs, setSplunkLogsEnabled, SplunkExportBrowserActionError } from "../api/client";
import { ObserverHostCloudRequestError } from "../host/transport";
import type { SplunkLogsStatus } from "../api/types";
import { ConnectionBadge, EditingBadge, ExportControls, ExportToggle, SavedTokenBadge } from "./ExportControls";
import { SecureStorageNotice } from "./SecureStorageNotice";
import { useCloudBridge, type CloudBridgeAction } from "./bridge";

export interface LogsConnectionDetails {
  status: SplunkLogsStatus | null;
  editing: boolean;
  unavailable: boolean;
  failed: boolean;
}

type LogsBinding = Pick<SplunkLogsStatus, "endpoint" | "index" | "source" | "insecureSkipVerify">;
type LogsMutation =
  | { kind: "save"; previousVersion: string; editing: boolean }
  | { kind: "enabled"; previousVersion: string; binding: LogsBinding; enabled: boolean }
  | { kind: "disconnect"; previousVersion: string; sessionOnly?: boolean };

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
  const connectionSubmitRef = useRef<HTMLButtonElement | null>(null);
  const [storagePlatform, setStoragePlatform] = useState<string>();
  const [sessionFallbackAvailable, setSessionFallbackAvailable] = useState(false);
  const [status, setStatus] = useState<SplunkLogsStatus | null>(null);
  const [endpoint, setEndpoint] = useState("");
  const [index, setIndex] = useState("");
  const [token, setToken] = useState("");
  const [insecureSkipVerify, setInsecureSkipVerify] = useState(false);
  const [busy, setBusy] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [disconnectSnapshot, setDisconnectSnapshot] = useState<SplunkLogsStatus | null>(null);
  const disconnectTriggerRef = useRef<HTMLButtonElement | null>(null);
  const disconnectCancelRef = useRef<HTMLButtonElement>(null);
  const disconnectConfirmRef = useRef<HTMLButtonElement>(null);
  const [reloadNeeded, setReloadNeeded] = useState(false);
  const [outcomeUnknown, setOutcomeUnknown] = useState(false);
  const [editing, setEditing] = useState(false);
  const [connectionFailed, setConnectionFailed] = useState(false);
  const [editToken, setEditToken] = useState(false);
  const { bridge, callBridge } = useCloudBridge();
  const rootRef = useRef<HTMLElement>(null);
  const successFocus = useRef<"cleanup" | "endpoint" | "export" | null>(null);
  const editRef = useRef<HTMLButtonElement>(null);
  const editFocus = useRef<"field" | "button" | null>(null);
  const restoreCleanupFocus = useRef(false);
  const [statusUnavailable, setStatusUnavailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<"endpoint" | "token" | "index" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const dirty = useRef(false);
  const draftVersion = useRef<string | undefined>(undefined);
  const inFlight = useRef(false);
  const requestSequence = useRef(0);
  const pendingMutation = useRef<{ mutation: LogsMutation; terminal: boolean } | null>(null);
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
  const mutationsDisabled = disabled || outcomeUnknown;

  useEffect(() => setSessionFallbackAvailable(false), [endpoint, token, index, insecureSkipVerify, status?.version]);

  useEffect(() => {
    if (disconnectSnapshot) disconnectCancelRef.current?.focus();
  }, [disconnectSnapshot]);

  function closeDisconnectDialog() {
    if (inFlight.current) return;
    setDisconnectSnapshot(null);
    window.requestAnimationFrame(() => {
      const trigger = disconnectTriggerRef.current;
      const target = trigger?.isConnected && !trigger.disabled ? trigger : cleanupRef.current ?? endpointRef.current ?? rootRef.current;
      target?.focus();
    });
  }

  function requestDisconnect(event: React.MouseEvent<HTMLButtonElement>) {
    disconnectTriggerRef.current = event.currentTarget;
    setDisconnectSnapshot(status);
  }

  function finishMutation(next: SplunkLogsStatus, mutation: LogsMutation) {
    pendingMutation.current = null;
    setOutcomeUnknown(false);
    setReloadNeeded(false);
    setError(null);
    setSessionFallbackAvailable(false);
    setStatusUnavailable(false);
    setConnectionFailed(false);
    if (mutation.kind !== "enabled") {
      dirty.current = false;
      draftVersion.current = undefined;
      hydrate(next);
      setToken("");
      setEditing(false);
      if (next.cleanupPending && !next.sessionOnly) successFocus.current = "cleanup";
      else successFocus.current = mutation.kind === "disconnect" ? "endpoint" : "export";
      if (mutation.kind === "disconnect") setNotice("Logs disconnected.");
      else setNotice(mutation.editing ? "Logs connection updated." : "Logs connected.");
    }
    reconcileStatus(next, true);
    onSaved?.();
  }

  function observePendingMutation(next: SplunkLogsStatus): boolean {
    const pending = pendingMutation.current;
    if (!pending) return false;
    const mutation = pending.mutation;
    let confirmed: boolean;
    if (mutation.kind === "disconnect") {
      confirmed = !next.tokenConfigured && !next.connected && !next.enabled
        && (mutation.sessionOnly ? next.sessionOnly === true : next.canDisconnect === false && !next.cleanupPending);
    } else if (mutation.kind === "enabled") {
      confirmed = Object.entries(mutation.binding).every(([key, value]) => next[key as keyof LogsBinding] === value)
        && next.enabled === mutation.enabled && next.tokenConfigured;
    } else {
      // Versions change on restart and the saved token is masked. Keep the draft until a save reply acknowledges it.
      confirmed = false;
    }
    if (confirmed) {
      finishMutation(next, mutation);
      return true;
    }
    if (pending.terminal && (mutation.kind === "enabled" || next.version === mutation.previousVersion)) {
      pendingMutation.current = null;
      setOutcomeUnknown(false);
      setReloadNeeded(next.version !== mutation.previousVersion);
    }
    return false;
  }

  function recordMutationFailure(reason: unknown, mutation?: LogsMutation): boolean {
    if (reason instanceof ObserverHostCloudRequestError && reason.retrySafe === true) return false;
    const terminal = reason instanceof SplunkExportBrowserActionError;
    const ambiguous = !terminal || reason.statusCode === 500;
    if (ambiguous) {
      if (mutation) pendingMutation.current = { mutation, terminal };
      setOutcomeUnknown(true);
      setReloadNeeded(true);
    }
    return ambiguous;
  }

  useEffect(() => { onDetailsChange?.({ status, editing, unavailable: statusUnavailable, failed: connectionFailed || sessionFallbackAvailable || fieldError !== null || cleanupPending || outcomeUnknown }); }, [status, editing, statusUnavailable, connectionFailed, sessionFallbackAvailable, fieldError, cleanupPending, outcomeUnknown, onDetailsChange]);
  useEffect(() => {
    if (editing && editFocus.current === "field") {
      editFocus.current = null;
      (editToken ? tokenRef : endpointRef).current?.focus();
    } else if (!editing && editFocus.current === "button") {
      editFocus.current = null;
      editRef.current?.focus();
    }
  }, [editing, editToken]);

  useEffect(() => {
    if (!busy && restoreCleanupFocus.current) {
      restoreCleanupFocus.current = false;
      if (cleanupPending && (document.activeElement === document.body || rootRef.current?.contains(document.activeElement))) cleanupRef.current?.focus();
    }
  }, [status, busy, cleanupPending]);

  useEffect(() => {
    const target = successFocus.current;
    if (!notice || !target) return;
    successFocus.current = null;
    if (document.activeElement !== document.body && !rootRef.current?.contains(document.activeElement)) return;
    if (target === "cleanup") cleanupRef.current?.focus();
    else if (target === "endpoint") endpointRef.current?.focus();
    else exportRef.current?.focus();
  }, [notice]);

  function reconcileStatus(next: SplunkLogsStatus, userInitiated = false) {
    if (userInitiated) restoreCleanupFocus.current = next.cleanupPending === true;
    setStatus(next);
    if (dirty.current && (next.connected ?? Boolean(next.lastExportSuccess))) setEditing(true);
  }

  function hydrate(next: SplunkLogsStatus) {
    const hasConnection = next.configured || next.connected || next.canDisconnect;
    setEndpoint(hasConnection ? next.endpoint ?? "" : "");
    setIndex(hasConnection ? next.index ?? "" : "");
    setInsecureSkipVerify(Boolean(hasConnection && next.insecureSkipVerify));
  }

  async function refresh(signal?: AbortSignal) {
    const sequence = ++requestSequence.current;
    try {
      const next = await fetchSplunkLogsStatus(signal);
      if (
        !mounted.current ||
        signal?.aborted ||
        inFlight.current ||
        sequence !== requestSequence.current
      )
        return;
      if (observePendingMutation(next)) return;
      if (!dirty.current) hydrate(next);
      reconcileStatus(next);
      setStatusUnavailable(false);
    } catch {
      if (
        mounted.current &&
        !signal?.aborted &&
        sequence === requestSequence.current
      ) {
        setStatusUnavailable(true);
      }
    }
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    let timer: number | undefined;
    async function poll() {
      if (!inFlight.current) await refresh(controller.signal);
      if (!controller.signal.aborted) timer = window.setTimeout(() => { void poll(); }, 5000);
    }
    void poll();
    return () => {
      mounted.current = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [refreshKey]);

  function edit() {
    if (!dirty.current) draftVersion.current = status?.version;
    dirty.current = true;
    requestSequence.current += 1;
    setNotice(null);
    setError(null);
    setFieldError(null);
  }

  function beginEdit(tokenOnly = false) {
    if (!status) return;
    editFocus.current = "field";
    draftVersion.current = status.version;
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
    setSessionFallbackAvailable(false);
    draftVersion.current = undefined;
    if (status) hydrate(status);
    setToken("");
    dirty.current = false;
    setError(null);
    setFieldError(null);
    setNotice(null);
    setConnectionFailed(false);
    editFocus.current = "button";
    setEditing(false);
  }

  useEffect(() => {
    if (sessionFallbackAvailable && !busy && document.activeElement === document.body) connectionSubmitRef.current?.focus();
  }, [sessionFallbackAvailable, busy]);

  async function connect(sessionOnly = sessionFallbackAvailable) {
    if (!status || outcomeUnknown || inFlight.current) return;
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
      insecureSkipVerify,
    };
    const mutation: LogsMutation = { kind: "save", previousVersion: status.version, editing };
    inFlight.current = true;
    if (!dirty.current) draftVersion.current = status.version;
    dirty.current = true;
    requestSequence.current += 1;
    setBusy(true);
    setError(null);
    setNotice(null);
    setConnectionFailed(false);
    try {
      const next = await configureSplunkLogs({
        ...settings,
        ...(sessionOnly ? { sessionOnly: true } : {}),
        enabled: editing ? status.enabled : true,
        ...(editing ? { preserveEnabled: true } : {}),
        verifyConnection: true,
        expectedVersion: draftVersion.current ?? status.version,
      });
      if (!mounted.current) return;
      finishMutation(next, mutation);
    } catch (reason) {
      const storageRefused = (reason as { code?: string })?.code === "credential_storage_unavailable";
      setSessionFallbackAvailable(storageRefused);
      if (storageRefused) {
        setStoragePlatform((reason as { platform?: string }).platform);
        setConnectionFailed(false);
        return;
      }
      const uncertain = recordMutationFailure(reason, mutation);
      if (reason instanceof SplunkExportBrowserActionError && reason.statusCode === 409) setReloadNeeded(true);
      setConnectionFailed(true);
      if (mounted.current)
        setError(uncertain && !(reason instanceof SplunkExportBrowserActionError)
          ? "Could not confirm that the connection was saved. Reload saved logs settings before trying again."
          : reason instanceof Error ? reason.message : "Could not connect logs.");
      try {
        const next = await fetchSplunkLogsStatus();
        if (mounted.current) {
          if (observePendingMutation(next)) return;
          reconcileStatus(next, true);
          const nextConnected = next.connected ?? Boolean(next.lastExportSuccess);
          setStatusUnavailable(false);
          if (!editing && nextConnected) setEditing(true);
        }
      } catch {
        // Retain the draft until saved state can be confirmed.
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setBusy(false);
        window.requestAnimationFrame(() => { if (document.activeElement === document.body) (cleanupRef.current ?? connectionSubmitRef.current)?.focus(); });
      }
    }
  }

  async function toggleExport() {
    setSessionFallbackAvailable(false);
    if (!status || outcomeUnknown || inFlight.current || (dirty.current && !status.enabled)) return;
    const mutation: LogsMutation = { kind: "enabled", previousVersion: status.version, binding: {
      endpoint: status.endpoint, index: status.index, source: status.source, insecureSkipVerify: status.insecureSkipVerify,
    }, enabled: !status.enabled };
    inFlight.current = true;
    requestSequence.current += 1;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await setSplunkLogsEnabled(!status.enabled, status.version);
      if (!mounted.current) return;
      finishMutation(next, mutation);
    } catch (reason) {
      recordMutationFailure(reason, mutation);
      if (reason instanceof SplunkExportBrowserActionError && reason.statusCode === 409) setReloadNeeded(true);
      if (mounted.current) setError(reason instanceof Error ? reason.message : "Could not update logs export.");
      try {
        const next = await fetchSplunkLogsStatus();
        if (mounted.current && !observePendingMutation(next)) reconcileStatus(next, true);
      } catch {
        // Normal polling retries when the collector is available again.
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function disconnect() {
    setSessionFallbackAvailable(false);
    if (!disconnectSnapshot || mutationsDisabled || statusUnavailable || inFlight.current) return;
    const mutation: LogsMutation = { kind: "disconnect", previousVersion: disconnectSnapshot.version, sessionOnly: disconnectSnapshot.sessionOnly };
    inFlight.current = true;
    requestSequence.current += 1;
    setBusy(true);
    setDisconnecting(true);
    setError(null);
    setFieldError(null);
    setNotice(null);
    try {
      const next = await disconnectSplunkLogs(disconnectSnapshot.version);
      if (!mounted.current) return;
      finishMutation(next, mutation);
    } catch (reason) {
      recordMutationFailure(reason, mutation);
      if (reason instanceof SplunkExportBrowserActionError && reason.statusCode === 409) setReloadNeeded(true);
      if (mounted.current) setError(reason instanceof Error ? reason.message : "Could not disconnect logs.");
      try {
        const next = await fetchSplunkLogsStatus();
        if (mounted.current && !observePendingMutation(next)) reconcileStatus(next, true);
      } catch {
        // Keep the connection visible until its state can be confirmed.
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setBusy(false);
        setDisconnecting(false);
        closeDisconnectDialog();
      }
    }
  }

  async function reload() {
    setSessionFallbackAvailable(false);
    if (inFlight.current) return;
    inFlight.current = true;
    requestSequence.current += 1;
    setBusy(true);
    setError(null);
    try {
      const next = await refreshSplunkLogs();
      if (!mounted.current) return;
      if (observePendingMutation(next)) return;
      pendingMutation.current = null;
      setOutcomeUnknown(false);
      draftVersion.current = dirty.current ? next.version : undefined;
      reconcileStatus(next, true);
      if (!dirty.current) hydrate(next);
      setStatusUnavailable(false);
      setReloadNeeded(false);
      setConnectionFailed(false);
      onSaved?.();
      window.requestAnimationFrame(() => {
        if (document.activeElement !== document.body && !rootRef.current?.contains(document.activeElement)) return;
        if (next.connected && !dirty.current && !editing) exportRef.current?.focus();
        else endpointRef.current?.focus();
      });
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : "Could not reload saved logs settings.");
      try {
        const next = await fetchSplunkLogsStatus();
        if (mounted.current && !observePendingMutation(next)) reconcileStatus(next, true);
      } catch {
        // Retain the recovery action until saved settings can be read.
      }
      window.requestAnimationFrame(() => {
        if (document.activeElement === document.body || document.activeElement === cleanupRef.current)
          (cleanupRef.current ?? exportRef.current ?? endpointRef.current)?.focus();
      });
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const badge = statusUnavailable ? "Unavailable" : !status ? "Loading" : rejected ? "Rejected"
    : status?.lastExportError ? "Connection failed" : sessionFallbackAvailable ? "Secure storage unavailable" : connected ? "Connected" : connectionFailed ? "Connection failed" : "Not connected";
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
    <section ref={rootRef} tabIndex={-1} aria-labelledby="cloud-logs-title" className={`cloud-panel cloud-logs cloud-destination cloud-destination--logs${connected ? " cloud-destination--connected" : ""}${editing ? " cloud-destination--editing" : ""}${rejected ? " cloud-destination--rejected" : ""}`}>
      <header className="cloud-panel__header">
        <h2 id="cloud-logs-title">Splunk Platform</h2>
        {connected ? <code className="destination-identifier" title={status?.endpoint}>{host} · {status?.index}</code> : <>
          <span className="destination-chip">Logs</span>
        </>}
        <ConnectionBadge state={badge} />
        {editing ? <EditingBadge /> : connected && status && !statusUnavailable ? (
          <ExportToggle enabled={status.enabled} busy={busy} disabled={mutationsDisabled} onToggle={() => void toggleExport()} switchLabel="Logs export" buttonRef={exportRef} />
        ) : null}
      </header>
      {editing ? <p className="destination-editing-note">{status?.sessionOnly ? "The session connection stays in use until you save." : "Saved settings stay in use until you save."}</p> : null}
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
          <button className="cloud-button" disabled={busy || mutationsDisabled || statusUnavailable}
            aria-label="Edit token for Splunk Platform" onClick={() => beginEdit(rejected)} ref={editRef} type="button">Edit token</button>
          <button aria-label="Disconnect Splunk Platform" className="cloud-button cloud-button--danger" disabled={busy || mutationsDisabled || statusUnavailable}
            onClick={requestDisconnect} type="button">Disconnect</button>
          {searchURL && !rejected ? <a className="destination-open-link" href={bridge ? "#" : searchURL} target={bridge ? undefined : "_blank"} rel={bridge ? undefined : "noopener noreferrer"}
            onClick={(event) => openExternal(event, "open-splunk-search")}>Search index {status.index}</a> : null}
          {rejected ? <span className="destination-footnote">Update the token to resume exporting new logs.</span> : null}
        </div>
      </> : null}
      <div className={showForm ? "cloud-logs__form destination-body" : "destination-feedback"} aria-busy={busy}>
        <span className="visually-hidden">{!status ? "Loading" : !status.configured ? "Not configured" : status.enabled ? "Forwarding on" : connected ? "Paused" : ""}</span>
        {displayedError ? <p className="cloud-field__error" role="alert" id="cloud-logs-error">{displayedError}</p> : null}
        {notice ? <p className="visually-hidden" role="status">{notice}</p> : null}
        {cleanupPending ? <p className="destination-buffered" role="status">{status?.sessionOnly ? "Credential cleanup is pending. Save a connection after secure storage is available to retry." : "Credential cleanup is pending. Unlock secure storage, then retry."}</p> : null}
        {cleanupPending && !status?.sessionOnly || reloadNeeded || canDisconnect && !status?.tokenConfigured ? <div className="destination-actions destination-actions--form">
          <button className="cloud-button" disabled={busy || disabled} ref={cleanupRef} onClick={() => void reload()} type="button">{cleanupPending && !status?.sessionOnly ? "Retry credential cleanup" : status?.sessionOnly ? "Reload session connection" : "Reload saved logs settings"}</button>
        </div> : null}
        {showForm ? <form aria-label="Logs connection" noValidate onSubmit={(event) => { event.preventDefault(); void connect(); }}>
          <fieldset disabled={!status || busy || mutationsDisabled}>
            <div className="cloud-field destination-field">
              <div className="destination-label-row"><label className="cloud-field__label" htmlFor="cloud-logs-endpoint">HEC endpoint</label>
                <a href={bridge ? "#" : hecEndpointHelpURL} target={bridge ? undefined : "_blank"} rel={bridge ? undefined : "noopener noreferrer"}
                  onClick={(event) => openExternal(event, "open-hec-endpoint-help")}>Find your HEC endpoint</a>
              </div>
              <input id="cloud-logs-endpoint" type="url" autoComplete="off" spellCheck={false}
                aria-invalid={fieldError === "endpoint"} aria-describedby={fieldError === "endpoint" ? "cloud-logs-error cloud-logs-endpoint-help" : "cloud-logs-endpoint-help"}
                placeholder="HEC endpoint" value={endpoint} ref={endpointRef}
                onChange={(event) => { edit(); if (event.target.value.trim() !== endpoint.trim()) setInsecureSkipVerify(false); setEndpoint(event.target.value); }} />
              <small id="cloud-logs-endpoint-help">Enter the full HEC ingestion URL, including /services/collector/event.</small>
            </div>
            <div className="cloud-field destination-field">
              <div className="destination-label-row"><label className="cloud-field__label" htmlFor="cloud-logs-token">HEC token</label>
                <a href={bridge ? "#" : hecTokenHelpURL} target={bridge ? undefined : "_blank"} rel={bridge ? undefined : "noopener noreferrer"}
                  onClick={(event) => openExternal(event, "open-hec-token-help")}>Find your HEC token</a>
              </div>
              <div className="destination-token">
                <input id="cloud-logs-token" type="password" autoComplete="new-password" spellCheck={false}
                  aria-invalid={fieldError === "token"}
                  placeholder={status?.tokenConfigured ? "Paste a new token to replace" : "Paste token"} value={token} ref={tokenRef}
                  onChange={(event) => { edit(); setToken(event.target.value); }} aria-describedby={[fieldError === "token" ? "cloud-logs-error" : savedToken ? "cloud-logs-token-help" : "", sessionFallbackAvailable ? "cloud-logs-storage-help" : ""].filter(Boolean).join(" ") || undefined} />
                {savedToken && !status?.sessionOnly ? <SavedTokenBadge /> : null}
              </div>
              {sessionFallbackAvailable ? <SecureStorageNotice id="cloud-logs-storage-help" platform={storagePlatform} editing={editing} onOpenHelp={(event, platform) => {
                setSessionFallbackAvailable(false);
                if (bridge) {
                  event.preventDefault();
                  void callBridge("open-credential-storage-help", platform ? { platform } : undefined).catch((reason) => setError(reason instanceof Error ? reason.message : "Could not open secure storage help."));
                }
                window.requestAnimationFrame(() => connectionSubmitRef.current?.focus());
              }} /> : null}
              {savedToken ? <small id="cloud-logs-token-help">{status?.sessionOnly ? "Leave blank to keep the session token." : "Leave blank to keep the saved token."}</small> : null}
            </div>
            <div className="cloud-field destination-field destination-field--short">
              <label className="cloud-field__label" htmlFor="cloud-logs-index">Logs index</label>
              <input id="cloud-logs-index" value={index} ref={indexRef} onChange={(event) => { edit(); setIndex(event.target.value); }} placeholder="Index"
                aria-invalid={fieldError === "index"} aria-describedby={fieldError === "index" ? "cloud-logs-error" : undefined} />
              <small>Must already accept events from this token.</small>
            </div>
            <div className="destination-tls">
              <label htmlFor="cloud-logs-insecure">
                <input id="cloud-logs-insecure" type="checkbox" checked={insecureSkipVerify}
                  aria-describedby="cloud-logs-insecure-help"
                  onChange={(event) => { edit(); setInsecureSkipVerify(event.target.checked); }} />
                Skip TLS certificate verification
              </label>
              <small id="cloud-logs-insecure-help">Enabling this skips server identity checks.</small>
            </div>
            <div className="destination-actions destination-actions--form">
              <button aria-label={sessionFallbackAvailable ? editing ? "Save Splunk Platform for this session" : "Connect Splunk Platform for this session" : editing ? "Save Splunk Platform changes" : "Connect Splunk Platform"} ref={connectionSubmitRef} className="cloud-button cloud-button--primary" type="submit">
                {busy ? editing ? "Saving..." : "Connecting..." : sessionFallbackAvailable ? editing ? "Save for this session" : "Connect for this session" : editing ? "Save changes" : "Connect"}
              </button>
              {editing ? <button className="cloud-button" onClick={cancelEdit} type="button">Cancel</button> : <span className="destination-inline-help">No Splunk instance yet? <a className="destination-text-button" href={bridge ? "#" : splunkPlatformTrialURL} target={bridge ? undefined : "_blank"} rel={bridge ? undefined : "noopener noreferrer"} onClick={(event) => openExternal(event, "open-splunk-platform-trial")}>Start a free trial</a></span>}
              {editing || canDisconnect ? <button aria-label="Disconnect Splunk Platform" className="cloud-button cloud-button--danger destination-disconnect" disabled={statusUnavailable} onClick={requestDisconnect} type="button">Disconnect</button> : null}
            </div>
          </fieldset>
        </form> : null}
      </div>
      {disconnectSnapshot ? <div className="cloud-dialog-backdrop" onMouseDown={(event) => {
        if (event.currentTarget !== event.target) return;
        event.preventDefault();
        if (!disconnecting) closeDisconnectDialog();
      }}>
        <section className="cloud-dialog" role="dialog" aria-modal="true" tabIndex={-1}
          aria-labelledby="cloud-logs-disconnect-title" aria-describedby="cloud-logs-disconnect-description"
          aria-busy={disconnecting}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !disconnecting) {
              event.preventDefault();
              closeDisconnectDialog();
            }
            if (event.key !== "Tab") return;
            if (disconnecting) { event.preventDefault(); return; }
            const first = disconnectCancelRef.current;
            const last = disconnectConfirmRef.current;
            const active = document.activeElement;
            if (event.shiftKey && (active === first || active === event.currentTarget)) {
              event.preventDefault(); last?.focus();
            } else if (!event.shiftKey && (active === last || active === event.currentTarget)) {
              event.preventDefault(); first?.focus();
            }
          }}>
          <h2 id="cloud-logs-disconnect-title">Disconnect Splunk Platform?</h2>
          <p id="cloud-logs-disconnect-description">{disconnectSnapshot.sessionOnly ? "This clears the token from this session and turns off logs export. Logs remain available locally." : "This removes the saved HEC token and turns off logs export. Logs remain available locally."}</p>
          {!disconnecting && (mutationsDisabled || statusUnavailable) ? <p role="alert">Disconnect is unavailable. Cancel to review the connection status.</p> : null}
          <div>
            <button className="cloud-button" aria-disabled={disconnecting} ref={disconnectCancelRef} onClick={closeDisconnectDialog} type="button">Cancel</button>
            <button className="cloud-button cloud-button--danger" aria-disabled={busy || mutationsDisabled || statusUnavailable}
              aria-label="Disconnect Splunk Platform" ref={disconnectConfirmRef} onClick={() => void disconnect()} type="button">{disconnecting ? "Disconnecting..." : "Disconnect"}</button>
          </div>
        </section>
      </div> : null}
    </section>
  );
}

const splunkPlatformTrialURL = "https://www.splunk.com/en_us/download/splunk-cloud.html";

export function isLogsRejected(status: SplunkLogsStatus | null): boolean {
  return Boolean(status?.lastExportError && (status.lastHTTPStatus === 401 || status.lastHTTPStatus === 403 || status.lastHECCode === 4));
}
