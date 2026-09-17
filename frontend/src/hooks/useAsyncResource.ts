import { useCallback, useEffect, useState } from "react";

interface UseAsyncResourceOptions {
  /**
   * When set, the fetcher is re-run on this interval in addition to the
   * initial fetch and any manual refresh() calls.
   */
  pollIntervalMs?: number;
  /**
   * Whether a manual refresh() (or a change in deps) should reset loading
   * to true and clear the previous error while the new fetch is in flight.
   * Defaults to true. Set to false for hooks that poll in the background
   * and should not show a loading state on every tick.
   */
  resetLoadingOnRefresh?: boolean;
}

interface UseAsyncResourceResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * Fetches data on mount, on any change to `deps`, and (optionally) on a
 * fixed poll interval, with a single manual `refresh()` escape hatch.
 *
 * A response that resolves after a newer fetch was already started (a
 * stale id, an unmounted component, a superseded poll tick) is ignored
 * rather than applied, so out-of-order responses can never overwrite
 * fresher state.
 */
export function useAsyncResource<T>(
  fetcher: () => Promise<T>,
  deps: unknown[],
  options: UseAsyncResourceOptions = {},
): UseAsyncResourceResult<T> {
  const { pollIntervalMs, resetLoadingOnRefresh = true } = options;

  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const refresh = useCallback(() => {
    setRefreshToken((token) => token + 1);
  }, []);

  useEffect(() => {
    const signal = { ignore: false };

    async function load(isRefresh: boolean) {
      if (isRefresh && resetLoadingOnRefresh) {
        setLoading(true);
        setError(null);
      }

      try {
        const result = await fetcher();

        if (signal.ignore) {
          return;
        }

        setData(result);
        setError(null);
      } catch (err) {
        if (signal.ignore) {
          return;
        }

        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        if (!signal.ignore) {
          setLoading(false);
        }
      }
    }

    void load(refreshToken > 0);

    const interval = pollIntervalMs
      ? setInterval(() => void load(false), pollIntervalMs)
      : undefined;

    return () => {
      signal.ignore = true;
      if (interval) {
        clearInterval(interval);
      }
    };
    // Intentionally spreads a caller-supplied deps array, the same
    // contract useEffect and useMemo already ask consumers to uphold.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refreshToken]);

  return { data, loading, error, refresh };
}
