import type { TraceDetail } from "./types";

const BASE = "";

async function fetchJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

/** Fetch full trace detail (all spans) for a given trace ID. */
export async function fetchTraceDetail(traceId: string): Promise<TraceDetail> {
  return fetchJSON(`/api/query/traces/${traceId}`);
}
