import { useCallback, useEffect, useState } from "react";

import { getWorker } from "../api/workers";
import type { GetWorkerResponse } from "../api/types";

export function useWorker(workerId: string) {
  const [worker, setWorker] = useState<GetWorkerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await getWorker(workerId);

      setWorker(response);
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unknown error");
      }
    } finally {
      setLoading(false);
    }
  }, [workerId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    worker,
    loading,
    error,
    refresh,
  };
}
