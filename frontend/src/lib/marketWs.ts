/**
 * Singleton WebSocket client for /ws/market.
 * One connection shared across all panes.
 * Ref-counts subscriptions: unsubscribes only when last pane drops a symbol.
 */
import { useLiveQuotesStore } from "../store/liveQuotes";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000")
  .replace(/^http/, "ws");

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _token = "";

const refCounts: Map<string, number> = new Map();

function send(msg: object) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

function handleMessage(evt: MessageEvent) {
  try {
    const msg = JSON.parse(evt.data as string) as Record<string, unknown>;
    const store = useLiveQuotesStore.getState();
    if (msg.type === "quote") {
      store.setQuote({
        symbol:  msg.symbol  as string,
        ltp:     msg.ltp     as number,
        open:    msg.open    as number,
        high:    msg.high    as number,
        low:     msg.low     as number,
        close:   msg.close   as number,
        volume:  msg.volume  as number,
        ts:      msg.ts      as string,
      });
    } else if (msg.type === "broker_status") {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { type: _t, ...status } = msg;
      store.setBrokerStatus(status as Record<string, string>);
    }
  } catch {
    // malformed — ignore
  }
}

export function connect(token: string) {
  _token = token;
  if (ws && ws.readyState !== WebSocket.CLOSED) {
    console.log("[marketWs] connect: already open/connecting, state=", ws.readyState);
    return;
  }

  const url = `${API_BASE}/ws/market?token=${encodeURIComponent(token)}`;
  console.log("[marketWs] connecting to", url.slice(0, 60));
  ws = new WebSocket(url);
  ws.onmessage = handleMessage;

  ws.onopen = () => {
    console.log("[marketWs] connected");
    const symbols = Array.from(refCounts.keys()).filter((s) => (refCounts.get(s) ?? 0) > 0);
    console.log("[marketWs] subscribing on open:", symbols);
    if (symbols.length) send({ action: "subscribe", symbols });
  };

  ws.onclose = (evt) => {
    console.log("[marketWs] closed code=", evt.code);
    ws = null;
    reconnectTimer = setTimeout(() => connect(_token), 3000);
  };

  ws.onerror = (err) => {
    console.error("[marketWs] error", err);
    ws?.close();
  };
}

export function disconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  ws?.close();
  ws = null;
  refCounts.clear();
}

export function subscribe(symbols: string[]) {
  const newSymbols: string[] = [];
  for (const sym of symbols) {
    const count = refCounts.get(sym) ?? 0;
    refCounts.set(sym, count + 1);
    if (count === 0) newSymbols.push(sym);
  }
  if (newSymbols.length) send({ action: "subscribe", symbols: newSymbols });
}

export function unsubscribe(symbols: string[]) {
  const dropSymbols: string[] = [];
  for (const sym of symbols) {
    const count = refCounts.get(sym) ?? 0;
    const next = Math.max(0, count - 1);
    refCounts.set(sym, next);
    if (next === 0) dropSymbols.push(sym);
  }
  if (dropSymbols.length) send({ action: "unsubscribe", symbols: dropSymbols });
}
