// OTLP/HTTP receiver on port 4318.
// Accepts JSON (application/json) and protobuf (application/x-protobuf).

import type { Store } from "../store/store.ts";
import { convertTraces, convertMetrics, convertLogs } from "./convert.ts";
import type { OtlpTracesPayload, OtlpMetricsPayload, OtlpLogsPayload } from "./convert.ts";
import { decodeTracesProtobuf, decodeMetricsProtobuf, decodeLogsProtobuf } from "./proto.ts";

export function startOtlpHttpReceiver(store: Store, host: string, port: number): { stop: () => void } {
  const server = Bun.serve({
    hostname: host,
    port,
    fetch(req) {
      const url = new URL(req.url);

      // CORS preflight.
      if (req.method === "OPTIONS") {
        return new Response(null, {
          status: 204,
          headers: {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
          },
        });
      }

      if (req.method !== "POST") {
        return new Response("Method not allowed", { status: 405 });
      }

      switch (url.pathname) {
        case "/v1/traces":
          return handleTraces(req, store);
        case "/v1/metrics":
          return handleMetrics(req, store);
        case "/v1/logs":
          return handleLogs(req, store);
        default:
          return new Response("Not found", { status: 404 });
      }
    },
  });

  return {
    stop: () => server.stop(),
  };
}

function isProtobuf(req: Request): boolean {
  return (req.headers.get("content-type") ?? "").includes("application/x-protobuf");
}

async function handleTraces(req: Request, store: Store): Promise<Response> {
  try {
    const payload = isProtobuf(req)
      ? await decodeTracesProtobuf(new Uint8Array(await req.arrayBuffer())) as OtlpTracesPayload
      : await req.json() as OtlpTracesPayload;
    const spans = convertTraces(payload);
    if (spans.length > 0) {
      store.addSpans(spans);
    }
    return otlpResponse();
  } catch (e) {
    return errorResponse(e);
  }
}

async function handleMetrics(req: Request, store: Store): Promise<Response> {
  try {
    const payload = isProtobuf(req)
      ? await decodeMetricsProtobuf(new Uint8Array(await req.arrayBuffer())) as OtlpMetricsPayload
      : await req.json() as OtlpMetricsPayload;
    const metrics = convertMetrics(payload);
    if (metrics.length > 0) {
      store.addMetrics(metrics);
    }
    return otlpResponse();
  } catch (e) {
    return errorResponse(e);
  }
}

async function handleLogs(req: Request, store: Store): Promise<Response> {
  try {
    const payload = isProtobuf(req)
      ? await decodeLogsProtobuf(new Uint8Array(await req.arrayBuffer())) as OtlpLogsPayload
      : await req.json() as OtlpLogsPayload;
    const logs = convertLogs(payload);
    if (logs.length > 0) {
      store.addLogs(logs);
    }
    return otlpResponse();
  } catch (e) {
    return errorResponse(e);
  }
}

function otlpResponse(): Response {
  return new Response("{}", {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function errorResponse(e: unknown): Response {
  const msg = e instanceof Error ? e.message : "Unknown error";
  return new Response(JSON.stringify({ error: msg }), {
    status: 400,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
