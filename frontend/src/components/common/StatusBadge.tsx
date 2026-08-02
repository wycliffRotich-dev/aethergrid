type Props = {
  status: "Healthy" | "Busy" | "Offline" | "Idle" | "Starting" | "Draining";
};

export function StatusBadge({ status }: Props) {
  const styles = {
    Healthy:
      "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30",
    Busy:
      "bg-amber-500/20 text-amber-400 border border-amber-500/30",
    Offline:
      "bg-red-500/20 text-red-400 border border-red-500/30",
    Idle:
      "bg-slate-500/20 text-slate-400 border border-slate-500/30",
    Starting:
      "bg-sky-500/20 text-sky-400 border border-sky-500/30",
    Draining:
      "bg-orange-500/20 text-orange-400 border border-orange-500/30",
  };

  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${styles[status]}`}
    >
      <span className="mr-2 h-2 w-2 rounded-full bg-current" />
      {status}
    </span>
  );
}
