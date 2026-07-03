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

const FETCH_TIMEOUT_MS = 10_000;

export function useDashboardPreview(paused = false): UseDashboardPreview {
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetchingRef = useRef(false);
  // Track whether any fetch has ever succeeded so we don't show the spinner
  // on retries after a persistent error (data stays null but we have already
  // attempted at least once).
  const hasEverLoadedRef = useRef(false);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    fetchingRef.current = true;

    // Only show loading spinner on the very first fetch attempt (no successful
    // load yet). On auto-refresh ticks or persistent-error retries we keep
    // showing the existing state without a loading flash.
    if (!hasEverLoadedRef.current) {
      setLoading(true);
    }
    // Clear any prior error at the start of each fetch/refresh so a stale
    // failure banner does not linger once a new attempt is in flight. Note we
    // never clear `data` here, so a failing refresh keeps the last good preview.
    setError(null);

    // Timeout guard: if the fetch hangs (e.g. server is slow or connection is
    // dropped after TCP connect), abort it after FETCH_TIMEOUT_MS so
    // fetchingRef.current is always cleared and auto-refresh can resume.
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    fetchDashboardPreview(controller.signal)
      .then((resp) => {
        if (active) {
          hasEverLoadedRef.current = true;
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
        clearTimeout(timeoutId);
        // Only clear the guard for the fetch that is still current. An aborted
        // stale fetch must not clobber the flag while a newer fetch is live.
        if (active) {
          fetchingRef.current = false;
        }
      });
    return () => {
      active = false;
      clearTimeout(timeoutId);
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
