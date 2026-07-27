import { useJobs } from "../hooks/useJobs";
import { SubmitJobForm } from "../components/jobs/SubmitJobForm";

export default function JobsPage() {
  const { jobs, loading, error, refresh } = useJobs();

  if (loading) {
    return (
      <main className="flex-1 p-4 text-neutral-300">
        Loading...
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex-1 p-4 text-red-400">
        {error}
      </main>
    );
  }

  const statusCounts = jobs.reduce((acc, job) => {
    acc[job.status] = (acc[job.status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  return (
    <main className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-white">Jobs</h1>
        <button
          onClick={() => refresh()}
          className="px-3 py-1.5 text-xs bg-neutral-800 hover:bg-neutral-700 text-neutral-300 rounded border border-neutral-700 transition-colors"
        >
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Total</p>
          <p className="text-2xl font-semibold text-white mt-1">{jobs.length}</p>
        </div>
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Running</p>
          <p className="text-2xl font-semibold text-white mt-1">{statusCounts.RUNNING || 0}</p>
        </div>
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Queued</p>
          <p className="text-2xl font-semibold text-white mt-1">{statusCounts.QUEUED || 0}</p>
        </div>
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Scheduled</p>
          <p className="text-2xl font-semibold text-white mt-1">{statusCounts.SCHEDULED || 0}</p>
        </div>
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Submitted</p>
          <p className="text-2xl font-semibold text-white mt-1">{statusCounts.SUBMITTED || 0}</p>
        </div>
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Completed</p>
          <p className="text-2xl font-semibold text-white mt-1">{statusCounts.COMPLETED || 0}</p>
        </div>
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Failed</p>
          <p className="text-2xl font-semibold text-white mt-1">{statusCounts.FAILED || 0}</p>
        </div>
      </div>

      <div className="border border-neutral-700 rounded-lg p-4">
        <h2 className="text-sm font-medium text-white mb-4">Submit New Job</h2>
        <SubmitJobForm onSubmitted={refresh} />
      </div>

      {jobs.length === 0 ? (
        <div className="border border-neutral-700 rounded-lg p-8 text-center">
          <p className="text-neutral-500">No jobs yet.</p>
          <p className="text-neutral-600 text-sm mt-1">Submit a job to get started.</p>
        </div>
      ) : (
        <div className="border border-neutral-700 rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-neutral-800 border-b border-neutral-700">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-400 uppercase tracking-wider">Job ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-400 uppercase tracking-wider">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-neutral-400 uppercase tracking-wider">CPU</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-neutral-400 uppercase tracking-wider">Memory</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-neutral-400 uppercase tracking-wider">VRAM</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-400 uppercase tracking-wider">Exit Code</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-400 uppercase tracking-wider">Submitted</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-400 uppercase tracking-wider">Started</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-400 uppercase tracking-wider">Completed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-700">
              {jobs.map((job) => (
                <tr key={job.id} className="hover:bg-neutral-800/50">
                  <td className="px-4 py-3 font-mono text-xs text-neutral-300">{job.id.slice(0, 8)}</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1.5">
                      <span className={`h-2 w-2 rounded-full ${
                        job.status === 'RUNNING' ? 'bg-green-500 animate-pulse' :
                        job.status === 'COMPLETED' ? 'bg-green-500' :
                        job.status === 'QUEUED' ? 'bg-amber-500' :
                        job.status === 'SCHEDULED' ? 'bg-white' :
                        job.status === 'FAILED' ? 'bg-red-500' :
                        'bg-neutral-500'
                      }`} />
                      <span className={`text-xs ${
                        job.status === 'RUNNING' ? 'text-green-400' :
                        job.status === 'COMPLETED' ? 'text-green-400' :
                        job.status === 'QUEUED' ? 'text-amber-400' :
                        job.status === 'SCHEDULED' ? 'text-white' :
                        job.status === 'FAILED' ? 'text-red-400' :
                        'text-neutral-400'
                      }`}>
                        {job.status.toLowerCase()}
                      </span>
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-neutral-300">{job.cpu_cores}</td>
                  <td className="px-4 py-3 text-right text-sm text-neutral-300">{job.memory_mib}m</td>
                  <td className="px-4 py-3 text-right text-sm text-neutral-300">{job.vram_mib}m</td>
                  <td className="px-4 py-3 text-sm text-neutral-400">
                    {job.exit_code !== null ? (
                      <span className={job.exit_code === 0 ? 'text-green-400' : 'text-red-400'}>
                        {job.exit_code}
                      </span>
                    ) : (
                      <span className="text-neutral-600">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-neutral-400">
                    {new Date(job.submitted_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-xs text-neutral-400">
                    {job.started_at ? new Date(job.started_at).toLocaleString() : '-'}
                  </td>
                  <td className="px-4 py-3 text-xs text-neutral-400">
                    {job.completed_at ? new Date(job.completed_at).toLocaleString() : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
