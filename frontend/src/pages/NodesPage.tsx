import { useNodes } from "../hooks/useNodes";
import { RegisterNodeForm } from "../components/nodes/RegisterNodeForm";

export default function NodesPage() {
  const { nodes, loading, error, refresh } = useNodes();

  if (loading) {
    return (
      <main className="flex-1 p-4 text-neutral-300">
        Loading...
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex-1 p-4 text-red-400">
        {error}
      </main>
    );
  }

  const totalCpu = nodes.reduce((sum, node) => sum + node.cpu_cores, 0);
  const totalMemory = nodes.reduce((sum, node) => sum + node.memory_mib, 0);
  const totalVram = nodes.reduce((sum, node) => sum + node.vram_mib, 0);
  const availableCpu = nodes.reduce((sum, node) => sum + node.available_cpu_cores, 0);
  const availableMemory = nodes.reduce((sum, node) => sum + node.available_memory_mib, 0);
  const availableVram = nodes.reduce((sum, node) => sum + node.available_vram_mib, 0);

  return (
    <main className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-white">Compute Nodes</h1>
        <button
          onClick={() => refresh()}
          className="px-3 py-1.5 text-xs bg-neutral-800 hover:bg-neutral-700 text-neutral-300 rounded border border-neutral-700 transition-colors"
        >
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Total Nodes</p>
          <p className="text-2xl font-semibold text-white mt-1">{nodes.length}</p>
        </div>
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">CPU</p>
          <p className="text-2xl font-semibold text-white mt-1">{totalCpu}</p>
          <p className="text-xs text-neutral-400 mt-1">{availableCpu} available</p>
        </div>
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Memory</p>
          <p className="text-2xl font-semibold text-white mt-1">{totalMemory.toLocaleString()}</p>
          <p className="text-xs text-neutral-400 mt-1">{availableMemory.toLocaleString()} available</p>
        </div>
        <div className="border border-neutral-700 rounded p-3">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">VRAM</p>
          <p className="text-2xl font-semibold text-white mt-1">{totalVram.toLocaleString()}</p>
          <p className="text-xs text-neutral-400 mt-1">{availableVram.toLocaleString()} available</p>
        </div>
        <div className="border border-neutral-700 rounded p-3 col-span-2 md:col-span-1">
          <p className="text-xs text-neutral-500 uppercase tracking-wide">Register</p>
          <RegisterNodeForm onCreated={refresh} compact />
        </div>
      </div>

      {nodes.length === 0 ? (
        <div className="border border-neutral-700 rounded-lg p-8 text-center">
          <p className="text-neutral-500">No nodes registered.</p>
          <p className="text-neutral-600 text-sm mt-1">Register a node to get started.</p>
        </div>
      ) : (
        <div className="border border-neutral-700 rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-neutral-800 border-b border-neutral-700">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-400 uppercase tracking-wider">Node ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-neutral-400 uppercase tracking-wider">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-neutral-400 uppercase tracking-wider">CPU Cores</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-neutral-400 uppercase tracking-wider">Memory (MiB)</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-neutral-400 uppercase tracking-wider">VRAM (MiB)</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-neutral-400 uppercase tracking-wider">Available CPU</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-neutral-400 uppercase tracking-wider">Available Mem</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-neutral-400 uppercase tracking-wider">Available VRAM</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-700">
              {nodes.map((node) => (
                <tr key={node.id} className="hover:bg-neutral-800/50">
                  <td className="px-4 py-3 font-mono text-xs text-neutral-300">{node.id.slice(0, 8)}</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full bg-neutral-400" />
                      <span className="text-xs text-neutral-400">online</span>
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-neutral-300">{node.cpu_cores}</td>
                  <td className="px-4 py-3 text-right text-sm text-neutral-300">{node.memory_mib.toLocaleString()}</td>
                  <td className="px-4 py-3 text-right text-sm text-neutral-300">{node.vram_mib.toLocaleString()}</td>
                  <td className="px-4 py-3 text-right text-sm text-neutral-300">{node.available_cpu_cores}</td>
                  <td className="px-4 py-3 text-right text-sm text-neutral-300">{node.available_memory_mib.toLocaleString()}</td>
                  <td className="px-4 py-3 text-right text-sm text-neutral-300">{node.available_vram_mib.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
