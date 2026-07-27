import { SectionCard } from "./SectionCard";

const events = [
  {
    id: 1,
    title: "Cluster initialized",
    time: "Just now",
  },
  {
    id: 2,
    title: "Dashboard connected",
    time: "1 min ago",
  },
  {
    id: 3,
    title: "Waiting for compute nodes",
    time: "2 min ago",
  },
];

export function ActivityFeed() {
  return (
    <SectionCard
      title="Activity Feed"
      subtitle="Recent cluster events"
    >
      <div className="space-y-4">
        {events.map((event) => (
          <div
            key={event.id}
            className="flex items-center justify-between rounded-lg border border-neutral-700 bg-neutral-900 px-4 py-3"
          >
            <span className="text-sm text-neutral-100">
              {event.title}
            </span>

            <span className="text-xs text-neutral-500">
              {event.time}
            </span>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}
