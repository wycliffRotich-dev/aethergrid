import { Skeleton } from "./Skeleton";

/**
 * Placeholder for JobDetailPage/WorkerDetailPage while their data
 * is loading. Both pages share the same real layout (a back link, a
 * heading, a full id, a 4-column stat grid, then a bordered section
 * below it), so one skeleton shape serves both rather than each
 * page inventing its own.
 */
export function DetailPageSkeleton() {
  return (
    <div>
      <Skeleton className="mb-4 h-5 w-32" />
      <Skeleton className="mb-2 mt-4 h-9 w-64" />
      <Skeleton className="mb-8 h-4 w-80" />

      <div className="mb-8 grid grid-cols-2 gap-6 rounded-2xl border border-slate-800 bg-slate-900 p-6 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index}>
            <Skeleton className="mb-2 h-3 w-20" />
            <Skeleton className="h-6 w-24" />
          </div>
        ))}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
        <Skeleton className="mb-4 h-6 w-40" />
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}
