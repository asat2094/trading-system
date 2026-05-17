import { create } from "zustand";

interface Signal {
  event_id: string;
  symbol: string;
  signal_name: string;
  direction: string;
  strength_score: number;
  timestamp: string;
}

interface SignalsStore {
  signals: Signal[];
  lastEventId: string;
  wsStatus: "connecting" | "connected" | "disconnected";
  addSignal: (signal: Signal) => void;
  setLastEventId: (id: string) => void;
  setWsStatus: (status: "connecting" | "connected" | "disconnected") => void;
}

export const useSignalsStore = create<SignalsStore>((set) => ({
  signals: [],
  lastEventId: "0",
  wsStatus: "disconnected",
  addSignal: (signal) =>
    set((s) => ({ signals: [signal, ...s.signals].slice(0, 100) })),
  setLastEventId: (id) => set({ lastEventId: id }),
  setWsStatus: (status) => set({ wsStatus: status }),
}));
