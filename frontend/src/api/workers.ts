import { api } from "./client";
import type {
  CreateWorkerRequest,
  CreateWorkerResponse,
  ListWorkersResponse,
} from "./types";

export function listWorkers() {
  return api<ListWorkersResponse>("/workers");
}

export function createWorker(worker: CreateWorkerRequest) {
  return api<CreateWorkerResponse>("/workers", {
    method: "POST",
    body: JSON.stringify(worker),
  });
}
