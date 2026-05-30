import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Login from "./pages/Login";
import Screener from "./pages/Screener";
import Chart from "./pages/Chart";
import Sidebar from "./components/Layout/Sidebar";
import ChatInterface from "./components/Chat/ChatInterface";
import SignalFeedPanel from "./components/SignalFeed/SignalFeedPanel";
import FnoLive from "./pages/FnoLive";
import { isAuthenticated } from "./api/client";

const queryClient = new QueryClient();

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", height: "100vh", background: "#0d0d1a", color: "#d1d4dc", overflow: "hidden" }}>
      <Sidebar />
      <div style={{ flex: 1, overflow: "auto" }}>{children}</div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/screener" element={
            <ProtectedRoute><AppLayout><Screener /></AppLayout></ProtectedRoute>
          } />
          <Route path="/chart/:symbol" element={
            <ProtectedRoute><AppLayout><Chart /></AppLayout></ProtectedRoute>
          } />
          <Route path="/signals" element={
            <ProtectedRoute><AppLayout><SignalFeedPanel /></AppLayout></ProtectedRoute>
          } />
          <Route path="/chat" element={
            <ProtectedRoute><AppLayout><ChatInterface /></AppLayout></ProtectedRoute>
          } />
          <Route path="/fno" element={
            <ProtectedRoute><AppLayout><FnoLive /></AppLayout></ProtectedRoute>
          } />
          <Route path="*" element={<Navigate to="/screener" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
