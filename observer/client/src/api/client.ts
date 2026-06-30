import type { LogRecord, MetricGroup, TraceDetail, TraceSummary } from "./types";
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
