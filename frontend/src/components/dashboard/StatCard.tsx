interface StatCardProps {
  title: string;
  value: number | string;
}

export function StatCard({
  title,
  value,
}: StatCardProps) {
  return (
    <div className="rounded-xl border border-neutral-700 bg-neutral-800 p-6 shadow">
      <p className="text-sm text-neutral-400">
        {title}
      </p>

      <h2 className="mt-3 text-3xl font-bold text-neutral-100">
        {value}
      </h2>
    </div>
  );
}