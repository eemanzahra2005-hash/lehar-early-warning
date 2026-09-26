"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/**
 * Run an async loader on mount (and whenever `deps` change), optionally
 * re-running it every `refreshMs`. Keeps the last good data while a refresh
 * is in flight so the alert board never flashes empty.
 */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = [], refreshMs?: number): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);

  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- marks the start of a fetch the effect itself starts
    setLoading(true);
    loaderRef
      .current()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- callers pass their own dependency list
  }, [...deps, tick]);

  useEffect(() => {
    if (!refreshMs) return;
    const id = window.setInterval(() => setTick((n) => n + 1), refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, reload };
}
