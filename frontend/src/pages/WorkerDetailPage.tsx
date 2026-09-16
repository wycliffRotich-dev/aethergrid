import { Link, useParams } from "react-router-dom";

import { useWorker } from "../hooks/useWorker";

function shortId(id: string): string {
  return id.slice(0, 8);
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

export default function WorkerDetailPage() {
  const { workerId } = useParams<{ workerId: string }>();
  const { worker, loading, error } = useWorker(workerId ?? "");

  if (loading) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-white">
        Loading worker...
      </main>
    );
  }

  if (error || worker === null) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-red-400">
        {error ?? "Worker not found."}
      </main>
    );
  }

  const runningJob = worker.running_job;

  return (
    <main className="flex-1 bg-slate-950 p-8">
      <Link
        to="/workers"
        className="mb-4 inline-flex items-center gap-1 text-sm text-slate-400 hover:text-indigo-400"
      >
        {"\u2190"} Back to Workers
      </Link>

      <h1 className="mb-2 mt-4 text-3xl font-bold text-white">
        Worker {shortId(worker.id)}
      </h1>

      <p className="mb-8 font-mono text-sm text-slate-500">
        {worker.id}
      </p>

      <section className="mb-8 grid grid-cols-2 gap-6 rounded-2xl border border-slate-800 bg-slate-900 p-6 md:grid-cols-4">
        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">
            Status
          </p>
          <p className="mt-1 text-lg text-white">{worker.status}</p>
        </div>

        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">
            Node
          </p>
          <p className="mt-1 font-mono text-lg text-white">
            {shortId(worker.node_id)}
          </p>
        </div>

        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">
            Running Job
          </p>
          <p className="mt-1 font-mono text-lg text-white">
            {runningJob ? shortId(runningJob.id) : "--"}
          </p>
        </div>

        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">
            Last Seen
          </p>
          <p className="mt-1 text-lg text-white">
            {formatTimestamp(worker.last_seen_at)}
          </p>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
        <h2 className="mb-4 text-xl font-semibold text-white">
          Execution Ownership
        </h2>

        {runningJob === null ? (
          <p className="text-slate-500">
            This worker holds no active lease.
          </p>
        ) : runningJob.lease_id === null ? (
          <p className="text-slate-500">
            This worker has a running job but no lease is currently
            resolvable for it.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-6 md:grid-cols-3">
            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500">
                Lease
              </p>
              <p className="mt-1 font-mono text-white">
                {shortId(runningJob.lease_id)}
              </p>
            </div>

            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500">
                Acquired
              </p>
              <p className="mt-1 text-white">
                {runningJob.lease_acquired_at
                  ? formatTimestamp(runningJob.lease_acquired_at)
                  : "--"}
              </p>
            </div>

            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500">
                Expires
              </p>
              <p className="mt-1 text-white">
                {runningJob.lease_expires_at
                  ? formatTimestamp(runningJob.lease_expires_at)
                  : "--"}
              </p>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
