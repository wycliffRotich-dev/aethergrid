import { RecentJobs } from "../components/jobs/RecentJobs";
import { SubmitJobForm } from "../components/jobs/SubmitJobForm";
import { useJobs } from "../hooks/useJobs";

export default function JobsPage() {
  const {
    jobs,
    loading,
    error,
    refresh,
  } = useJobs();

  if (loading) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-white">
        Loading jobs...
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

  return (
    <main className="flex-1 bg-slate-950 p-8">
      <h1 className="mb-8 text-3xl font-bold text-white">
        Jobs
      </h1>

      <SubmitJobForm
        onSubmitted={refresh}
      />

      <RecentJobs
        jobs={jobs}
        onChanged={refresh}
      />
    </main>
  );
}
