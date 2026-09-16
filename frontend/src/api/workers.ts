import { api } from "./client";
import type {
  CreateWorkerRequest,
  CreateWorkerResponse,
  GetWorkerResponse,
  ListWorkersResponse,
} from "./types";

export function listWorkers() {
  return api<ListWorkersResponse>("/workers");
}

export function getWorker(workerId: string) {
  return api<GetWorkerResponse>(`/workers/${workerId}`);
}

export function createWorker(worker: CreateWorkerRequest) {
  return api<CreateWorkerResponse>("/workers", {
    method: "POST",
    body: JSON.stringify(worker),
  });
}

export function heartbeatWorker(workerId: string) {
  return api<CreateWorkerResponse>(`/workers/${workerId}/heartbeat`, {
    method: "POST",
  });
}
