import { useState } from "react";
import type { NodeResponse } from "../../api/types";
import { removeOfflineNode } from "../../api/nodes";
import { StatusBadge } from "../common/StatusBadge";

type Props = {
  nodes: NodeResponse[];
  onChanged: () => void;
};

export function NodeTable({ nodes, onChanged }: Props) {
  const [removingId, setRemovingId] = useState<string | null>(null);

  async function handleRemove(nodeId: string) {
    setRemovingId(nodeId);

    try {
      await removeOfflineNode(nodeId);
      onChanged();
    } catch (error) {
      alert(error);
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <section className="mt-10 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-lg">
      <div className="flex items-center justify-between border-b border-slate-800 px-6 py-5">
        <div>
          <h2 className="text-xl font-semibold text-white">
            Cluster Nodes
          </h2>

          <p className="mt-1 text-sm text-slate-400">
            Registered compute resources
          </p>
        </div>

        <div className="rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-300">
          {nodes.length} Nodes
        </div>
      </div>

      <table className="w-full">
        <thead className="bg-slate-800/60 text-left text-xs uppercase tracking-wider text-slate-400">
          <tr>
            <th className="px-6 py-4">Node ID</th>
            <th>Health</th>
            <th>Total CPU</th>
            <th>Available CPU</th>
            <th>Memory</th>
            <th>VRAM</th>
            <th></th>
          </tr>
        </thead>

        <tbody>
          {nodes.length === 0 ? (
            <tr>
              <td
                colSpan={7}
                className="py-12 text-center text-slate-500"
              >
                No compute nodes have been registered.
              </td>
            </tr>
          ) : (
            nodes.map((node) => (
              <tr
                key={node.id}
                className="border-t border-slate-800 transition-colors hover:bg-slate-800/40"
              >
                <td className="px-6 py-4 font-mono text-sm text-white">
                  {node.id}
                </td>

                <td>
                  <StatusBadge status={node.is_alive ? "Healthy" : "Offline"} />
                </td>

                <td>{node.cpu_cores}</td>

                <td className="text-emerald-400">
                  {node.available_cpu_cores}
                </td>

                <td>
                  {node.memory_mib.toLocaleString()} MiB
                </td>

                <td>
                  {node.vram_mib.toLocaleString()} MiB
                </td>

                <td className="px-6 py-4 text-right">
                  {!node.is_alive && (
                    <button
                      onClick={() => handleRemove(node.id)}
                      disabled={removingId === node.id}
                      className="rounded border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                    >
                      {removingId === node.id ? "Removing..." : "Remove"}
                    </button>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
