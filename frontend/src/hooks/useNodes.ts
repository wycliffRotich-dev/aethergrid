import { fetchNodes } from "../api/dashboard";
import { useAsyncResource } from "./useAsyncResource";

const POLL_INTERVAL_MS = 3000;

export function useNodes() {
  const { data, loading, error, refresh } = useAsyncResource(fetchNodes, [], {
    pollIntervalMs: POLL_INTERVAL_MS,
    resetLoadingOnRefresh: false,
  });

  return {
    nodes: data?.nodes ?? [],
    loading,
    error,
    refresh,
  };
}
