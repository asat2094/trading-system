import ChartPane from "./ChartPane";
import { useDashboardStore } from "../../store/dashboard";

const GRID_STYLES: Record<number, React.CSSProperties> = {
  1: { gridTemplateColumns: "1fr" },
  2: { gridTemplateColumns: "1fr 1fr" },
  4: { gridTemplateColumns: "1fr 1fr", gridTemplateRows: "1fr 1fr" },
  6: { gridTemplateColumns: "1fr 1fr 1fr", gridTemplateRows: "1fr 1fr" },
  8: { gridTemplateColumns: "1fr 1fr 1fr 1fr", gridTemplateRows: "1fr 1fr" },
};

export default function PaneGrid() {
  const { paneCount, panes, focusedPaneId, setFocusedPane } = useDashboardStore();
  const gridStyle = GRID_STYLES[paneCount] ?? GRID_STYLES[4];
  const visiblePanes = panes.slice(0, paneCount);

  return (
    <div style={{ flex: 1, display: "grid", ...gridStyle, gap: 2, overflow: "hidden" }}>
      {visiblePanes.map((pane) => (
        <ChartPane
          key={pane.id}
          paneId={pane.id}
          focused={focusedPaneId === pane.id}
          onFocus={() => setFocusedPane(pane.id)}
        />
      ))}
    </div>
  );
}
