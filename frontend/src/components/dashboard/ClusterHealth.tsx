import type {
  ClusterCapacityResponse,
  ClusterHealthResponse,
  ClusterUtilizationResponse,
} from "../../api/types";

type Props = {
  health: ClusterHealthResponse;
  capacity: ClusterCapacityResponse;
  utilization: ClusterUtilizationResponse;
  jobCount: number;
};

type TrafficState = "red" | "yellow" | "green";

const HIGH_USAGE_THRESHOLD_PERCENT = 80;

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
      ? Math.round((utilization.cpu_cores / totalCpu) * 100)
      : 0;

  const hasOfflineNodes =
    health.total_nodes > 0 && health.offline_nodes > 0;

  const trafficState: TrafficState = hasOfflineNodes
    ? "red"
    : cpuUsagePercent >= HIGH_USAGE_THRESHOLD_PERCENT
      ? "yellow"
      : "green";

  const headline = hasOfflineNodes
    ? "Your cluster needs a look"
    : health.total_nodes === 0
      ? "Your cluster is just getting started"
      : trafficState === "yellow"
        ? "Your cluster is running near capacity"
        : "Your cluster is running smoothly";

  const nodeSentence =
    health.total_nodes === 0
      ? "You haven't registered any compute nodes yet."
      : health.total_nodes === 1
        ? `You have 1 compute node, and it's ${
            health.alive_nodes === 1 ? "healthy" : "offline"
          }.`
        : `You have ${health.total_nodes} compute nodes, ${health.alive_nodes} of them healthy.`;

  const usageSentence =
    totalCpu === 0
      ? "No capacity to report yet."
      : cpuUsagePercent >= HIGH_USAGE_THRESHOLD_PERCENT
        ? `${cpuUsagePercent}% of your capacity is in use — you're close to the limit.`
        : cpuUsagePercent < 50
          ? `Only ${cpuUsagePercent}% of your capacity is being used — plenty of room to grow.`
          : `${cpuUsagePercent}% of your capacity is currently in use.`;

  const jobSentence =
    jobCount === 0
      ? "No jobs are running right now."
      : jobCount === 1
        ? "1 job is currently running."
        : `${jobCount} jobs are currently running.`;

  return (
    <section className="mb-8 rounded-2xl border border-slate-800 bg-slate-900 p-6">
      <div className="flex items-center gap-3">
        <TrafficLight state={trafficState} />
        <div>
          <p
            className="text-lg text-white"
            style={{ fontFamily: "Georgia, \"Times New Roman\", serif" }}
          >
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
