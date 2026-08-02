import { NodeTable } from "../components/nodes/NodeTable";
import { RegisterNodeForm } from "../components/nodes/RegisterNodeForm";
import { useNodes } from "../hooks/useNodes";

export default function NodesPage() {
  const {
    nodes,
    loading,
    error,
    refresh,
  } = useNodes();

  if (loading) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-white">
        Loading nodes...
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex-1 bg-slate-950 p-8 text-red-400">
        {error}
      </main>
    );
  }

  return (
    <main className="flex-1 bg-slate-950 p-8">
      <h1 className="mb-8 text-3xl font-bold text-white">
        Nodes
      </h1>

      <RegisterNodeForm
        onCreated={refresh}
      />

      <NodeTable
        nodes={nodes}
        onChanged={refresh}
      />
    </main>
  );
}
