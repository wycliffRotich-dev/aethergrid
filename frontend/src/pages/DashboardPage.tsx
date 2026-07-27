import { useEffect, useState } from "react";
import { ClusterHealth } from "../components/dashboard/ClusterHealth";
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

  return (
    <main className="space-y-6">
      <ClusterHealth
        health={health}
        capacity={capacity}
        utilization={utilization}
        jobCount={jobs.length}
      />

      <div className="grid md:grid-cols-2 gap-4">
        <RegisterNodeForm onCreated={refresh} />
        <SubmitJobForm onSubmitted={refreshAll} />
      </div>

      <NodeTable nodes={nodes} />
      <RecentJobs jobs={jobs} />
    </main>
  );
}
