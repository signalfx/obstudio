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
    readonly code?: string,
    readonly retrySafe?: boolean,
  ) {
    super(message);
    this.name = "SplunkExportBrowserActionError";
  }
}

const splunkBrowserRequestHeader = "X-Obstudio-Browser-Request";

/** Run a cloud mutation directly from the trusted standalone browser origin. */
export async function runSplunkExportBrowserAction(
  action: SplunkExportBrowserAction,
  payload: {
    accessToken?: string;
    enabled?: boolean;
    expectedVersion?: string;
    realm?: string;
  },
): Promise<SplunkExportStatus> {
  const path = action === "connect"
    ? "/api/splunk/export"
    : action === "forget"
      ? "/api/splunk/export/forget"
      : "/api/splunk/export/enabled";
  return postSplunkBrowserJSON(path, payload) as Promise<SplunkExportStatus>;
}

/** Resolve a pasted Splunk URL to its canonical realm without sending an access token. */
export async function resolveSplunkCloudRealm(
  destination: string,
): Promise<string> {
  const response = await postSplunkBrowserJSON(
    "/api/splunk/export/realm",
    { destination },
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

export interface SplunkFreeAccountRequest {
  email: string;
  firstName: string;
  lastName: string;
  region: string;
  termsAccepted: true;
}

/** Detect the suggested Free Edition region from Observer's same-origin browser API. */
export async function detectSplunkFreeAccountRegion(
  signal?: AbortSignal,
): Promise<{ region?: unknown }> {
  const response = await fetchSplunkBrowserJSON("/api/splunk/free-account/region", { signal });
  return typeof response === "object" && response !== null
    ? response as { region?: unknown }
    : {};
}

/** Submit a Free Edition request through Observer's same-origin browser API. */
export async function submitSplunkFreeAccount(
  request: SplunkFreeAccountRequest,
  signal?: AbortSignal,
): Promise<unknown> {
  return postSplunkBrowserJSON("/api/splunk/free-account", request, signal);
}

async function postSplunkBrowserJSON(
  path: string,
  body: object,
  signal?: AbortSignal,
): Promise<unknown> {
  return fetchSplunkBrowserJSON(path, {
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
    method: "POST",
    signal,
  });
}

async function fetchSplunkBrowserJSON(
  path: string,
  init: RequestInit = {},
): Promise<unknown> {
  const headers = new Headers(init.headers);
  headers.set(splunkBrowserRequestHeader, "1");
  const response = await observerFetch(`${BASE}${path}`, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers,
  });
  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }
  if (!response.ok) {
    const errorResponse = typeof parsed === "object" && parsed !== null
      ? parsed as Record<string, unknown>
      : {};
    const message = typeof errorResponse.error === "string"
      ? errorResponse.error
      : `Observer request failed with HTTP ${response.status}.`;
    const code = typeof errorResponse.code === "string" ? errorResponse.code : undefined;
    const retrySafe = typeof errorResponse.retrySafe === "boolean" ? errorResponse.retrySafe : undefined;
    throw new SplunkExportBrowserActionError(message, response.status, code, retrySafe);
  }
  return parsed;
}

/**
 * Probe SIS CIMD client registration directly through Observer's own backend, for use
 * when there is no IDE bridge (e.g. standalone `go run ./cmd/obstudio` + browser dev).
 * Stores no secret, but the probe itself has side effects on SIS and its response
 * reveals federation redirect/cookie details, so Observer accepts it only from its
 * same-origin local page.
 */
export async function registerSISCIMDClient(signal?: AbortSignal): Promise<SISCIMDRegistrationResult> {
  return fetchSISCIMDLocal<SISCIMDRegistrationResult>("/api/splunk/cimd/register", { method: "POST", signal });
}

async function fetchSISCIMDLocal<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers: { ...init.headers, [splunkBrowserRequestHeader]: "1" },
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
 * result.
 */
export async function loginSISCIMD(): Promise<SISCIMDLoginStartResult> {
  return fetchSISCIMDLocal<SISCIMDLoginStartResult>("/api/splunk/cimd/login", { method: "POST" });
}

/** Poll the redacted SIS CIMD session status. Never returns a raw access token. */
export async function fetchSISCIMDSession(signal?: AbortSignal): Promise<SISCIMDSessionStatus> {
  return fetchSISCIMDLocal<SISCIMDSessionStatus>("/api/splunk/cimd/session", { signal });
}

/** Clear the in-memory SIS CIMD session held by Observer's own backend. */
export async function disconnectSISCIMDSession(): Promise<SISCIMDSessionStatus> {
  return fetchSISCIMDLocal<SISCIMDSessionStatus>("/api/splunk/cimd/session/disconnect", { method: "POST" });
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
