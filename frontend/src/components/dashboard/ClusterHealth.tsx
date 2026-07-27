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

function Bullet() {
  return (
    <svg
      width="6"
      height="6"
      viewBox="0 0 6 6"
      className="mt-1.5 flex-shrink-0 text-neutral-600"
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

  const headline = hasOfflineNodes
    ? "Cluster needs attention"
    : health.total_nodes === 0
      ? "No nodes registered"
      : cpuUsagePercent >= 80
        ? "Cluster near capacity"
        : "Cluster operational";

  const trafficLight = hasOfflineNodes || health.total_nodes === 0
    ? { left: 'bg-red-500', middle: 'bg-amber-500', right: 'bg-neutral-700' }
    : cpuUsagePercent >= 80
      ? { left: 'bg-green-500', middle: 'bg-amber-500', right: 'bg-neutral-700' }
      : { left: 'bg-green-500', middle: 'bg-green-500', right: 'bg-green-500' };

  const nodeSentence =
    health.total_nodes === 0
      ? "No compute nodes registered."
      : health.total_nodes === 1
        ? `1 node, ${health.alive_nodes === 1 ? "online" : "offline"}.`
        : `${health.total_nodes} nodes, ${health.alive_nodes} online.`;

  const usageSentence =
    totalCpu === 0
      ? "No capacity data."
      : `${cpuUsagePercent}% capacity in use.`;

  const jobSentence =
    jobCount === 0
      ? "No jobs running."
      : jobCount === 1
        ? "1 job running."
        : `${jobCount} jobs running.`;

  return (
    <section className="border border-neutral-700 rounded-lg p-4">
      <div className="flex items-center gap-3 mb-3">
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${trafficLight.left}`} />
          <div className={`w-2 h-2 rounded-full ${trafficLight.middle}`} />
          <div className={`w-2 h-2 rounded-full ${trafficLight.right}`} />
        </div>
        <div>
          <p className="text-sm font-medium text-white">
            {headline}
          </p>
          <p className="text-xs text-neutral-500">
            Last checked just now
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-start gap-2">
          <Bullet />
          <p className="text-xs text-neutral-400">
            {nodeSentence}
          </p>
        </div>

        <div className="flex items-start gap-2">
          <Bullet />
          <p className="text-xs text-neutral-400">
            {usageSentence}
          </p>
        </div>

        <div className="flex items-start gap-2">
          <Bullet />
          <p className="text-xs text-neutral-400">
            {jobSentence}
          </p>
        </div>
      </div>

      <p className="mt-3 text-xs text-neutral-600">
        {totalMemory.toLocaleString()} MiB total memory
      </p>
    </section>
  );
}
