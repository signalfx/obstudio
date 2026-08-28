import type { LogRecord, MetricGroup, SplunkExportStatus, TraceDetail, TraceSummary } from "./types";
import type { PreviewResponse } from "../dashboards/types";

const BASE = "";
type QueryScalar = string | number;

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
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

const unusableSplunkBrowserSessionMessages = new Set([
  "browser cloud control session is not valid",
  // Mixed-version compatibility with Observers that used the former timed-session wording.
  "browser cloud control session expired; reload Observer",
]);

export function isUnusableSplunkExportBrowserSession(error: unknown): boolean {
  return error instanceof SplunkExportBrowserActionError
    && error.statusCode === 401
    && unusableSplunkBrowserSessionMessages.has(error.message);
}

const splunkBrowserRequestHeader = "X-Obstudio-Browser-Request";
const splunkBrowserTokenHeader = "X-Obstudio-Browser-Token";
const splunkBrowserLaunchFragmentKey = "obstudio-cloud-control";
const splunkBrowserSessionStorageKey = "obstudio.cloud.browser-session.v1";
const splunkBrowserLaunchPattern = /^[A-Za-z0-9_-]{43}$/;
const splunkBrowserSessionPattern = /^[A-Za-z0-9_-]{76}$/;
let pendingSplunkBrowserSession: Promise<string> | null = null;

/** Create an in-memory, same-origin control session for the standalone browser UI. */
export function createSplunkExportBrowserSession(signal?: AbortSignal): Promise<string> {
  if (pendingSplunkBrowserSession === null) {
    const operation = issueSplunkExportBrowserSession();
    pendingSplunkBrowserSession = operation;
    void operation.then(
      () => {
        if (pendingSplunkBrowserSession === operation) pendingSplunkBrowserSession = null;
      },
      () => {
        if (pendingSplunkBrowserSession === operation) pendingSplunkBrowserSession = null;
      },
    );
  }
  return waitForSplunkBrowserSession(pendingSplunkBrowserSession, signal);
}

async function issueSplunkExportBrowserSession(): Promise<string> {
  const launchToken = readSplunkBrowserLaunchToken();
  const storedBrowserToken = readStoredSplunkBrowserToken();
  if (!launchToken && !storedBrowserToken) {
    throw new Error("Open Observer using the secure Telemetry Explorer URL printed by the Observer process.");
  }
  const response = await postSplunkExportBrowserJSON(
    "/api/splunk/export/browser/session",
    { launchToken },
    storedBrowserToken || undefined,
  );
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
  return token;
}

function waitForSplunkBrowserSession(
  operation: Promise<string>,
  signal?: AbortSignal,
): Promise<string> {
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

/** Run a cloud mutation directly from the trusted standalone browser origin. */
export async function runSplunkExportBrowserAction(
  action: SplunkExportBrowserAction,
  payload: { accessToken?: string; enabled?: boolean; realm?: string } | undefined,
  browserToken: string,
): Promise<SplunkExportStatus> {
  const path = action === "connect"
    ? "/api/splunk/export"
    : action === "forget"
      ? "/api/splunk/export/forget"
      : "/api/splunk/export/enabled";
  return postSplunkExportBrowserJSON(path, payload ?? {}, browserToken) as Promise<SplunkExportStatus>;
}

async function postSplunkExportBrowserJSON(
  path: string,
  body: object,
  browserToken?: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const storedBrowserToken = readStoredSplunkBrowserToken();
  const effectiveBrowserToken = storedBrowserToken || browserToken;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    [splunkBrowserRequestHeader]: "1",
  };
  if (effectiveBrowserToken) headers[splunkBrowserTokenHeader] = effectiveBrowserToken;
  const response = await fetch(`${BASE}${path}`, {
    body: JSON.stringify(body),
    cache: "no-store",
    credentials: "same-origin",
    headers,
    method: "POST",
    signal,
  });
  const renewedBrowserToken = response.headers.get(splunkBrowserTokenHeader)?.trim() ?? "";
  if (splunkBrowserSessionPattern.test(renewedBrowserToken)) {
    storeSplunkBrowserToken(renewedBrowserToken);
  }
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
