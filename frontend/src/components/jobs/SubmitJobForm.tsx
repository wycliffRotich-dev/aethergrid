import { useState } from "react";

import { createJob } from "../../api/jobs";

type Props = {
  onSubmitted: () => void;
};

export function SubmitJobForm({
  onSubmitted,
}: Props) {
  const [cpu, setCpu] = useState(1);
  const [memory, setMemory] = useState(2048);
  const [vram, setVram] = useState(0);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(
    e: React.FormEvent,
  ) {
    e.preventDefault();
    setError(null);

    if (cpu < 1) {
      setError("CPU cores must be at least 1.");
      return;
    }
    if (memory < 1) {
      setError("Memory must be at least 1 MiB.");
      return;
    }
    if (vram < 0) {
      setError("VRAM cannot be negative.");
      return;
    }

    setLoading(true);

    try {
      await createJob({
        cpu_cores: cpu,
        memory_mib: memory,
        vram_mib: vram,
      });

      onSubmitted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="border border-neutral-700 rounded-lg p-4">
      <h2 className="text-sm font-semibold text-white mb-4">
        Submit Job
      </h2>

      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="block text-xs text-neutral-400 mb-1">
            CPU Cores
          </label>
          <input
            type="number"
            value={cpu}
            onChange={(e) => setCpu(Number(e.target.value))}
            className="w-full border border-neutral-600 rounded p-2 text-sm text-white bg-neutral-800 focus:border-neutral-500 focus:outline-none"
          />
        </div>

        <div>
          <label className="block text-xs text-neutral-400 mb-1">
            Memory (MiB)
          </label>
          <input
            type="number"
            value={memory}
            onChange={(e) => setMemory(Number(e.target.value))}
            className="w-full border border-neutral-600 rounded p-2 text-sm text-white bg-neutral-800 focus:border-neutral-500 focus:outline-none"
          />
        </div>

        <div>
          <label className="block text-xs text-neutral-400 mb-1">
            VRAM (MiB)
          </label>
          <input
            type="number"
            value={vram}
            onChange={(e) => setVram(Number(e.target.value))}
            className="w-full border border-neutral-600 rounded p-2 text-sm text-white bg-neutral-800 focus:border-neutral-500 focus:outline-none"
          />
        </div>

        <button
          disabled={loading}
          className="w-full bg-muted-purple rounded p-2 text-sm text-white hover:bg-muted-purple-hover disabled:opacity-50 transition-colors"
        >
          {loading ? "Submitting..." : "Submit Job"}
        </button>

        {error && (
          <p className="text-xs text-neutral-400">
            {error}
          </p>
        )}
      </form>
    </section>
  );
}
