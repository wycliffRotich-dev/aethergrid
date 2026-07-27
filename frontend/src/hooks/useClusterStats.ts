import { useCallback, useEffect, useState } from "react";

import {
  fetchClusterCapacity,
  fetchClusterHealth,
  fetchClusterUtilization,
} from "../api/dashboard";
import type {
  ClusterCapacityResponse,
  ClusterHealthResponse,
  ClusterUtilizationResponse,
} from "../api/types";

export function useClusterStats() {
  const [health, setHealth] = useState<ClusterHealthResponse | null>(null);
  const [capacity, setCapacity] = useState<ClusterCapacityResponse | null>(null);
  const [utilization, setUtilization] = useState<ClusterUtilizationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [
        healthResponse,
        capacityResponse,
        utilizationResponse,
      ] = await Promise.all([
        fetchClusterHealth(),
        fetchClusterCapacity(),
        fetchClusterUtilization(),
      ]);

      setHealth(healthResponse);
      setCapacity(capacityResponse);
      setUtilization(utilizationResponse);
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unknown error");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    health,
    capacity,
    utilization,
    loading,
    error,
    refresh,
  };
}
