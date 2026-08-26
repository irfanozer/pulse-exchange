import type {
  BookLevel,
  OrderBook,
  RecoveredMarketEvent,
  SymbolCode,
  Trade,
  TradeWire,
} from "./types";

const asNumber = (value: unknown): number => {
  const result = typeof value === "number" ? value : Number(value);
  return Number.isFinite(result) ? result : 0;
};

export const normalizeBookLevel = (value: Partial<BookLevel>): BookLevel => ({
  price: asNumber(value.price),
  quantity: asNumber(value.quantity),
  order_count: asNumber(value.order_count),
});

export const normalizeOrderBook = (
  value: Partial<OrderBook> | undefined,
  fallbackSymbol: SymbolCode,
): OrderBook => ({
  symbol: value?.symbol ?? fallbackSymbol,
  sequence: asNumber(value?.sequence),
  event_id: value?.event_id === undefined ? undefined : asNumber(value.event_id),
  bids: (value?.bids ?? []).map(normalizeBookLevel).sort((a, b) => b.price - a.price),
  asks: (value?.asks ?? []).map(normalizeBookLevel).sort((a, b) => a.price - b.price),
});

export const normalizeTrade = (value: TradeWire | Trade): Trade => ({
  id: String(value.id ?? ("trade_id" in value ? value.trade_id : undefined) ?? "unknown-trade"),
  symbol: value.symbol,
  sequence: asNumber(value.sequence ?? ("trade_sequence" in value ? value.trade_sequence : undefined)),
  price: asNumber(value.price),
  quantity: asNumber(value.quantity),
  buy_order_id: value.buy_order_id,
  sell_order_id: value.sell_order_id,
  created_at: value.created_at,
});

export const mergeTrades = (current: Trade[], incoming: Array<TradeWire | Trade>, limit = 30): Trade[] => {
  const byId = new Map<string, Trade>();
  [...incoming, ...current].forEach((trade) => {
    const normalized = normalizeTrade(trade);
    byId.set(normalized.id, normalized);
  });
  return [...byId.values()]
    .sort((a, b) => b.sequence - a.sequence)
    .slice(0, limit);
};

export const marketSpread = (book: OrderBook | null): number | null => {
  if (!book?.bids.length || !book.asks.length) return null;
  return Math.max(0, book.asks[0].price - book.bids[0].price);
};

export const maxVisibleQuantity = (book: OrderBook | null): number => {
  if (!book) return 1;
  return Math.max(1, ...book.bids.map((level) => level.quantity), ...book.asks.map((level) => level.quantity));
};

export const shouldApplyMarketUpdate = (incoming: number, lastApplied: number): boolean =>
  Number.isFinite(incoming) && incoming > lastApplied;

export const shouldApplyBookSnapshot = (
  incoming: number,
  lastApplied: number,
  lastBook: number,
): boolean =>
  Number.isFinite(incoming) && incoming >= lastApplied && incoming > lastBook;

export const unseenRecoveredEvents = (
  events: RecoveredMarketEvent[],
  lastReceivedEventId: number,
): RecoveredMarketEvent[] =>
  events
    .filter((event) => Number.isFinite(event.event_id) && event.event_id > lastReceivedEventId)
    .sort((left, right) => left.event_id - right.event_id);
