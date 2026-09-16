import { useCallback, useEffect, useState } from "react";

import { listJobs } from "../api/jobs";
import type { JobSummaryResponse } from "../api/types";

const POLL_INTERVAL_MS = 3000;

export function useJobs() {
  const [jobs, setJobs] = useState<JobSummaryResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await listJobs();

      setJobs(response.jobs);
      setError(null);
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

    const interval = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [refresh]);

  return {
    jobs,
    loading,
    error,
    refresh,
  };
}
