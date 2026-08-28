import type {
  CommandReceipt,
  DiagnosticsSummary,
  MarketProfile,
  MarketsResponse,
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

const stringOrNull = (value: unknown): string | null => (
  typeof value === "string" && value.length > 0 ? value : null
);

const safeIntegerOrNull = (value: unknown): number | null => {
  const candidate = Number(value);
  return Number.isSafeInteger(candidate) ? candidate : null;
};

export const getBook = async (symbol: SymbolCode): Promise<OrderBook> => {
  const book = await requestJson<OrderBook>(`/markets/${symbol}/book`);
  return normalizeOrderBook(book, symbol);
};

export const getMarkets = async (): Promise<MarketProfile[]> => {
  const response = await requestJson<MarketsResponse>("/markets");
  return response.items;
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
  const httpResponse = await fetch(`${API_ROOT}/orders`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify(input),
  });
  if (!httpResponse.ok) throw new Error(await readError(httpResponse));

  const response = (await httpResponse.json()) as Record<string, unknown>;
  const nested = typeof response.order === "object" && response.order !== null
    ? (response.order as Record<string, unknown>)
    : response;
  const orderId = stringOrNull(nested.id ?? nested.order_id ?? response.order_id);
  const commandId = stringOrNull(response.command_id);
  const commandSequence = safeIntegerOrNull(response.sequence);
  const correlationId = httpResponse.headers.get("X-Correlation-ID")
    ?? stringOrNull(response.correlation_id);
  const status = response.status === "queued"
    || response.status === "completed"
    || response.status === "rejected"
    ? response.status
    : null;
  return {
    orderId,
    commandId,
    commandSequence,
    httpStatus: httpResponse.status,
    correlationId,
    location: httpResponse.headers.get("Location"),
    status,
    createdAt: stringOrNull(response.created_at),
    completedAt: stringOrNull(response.completed_at),
    message: orderId
      ? `HTTP ${httpResponse.status} accepted order ${orderId.slice(0, 8)}`
      : `HTTP ${httpResponse.status} accepted the order command`,
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
