import { describe, expect, it } from "vitest";

import { computeUtilizationPercentages } from "./clusterMetrics";

describe("computeUtilizationPercentages", () => {
  it("returns 0 when a cluster has no capacity at all", () => {
    const result = computeUtilizationPercentages(
      { cpu_cores: 0, memory_mib: 0, vram_mib: 0 },
      { cpu_cores: 0, memory_mib: 0, vram_mib: 0 },
    );

    expect(result.cpuPercent).toBe(0);
    expect(result.memoryPercent).toBe(0);
    expect(result.vramPercent).toBe(0);
  });

  it("computes the correct percentage for partial usage", () => {
    const result = computeUtilizationPercentages(
      { cpu_cores: 4, memory_mib: 8192, vram_mib: 4096 },
      { cpu_cores: 4, memory_mib: 8192, vram_mib: 4096 },
    );

    expect(result.cpuPercent).toBe(50);
    expect(result.memoryPercent).toBe(50);
    expect(result.vramPercent).toBe(50);
  });

  it("reports 100 percent when there is no remaining capacity", () => {
    const result = computeUtilizationPercentages(
      { cpu_cores: 0, memory_mib: 0, vram_mib: 0 },
      { cpu_cores: 8, memory_mib: 16384, vram_mib: 8192 },
    );

    expect(result.cpuPercent).toBe(100);
    expect(result.memoryPercent).toBe(100);
    expect(result.vramPercent).toBe(100);
  });
});
