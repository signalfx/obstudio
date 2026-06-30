import { useCallback, useEffect, useRef, useState } from "react";
import { fetchDashboardPreview } from "../api/client";
import type { PreviewResponse } from "./types";

const AUTO_REFRESH_MS = 5_000;

interface UseDashboardPreview {
  data: PreviewResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useDashboardPreview(paused = false): UseDashboardPreview {
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetchingRef = useRef(false);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    fetchingRef.current = true;
    setLoading(true);
    setError(null);
    fetchDashboardPreview(controller.signal)
      .then((resp) => {
        if (active) {
          setData(resp);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!active || controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      })
      .finally(() => {
        fetchingRef.current = false;
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [nonce]);

  // Auto-refresh when live (not paused).
  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => {
      if (!fetchingRef.current) setNonce((n) => n + 1);
    }, AUTO_REFRESH_MS);
    return () => clearInterval(id);
  }, [paused]);

  return { data, loading, error, refresh };
}
