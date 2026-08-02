import { useCallback, useEffect, useState } from "react";

import { listWorkers } from "../api/workers";
import type { WorkerResponse } from "../api/types";

export function useWorkers() {
  const [workers, setWorkers] = useState<WorkerResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await listWorkers();

      setWorkers(response.workers);
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
    void refresh();
  }, [refresh]);

  return {
    workers,
    loading,
    error,
    refresh,
  };
}
