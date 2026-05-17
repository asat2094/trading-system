import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export const apiClient = axios.create({ baseURL: API_BASE });

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401 && window.location.pathname !== "/login") {
      localStorage.removeItem("access_token");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export async function login(username: string, password: string): Promise<string> {
  const { data } = await apiClient.post<{ access_token: string }>("/auth/login", {
    username,
    password,
  });
  localStorage.setItem("access_token", data.access_token);
  return data.access_token;
}

export function logout(): void {
  localStorage.removeItem("access_token");
  window.location.href = "/login";
}

export function isAuthenticated(): boolean {
  return !!localStorage.getItem("access_token");
}
