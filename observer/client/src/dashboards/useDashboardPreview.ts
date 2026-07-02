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

    // Only show loading spinner on the initial fetch (no data yet). On
    // auto-refresh ticks we keep showing existing data without a loading flash.
    if (data === null) {
      setLoading(true);
    }
    // Clear any prior error at the start of each fetch/refresh so a stale
    // failure banner does not linger once a new attempt is in flight. Note we
    // never clear `data` here, so a failing refresh keeps the last good preview.
    setError(null);

    fetchDashboardPreview(controller.signal)
      .then((resp) => {
        if (active) {
          setData(resp);
          setError(null);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!active || controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      })
      .finally(() => {
        // Only clear the guard for the fetch that is still current. An aborted
        // stale fetch must not clobber the flag while a newer fetch is live.
        if (active) {
          fetchingRef.current = false;
        }
      });
    return () => {
      active = false;
      controller.abort();
      // Clear the guard here too so a quick cleanup+restart cycle doesn't get
      // stuck — the new effect will set it to true immediately anyway.
      fetchingRef.current = false;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
