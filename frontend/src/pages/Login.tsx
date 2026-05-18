import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/client";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      navigate("/screener");
    } catch {
      setError("Invalid credentials");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", background: "#0d0d1a", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 380, background: "#131722", border: "1px solid #2a2e39", borderRadius: 8, padding: 40 }}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{ fontSize: 28, fontWeight: 700, color: "#2962ff", marginBottom: 4 }}>⚡ TradingOS</div>
          <div style={{ color: "#787b86", fontSize: 13 }}>NSE · BSE Market Intelligence</div>
        </div>
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", fontSize: 11, color: "#787b86", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 6 }}>Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              style={{ width: "100%", padding: "10px 12px", background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4, color: "#d1d4dc", fontSize: 14, outline: "none" }}
              onFocus={e => e.target.style.borderColor = "#2962ff"}
              onBlur={e => e.target.style.borderColor = "#2a2e39"}
            />
          </div>
          <div style={{ marginBottom: 24 }}>
            <label style={{ display: "block", fontSize: 11, color: "#787b86", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 6 }}>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              style={{ width: "100%", padding: "10px 12px", background: "#1e222d", border: "1px solid #2a2e39", borderRadius: 4, color: "#d1d4dc", fontSize: 14, outline: "none" }}
              onFocus={e => e.target.style.borderColor = "#2962ff"}
              onBlur={e => e.target.style.borderColor = "#2a2e39"}
            />
          </div>
          {error && (
            <div style={{ background: "rgba(239,83,80,0.1)", border: "1px solid rgba(239,83,80,0.3)", borderRadius: 4, padding: "8px 12px", color: "#ef5350", fontSize: 13, marginBottom: 16 }}>
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={loading || !username || !password}
            style={{ width: "100%", padding: "11px 0", background: loading ? "#1e4bd0" : "#2962ff", color: "#fff", border: "none", borderRadius: 4, fontSize: 14, fontWeight: 600, cursor: loading ? "not-allowed" : "pointer", opacity: (!username || !password) ? 0.6 : 1 }}
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
}
