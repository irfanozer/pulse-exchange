export type SymbolCode = "NOVA" | "ORBIT";
export type OrderSide = "buy" | "sell";
export type ConnectionState = "connecting" | "live" | "reconnecting" | "offline";

export interface BookLevel {
  price: number;
  quantity: number;
  order_count: number;
}

export interface OrderBook {
  symbol: SymbolCode;
  sequence: number;
  event_id?: number;
  bids: BookLevel[];
  asks: BookLevel[];
}

export interface Trade {
  id: string;
  symbol: SymbolCode;
  sequence: number;
  price: number;
  quantity: number;
  buy_order_id?: string;
  sell_order_id?: string;
  created_at: string;
}

export interface TradeWire {
  id?: string | number;
  trade_id?: string | number;
  symbol: SymbolCode;
  sequence?: number;
  trade_sequence?: number;
  command_sequence?: number;
  price: number | string;
  quantity: number | string;
  buy_order_id?: string;
  sell_order_id?: string;
  maker_order_id?: string;
  taker_order_id?: string;
  created_at: string;
}

export interface RecoveredMarketEvent {
  event_id: number;
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface MarketStreamMessage {
  type: "snapshot" | "market_update" | "heartbeat";
  symbol?: SymbolCode;
  sequence: number;
  event_id: number;
  event_type?: string;
  payload?: Record<string, unknown>;
  book?: OrderBook;
  trades?: TradeWire[];
  recovered_events?: RecoveredMarketEvent[];
  replay_truncated?: boolean;
  events?: unknown[];
}

export interface OrderReceipt {
  orderId: string | null;
  message: string;
}
