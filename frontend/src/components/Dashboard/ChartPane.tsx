import { useDashboardStore } from "../../store/dashboard";
import ChartUnit from "../Chart/ChartUnit";
import PaneControls from "./PaneControls";
import PaneClock from "./PaneClock";

const TV = { bg: "#131722", border: "#2a2e39", accent: "#2962ff" } as const;

interface Props {
  paneId:  string;
  focused: boolean;
  onFocus: () => void;
}

export default function ChartPane({ paneId, focused, onFocus }: Props) {
  const pane = useDashboardStore((s) => s.panes.find((p) => p.id === paneId));
  const symbol    = pane?.symbol    ?? "NSE:RELIANCE";
  const timeframe = pane?.timeframe ?? "15min";

  return (
    <div
      style={{
        position: "relative", display: "flex", flexDirection: "column",
        height: "100%",
        border: focused ? `2px solid ${TV.accent}` : `1px solid ${TV.border}`,
        boxSizing: "border-box", background: TV.bg, overflow: "hidden",
      }}
      onClick={onFocus}
    >
      {/* Header: symbol search + timeframe */}
      <div style={{
        padding: "3px 8px", background: "#1a1e2e", flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6,
      }}>
        <PaneControls paneId={paneId} symbol={symbol} timeframe={timeframe} />
        <PaneClock timeframe={timeframe} />
      </div>

      {/* Unified chart unit */}
      <ChartUnit
        symbol={symbol}
        timeframe={timeframe}
        paneId={paneId}
        onFocus={onFocus}
      />
    </div>
  );
}
