import type {
  ClusterCapacityResponse,
  ClusterUtilizationResponse,
} from "../api/types";

export const HIGH_USAGE_THRESHOLD_PERCENT = 80;

export interface ClusterUtilizationPercentages {
  cpuPercent: number;
  memoryPercent: number;
  vramPercent: number;
}

function toUtilizationPercent(used: number, available: number): number {
  const total = used + available;

  return total > 0 ? (used / total) * 100 : 0;
}

/**
 * Converts raw available-capacity + used-utilization figures into
 * percentages. `capacity` here is REMAINING capacity, not total —
 * total = capacity + utilization, matching the convention already
 * established in ClusterHealth.
 */
export function computeUtilizationPercentages(
  capacity: ClusterCapacityResponse,
  utilization: ClusterUtilizationResponse,
): ClusterUtilizationPercentages {
  return {
    cpuPercent: toUtilizationPercent(utilization.cpu_cores, capacity.cpu_cores),
    memoryPercent: toUtilizationPercent(utilization.memory_mib, capacity.memory_mib),
    vramPercent: toUtilizationPercent(utilization.vram_mib, capacity.vram_mib),
  };
}
