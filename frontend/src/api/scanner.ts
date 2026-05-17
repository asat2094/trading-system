import { useMutation, useQuery } from "@tanstack/react-query";
import { apiClient } from "./client";

interface ScanRequest {
  source: string;
  filters: Array<{ field: string; operator: string; value: unknown }>;
  indicators: string[];
  max_symbols: number;
}

interface ScanResult {
  symbol: string;
  signals?: Record<string, unknown>;
  score?: number;
}

interface ScanResponse {
  symbols: string[];
  results?: ScanResult[];
}

export function useRunScan() {
  return useMutation({
    mutationFn: async (req: ScanRequest): Promise<ScanResponse> => {
      const { data } = await apiClient.post<ScanResponse>("/scanner/run", req);
      return data;
    },
  });
}

export function useListSignals() {
  return useQuery({
    queryKey: ["signals"],
    queryFn: async () => {
      const { data } = await apiClient.get("/scanner/signals");
      return data;
    },
  });
}
