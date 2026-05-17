import { create } from "zustand";

interface Filter {
  field: string;
  operator: string;
  value: string | number;
}

interface FiltersStore {
  source: string;
  filters: Filter[];
  indicators: string[];
  maxSymbols: number;
  setSource: (source: string) => void;
  addFilter: (filter: Filter) => void;
  removeFilter: (index: number) => void;
  setIndicators: (indicators: string[]) => void;
  reset: () => void;
}

export const useFiltersStore = create<FiltersStore>((set) => ({
  source: "nse_universe",
  filters: [],
  indicators: [],
  maxSymbols: 500,
  setSource: (source) => set({ source }),
  addFilter: (filter) => set((s) => ({ filters: [...s.filters, filter] })),
  removeFilter: (index) => set((s) => ({ filters: s.filters.filter((_, i) => i !== index) })),
  setIndicators: (indicators) => set({ indicators }),
  reset: () => set({ source: "nse_universe", filters: [], indicators: [] }),
}));
