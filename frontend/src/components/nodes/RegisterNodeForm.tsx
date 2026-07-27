import { useState } from "react";

type Props = {
  onCreated: () => void;
  compact?: boolean;
};

export function RegisterNodeForm({
  onCreated,
  compact = false,
}: Props) {
  const [cpu, setCpu] = useState(8);
  const [memory, setMemory] = useState(32768);
  const [vram, setVram] = useState(8192);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(
    event: React.FormEvent,
  ) {
    event.preventDefault();
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
      const response = await fetch(
        "http://localhost:8000/nodes",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            cpu_cores: cpu,
            memory_mib: memory,
            vram_mib: vram,
          }),
        },
      );

      if (!response.ok) {
        throw new Error("Failed to register node.");
      }

      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  if (compact) {
    return (
      <form onSubmit={submit} className="space-y-2">
        <div className="flex gap-2">
          <input
            type="number"
            value={cpu}
            onChange={(e) => setCpu(Number(e.target.value))}
            placeholder="CPU"
            className="w-16 border border-neutral-600 rounded p-1.5 text-xs text-white bg-neutral-800 focus:border-neutral-500 focus:outline-none"
          />
          <input
            type="number"
            value={memory}
            onChange={(e) => setMemory(Number(e.target.value))}
            placeholder="Mem"
            className="w-20 border border-neutral-600 rounded p-1.5 text-xs text-white bg-neutral-800 focus:border-neutral-500 focus:outline-none"
          />
          <input
            type="number"
            value={vram}
            onChange={(e) => setVram(Number(e.target.value))}
            placeholder="VRAM"
            className="w-20 border border-neutral-600 rounded p-1.5 text-xs text-white bg-neutral-800 focus:border-neutral-500 focus:outline-none"
          />
        </div>
        <button
          disabled={loading}
          className="w-full bg-muted-purple rounded p-1.5 text-xs text-white hover:bg-muted-purple-hover disabled:opacity-50 transition-colors"
        >
          {loading ? "..." : "Register"}
        </button>
        {error && (
          <p className="text-xs text-red-400">{error}</p>
        )}
      </form>
    );
  }

  return (
    <section className="border border-neutral-700 rounded-lg p-4">
      <h2 className="text-sm font-semibold text-white mb-4">
        Register Node
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
          {loading ? "Registering..." : "Register Node"}
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
