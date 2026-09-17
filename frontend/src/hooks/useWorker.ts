import { getWorker } from "../api/workers";
import { useAsyncResource } from "./useAsyncResource";

export function useWorker(workerId: string) {
  const { data, loading, error, refresh } = useAsyncResource(
    () => getWorker(workerId),
    [workerId],
  );

  return {
    worker: data,
    loading,
    error,
    refresh,
  };
}
