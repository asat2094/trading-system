import { useParams } from "react-router-dom";
import CandlestickChart from "../components/Chart/CandlestickChart";
import { useOHLCV } from "../api/technical";

export default function Chart() {
  const { symbol } = useParams<{ symbol: string }>();
  const today = new Date().toISOString().split("T")[0];
  const yearAgo = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split("T")[0];

  const { data: rows, isLoading } = useOHLCV(symbol!, "1d", yearAgo, today);

  return (
    <div style={{ padding: 16 }}>
      <h2>{symbol}</h2>
      {isLoading ? (
        <div>Loading chart...</div>
      ) : (
        <CandlestickChart bars={rows ?? []} />
      )}
    </div>
  );
}
