import { useEffect, useState } from "react";

import { useEvents } from "../../hooks/useEvents";
import { SectionCard } from "./SectionCard";

const EVENT_STYLES: Record<string, string> = {
  JobCreated: "bg-slate-400",
  JobScheduled: "bg-amber-400",
  WorkerAssigned: "bg-amber-400",
  LeaseAcquired: "bg-amber-400",
  LeaseReleased: "bg-slate-500",
  JobCompleted: "bg-emerald-500",
  JobFailed: "bg-rose-500",
  JobReclaimed: "bg-rose-400",
};

function useNow(): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const interval = setInterval(() => {
      setNow(Date.now());
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  return now;
}

function formatRelativeTime(occurredAt: string, now: number): string {
  const seconds = Math.max(
    0,
    Math.floor((now - new Date(occurredAt).getTime()) / 1000),
  );

  if (seconds < 5) {
    return "just now";
  }

  if (seconds < 60) {
    return `${seconds}s ago`;
  }

  const minutes = Math.floor(seconds / 60);

  if (minutes < 60) {
    return `${minutes}m ago`;
  }

  const hours = Math.floor(minutes / 60);

  return `${hours}h ago`;
}

function shortId(id: string): string {
  return id.slice(0, 8);
}

export function ActivityFeed() {
  const { events, loading, error } = useEvents();
  const now = useNow();

  const recent = events.slice(-25).reverse();

  return (
    <SectionCard
      title="Activity Feed"
      subtitle="Live cluster events"
    >
      {loading ? (
        <p className="text-sm text-slate-500">
          Loading events...
        </p>
      ) : error ? (
        <p className="text-sm text-rose-400">
          {error}
        </p>
      ) : recent.length === 0 ? (
        <p className="text-sm text-slate-500">
          No events recorded yet.
        </p>
      ) : (
        <div className="max-h-96 space-y-2 overflow-y-auto">
          {recent.map((event) => (
            <div
              key={event.id}
              className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-4 py-3"
            >
              <span className="flex items-center gap-2 text-sm text-white">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    EVENT_STYLES[event.event_type] ?? "bg-slate-500"
                  }`}
                />
                {event.event_type}
                <span className="font-mono text-xs text-slate-500">
                  {shortId(event.aggregate_id)}
                </span>
              </span>

              <span className="text-xs text-slate-500">
                {formatRelativeTime(event.occurred_at, now)}
              </span>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
