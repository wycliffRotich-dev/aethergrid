import { useCallback, useEffect, useState } from "react";

import { getJob, getJobHistory } from "../api/jobs";
import type { EventResponse, JobSummaryResponse } from "../api/types";

export function useJobDetail(jobId: string) {
  const [job, setJob] = useState<JobSummaryResponse | null>(null);
  const [history, setHistory] = useState<EventResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [jobResponse, historyResponse] = await Promise.all([
        getJob(jobId),
        getJobHistory(jobId),
      ]);

      setJob(jobResponse);
      setHistory(historyResponse.events);
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unknown error");
      }
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    job,
    history,
    loading,
    error,
    refresh,
  };
}
