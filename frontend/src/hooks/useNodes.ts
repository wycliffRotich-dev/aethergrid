import { fetchNodes } from "../api/dashboard";
import { useAsyncResource } from "./useAsyncResource";

export function useNodes() {
  const { data, loading, error, refresh } = useAsyncResource(fetchNodes, []);

  return {
    nodes: data?.nodes ?? [],
    loading,
    error,
    refresh,
  };
}
