import { WorkerTable } from "../components/workers/WorkerTable";
import { TableSkeleton } from "../components/common/TableSkeleton";
import { useWorkers } from "../hooks/useWorkers";

export default function WorkersPage() {
  const {
    workers,
    loading,
    error,
  } = useWorkers();

  if (loading) {
    return (
      <main className="flex-1 bg-slate-950 p-8">
        <h1 className="mb-8 text-3xl font-bold text-white">
          Workers
        </h1>
        <TableSkeleton rows={3} columns={5} />
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
        Workers
      </h1>

      <WorkerTable
        workers={workers}
      />
    </main>
  );
}
