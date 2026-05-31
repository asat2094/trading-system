/**
 * In-memory live quotes store — NOT persisted.
 * Populated by marketWs.ts on each incoming quote message.
 */
import { create } from "zustand";

export interface LiveQuote {
  symbol: string;
  ltp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ts: string;
  prevLtp: number;
}

interface LiveQuotesStore {
  quotes: Record<string, LiveQuote>;
  setQuote: (q: Omit<LiveQuote, "prevLtp">) => void;
  brokerStatus: Record<string, string>;
  setBrokerStatus: (status: Record<string, string>) => void;
  upstoxHasToken: boolean;
  setUpstoxHasToken: (v: boolean) => void;
}

export const useLiveQuotesStore = create<LiveQuotesStore>()((set) => ({
  quotes: {},
  brokerStatus: {},
  upstoxHasToken: false,

  setQuote: (q) => set((s) => {
    const prev = s.quotes[q.symbol];
    return {
      quotes: {
        ...s.quotes,
        [q.symbol]: { ...q, prevLtp: prev?.ltp ?? q.ltp },
      },
    };
  }),

  setBrokerStatus: (status) => set({ brokerStatus: status }),
  setUpstoxHasToken: (v) => set({ upstoxHasToken: v }),
}));
