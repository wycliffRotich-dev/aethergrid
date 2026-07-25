import { api } from "./client";
import type {
  ClusterCapacityResponse,
  ClusterHealthResponse,
  ClusterUtilizationResponse,
  ListNodesResponse,
} from "./types";

export function fetchNodes() {
  return api<ListNodesResponse>("/nodes");
}

export function fetchClusterHealth() {
  return api<ClusterHealthResponse>("/cluster/health");
}

export function fetchClusterCapacity() {
  return api<ClusterCapacityResponse>("/cluster/capacity");
}

export function fetchClusterUtilization() {
  return api<ClusterUtilizationResponse>("/cluster/utilization");
}
