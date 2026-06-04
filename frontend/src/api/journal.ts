import { apiClient as client } from "./client";

export interface JrnTrade {
  id: number;
  broker: string;
  trade_date: string;
  trade_time: string | null;
  symbol: string;
  raw_symbol: string;
  underlying: string;
  exchange: string;
  segment: string;
  trade_type: "BUY" | "SELL";
  quantity: number;
  price: number;
  brokerage: number;
  status: string;
  remark: string | null;
  is_force_squared: boolean;
  fill_grain: "fill" | "wap";
}

export interface JrnPair {
  id: number;
  broker: string | null;
  symbol: string;
  underlying: string;
  side: "LONG" | "SHORT";
  quantity: number;
  lots: number | null;
  open_date: string;
  open_time: string | null;
  entry_price: number;
  close_date: string | null;
  close_time: string | null;
  exit_price: number | null;
  gross_pnl: number | null;
  net_pnl: number | null;
  hold_seconds: number | null;
  is_intraday: boolean | null;
  force_squared: boolean;
  charges: Record<string, string> | null;
}

export interface JrnSummary {
  id: number;
  trade_date: string;
  broker: string | null;
  fiscal_year: string | null;
  total_fills: number;
  total_lots: number;
  failed_order_count: number;
  force_squared_count: number;
  first_trade_time: string | null;
  last_trade_time: string | null;
  avg_hold_seconds: number | null;
  time_bucket_pnl: Record<string, number> | null;
  gross_pnl: number;
  total_charges: number;
  net_pnl: number;
  win_pairs: number;
  loss_pairs: number;
  open_pairs: number;
}

export const journalApi = {
  importPdf: (file: File, broker = "auto", password?: string) => {
    const form = new FormData();
    form.append("file", file);
    return client.post<{ imported: number; inserted: number; filename: string; dates: string[] }>(
      `/journal/import/pdf?broker=${broker}${password ? `&password=${password}` : ""}`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } }
    );
  },
  getTrades: (params?: Record<string, string>) =>
    client.get<JrnTrade[]>("/journal/trades", { params }),
  getPairs: (params?: Record<string, string>) =>
    client.get<JrnPair[]>("/journal/pairs", { params }),
  getSummaries: (params?: Record<string, string>) =>
    client.get<JrnSummary[]>("/journal/summary", { params }),
  recompute: (date: string) =>
    client.post(`/journal/recompute?trade_date=${date}`),
};
