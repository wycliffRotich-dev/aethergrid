import { useState } from "react";

import { createJob } from "../../api/jobs";

type Props = {
  onSubmitted: () => void;
};

function actionErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong.";
}

export function SubmitJobForm({
  onSubmitted,
}: Props) {
  const [cpu, setCpu] = useState(1);
  const [memory, setMemory] = useState(2048);
  const [vram, setVram] = useState(0);
  const [command, setCommand] = useState("");

  const [loading, setLoading] =
    useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function submit(
    e: React.FormEvent,
  ) {
    e.preventDefault();

    setLoading(true);
    setSubmitError(null);

    try {
      const trimmedCommand = command.trim();

      await createJob({
        cpu_cores: cpu,
        memory_mib: memory,
        vram_mib: vram,
        ...(trimmedCommand.length > 0
          ? { command: trimmedCommand.split(/\s+/) }
          : {}),
      });

      onSubmitted();
    } catch (err) {
      setSubmitError(actionErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-6">
      <h2 className="mb-6 text-xl font-semibold text-white">
        Submit Job
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

        <div>
          <label className="mb-2 block text-sm text-slate-300">
            Command (optional)
          </label>

          <input
            type="text"
            value={command}
            onChange={(e) =>
              setCommand(e.target.value)
            }
            placeholder="python train.py --epochs 5"
            className="w-full rounded border border-slate-700 bg-slate-800 p-2 font-mono text-sm text-white placeholder:text-slate-600"
          />

          <p className="mt-1 text-xs text-slate-500">
            Split on spaces into an argv-style command, e.g.
            the same way you'd type it in a terminal. No shell
            operators like | or &gt; are supported. Leave blank
            for a no-op job.
          </p>
        </div>

        {submitError !== null && (
          <div className="flex items-center justify-between rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
            <span>{submitError}</span>
            <button
              type="button"
              onClick={() => setSubmitError(null)}
              className="ml-4 text-rose-400 hover:text-rose-300"
              aria-label="Dismiss error"
            >
              {"\u00d7"}
            </button>
          </div>
        )}

        <button
          disabled={loading}
          className="rounded bg-indigo-600 px-5 py-2 text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading
            ? "Submitting..."
            : "Submit Job"}
        </button>
      </form>
    </section>
  );
}
