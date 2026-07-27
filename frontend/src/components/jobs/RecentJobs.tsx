import type { JobStatus, JobSummaryResponse } from "../../api/types";
import { useEffect, useState } from "react";

type Props = {
  jobs: JobSummaryResponse[];
};

const STATUS_STYLES: Record<
  JobStatus,
  { dot: string; text: string; label: string }
> = {
  SUBMITTED: { dot: "bg-neutral-500", text: "text-neutral-400", label: "submitted" },
  QUEUED: { dot: "bg-amber-500", text: "text-amber-400", label: "queued" },
  SCHEDULED: { dot: "bg-white", text: "text-white", label: "scheduled" },
  RUNNING: { dot: "bg-green-500 animate-pulse", text: "text-green-400", label: "running" },
  COMPLETED: { dot: "bg-green-500", text: "text-green-400", label: "completed" },
  FAILED: { dot: "bg-red-500", text: "text-red-400", label: "failed" },
  CANCELLED: { dot: "bg-neutral-500", text: "text-neutral-400", label: "cancelled" },
};

function shortId(id: string): string {
  return id.slice(0, 8);
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.floor(seconds % 60);
  return `${minutes}m ${remainingSeconds}s`;
}

function useTicker(enabled: boolean): number {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    const interval = setInterval(() => {
      setTick((current) => current + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [enabled]);

  return tick;
}

function JobDuration({ job }: { job: JobSummaryResponse }) {
  const isRunning = job.status === "RUNNING";
  const now = useTicker(isRunning);

  if (job.started_at === null) {
    return <span className="text-neutral-600">--</span>;
  }

  const start = new Date(job.started_at).getTime();
  const end = job.completed_at ? new Date(job.completed_at).getTime() : now;
  const seconds = (end - start) / 1000;

  return (
    <span className="font-mono text-neutral-300">
      {formatDuration(Math.max(seconds, 0))}
    </span>
  );
}

export function RecentJobs({ jobs }: Props) {
  return (
    <section className="border border-neutral-700 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-700">
        <h2 className="text-sm font-semibold text-white">
          Jobs
        </h2>
        <span className="text-xs text-neutral-500">
          {jobs.length}
        </span>
      </div>

      {jobs.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-neutral-500">
          No jobs.
        </div>
      ) : (
        <div className="divide-y divide-neutral-700">
          {jobs.map((job) => {
            const style = STATUS_STYLES[job.status];
            return (
              <div key={job.id} className="px-4 py-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono text-xs text-neutral-300">
                    {shortId(job.id)}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
                    <span className={`text-xs ${style.text}`}>
                      {style.label}
                    </span>
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-neutral-500">
                  <span className="font-mono">
                    {job.cpu_cores}c / {job.memory_mib}m
                  </span>
                  <JobDuration job={job} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
