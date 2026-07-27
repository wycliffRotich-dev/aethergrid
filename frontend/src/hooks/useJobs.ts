import { useCallback, useEffect, useState } from "react";

import { listJobs } from "../api/jobs";
import type { JobSummaryResponse } from "../api/types";

export function useJobs() {
  const [jobs, setJobs] = useState<JobSummaryResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await listJobs();

      setJobs(response.jobs);
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
    jobs,
    loading,
    error,
    refresh,
  };
}
