import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Login from "./pages/Login";
import Screener from "./pages/Screener";
import { isAuthenticated } from "./api/client";

const queryClient = new QueryClient();

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/screener" element={
            <ProtectedRoute><Screener /></ProtectedRoute>
          } />
          <Route path="/chart/:symbol" element={
            <ProtectedRoute><div>Chart (Task 22)</div></ProtectedRoute>
          } />
          <Route path="/signals" element={
            <ProtectedRoute><div>Signals (Task 23)</div></ProtectedRoute>
          } />
          <Route path="/chat" element={
            <ProtectedRoute><div>Chat (Task 23)</div></ProtectedRoute>
          } />
          <Route path="*" element={<Navigate to="/screener" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
