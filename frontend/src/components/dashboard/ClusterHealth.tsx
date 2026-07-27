import type {
  ClusterCapacityResponse,
  ClusterHealthResponse,
  ClusterUtilizationResponse,
} from "../../api/types";
import { HIGH_USAGE_THRESHOLD_PERCENT } from "../../lib/clusterMetrics";

type Props = {
  health: ClusterHealthResponse;
  capacity: ClusterCapacityResponse;
  utilization: ClusterUtilizationResponse;
  jobCount: number;
};

type TrafficState = "red" | "yellow" | "green";

interface TrafficColorPair {
  lit: string;
  dim: string;
}

const TRAFFIC_COLORS: Record<TrafficState, TrafficColorPair> = {
  red: { lit: "bg-red-500", dim: "bg-red-500/15" },
  yellow: { lit: "bg-yellow-400", dim: "bg-yellow-400/15" },
  green: { lit: "bg-emerald-500", dim: "bg-emerald-500/15" },
};

function TrafficLight({ state }: { state: TrafficState }) {
  const order: TrafficState[] = ["red", "yellow", "green"];

  return (
    <div className="flex flex-shrink-0 flex-col gap-1 rounded-lg border border-slate-700 bg-slate-800 p-1.5">
      {order.map((color) => (
        <div
          key={color}
          className={`h-2 w-2 rounded-full ${
            color === state
              ? TRAFFIC_COLORS[color].lit
              : TRAFFIC_COLORS[color].dim
          }`}
        />
      ))}
    </div>
  );
}

function Bullet() {
  return (
    <svg
      width="6"
      height="6"
      viewBox="0 0 6 6"
      className="mt-2 flex-shrink-0 text-slate-500"
      aria-hidden="true"
    >
      <circle cx="3" cy="3" r="3" fill="currentColor" />
    </svg>
  );
}

export function ClusterHealth({
  health,
  capacity,
  utilization,
  jobCount,
}: Props) {
  const totalCpu = capacity.cpu_cores + utilization.cpu_cores;
  const totalMemory = capacity.memory_mib + utilization.memory_mib;

  const cpuUsagePercent =
    totalCpu > 0
      ? Math.round((utilization.cpu_cores / totalCpu) * 1000) / 10
      : 0;

  const hasOfflineNodes =
    health.total_nodes > 0 && health.offline_nodes > 0;

  const trafficState: TrafficState = hasOfflineNodes
    ? "red"
    : cpuUsagePercent >= HIGH_USAGE_THRESHOLD_PERCENT
      ? "yellow"
      : "green";

  const headline = hasOfflineNodes
    ? "Cluster degraded"
    : health.total_nodes === 0
      ? "No nodes registered"
      : trafficState === "yellow"
        ? "Cluster near capacity"
        : "Cluster nominal";

  const nodeSentence =
    health.total_nodes === 0
      ? "No compute nodes registered."
      : health.total_nodes === 1
        ? `1 node registered, ${
            health.alive_nodes === 1 ? "healthy" : "offline"
          }.`
        : `${health.total_nodes} nodes registered, ${health.alive_nodes} healthy.`;

  const usageSentence =
    totalCpu === 0
      ? "No capacity registered."
      : cpuUsagePercent >= HIGH_USAGE_THRESHOLD_PERCENT
        ? `CPU utilization: ${cpuUsagePercent}%, approaching capacity.`
        : `CPU utilization: ${cpuUsagePercent}%.`;

  const jobSentence =
    jobCount === 0
      ? "No jobs running."
      : jobCount === 1
        ? "1 job running."
        : `${jobCount} jobs running.`;

  return (
    <section className="mb-8 rounded-2xl border border-slate-800 bg-slate-900 p-6">
      <div className="flex items-center gap-3">
        <TrafficLight state={trafficState} />
        <div>
          <p className="text-lg font-semibold text-white">
            {headline}
          </p>
          <p className="mt-0.5 text-sm text-slate-500">
            Last checked just now
          </p>
        </div>
      </div>

      <div className="my-5 border-t border-slate-800" />

      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-3">
          <Bullet />
          <p className="text-sm text-slate-300">
            {nodeSentence}
          </p>
        </div>

        <div className="flex items-start gap-3">
          <Bullet />
          <p className="text-sm text-slate-300">
            {usageSentence}
          </p>
        </div>

        <div className="flex items-start gap-3">
          <Bullet />
          <p className="text-sm text-slate-300">
            {jobSentence}
          </p>
        </div>
      </div>

      <p className="mt-4 text-xs text-slate-600">
        {totalMemory.toLocaleString()} MiB total memory across the cluster
      </p>
    </section>
  );
}
