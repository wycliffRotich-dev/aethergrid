import { listEvents } from "../api/events";
import { useAsyncResource } from "./useAsyncResource";

const POLL_INTERVAL_MS = 3000;

export function useEvents() {
  const { data, loading, error, refresh } = useAsyncResource(listEvents, [], {
    pollIntervalMs: POLL_INTERVAL_MS,
    resetLoadingOnRefresh: false,
  });

  return {
    events: data?.events ?? [],
    loading,
    error,
    refresh,
  };
}
