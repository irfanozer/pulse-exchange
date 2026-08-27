import type {
  CommandReceipt,
  DiagnosticsSummary,
  OrderBook,
  OrderReceipt,
  OrderSide,
  SymbolCode,
  Trade,
  TradeWire,
} from "./types";
import { normalizeOrderBook, normalizeTrade } from "./market";

const API_ROOT = "/api/v1";

const idempotencyKey = (): string =>
  globalThis.crypto?.randomUUID?.() ?? `px-${Date.now()}-${Math.random().toString(16).slice(2)}`;

const readError = async (response: Response): Promise<string> => {
  try {
    const body = (await response.json()) as { detail?: string; message?: string };
    return body.detail ?? body.message ?? `Request failed with HTTP ${response.status}`;
  } catch {
    return `Request failed with HTTP ${response.status}`;
  }
};

const requestJson = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(`${API_ROOT}${path}`, init);
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
};

export const getBook = async (symbol: SymbolCode): Promise<OrderBook> => {
  const book = await requestJson<OrderBook>(`/markets/${symbol}/book`);
  return normalizeOrderBook(book, symbol);
};

export const getTrades = async (symbol: SymbolCode): Promise<Trade[]> => {
  const response = await requestJson<TradeWire[] | { items?: TradeWire[]; trades?: TradeWire[] }>(
    `/markets/${symbol}/trades?limit=30`,
  );
  const trades = Array.isArray(response) ? response : (response.items ?? response.trades ?? []);
  return trades.map(normalizeTrade);
};

export const getDiagnosticsSummary = async (): Promise<DiagnosticsSummary> =>
  requestJson<DiagnosticsSummary>("/diagnostics/summary");

export const getCommand = async (commandId: string): Promise<CommandReceipt> =>
  requestJson<CommandReceipt>(`/commands/${encodeURIComponent(commandId)}`);

export const placeOrder = async (input: {
  symbol: SymbolCode;
  side: OrderSide;
  price: number;
  quantity: number;
}): Promise<OrderReceipt> => {
  const response = await requestJson<Record<string, unknown>>("/orders", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify(input),
  });
  const nested = typeof response.order === "object" && response.order !== null
    ? (response.order as Record<string, unknown>)
    : response;
  const orderId = String(nested.id ?? nested.order_id ?? response.order_id ?? "") || null;
  const commandId = String(response.command_id ?? "") || null;
  const commandSequence = Number(response.sequence);
  return {
    orderId,
    commandId,
    commandSequence: Number.isSafeInteger(commandSequence) ? commandSequence : null,
    message: orderId ? `Order command ${orderId.slice(0, 8)} queued` : "Order command queued",
  };
};

export const cancelOrder = async (orderId: string, symbol: SymbolCode): Promise<void> => {
  const response = await fetch(
    `${API_ROOT}/orders/${encodeURIComponent(orderId)}?symbol=${symbol}`,
    {
    method: "DELETE",
    headers: { "Idempotency-Key": idempotencyKey() },
    },
  );
  if (!response.ok) throw new Error(await readError(response));
};

export const marketStreamPath = (symbol: SymbolCode, afterEventId?: number): string => {
  const cursor = afterEventId !== undefined && Number.isSafeInteger(afterEventId) && afterEventId >= 0
    ? `?after_event_id=${afterEventId}`
    : "";
  return `${API_ROOT}/markets/${symbol}/stream${cursor}`;
};

export const marketSocketUrl = (symbol: SymbolCode, afterEventId?: number): string => {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${marketStreamPath(symbol, afterEventId)}`;
};
