import { useEffect, useState } from "react";

import { Skeleton } from "../common/Skeleton";
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

function formatFullTimestamp(occurredAt: string): string {
  return new Date(occurredAt).toLocaleString();
}

export function ActivityFeed() {
  const { events, loading, error } = useEvents();
  const now = useNow();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const recent = events.slice(-25).reverse();

  function toggleExpanded(eventId: string) {
    setExpandedId((current) => (current === eventId ? null : eventId));
  }

  return (
    <SectionCard
      title="Activity Feed"
      subtitle="Live cluster events"
    >
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-11 w-full rounded-lg" />
          ))}
        </div>
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
          {recent.map((event) => {
            const isExpanded = expandedId === event.id;
            const payloadEntries = Object.entries(event.payload);

            return (
              <div
                key={event.id}
                className="rounded-lg border border-slate-800 bg-slate-950"
              >
                <button
                  onClick={() => toggleExpanded(event.id)}
                  className="flex w-full items-center justify-between px-4 py-3 text-left"
                  aria-expanded={isExpanded}
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

                  <span className="flex items-center gap-2 text-xs text-slate-500">
                    {formatRelativeTime(event.occurred_at, now)}
                    <span
                      className={`transition-transform ${isExpanded ? "rotate-90" : ""}`}
                    >
                      {"\u203a"}
                    </span>
                  </span>
                </button>

                {isExpanded && (
                  <div className="border-t border-slate-800 px-4 py-3 text-xs">
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                      <div>
                        <p className="uppercase tracking-wider text-slate-500">
                          Aggregate Type
                        </p>
                        <p className="mt-1 text-slate-300">
                          {event.aggregate_type}
                        </p>
                      </div>

                      <div>
                        <p className="uppercase tracking-wider text-slate-500">
                          Aggregate Id
                        </p>
                        <p className="mt-1 font-mono text-slate-300">
                          {event.aggregate_id}
                        </p>
                      </div>

                      <div>
                        <p className="uppercase tracking-wider text-slate-500">
                          Occurred At
                        </p>
                        <p className="mt-1 text-slate-300">
                          {formatFullTimestamp(event.occurred_at)}
                        </p>
                      </div>
                    </div>

                    {payloadEntries.length > 0 && (
                      <div className="mt-3 border-t border-slate-800 pt-3">
                        <p className="uppercase tracking-wider text-slate-500">
                          Payload
                        </p>
                        <div className="mt-2 space-y-1">
                          {payloadEntries.map(([key, value]) => (
                            <div key={key} className="flex gap-2 font-mono">
                              <span className="text-slate-500">{key}:</span>
                              <span className="text-slate-300">{value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </SectionCard>
  );
}
