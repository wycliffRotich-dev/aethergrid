import { api } from "./client";
import type {
  JobSummaryResponse,
  ListEventsResponse,
  ListJobsResponse,
} from "./types";

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

export function getJob(jobId: string) {
  return api<JobSummaryResponse>(`/jobs/${jobId}`);
}

export function getJobHistory(jobId: string) {
  return api<ListEventsResponse>(`/jobs/${jobId}/history`);
}

export function cancelJob(jobId: string) {
  return api<JobSummaryResponse>(`/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export function retryJob(jobId: string) {
  return api<JobSummaryResponse>(`/jobs/${jobId}/retry`, {
    method: "POST",
  });
}
