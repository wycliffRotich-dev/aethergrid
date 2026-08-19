import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { getApiKey, setApiKey, subscribeApiKey } from "../../api/authKey";

export function AuthGate({ children }: { children: ReactNode }) {
  const [key, setKey] = useState<string | null>(getApiKey());
  const [input, setInput] = useState("");

  useEffect(() => {
    return subscribeApiKey(setKey);
  }, []);

  if (key) {
    return <>{children}</>;
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (input.trim()) {
      setApiKey(input.trim());
    }
  }

  return (
    <div
      style={{
        display: "flex",
        minHeight: "100vh",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          maxWidth: 360,
          width: "100%",
          padding: 32,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
        }}
      >
        <img
          src="/logo.png"
          alt="AetherGrid"
          style={{ width: "100%", maxWidth: 220, height: "auto", marginBottom: 24 }}
        />
        <p style={{ marginBottom: 20, color: "#888", fontSize: 14, lineHeight: 1.5 }}>
          Enter your API key to access the dashboard. Your key stays in this
          browser tab and is never sent anywhere except this API.
        </p>
        <input
          type="password"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="API key"
          autoFocus
          style={{
            width: "100%",
            padding: "10px 12px",
            marginBottom: 14,
            borderRadius: 6,
            border: "1px solid #ccc",
            color: "#111",
            backgroundColor: "#fff",
            fontSize: 14,
          }}
        />
        <button
          type="submit"
          style={{
            width: "100%",
            padding: "10px 12px",
            borderRadius: 6,
            border: "none",
            backgroundColor: "#2563eb",
            color: "#fff",
            fontSize: 14,
            cursor: "pointer",
          }}
        >
          Continue
        </button>
      </form>
    </div>
  );
}
