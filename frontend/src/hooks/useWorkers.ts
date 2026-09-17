import { listWorkers } from "../api/workers";
import { useAsyncResource } from "./useAsyncResource";

export function useWorkers() {
  const { data, loading, error, refresh } = useAsyncResource(listWorkers, []);

  return {
    workers: data?.workers ?? [],
    loading,
    error,
    refresh,
  };
}
