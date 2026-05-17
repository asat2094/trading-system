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
    <div style={{ padding: 16, height: "100%" }}>
      <h3>Ask in plain English</h3>
      <textarea
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="e.g. Show me oversold large cap NSE stocks with uptrend in last 2 hours"
        rows={4}
        style={{ width: "100%", padding: 8, marginBottom: 8 }}
      />
      <button onClick={() => sendQuery(query)} disabled={isPending || !query}>
        {isPending ? "Thinking..." : "Analyze"}
      </button>
      {error && <p style={{ color: "red" }}>Error: budget exceeded or API unavailable</p>}
      {data && (
        <div style={{ marginTop: 16 }}>
          <p style={{ color: "#aaa" }}>{data.explanation}</p>
          <p>Redirecting to screener...</p>
        </div>
      )}
    </div>
  );
}
