import { api } from "./client";
import type { CreateNodeRequest, CreateNodeResponse } from "./types";

export function createNode(node: CreateNodeRequest) {
  return api<CreateNodeResponse>("/nodes", {
    method: "POST",
    body: JSON.stringify(node),
  });
}

export function removeOfflineNode(nodeId: string) {
  return api<void>(`/nodes/${nodeId}`, {
    method: "DELETE",
  });
}

export function heartbeatNode(nodeId: string) {
  return api<CreateNodeResponse>(`/nodes/${nodeId}/heartbeat`, {
    method: "POST",
  });
}
