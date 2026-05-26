// frontend/src/api/scanner.ts
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiClient } from "./client";

// ── condition tree types (mirror backend ConditionNode) ───────────────────────

export interface ConditionLeaf {
  id: string;           // uuid for React key only — stripped before sending to API
  type: "indicator" | "crossover" | "candlestick" | "chart_pattern" | "volume" | "trend";
  // indicator
  indicator?: string;
  operator?: string;
  value?: number | string;
  params?: Record<string, number | string>;
  // crossover
  indicator_a?: string;
  indicator_b?: string;
  params_a?: Record<string, number | string>;
  params_b?: Record<string, number | string>;
  crossover?: "above" | "below";
  // candlestick / chart_pattern
  pattern?: string;
  min_confidence?: number;
  // volume
  volume_ratio?: number;
  volume_period?: number;
  // trend
  trend?: string;
  trend_window?: number;
  // shared
  timeframe?: string;    // undefined = use scan default
}

export interface ConditionGroup {
  id: string;
  logic: "AND" | "OR";
  children: (ConditionLeaf | ConditionGroup)[];
}

// ── API wire types (no id fields) ─────────────────────────────────────────────

type WireLeaf = Omit<ConditionLeaf, "id">;
interface WireGroup {
  logic: "AND" | "OR";
  conditions: (WireLeaf | WireGroup)[];
}

function toWireNode(node: ConditionLeaf | ConditionGroup): WireLeaf | WireGroup {
  if ("logic" in node) {
    return {
      logic: node.logic,
      conditions: node.children.map(toWireNode),
    };
  }
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { id, ...rest } = node;
  return rest as WireLeaf;
}

// ── signal types ──────────────────────────────────────────────────────────────

export interface SignalConfig {
  name: string;
  category: string;
  direction: string;
  timeframes: string[];
  display: { color: string; icon: string; strength_score: number };
  severity: string;
}

// ── scan request/response ─────────────────────────────────────────────────────

interface ScanRequest {
  universe: string[] | string;
  max_symbols: number;
  default_timeframe: string;
  signals: string[];
  custom_conditions: WireGroup | null;
  match_mode: string;
}

export interface SignalDetail {
  passed: boolean;
  score: number;
  conditions_passed: number;
  conditions_total: number;
  details: {
    children?: Array<{
      passed: boolean;
      score: number;
      node_type: string;
      [key: string]: unknown;
    }>;
    [key: string]: unknown;
  };
  display: { color: string; icon: string; strength_score: number };
}

export interface ScanResultItem {
  symbol: string;
  overall_score: number;
  matched_signals: string[];
  signal_details: Record<string, SignalDetail>;
  custom_passed: boolean;
}

export interface ScanResponse {
  symbols: string[];
  results: ScanResultItem[];
  total_scanned: number;
  matched: number;
  duration_ms: number;
}

// ── evaluate request/response ─────────────────────────────────────────────────

interface EvaluateRequest {
  symbol: string;
  default_timeframe: string;
  conditions: WireGroup;
}

export interface EvaluateResponse {
  symbol: string;
  passed: boolean;
  score: number;
  details: {
    children?: Array<{
      passed: boolean;
      score: number;
      node_type: string;
      [key: string]: unknown;
    }>;
  };
}

// ── hooks ─────────────────────────────────────────────────────────────────────

export function useRunScan() {
  return useMutation({
    mutationFn: async (req: {
      universe: string[] | string;
      maxSymbols: number;
      defaultTimeframe: string;
      signals: string[];
      customConditions: ConditionGroup | null;
      matchMode: string;
    }): Promise<ScanResponse> => {
      const body: ScanRequest = {
        universe: req.universe,
        max_symbols: req.maxSymbols,
        default_timeframe: req.defaultTimeframe,
        signals: req.signals,
        custom_conditions: req.customConditions ? toWireNode(req.customConditions) as WireGroup : null,
        match_mode: req.matchMode,
      };
      const { data } = await apiClient.post<ScanResponse>("/scanner/run", body);
      return data;
    },
  });
}

export function useEvaluateSymbol() {
  return useMutation({
    mutationFn: async (req: {
      symbol: string;
      defaultTimeframe: string;
      conditions: ConditionGroup;
    }): Promise<EvaluateResponse> => {
      const body: EvaluateRequest = {
        symbol: req.symbol,
        default_timeframe: req.defaultTimeframe,
        conditions: toWireNode(req.conditions) as WireGroup,
      };
      const { data } = await apiClient.post<EvaluateResponse>("/scanner/evaluate", body);
      return data;
    },
  });
}

export function useListSignals() {
  return useQuery({
    queryKey: ["signals"],
    queryFn: async (): Promise<SignalConfig[]> => {
      const { data } = await apiClient.get<SignalConfig[]>("/scanner/signals");
      return data;
    },
  });
}
