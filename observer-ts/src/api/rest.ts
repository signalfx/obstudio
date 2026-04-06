import type { Store } from "../store/store.ts";
import { queryTraces, getTrace, queryMetrics, queryLogs, stats, queryServiceMap } from "../store/query.ts";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Cache-Control": "no-store",
  "Content-Type": "application/json",
};

export function handleRest(req: Request, store: Store): Response | null {
  const url = new URL(req.url);
  const path = url.pathname;

  if (req.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      },
    });
  }

  if (req.method === "DELETE" && path === "/api/data") {
    store.clear();
    return json({ status: "cleared" });
  }

  if (req.method !== "GET") return null;

  // GET /api/query/traces/:traceId
  const traceDetailMatch = path.match(/^\/api\/query\/traces\/([^/]+)$/);
  if (traceDetailMatch) {
    const traceId = traceDetailMatch[1]!;
    const eventLimit = intParam(url, "eventLimit", 12);
    const detail = getTrace(store, traceId, eventLimit);
    if (!detail) {
      return new Response(JSON.stringify({ error: "trace not found" }), {
        status: 404,
        headers: CORS_HEADERS,
      });
    }
    return json(detail);
  }

  switch (path) {
    case "/api/query/traces":
      return json(
        queryTraces(store, {
          serviceName: strParam(url, "serviceName"),
          spanName: strParam(url, "spanName"),
          status: strParam(url, "status"),
          traceIdPrefix: strParam(url, "traceIdPrefix"),
          limit: intParam(url, "limit"),
          spanPreviewCount: intParam(url, "spanPreviewCount"),
        }),
      );

    case "/api/query/metrics":
      return json(
        queryMetrics(store, {
          metricName: strParam(url, "metricName"),
          serviceName: strParam(url, "serviceName"),
          scopeName: strParam(url, "scopeName"),
          type: strParam(url, "type"),
          resourceAttribute: strParam(url, "resourceAttribute"),
          limit: intParam(url, "limit"),
          dataPointLimit: intParam(url, "dataPointLimit"),
        }),
      );

    case "/api/query/logs":
      return json(
        queryLogs(store, {
          serviceName: strParam(url, "serviceName"),
          severityText: strParam(url, "severityText"),
          body: strParam(url, "body"),
          traceId: strParam(url, "traceId"),
          limit: intParam(url, "limit"),
        }),
      );

    case "/api/query/stats":
      return json(stats(store));

    case "/api/query/service-map":
      return json(queryServiceMap(store));

    default:
      return null;
  }
}

function json(data: unknown): Response {
  return new Response(JSON.stringify(data), { headers: CORS_HEADERS });
}

function strParam(url: URL, key: string): string | undefined {
  const v = url.searchParams.get(key);
  return v || undefined;
}

function intParam(url: URL, key: string, fallback?: number): number | undefined {
  const v = url.searchParams.get(key);
  if (!v) return fallback;
  const n = parseInt(v, 10);
  return isNaN(n) ? fallback : n;
}
