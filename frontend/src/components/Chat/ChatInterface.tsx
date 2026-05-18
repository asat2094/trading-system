import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "../../api/client";
import { useFiltersStore } from "../../store/filters";
import { useNavigate } from "react-router-dom";

export default function ChatInterface() {
  const [query, setQuery] = useState("");
  const { setSource } = useFiltersStore();
  const navigate = useNavigate();

  const { mutate: sendQuery, data, isPending, error } = useMutation({
    mutationFn: async (q: string) => {
      const { data } = await apiClient.post("/chat/query", { query: q });
      return data;
    },
    onSuccess: (data) => {
      if (data.dsl?.source?.name) {
        setSource(data.dsl.source.name);
        navigate("/screener");
      }
    },
  });

  return (
    <div style={{ padding: 24, height: "100vh", display: "flex", flexDirection: "column", background: "#0d0d1a" }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>AI Chat</h2>
        <p style={{ margin: "4px 0 0", color: "#787b86", fontSize: 13 }}>Describe what you're looking for in plain English</p>
      </div>

      {/* Response area */}
      {data && (
        <div style={{ marginBottom: 16, padding: 16, background: "#131722", border: "1px solid #2a2e39", borderRadius: 6 }}>
          <p style={{ margin: 0, color: "#d1d4dc", fontSize: 13, lineHeight: 1.6 }}>{data.explanation}</p>
          <p style={{ margin: "8px 0 0", color: "#26a69a", fontSize: 12 }}>✓ Redirecting to screener...</p>
        </div>
      )}

      {error && (
        <div style={{ marginBottom: 16, padding: 12, background: "rgba(239,83,80,0.1)", border: "1px solid rgba(239,83,80,0.3)", borderRadius: 6, color: "#ef5350", fontSize: 13 }}>
          LLM budget exceeded or API unavailable. Enable ENABLE_LLM_CHAT in .env to use this feature.
        </div>
      )}

      {/* Input area */}
      <div style={{ background: "#131722", border: "1px solid #2a2e39", borderRadius: 6, overflow: "hidden" }}>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && e.metaKey) sendQuery(query); }}
          placeholder="e.g. Show me oversold large-cap NSE stocks with uptrend in the last 2 hours..."
          rows={4}
          style={{
            width: "100%", padding: 16, background: "transparent", border: "none",
            color: "#d1d4dc", fontSize: 14, resize: "none", outline: "none", lineHeight: 1.6,
          }}
        />
        <div style={{ padding: "8px 16px", borderTop: "1px solid #2a2e39", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "#363c4e" }}>⌘ + Enter to send</span>
          <button
            onClick={() => sendQuery(query)}
            disabled={isPending || !query.trim()}
            style={{
              padding: "7px 20px", background: isPending || !query.trim() ? "#1e222d" : "#2962ff",
              border: "1px solid", borderColor: isPending || !query.trim() ? "#2a2e39" : "#2962ff",
              borderRadius: 4, color: isPending || !query.trim() ? "#787b86" : "#fff",
              fontSize: 13, fontWeight: 600, cursor: isPending || !query.trim() ? "not-allowed" : "pointer",
            }}
          >
            {isPending ? "Thinking..." : "Analyze →"}
          </button>
        </div>
      </div>
    </div>
  );
}
