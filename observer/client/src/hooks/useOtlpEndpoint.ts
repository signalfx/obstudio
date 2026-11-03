import { useEffect, useState } from "react";
import { observerFetch } from "../host/transport";

/** Shape of the fields we read from GET /api/health. */
interface HealthResponse {
  endpoints?: { otlpHttp?: string; otlpGrpc?: string; rest?: string; mcp?: string };
}

/**
 * Fetch the OTLP/HTTP receiver endpoint (e.g. `http://127.0.0.1:4318`) from
 * /api/health once on mount so hints name the actually-configured receiver
 * instead of a hardcoded port (#19). Returns `null` until loaded or on
 * failure; callers fall back to a port-free message in that case.
 */
export function useOtlpEndpoint(): string | null {
  const [endpoint, setEndpoint] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    observerFetch("/api/health", { signal: controller.signal })
      .then((r) => (r.ok ? (r.json() as Promise<HealthResponse>) : null))
      .then((health) => {
        const otlpHttp = health?.endpoints?.otlpHttp?.trim();
        if (otlpHttp) setEndpoint(otlpHttp);
      })
      .catch(() => {
        /* leave null → hint uses the port-free fallback */
      });
    return () => controller.abort();
  }, []);
  return endpoint;
}
