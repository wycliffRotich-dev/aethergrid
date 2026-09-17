import {
  fetchClusterCapacity,
  fetchClusterHealth,
  fetchClusterUtilization,
} from "../api/dashboard";
import { useAsyncResource } from "./useAsyncResource";

export function useClusterStats() {
  const { data, loading, error, refresh } = useAsyncResource(
    async () => {
      const [health, capacity, utilization] = await Promise.all([
        fetchClusterHealth(),
        fetchClusterCapacity(),
        fetchClusterUtilization(),
      ]);

      return { health, capacity, utilization };
    },
    [],
  );

  return {
    health: data?.health ?? null,
    capacity: data?.capacity ?? null,
    utilization: data?.utilization ?? null,
    loading,
    error,
    refresh,
  };
}
