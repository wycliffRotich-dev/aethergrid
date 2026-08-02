import { useState } from "react";

import { createNode } from "../../api/nodes";
import { createWorker } from "../../api/workers";

type Props = {
  onCreated: () => void;
};

export function RegisterNodeForm({
  onCreated,
}: Props) {
  const [cpu, setCpu] = useState(8);
  const [memory, setMemory] = useState(32768);
  const [vram, setVram] = useState(8192);

  const [loading, setLoading] = useState(false);

  async function submit(
    event: React.FormEvent,
  ) {
    event.preventDefault();

    setLoading(true);

    try {
      const node = await createNode({
        cpu_cores: cpu,
        memory_mib: memory,
        vram_mib: vram,
      });

      // A node with no worker can never execute anything --
      // it just sits idle until its heartbeat goes stale and
      // it flips to offline. Registering a worker against the
      // node immediately is what actually makes it capable of
      // running jobs, not just existing as capacity on paper.
      await createWorker({
        node_id: node.id,
      });

      onCreated();
    } catch (error) {
      alert(error);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-6">
      <h2 className="mb-6 text-xl font-semibold text-white">
        Register Compute Node
      </h2>

      <form
        onSubmit={submit}
        className="space-y-4"
      >
        <div>
          <label className="mb-2 block text-sm text-slate-300">
            CPU Cores
          </label>

          <input
            type="number"
            value={cpu}
            onChange={(e) =>
              setCpu(Number(e.target.value))
            }
            className="w-full rounded border border-slate-700 bg-slate-800 p-2 text-white"
          />
        </div>

        <div>
          <label className="mb-2 block text-sm text-slate-300">
            Memory (MiB)
          </label>

          <input
            type="number"
            value={memory}
            onChange={(e) =>
              setMemory(Number(e.target.value))
            }
            className="w-full rounded border border-slate-700 bg-slate-800 p-2 text-white"
          />
        </div>

        <div>
          <label className="mb-2 block text-sm text-slate-300">
            VRAM (MiB)
          </label>

          <input
            type="number"
            value={vram}
            onChange={(e) =>
              setVram(Number(e.target.value))
            }
            className="w-full rounded border border-slate-700 bg-slate-800 p-2 text-white"
          />
        </div>

        <button
          disabled={loading}
          className="rounded bg-indigo-600 px-5 py-2 font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading
            ? "Registering..."
            : "Register Node"}
        </button>
      </form>
    </section>
  );
}
