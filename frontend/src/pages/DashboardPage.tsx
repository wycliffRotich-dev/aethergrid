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
import { WorkerTable } from "../components/workers/WorkerTable";
import { useClusterStats } from "../hooks/useClusterStats";
import { useJobs } from "../hooks/useJobs";
import { useNodes } from "../hooks/useNodes";
import { useWorkers } from "../hooks/useWorkers";
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
    workers,
    refresh: refreshWorkers,
  } = useWorkers();

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
    refreshWorkers();
    refreshClusterStats();
  }

  if ((loading || clusterStatsLoading) && !hasLoadedOnce) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-white">
        Loading cluster...
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-red-400">
        {error}
      </main>
    );
  }

  if (clusterStatsError) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-red-400">
        {clusterStatsError}
      </main>
    );
  }

  if (health === null || capacity === null || utilization === null) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-white">
        Loading cluster...
      </main>
    );
  }
  const runningJobCount = jobs.filter(
    (job) => job.status === "RUNNING",
  ).length;
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
    <main className="flex-1 bg-slate-950 p-8">
      <h1 className="mb-8 text-3xl font-bold text-white">
        Dashboard
      </h1>

      <ClusterHealth
        health={health}
        capacity={capacity}
        utilization={utilization}
        jobCount={runningJobCount}
      />

      <div className="mt-8 grid gap-6 md:grid-cols-2 xl:grid-cols-4">
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

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <RegisterNodeForm
          onCreated={refreshAll}
        />

        <SubmitJobForm
          onSubmitted={refreshAll}
        />
      </div>

      <div className="mt-8">
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
      </div>

      <NodeTable
        nodes={nodes}
        onChanged={refreshAll}
      />

      <RecentJobs
        jobs={jobs}
        onChanged={refreshAll}
      />

      <WorkerTable
        workers={workers}
      />

      <ActivityFeed />
    </main>
  );
}
