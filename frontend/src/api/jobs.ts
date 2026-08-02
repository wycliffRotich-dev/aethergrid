import { api } from "./client";
import type { JobSummaryResponse, ListJobsResponse } from "./types";

export type CreateJobRequest = {
  cpu_cores: number;
  memory_mib: number;
  vram_mib: number;
};

export function createJob(
  job: CreateJobRequest,
) {
  return api(
    "/jobs",
    {
      method: "POST",
      body: JSON.stringify(job),
    },
  );
}

export function listJobs() {
  return api<ListJobsResponse>("/jobs");
}

export function cancelJob(jobId: string) {
  return api<JobSummaryResponse>(`/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}
