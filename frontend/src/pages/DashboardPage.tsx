import { ActivityFeed } from "../components/dashboard/ActivityFeed";
import { ClusterHealth } from "../components/dashboard/ClusterHealth";
import { ResourceUsage } from "../components/dashboard/ResourceUsage";
import { StatCard } from "../components/dashboard/StatCard";
import { RecentJobs } from "../components/jobs/RecentJobs";
import { NodeTable } from "../components/nodes/NodeTable";
import { RegisterNodeForm } from "../components/nodes/RegisterNodeForm";
import { SubmitJobForm } from "../components/jobs/SubmitJobForm";
import { useClusterStats } from "../hooks/useClusterStats";
import { useJobs } from "../hooks/useJobs";
import { useNodes } from "../hooks/useNodes";

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

  function refreshAll() {
    refresh();
    refreshJobs();
    refreshClusterStats();
  }

  if (loading || clusterStatsLoading) {
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

  return (
    <main className="flex-1 bg-slate-950 p-8">
      <h1 className="mb-8 text-3xl font-bold text-white">
        Dashboard
      </h1>

      <ClusterHealth
        health={health}
        capacity={capacity}
        utilization={utilization}
        jobCount={jobs.length}
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
          onCreated={refresh}
        />

        <SubmitJobForm
          onSubmitted={refreshAll}
        />
      </div>

      <ResourceUsage
        nodes={nodes}
      />

      <NodeTable
        nodes={nodes}
      />

      <RecentJobs
        jobs={jobs}
      />

      <ActivityFeed />
    </main>
  );
}
