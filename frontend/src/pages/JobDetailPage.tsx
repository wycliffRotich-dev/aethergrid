import { useParams } from "react-router-dom";

import { cancelJob, retryJob } from "../api/jobs";
import { useJobDetail } from "../hooks/useJobDetail";
import { useState } from "react";

function shortId(id: string): string {
  return id.slice(0, 8);
}

function formatTimestamp(occurredAt: string): string {
  return new Date(occurredAt).toLocaleString();
}

const EVENT_STYLES: Record<string, string> = {
  JobCreated: "bg-slate-400",
  JobScheduled: "bg-amber-400",
  WorkerAssigned: "bg-amber-400",
  LeaseAcquired: "bg-amber-400",
  LeaseReleased: "bg-slate-500",
  JobCompleted: "bg-emerald-500",
  JobFailed: "bg-rose-500",
  JobReclaimed: "bg-rose-400",
};

export default function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { job, history, loading, error, refresh } = useJobDetail(jobId ?? "");
  const [actionLoading, setActionLoading] = useState(false);

  async function handleCancel() {
    if (!jobId) return;

    setActionLoading(true);

    try {
      await cancelJob(jobId);
      await refresh();
    } catch (err) {
      alert(err);
    } finally {
      setActionLoading(false);
    }
  }

  async function handleRetry() {
    if (!jobId) return;

    setActionLoading(true);

    try {
      await retryJob(jobId);
      await refresh();
    } catch (err) {
      alert(err);
    } finally {
      setActionLoading(false);
    }
  }

  if (loading) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-white">
        Loading job...
      </main>
    );
  }

  if (error || job === null) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-red-400">
        {error ?? "Job not found."}
      </main>
    );
  }

  const canCancel = ["SUBMITTED", "QUEUED", "SCHEDULED", "RUNNING"].includes(job.status);
  const canRetry = job.status === "FAILED";

  return (
    <main className="flex-1 bg-slate-950 p-8">
      <h1 className="mb-2 text-3xl font-bold text-white">
        Job {shortId(job.id)}
      </h1>

      <p className="mb-8 font-mono text-sm text-slate-500">
        {job.id}
      </p>

      <section className="mb-8 grid grid-cols-2 gap-6 rounded-2xl border border-slate-800 bg-slate-900 p-6 md:grid-cols-4">
        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">
            Status
          </p>
          <p className="mt-1 text-lg text-white">{job.status}</p>
        </div>

        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">
            Resources
          </p>
          <p className="mt-1 text-lg text-white">
            {job.cpu_cores}c / {job.memory_mib}mb
            {job.vram_mib > 0 && ` / ${job.vram_mib}vram`}
          </p>
        </div>

        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">
            Exit Code
          </p>
          <p className="mt-1 text-lg text-white">
            {job.exit_code ?? "--"}
          </p>
        </div>

        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">
            Submitted
          </p>
          <p className="mt-1 text-lg text-white">
            {formatTimestamp(job.submitted_at)}
          </p>
        </div>
      </section>

      {(canCancel || canRetry) && (
        <div className="mb-8 flex gap-3">
          {canCancel && (
            <button
              onClick={handleCancel}
              disabled={actionLoading}
              className="rounded bg-rose-600 px-5 py-2 font-medium text-white hover:bg-rose-500 disabled:opacity-50"
            >
              {actionLoading ? "Working..." : "Cancel Job"}
            </button>
          )}

          {canRetry && (
            <button
              onClick={handleRetry}
              disabled={actionLoading}
              className="rounded bg-indigo-600 px-5 py-2 font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {actionLoading ? "Working..." : "Retry Job"}
            </button>
          )}
        </div>
      )}

      <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
        <h2 className="mb-4 text-xl font-semibold text-white">
          Lifecycle History
        </h2>

        {history.length === 0 ? (
          <p className="text-slate-500">No events recorded yet.</p>
        ) : (
          <div className="space-y-2">
            {history.map((event) => (
              <div
                key={event.id}
                className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-4 py-3"
              >
                <span className="flex items-center gap-2 text-sm text-white">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      EVENT_STYLES[event.event_type] ?? "bg-slate-500"
                    }`}
                  />
                  {event.event_type}
                </span>

                <span className="text-xs text-slate-500">
                  {formatTimestamp(event.occurred_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
