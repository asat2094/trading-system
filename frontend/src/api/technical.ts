import { useQuery } from "@tanstack/react-query";
import { apiClient } from "./client";

interface OHLCVRow {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function useOHLCV(symbol: string, tf: string, fromDt: string, toDt: string) {
  return useQuery({
    queryKey: ["ohlcv", symbol, tf, fromDt, toDt],
    queryFn: async (): Promise<OHLCVRow[]> => {
      const { data } = await apiClient.get(`/technical/ohlcv/${symbol}`, {
        params: { tf, from_dt: fromDt, to_dt: toDt },
      });
      return data.rows;
    },
    enabled: !!symbol,
  });
}
