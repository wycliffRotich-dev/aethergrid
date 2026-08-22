import { getApiKey, setApiKey } from "./authKey";

const API_BASE =
  import.meta.env.VITE_API_URL ??
  "http://localhost:8000";

export async function api<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(
    `${API_BASE}${path}`,
    {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getApiKey() ?? ""}`,
        ...(init?.headers ?? {}),
      },
    },
  );
  if (!response.ok) {
    if (response.status === 401) {
      // Key was present but the server rejected it (rotated, revoked,
      // expired). Clear it so AuthGate falls back to the login form
      // instead of leaving the user stranded on a bare error screen.
      setApiKey(null);
    }
    throw new Error(
      `API Error ${response.status}`,
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json();
}
