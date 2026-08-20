import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { getApiKey, setApiKey, subscribeApiKey } from "../../api/authKey";

function LocalOnlyBanner() {
  return (
    <div
      style={{
        position: "relative",
        overflow: "hidden",
        borderRadius: 8,
        border: "1px solid rgba(37, 99, 235, 0.3)",
        backgroundColor: "rgba(37, 99, 235, 0.08)",
        padding: "10px 16px",
        marginBottom: 16,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(90deg, transparent, rgba(96,165,250,0.2), transparent)",
          animation: "shimmer 2.5s infinite",
        }}
      />
      <p
        style={{
          position: "relative",
          fontSize: 13,
          color: "#93c5fd",
          textAlign: "center",
          margin: 0,
        }}
      >
        No public API keys, by design. Clone the repo, run it locally, issue
        your own.
      </p>
      <style>{`
        @keyframes shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
      `}</style>
    </div>
  );
}

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
        <LocalOnlyBanner />
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
