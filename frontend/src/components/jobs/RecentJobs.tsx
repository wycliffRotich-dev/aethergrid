import type { JobStatus, JobSummaryResponse } from "../../api/types";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { cancelJob } from "../../api/jobs";

type Props = {
  jobs: JobSummaryResponse[];
  onChanged: () => void;
};

type StatusStyle = { dot: string; text: string; label: string };

const STATUS_STYLES: Record<JobStatus, StatusStyle> = {
  SUBMITTED: {
    dot: "bg-slate-500",
    text: "text-slate-400",
    label: "submitted",
  },
  QUEUED: {
    dot: "bg-slate-400",
    text: "text-slate-300",
    label: "queued",
  },
  SCHEDULED: {
    dot: "bg-amber-500",
    text: "text-amber-400",
    label: "scheduled",
  },
  RUNNING: {
    dot: "bg-amber-400 animate-pulse",
    text: "text-amber-300",
    label: "running",
  },
  COMPLETED: {
    dot: "bg-emerald-500",
    text: "text-emerald-400",
    label: "completed",
  },
  FAILED: {
    dot: "bg-rose-500",
    text: "text-rose-400",
    label: "failed",
  },
  CANCELLED: {
    dot: "bg-slate-600",
    text: "text-slate-500",
    label: "cancelled",
  },
};

const CANCELLABLE_STATUSES: JobStatus[] = [
  "SUBMITTED",
  "QUEUED",
  "SCHEDULED",
];

function shortId(id: string): string {
  return id.slice(0, 8);
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.floor(seconds)}s`;
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.floor(seconds % 60);

  return `${minutes}m ${remainingSeconds}s`;
}

function useTicker(enabled: boolean): number {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const interval = setInterval(() => {
      setTick((current) => current + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, [enabled]);

  return Date.now();
}

function JobDuration({ job }: { job: JobSummaryResponse }) {
  const isRunning = job.status === "RUNNING";
  const now = useTicker(isRunning);

  if (job.started_at === null) {
    return <span className="text-slate-600">--</span>;
  }

  const start = new Date(job.started_at).getTime();
  const end = job.completed_at
    ? new Date(job.completed_at).getTime()
    : now;

  const seconds = (end - start) / 1000;

  return (
    <span className="font-mono text-slate-300">
      {formatDuration(Math.max(seconds, 0))}
    </span>
  );
}

function ExitCode({ job }: { job: JobSummaryResponse }) {
  if (job.exit_code === null) {
    return <span className="text-slate-600">--</span>;
  }

  const isSuccess = job.exit_code === 0;

  return (
    <span
      className={`font-mono ${
        isSuccess ? "text-emerald-400" : "text-rose-400"
      }`}
    >
      [exit {job.exit_code}]
    </span>
  );
}

export function RecentJobs({ jobs, onChanged }: Props) {
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  async function handleCancel(jobId: string) {
    setCancellingId(jobId);

    try {
      await cancelJob(jobId);
      onChanged();
    } catch (error) {
      alert(error);
    } finally {
      setCancellingId(null);
    }
  }

  return (
    <section className="mt-8 rounded-xl border border-slate-800 bg-slate-950">
      <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
        <h2 className="text-lg font-semibold tracking-tight text-white">
          Recent Jobs
        </h2>

        <span className="font-mono text-xs text-slate-500">
          {jobs.length} shown
        </span>
      </div>

      {jobs.length === 0 ? (
        <div className="px-6 py-16 text-center">
          <p className="text-slate-400">
            No jobs have run on this cluster yet.
          </p>
          <p className="mt-1 text-sm text-slate-600">
            Submit a job above to see it appear here.
          </p>
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="border-b border-slate-800 text-left text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-6 py-3 font-medium">Job</th>
              <th className="px-3 py-3 font-medium">Status</th>
              <th className="px-3 py-3 font-medium">Resources</th>
              <th className="px-3 py-3 font-medium">Duration</th>
              <th className="px-3 py-3 font-medium">Result</th>
              <th className="px-6 py-3 font-medium"></th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-800/60">
            {jobs.map((job) => {
              const style = STATUS_STYLES[job.status];
              const canCancel = CANCELLABLE_STATUSES.includes(job.status);

              return (
                <tr
                  key={job.id}
                  className="transition-colors hover:bg-slate-900/60"
                >
                  <td className="px-6 py-3">
                    <Link
                      to={`/jobs/${job.id}`}
                      className="font-mono text-slate-300 hover:text-indigo-400 hover:underline"
                    >
                      {shortId(job.id)}
                    </Link>
                  </td>

                  <td className="px-3 py-3">
                    <span className="inline-flex items-center gap-2">
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${style.dot}`}
                      />
                      <span className={style.text}>
                        {style.label}
                      </span>
                    </span>
                  </td>

                  <td className="px-3 py-3 font-mono text-slate-400">
                    {job.cpu_cores}c
                    {" / "}
                    {job.memory_mib}mb
                    {job.vram_mib > 0 && (
                      <>{" / "}{job.vram_mib}vram</>
                    )}
                  </td>

                  <td className="px-3 py-3">
                    <JobDuration job={job} />
                  </td>

                  <td className="px-3 py-3">
                    <ExitCode job={job} />
                  </td>

                  <td className="px-6 py-3 text-right">
                    {canCancel && (
                      <button
                        onClick={() => handleCancel(job.id)}
                        disabled={cancellingId === job.id}
                        className="rounded border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                      >
                        {cancellingId === job.id ? "Cancelling..." : "Cancel"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
