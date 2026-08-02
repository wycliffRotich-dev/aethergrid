import type { WorkerResponse, WorkerStatus } from "../../api/types";
import { StatusBadge } from "../common/StatusBadge";

type Props = {
  workers: WorkerResponse[];
};

type BadgeStatus = "Healthy" | "Busy" | "Offline" | "Idle" | "Starting" | "Draining";

const STATUS_LABELS: Record<WorkerStatus, BadgeStatus> = {
  STARTING: "Starting",
  IDLE: "Idle",
  BUSY: "Busy",
  DRAINING: "Draining",
  OFFLINE: "Offline",
};

function shortId(id: string): string {
  return id.slice(0, 8);
}

function formatLastSeen(lastSeenAt: string): string {
  const seconds = Math.max(
    0,
    Math.floor((Date.now() - new Date(lastSeenAt).getTime()) / 1000),
  );

  if (seconds < 5) {
    return "just now";
  }

  if (seconds < 60) {
    return `${seconds}s ago`;
  }

  const minutes = Math.floor(seconds / 60);

  return `${minutes}m ago`;
}

export function WorkerTable({ workers }: Props) {
  return (
    <section className="mt-10 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-lg">
      <div className="flex items-center justify-between border-b border-slate-800 px-6 py-5">
        <div>
          <h2 className="text-xl font-semibold text-white">
            Workers
          </h2>

          <p className="mt-1 text-sm text-slate-400">
            Registered worker processes
          </p>
        </div>

        <div className="rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-300">
          {workers.length} Workers
        </div>
      </div>

      <table className="w-full">
        <thead className="bg-slate-800/60 text-left text-xs uppercase tracking-wider text-slate-400">
          <tr>
            <th className="px-6 py-4">Worker ID</th>
            <th>Status</th>
            <th>Node</th>
            <th>Running Job</th>
            <th>Last Seen</th>
          </tr>
        </thead>

        <tbody>
          {workers.length === 0 ? (
            <tr>
              <td
                colSpan={5}
                className="py-12 text-center text-slate-500"
              >
                No workers have been registered.
              </td>
            </tr>
          ) : (
            workers.map((worker) => (
              <tr
                key={worker.id}
                className="border-t border-slate-800 transition-colors hover:bg-slate-800/40"
              >
                <td className="px-6 py-4 font-mono text-sm text-white">
                  {shortId(worker.id)}
                </td>

                <td>
                  <StatusBadge
                    status={STATUS_LABELS[worker.status]}
                  />
                </td>

                <td className="font-mono text-sm text-slate-400">
                  {shortId(worker.node_id)}
                </td>

                <td className="font-mono text-sm text-slate-400">
                  {worker.running_job_id
                    ? shortId(worker.running_job_id)
                    : "--"}
                </td>

                <td className="text-slate-400">
                  {formatLastSeen(worker.last_seen_at)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
