/** Shared TypeScript interfaces for FnO live analysis. */

export interface OptionSide {
  ltp: number;
  oi: number;
  delta_oi: number;
  open: number;
  high: number;
  is_oh: boolean;      // open == high (bearish OH candle)
  is_oh_hit: boolean;  // price has returned to the open/high level
}

export interface StrikeRow {
  strike: number;
  ce: OptionSide | null;
  pe: OptionSide | null;
  ce_symbol: string;   // e.g. "NFO:NIFTY26JUN24500CE"
  pe_symbol: string;   // e.g. "NFO:NIFTY26JUN24500PE"
}

export interface FnoSnapshot {
  symbol: string;
  spot: number;
  expiry: string;       // "YYYY-MM-DD"
  atm_strike: number;
  pcr: number;
  pcdr: number;
  pcd: number;
  total_ce_oi: number;
  total_pe_oi: number;
  strikes: StrikeRow[];
  fetched_at: string;   // ISO timestamp
  stale?: boolean;      // true when served from cache (Kite MCP unavailable)
}
