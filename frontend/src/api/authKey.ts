const STORAGE_KEY = "aethergrid_api_key";

let currentKey: string | null = sessionStorage.getItem(STORAGE_KEY);
const listeners = new Set<(key: string | null) => void>();

export function getApiKey(): string | null {
  return currentKey;
}

export function setApiKey(key: string | null): void {
  currentKey = key;
  if (key) {
    sessionStorage.setItem(STORAGE_KEY, key);
  } else {
    sessionStorage.removeItem(STORAGE_KEY);
  }
  listeners.forEach((listener) => listener(currentKey));
}

export function subscribeApiKey(listener: (key: string | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
