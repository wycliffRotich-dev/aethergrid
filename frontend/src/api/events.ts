import { api } from "./client";
import type { ListEventsResponse } from "./types";

export function listEvents() {
  return api<ListEventsResponse>("/events");
}
