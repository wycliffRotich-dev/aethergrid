import { listJobs } from "../api/jobs";
import { useAsyncResource } from "./useAsyncResource";

const POLL_INTERVAL_MS = 3000;

export function useJobs() {
  const { data, loading, error, refresh } = useAsyncResource(listJobs, [], {
    pollIntervalMs: POLL_INTERVAL_MS,
    resetLoadingOnRefresh: false,
  });

  return {
    jobs: data?.jobs ?? [],
    loading,
    error,
    refresh,
  };
}
