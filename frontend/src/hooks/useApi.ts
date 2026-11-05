import { useCallback, useEffect, useState } from "react";

import { api, toFailure, type ApiFailure } from "../services/api";

interface Result<T> {
  key: string | null; // which request this result belongs to
  data: T | null;
  error: ApiFailure | null;
}

/**
 * GET `path` with `params`; refetches when they change and aborts stale requests.
 * Pass `null` as path to skip (e.g. until a required input is provided).
 *
 * `loading` is derived (the latest result belongs to an older request), so the effect only
 * sets state from the request callbacks.
 */
export function useApi<T>(path: string | null, params?: Record<string, unknown>) {
  const [nonce, setNonce] = useState(0);
  const query = JSON.stringify(params ?? {});
  const requestKey = path === null ? null : `${path}?${query}#${nonce}`;
  const [result, setResult] = useState<Result<T>>({ key: null, data: null, error: null });

  useEffect(() => {
    if (path === null || requestKey === null) return;
    const controller = new AbortController();
    const cleaned = Object.fromEntries(
      Object.entries(JSON.parse(query) as Record<string, unknown>).filter(([, v]) => v !== "" && v != null),
    );
    api
      .get<T>(path, { params: cleaned, signal: controller.signal })
      .then((r) => setResult({ key: requestKey, data: r.data, error: null }))
      .catch((e) => {
        const failure = toFailure(e);
        if (failure.code !== "cancelled") setResult({ key: requestKey, data: null, error: failure });
      });
    return () => controller.abort();
  }, [path, query, requestKey]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const current = result.key === requestKey;
  return {
    // Previous data stays visible while a new filter combination loads (no flash of empty UI).
    data: requestKey === null ? null : result.data,
    error: current ? result.error : null,
    loading: requestKey !== null && !current,
    reload,
  };
}
