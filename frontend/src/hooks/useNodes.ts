import { useCallback, useEffect, useState } from "react";

import { fetchNodes } from "../api/dashboard";
import type { NodeResponse } from "../api/types";

export function useNodes() {
  const [nodes, setNodes] = useState<NodeResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetchNodes();

      setNodes(response.nodes);
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unknown error");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    nodes,
    loading,
    error,
    refresh,
  };
}