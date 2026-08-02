import { useCallback, useEffect, useState } from "react";

import { listEvents } from "../api/events";
import type { EventResponse } from "../api/types";

const POLL_INTERVAL_MS = 3000;

export function useEvents() {
  const [events, setEvents] = useState<EventResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await listEvents();

      setEvents(response.events);
      setError(null);
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unknown error");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();

    const interval = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [refresh]);

  return {
    events,
    loading,
    error,
    refresh,
  };
}
