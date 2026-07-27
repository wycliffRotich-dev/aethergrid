import { useEffect, useState } from "react";
import { ActivityFeed } from "../components/dashboard/ActivityFeed";
import { ClusterHealth } from "../components/dashboard/ClusterHealth";
import { Gauge } from "../components/dashboard/gauge/Gauge";
import { SectionCard } from "../components/dashboard/SectionCard";
import { StatCard } from "../components/dashboard/StatCard";
import { RecentJobs } from "../components/jobs/RecentJobs";
import { NodeTable } from "../components/nodes/NodeTable";
import { RegisterNodeForm } from "../components/nodes/RegisterNodeForm";
import { SubmitJobForm } from "../components/jobs/SubmitJobForm";
import { useClusterStats } from "../hooks/useClusterStats";
import { useJobs } from "../hooks/useJobs";
import { useNodes } from "../hooks/useNodes";
import {
  computeUtilizationPercentages,
  HIGH_USAGE_THRESHOLD_PERCENT,
} from "../lib/clusterMetrics";

function formatGaugeValue(value: number): string {
  return value.toFixed(1);
}

export default function DashboardPage() {
  const {
    nodes,
    loading,
    error,
    refresh,
  } = useNodes();

  const {
    jobs,
    refresh: refreshJobs,
  } = useJobs();

  const {
    health,
    capacity,
    utilization,
    loading: clusterStatsLoading,
    error: clusterStatsError,
    refresh: refreshClusterStats,
  } = useClusterStats();

  // The full-page "Loading cluster..." screen should only appear
  // before the dashboard has ever successfully loaded. Every hook's
  // refresh() flips its loading flag back to true on every
  // subsequent call too, including the ones triggered by submitting
  // a form. Without this guard, registering a node or submitting a
  // job would tear down and rebuild the entire page, which is what
  // caused the scroll position to jump back to the top on every
  // action.
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);

  useEffect(() => {
    if (!loading && !clusterStatsLoading && !hasLoadedOnce) {
      setHasLoadedOnce(true);
    }
  }, [loading, clusterStatsLoading, hasLoadedOnce]);

  function refreshAll() {
    refresh();
    refreshJobs();
    refreshClusterStats();
  }

  if ((loading || clusterStatsLoading) && !hasLoadedOnce) {
    return (
      <main className="flex-1 p-4 text-neutral-300">
        Loading...
      </main>
    );
  }

  if (error || clusterStatsError) {
    return (
      <main className="flex-1 p-4 text-red-400">
        {error || clusterStatsError}
      </main>
    );
  }

  if (health === null || capacity === null || utilization === null) {
    return (
      <main className="flex-1 p-4 text-neutral-300">
        Loading...
      </main>
    );
  }

  const totalCpu = nodes.reduce(
    (sum, node) => sum + node.cpu_cores,
    0,
  );

  const totalMemory = nodes.reduce(
    (sum, node) => sum + node.memory_mib,
    0,
  );

  const totalVram = nodes.reduce(
    (sum, node) => sum + node.vram_mib,
    0,
  );

  const utilizationPercentages = computeUtilizationPercentages(
    capacity,
    utilization,
  );

  return (
    <main className="space-y-6">
      <h1 className="text-2xl font-bold text-neutral-100">
        Dashboard
      </h1>

      <ClusterHealth
        health={health}
        capacity={capacity}
        utilization={utilization}
        jobCount={jobs.length}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Registered Nodes"
          value={nodes.length}
        />
        <StatCard
          title="CPU Cores"
          value={totalCpu}
        />
        <StatCard
          title="Memory (MiB)"
          value={totalMemory.toLocaleString()}
        />
        <StatCard
          title="VRAM (MiB)"
          value={totalVram.toLocaleString()}
        />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <RegisterNodeForm onCreated={refresh} />
        <SubmitJobForm onSubmitted={refreshAll} />
      </div>

      <SectionCard
        title="Resource Utilization"
        subtitle="Aggregate CPU, memory, and VRAM usage across the cluster"
      >
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          <Gauge
            label="CPU"
            value={utilizationPercentages.cpuPercent}
            warningThreshold={HIGH_USAGE_THRESHOLD_PERCENT}
            formatValue={formatGaugeValue}
          />
          <Gauge
            label="Memory"
            value={utilizationPercentages.memoryPercent}
            warningThreshold={HIGH_USAGE_THRESHOLD_PERCENT}
            formatValue={formatGaugeValue}
          />
          <Gauge
            label="VRAM"
            value={utilizationPercentages.vramPercent}
            warningThreshold={HIGH_USAGE_THRESHOLD_PERCENT}
            formatValue={formatGaugeValue}
          />
        </div>
      </SectionCard>

      <NodeTable nodes={nodes} />
      <RecentJobs jobs={jobs} />
      <ActivityFeed />
    </main>
  );
}
