import { api } from "./client";
import type { ListWorkersResponse } from "./types";

export function listWorkers() {
  return api<ListWorkersResponse>("/workers");
}
