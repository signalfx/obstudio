import type {
  LogRecord,
  MetricGroup,
  SISCIMDLoginStartResult,
  SISCIMDRegistrationResult,
  SISCIMDSessionStatus,
  SplunkExportStatus,
  TraceDetail,
  TraceSummary,
} from "./types";
import type { PreviewResponse } from "../dashboards/types";
import { observerFetch } from "../host/transport";

const BASE = "";
type QueryScalar = string | number;

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await observerFetch(`${BASE}${path}`, init);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function normalizeArrayResponse<T>(value: T[] | null): T[] {
  return Array.isArray(value) ? value : [];
}

export interface RangeQueryValue {
  gt?: QueryScalar;
  gte?: QueryScalar;
  lt?: QueryScalar;
  lte?: QueryScalar;
}

export interface TimeQuery {
  after?: string;
  before?: string;
  from?: string;
  to?: string;
}

interface StructuredQuery {
  filters?: Record<string, QueryScalar | undefined>;
  notFilters?: Record<string, QueryScalar | undefined>;
  ranges?: Record<string, RangeQueryValue | undefined>;
  time?: TimeQuery;
  limit?: number;
  query?: string;
}

export interface MetricsQuery extends StructuredQuery {}

export interface TracesQuery extends StructuredQuery {}

export interface LogsQuery extends StructuredQuery {}

function buildSearchParams(query: StructuredQuery): URLSearchParams {
  const search = new URLSearchParams();
  if (query.query) {
    search.set("query", query.query);
  }
  if (query.limit !== undefined) {
    search.set("limit", String(query.limit));
  }
  for (const [key, value] of Object.entries(query.filters ?? {})) {
    if (value === undefined || value === "") continue;
    search.set(`filter[${key}][eq]`, String(value));
  }
  for (const [key, value] of Object.entries(query.notFilters ?? {})) {
    if (value === undefined || value === "") continue;
    search.set(`filter[${key}][neq]`, String(value));
  }
  for (const [key, value] of Object.entries(query.ranges ?? {})) {
    if (!value) continue;
    if (value.gt !== undefined && value.gt !== "") {
      search.set(`range[${key}][gt]`, String(value.gt));
    }
    if (value.gte !== undefined && value.gte !== "") {
      search.set(`range[${key}][gte]`, String(value.gte));
    }
    if (value.lt !== undefined && value.lt !== "") {
      search.set(`range[${key}][lt]`, String(value.lt));
    }
    if (value.lte !== undefined && value.lte !== "") {
      search.set(`range[${key}][lte]`, String(value.lte));
    }
  }
  if (query.time?.after) {
    search.set("time[after]", query.time.after);
  }
  if (query.time?.before) {
    search.set("time[before]", query.time.before);
  }
  if (query.time?.from) {
    search.set("time[from]", query.time.from);
  }
  if (query.time?.to) {
    search.set("time[to]", query.time.to);
  }
  return search;
}

function buildQueryString(query: StructuredQuery): string {
  const search = buildSearchParams(query);
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

function buildValueSuggestionsQueryString(field: string, prefix: string, query: StructuredQuery, limit = 20): string {
  const search = buildSearchParams(query);
  search.set("field", field);
  search.set("limit", String(limit));
  if (prefix.trim() !== "") {
    search.set("prefix", prefix);
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

/** Fetch full trace detail (all spans) for a given trace ID. */
export async function fetchTraceDetail(traceId: string): Promise<TraceDetail> {
  return fetchJSON(`/api/query/traces/${traceId}`);
}

/** Fetch trace summaries using the REST query endpoint with optional server-side filters. */
export async function fetchTraces(query: TracesQuery = {}, signal?: AbortSignal): Promise<TraceSummary[]> {
  const qs = buildQueryString(query);
  const data = await fetchJSON<TraceSummary[] | null>(`/api/query/traces${qs}`, { signal });
  return normalizeArrayResponse(data);
}

/** Fetch metric groups using the REST query endpoint with optional server-side filters. */
export async function fetchMetrics(query: MetricsQuery = {}, signal?: AbortSignal): Promise<MetricGroup[]> {
  const qs = buildQueryString(query);
  const data = await fetchJSON<MetricGroup[] | null>(`/api/query/metrics${qs}`, { signal });
  return normalizeArrayResponse(data);
}

/** Fetch log records using the REST query endpoint with optional server-side filters. */
export async function fetchLogs(query: LogsQuery = {}, signal?: AbortSignal): Promise<LogRecord[]> {
  const qs = buildQueryString(query);
  const data = await fetchJSON<LogRecord[] | null>(`/api/query/logs${qs}`, { signal });
  return normalizeArrayResponse(data);
}

async function fetchValueSuggestions(path: string, field: string, prefix: string, query: StructuredQuery = {}, signal?: AbortSignal): Promise<string[]> {
  const qs = buildValueSuggestionsQueryString(field, prefix, query);
  const data = await fetchJSON<string[] | null>(`${path}${qs}`, { signal });
  return normalizeArrayResponse(data);
}

export async function fetchTraceFilterValues(field: string, prefix: string, query: TracesQuery = {}, signal?: AbortSignal): Promise<string[]> {
  return fetchValueSuggestions("/api/query/traces/filter-values", field, prefix, query, signal);
}

export async function fetchMetricFilterValues(field: string, prefix: string, query: MetricsQuery = {}, signal?: AbortSignal): Promise<string[]> {
  return fetchValueSuggestions("/api/query/metrics/filter-values", field, prefix, query, signal);
}

export async function fetchLogFilterValues(field: string, prefix: string, query: LogsQuery = {}, signal?: AbortSignal): Promise<string[]> {
  return fetchValueSuggestions("/api/query/logs/filter-values", field, prefix, query, signal);
}

/**
 * Fetch the approximate local-data dashboard preview. Returns the full
 * PreviewResponse, including the available:false case (the caller renders an
 * actionable empty state from `message`).
 */
export async function fetchDashboardPreview(signal?: AbortSignal): Promise<PreviewResponse> {
  return fetchJSON<PreviewResponse>("/api/dashboards/preview", { signal });
}

/** Fetch secret-free Splunk Observability Cloud export status. */
export async function fetchSplunkExportStatus(signal?: AbortSignal): Promise<SplunkExportStatus> {
  return fetchJSON<SplunkExportStatus>("/api/splunk/export", { signal });
}

export type SplunkExportBrowserAction = "connect" | "forget" | "set-enabled";

export class SplunkExportBrowserActionError extends Error {
  constructor(
    message: string,
    readonly statusCode: number,
  ) {
    super(message);
    this.name = "SplunkExportBrowserActionError";
  }
}

export function isUnusableSplunkExportBrowserSession(error: unknown): boolean {
  return error instanceof SplunkExportBrowserActionError
    && error.statusCode === 401
    && error.message === "browser cloud control session is not valid";
}

const splunkBrowserRequestHeader = "X-Obstudio-Browser-Request";
const splunkBrowserTokenHeader = "X-Obstudio-Browser-Token";
const splunkBrowserLaunchFragmentKey = "obstudio-cloud-control";
const splunkBrowserSessionStorageKey = "obstudio.cloud.browser-session.v1";
const splunkBrowserLaunchPattern = /^[A-Za-z0-9_-]{43}$/;
const splunkBrowserSessionPattern = /^[A-Za-z0-9_-]{43}$/;

export interface SplunkExportBrowserSession {
  browserToken: string;
  warning?: string;
}

interface PendingSplunkBrowserSession {
  controller: AbortController;
  operation: Promise<SplunkExportBrowserSession>;
  waiters: number;
}

let pendingSplunkBrowserSession: PendingSplunkBrowserSession | null = null;

/** Create an in-memory, same-origin control session for the standalone browser UI. */
export function createSplunkExportBrowserSession(signal?: AbortSignal): Promise<SplunkExportBrowserSession> {
  if (pendingSplunkBrowserSession === null) {
    const controller = new AbortController();
    const operation = issueSplunkExportBrowserSession(controller.signal);
    const pending = { controller, operation, waiters: 0 };
    pendingSplunkBrowserSession = pending;
    void operation.then(
      () => {
        if (pendingSplunkBrowserSession === pending) pendingSplunkBrowserSession = null;
      },
      () => {
        if (pendingSplunkBrowserSession === pending) pendingSplunkBrowserSession = null;
      },
    );
  }
  const pending = pendingSplunkBrowserSession;
  pending.waiters += 1;
  return waitForSplunkBrowserSession(pending.operation, signal).finally(() => {
    pending.waiters -= 1;
    queueMicrotask(() => {
      if (pendingSplunkBrowserSession === pending && pending.waiters === 0) {
        pendingSplunkBrowserSession = null;
        pending.controller.abort();
      }
    });
  });
}

async function issueSplunkExportBrowserSession(signal: AbortSignal): Promise<SplunkExportBrowserSession> {
  const launchToken = readSplunkBrowserLaunchToken();
  const storedBrowserToken = readStoredSplunkBrowserToken();
  const requestBody = { launchToken };
  let response: unknown;
  try {
    response = await postSplunkExportBrowserJSON(
      "/api/splunk/export/browser/session",
      requestBody,
      storedBrowserToken || undefined,
      signal,
    );
  } catch (error) {
    if (signal.aborted) throw error;
    if (error instanceof SplunkExportBrowserActionError) {
      if (error.statusCode !== 401 || (!launchToken && !storedBrowserToken)) throw error;
      clearStoredSplunkBrowserToken();
      clearSplunkBrowserLaunchFragment();
      response = await postSplunkExportBrowserJSON(
        "/api/splunk/export/browser/session",
        { launchToken: "" },
        undefined,
        signal,
      );
    } else {
      response = await postSplunkExportBrowserJSON(
        "/api/splunk/export/browser/session",
        requestBody,
        storedBrowserToken || undefined,
        signal,
      );
    }
  }
  const token = typeof response === "object"
    && response !== null
    && typeof (response as Record<string, unknown>).browserToken === "string"
    ? (response as Record<string, string>).browserToken
    : "";
  if (!splunkBrowserSessionPattern.test(token)) {
    throw new Error("Observer returned an invalid browser cloud control session.");
  }
  storeSplunkBrowserToken(token);
  clearSplunkBrowserLaunchFragment();
  const warning = typeof response === "object"
    && response !== null
    && typeof (response as Record<string, unknown>).warning === "string"
    ? (response as Record<string, string>).warning.trim()
    : "";
  return warning ? { browserToken: token, warning } : { browserToken: token };
}

function waitForSplunkBrowserSession(
  operation: Promise<SplunkExportBrowserSession>,
  signal?: AbortSignal,
): Promise<SplunkExportBrowserSession> {
  if (!signal) return operation;
  if (signal.aborted) return Promise.reject(new DOMException("The operation was aborted.", "AbortError"));
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException("The operation was aborted.", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
    void operation.then(
      (token) => {
        signal.removeEventListener("abort", abort);
        resolve(token);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", abort);
        reject(error);
      },
    );
  });
}

function readSplunkBrowserLaunchToken(): string {
  const fragment = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  const fragmentParameters = new URLSearchParams(fragment);
  const fragmentToken = fragmentParameters.get(splunkBrowserLaunchFragmentKey)?.trim() ?? "";
  return splunkBrowserLaunchPattern.test(fragmentToken) ? fragmentToken : "";
}

function clearSplunkBrowserLaunchFragment(): void {
  const fragment = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  const fragmentParameters = new URLSearchParams(fragment);
  if (fragmentParameters.has(splunkBrowserLaunchFragmentKey)) {
    fragmentParameters.delete(splunkBrowserLaunchFragmentKey);
    const remainingFragment = fragmentParameters.toString();
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}${remainingFragment ? `#${remainingFragment}` : ""}`,
    );
  }
}

function readStoredSplunkBrowserToken(): string {
  try {
    const token = window.sessionStorage.getItem(splunkBrowserSessionStorageKey)?.trim() ?? "";
    return splunkBrowserSessionPattern.test(token) ? token : "";
  } catch {
    return "";
  }
}

function storeSplunkBrowserToken(token: string): void {
  try {
    window.sessionStorage.setItem(splunkBrowserSessionStorageKey, token);
  } catch {
    // The in-memory browser session remains usable until the page reloads.
  }
}

function clearStoredSplunkBrowserToken(): void {
  try {
    window.sessionStorage.removeItem(splunkBrowserSessionStorageKey);
  } catch {
    // The in-memory token is still discarded by the caller.
  }
}

/** Replace an invalid process session without replaying the failed mutation. */
export function recoverSplunkExportBrowserSession(
  signal?: AbortSignal,
): Promise<SplunkExportBrowserSession> {
  clearStoredSplunkBrowserToken();
  clearSplunkBrowserLaunchFragment();
  return createSplunkExportBrowserSession(signal);
}

/** Run a cloud mutation directly from the trusted standalone browser origin. */
export async function runSplunkExportBrowserAction(
  action: SplunkExportBrowserAction,
  payload: {
    accessToken?: string;
    enabled?: boolean;
    expectedVersion: string;
    realm?: string;
  },
  browserToken: string,
): Promise<SplunkExportStatus> {
  const path = action === "connect"
    ? "/api/splunk/export"
    : action === "forget"
      ? "/api/splunk/export/forget"
      : "/api/splunk/export/enabled";
  return postSplunkExportBrowserJSON(path, payload, browserToken) as Promise<SplunkExportStatus>;
}

/** Resolve a pasted Splunk URL to its canonical realm without sending an access token. */
export async function resolveSplunkCloudRealm(
  destination: string,
  browserToken: string,
): Promise<string> {
  const response = await postSplunkExportBrowserJSON(
    "/api/splunk/export/realm",
    { destination },
    browserToken,
  );
  const realm = typeof response === "object"
    && response !== null
    && typeof (response as Record<string, unknown>).realm === "string"
    ? (response as Record<string, string>).realm
    : "";
  if (!/^[a-z]{2,12}[0-9]+$/.test(realm)) {
    throw new Error("Observer returned an invalid Splunk Observability Cloud realm.");
  }
  return realm;
}

async function postSplunkExportBrowserJSON(
  path: string,
  body: object,
  browserToken?: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    [splunkBrowserRequestHeader]: "1",
  };
  if (browserToken) headers[splunkBrowserTokenHeader] = browserToken;
  const response = await observerFetch(`${BASE}${path}`, {
    body: JSON.stringify(body),
    cache: "no-store",
    credentials: "same-origin",
    headers,
    method: "POST",
    signal,
  });
  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }
  if (!response.ok) {
    const message = typeof parsed === "object"
      && parsed !== null
      && typeof (parsed as Record<string, unknown>).error === "string"
      ? (parsed as Record<string, string>).error
      : `Observer request failed with HTTP ${response.status}.`;
    throw new SplunkExportBrowserActionError(message, response.status);
  }
  return parsed;
}

/**
 * Probe SIS CIMD client registration directly through Observer's own backend, for use
 * when there is no IDE bridge (e.g. standalone `go run ./cmd/obstudio` + browser dev).
 * Stores no secret, but the probe itself has side effects on SIS and its response
 * reveals federation redirect/cookie details, so -- like the sibling login routes below
 * -- it is gated by the Observer control token; see the route comment in
 * sis_cimd_register.go.
 */
export async function registerSISCIMDClient(signal?: AbortSignal): Promise<SISCIMDRegistrationResult> {
  return fetchSISCIMDGated<SISCIMDRegistrationResult>("/api/splunk/cimd/register", { method: "POST", signal });
}

/**
 * Observer's own auto-generated Observer control token, injected into index.html only
 * for the page Observer itself serves (see injectControlToken in server.go) -- never
 * fetchable cross-origin, unlike a plain JSON API response. Required to call the
 * gated SIS CIMD login/session routes below when there is no IDE bridge.
 */
function observerControlToken(): string | undefined {
  const token = (window as unknown as { __OBSTUDIO_CONTROL_TOKEN__?: unknown }).__OBSTUDIO_CONTROL_TOKEN__;
  return typeof token === "string" && token !== "" ? token : undefined;
}

async function fetchSISCIMDGated<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = observerControlToken();
  if (!token) {
    throw new Error("Observer did not provide a control token for this page. Reload the Cloud tab and try again.");
  }
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${token}` },
  });
  return parseSISCIMDJSONResponse<T>(response);
}

async function parseSISCIMDJSONResponse<T>(response: Response): Promise<T> {
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const message = body && typeof body === "object" && "error" in body && typeof body.error === "string"
      ? body.error
      : `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return body as T;
}

/**
 * Start SIS CIMD sign-in directly through Observer's own backend, for use when there is
 * no IDE bridge. Returns the authorization URL for the caller to open (e.g.
 * window.open from the click handler, to avoid popup blockers) -- the actual token
 * exchange happens in the background on Observer; poll fetchSISCIMDSession for the
 * result. Requires Observer's own injected control token; see observerControlToken.
 */
export async function loginSISCIMD(): Promise<SISCIMDLoginStartResult> {
  return fetchSISCIMDGated<SISCIMDLoginStartResult>("/api/splunk/cimd/login", { method: "POST" });
}

/** Poll the redacted SIS CIMD session status. Never returns a raw access token. */
export async function fetchSISCIMDSession(signal?: AbortSignal): Promise<SISCIMDSessionStatus> {
  return fetchSISCIMDGated<SISCIMDSessionStatus>("/api/splunk/cimd/session", { signal });
}

/** Clear the in-memory SIS CIMD session held by Observer's own backend. */
export async function disconnectSISCIMDSession(): Promise<SISCIMDSessionStatus> {
  return fetchSISCIMDGated<SISCIMDSessionStatus>("/api/splunk/cimd/session/disconnect", { method: "POST" });
}

/** Fetch per-service aggregates computed from the full span store. */
export async function fetchServiceStats(signal?: AbortSignal): Promise<ServiceStats[]> {
  const data = await fetchJSON<ServiceStats[] | null>("/api/query/stats/services", { signal });
  return Array.isArray(data) ? data : [];
}

export interface ServiceStats {
  name: string;
  traceCount: number;
  spanCount: number;
  errorCount: number;
  avgDurationMs: number | null;
  avgClientDurationMs: number | null;
  avgServerDurationMs: number | null;
}

/** One scored line item behind an instrumentation score. */
export interface InstrumentationScoreComponent {
  label: string;
  earned: number;
  max: number;
  detail: string;
}

/**
 * Instrumentation score derived from `.observe/otel-audit.json`, the canonical
 * report written by `$otel-audit`. `available` is false when no audit exists.
 */
export interface InstrumentationScore {
  available: boolean;
  source: string;
  message?: string;
  serviceName?: string;
  language?: string;
  framework?: string;
  generatedAt?: string;
  score: number;
  breakdown: {
    coverage: number;
    coverageMax: number;
    quality: number;
    qualityMax: number;
    components: InstrumentationScoreComponent[];
  };
  /** The audit's own verdict: Pass, Partial, or Blocked. */
  status?: string;
  /** Commit the audit ran against, and the checkout's current HEAD. */
  auditCommit?: string;
  workspaceCommit?: string;
  /**
   * Whether the audit no longer describes the working tree, and which check
   * found it: "commit" when HEAD moved, "changes" when files were edited after
   * the audit was written. Both are conservative — anything indeterminate
   * reports not-stale rather than warning wrongly.
   */
  stale: boolean;
  staleReason?: "commit" | "changes";
  /** Whether the skill's human-readable otel.html sits next to the JSON. */
  hasHtmlReport: boolean;
  hasSpans: boolean;
  hasMetrics: boolean;
  hasLogs: boolean;
  gapCount: number;
  antiPatternCount: number;
  recommendationCount: number;
  /** Verbatim bullet text from the report's corresponding sections. */
  gaps: string[];
  antiPatterns: string[];
  recommendations: string[];
}

/** Fetch the instrumentation score derived from the latest $otel-audit report. */
export async function fetchInstrumentationScore(signal?: AbortSignal): Promise<InstrumentationScore> {
  return fetchJSON<InstrumentationScore>("/api/audit/score", { signal });
}
