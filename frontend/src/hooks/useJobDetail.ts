import { getJob, getJobHistory } from "../api/jobs";
import { useAsyncResource } from "./useAsyncResource";

export function useJobDetail(jobId: string) {
  const { data, loading, error, refresh } = useAsyncResource(
    async () => {
      const [job, history] = await Promise.all([
        getJob(jobId),
        getJobHistory(jobId),
      ]);

      return { job, history: history.events };
    },
    [jobId],
  );

  return {
    job: data?.job ?? null,
    history: data?.history ?? [],
    loading,
    error,
    refresh,
  };
}
