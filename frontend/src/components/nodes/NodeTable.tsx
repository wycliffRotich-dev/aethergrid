import type { NodeResponse } from "../../api/types";

type Props = {
  nodes: NodeResponse[];
};

export function NodeTable({ nodes }: Props) {
  return (
    <section className="border border-neutral-700 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-700">
        <h2 className="text-sm font-semibold text-white">
          Nodes
        </h2>
        <span className="text-xs text-neutral-500">
          {nodes.length}
        </span>
      </div>

      {nodes.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-neutral-500">
          No nodes registered.
        </div>
      ) : (
        <div className="divide-y divide-neutral-700">
          {nodes.map((node) => (
            <div key={node.id} className="px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <span className="font-mono text-xs text-neutral-300">
                  {node.id.slice(0, 8)}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-neutral-500" />
                  <span className="text-xs text-neutral-500">online</span>
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs text-neutral-400">
                <div>
                  <span className="text-neutral-600">CPU</span>
                  <span className="ml-2 text-neutral-300">{node.cpu_cores}</span>
                </div>
                <div>
                  <span className="text-neutral-600">Mem</span>
                  <span className="ml-2 text-neutral-300">{node.memory_mib.toLocaleString()}</span>
                </div>
                <div>
                  <span className="text-neutral-600">VRAM</span>
                  <span className="ml-2 text-neutral-300">{node.vram_mib.toLocaleString()}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
