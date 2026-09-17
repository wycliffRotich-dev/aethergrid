import { listWorkers } from "../api/workers";
import { useAsyncResource } from "./useAsyncResource";

const POLL_INTERVAL_MS = 3000;

export function useWorkers() {
  const { data, loading, error, refresh } = useAsyncResource(
    listWorkers,
    [],
    {
      pollIntervalMs: POLL_INTERVAL_MS,
      resetLoadingOnRefresh: false,
    },
  );

  return {
    workers: data?.workers ?? [],
    loading,
    error,
    refresh,
  };
}
