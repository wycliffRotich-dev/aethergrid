const API_BASE =
  import.meta.env.VITE_API_URL ??
  "http://localhost:8000";

const API_KEY = import.meta.env.VITE_API_KEY;

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
        Authorization: `Bearer ${API_KEY}`,
        ...(init?.headers ?? {}),
      },
    },
  );

  if (!response.ok) {
    throw new Error(
      `API Error ${response.status}`,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}
