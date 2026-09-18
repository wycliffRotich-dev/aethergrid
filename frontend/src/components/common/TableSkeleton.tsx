import { Skeleton } from "./Skeleton";

type Props = {
  rows?: number;
  columns?: number;
};

/**
 * Placeholder rows for a table-shaped list page (Jobs, Nodes,
 * Workers) while its data is loading. rows/columns default to a
 * shape close enough to the real tables that the layout does not
 * visibly jump once real data replaces it.
 */
export function TableSkeleton({ rows = 5, columns = 5 }: Props) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900">
      <div className="divide-y divide-slate-800">
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <div
            key={rowIndex}
            className="flex items-center gap-6 px-6 py-4"
          >
            {Array.from({ length: columns }).map((_, colIndex) => (
              <Skeleton key={colIndex} className="h-4 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
