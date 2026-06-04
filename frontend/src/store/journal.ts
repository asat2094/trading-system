import { create } from "zustand";
import { journalApi, JrnTrade, JrnPair, JrnSummary } from "../api/journal";

interface JournalState {
  trades: JrnTrade[];
  pairs: JrnPair[];
  summaries: JrnSummary[];
  loading: boolean;
  error: string | null;
  reset: () => void;
  fetchTrades: (params?: Record<string, string>) => Promise<void>;
  fetchPairs: (params?: Record<string, string>) => Promise<void>;
  fetchSummaries: (params?: Record<string, string>) => Promise<void>;
  importPdf: (file: File, broker?: string, password?: string) => Promise<{ imported: number; inserted: number }>;
}

export const useJournalStore = create<JournalState>((set) => ({
  trades: [],
  pairs: [],
  summaries: [],
  loading: false,
  error: null,

  reset: () => set({ trades: [], pairs: [], error: null }),

  fetchTrades: async (params) => {
    set({ loading: true, error: null });
    try {
      const { data } = await journalApi.getTrades(params);
      set({ trades: data });
    } catch (e: any) {
      set({ error: e.message });
    } finally {
      set({ loading: false });
    }
  },

  fetchPairs: async (params) => {
    set({ loading: true, error: null });
    try {
      const { data } = await journalApi.getPairs(params);
      set({ pairs: data });
    } catch (e: any) {
      set({ error: e.message });
    } finally {
      set({ loading: false });
    }
  },

  fetchSummaries: async (params) => {
    set({ loading: true, error: null });
    try {
      const { data } = await journalApi.getSummaries(params);
      set({ summaries: data });
    } catch (e: any) {
      set({ error: e.message });
    } finally {
      set({ loading: false });
    }
  },

  importPdf: async (file, broker = "auto", password) => {
    set({ loading: true, error: null });
    try {
      const { data } = await journalApi.importPdf(file, broker, password);
      return data;
    } catch (e: any) {
      set({ error: e.message });
      throw e;
    } finally {
      set({ loading: false });
    }
  },
}));
