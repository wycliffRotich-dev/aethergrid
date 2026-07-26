import type { NodeResponse } from "../../api/types";
import { StatusBadge } from "../common/StatusBadge";

type Props = {
  nodes: NodeResponse[];
};

export function NodeTable({ nodes }: Props) {
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
          </tr>
        </thead>

        <tbody>
          {nodes.length === 0 ? (
            <tr>
              <td
                colSpan={6}
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
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
