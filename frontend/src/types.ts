export type SymbolCode = "NOVA" | "ORBIT";
export type OrderSide = "buy" | "sell";
export type ConnectionState = "connecting" | "live" | "reconnecting" | "offline";
export type CommandType = "submit_order" | "cancel_order";
export type CommandStatus = "queued" | "completed" | "rejected";

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

export interface MarketProfile {
  symbol: SymbolCode;
  display_name: string;
  description: string;
  activity_profile: string;
  reference_tick: number;
}

export interface MarketsResponse {
  items: MarketProfile[];
}

export interface Trade {
  id: string;
  symbol: SymbolCode;
  sequence: number;
  price: number;
  quantity: number;
  buy_order_id?: string;
  sell_order_id?: string;
  maker_order_id?: string;
  taker_order_id?: string;
  maker_side?: OrderSide;
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
  maker_side?: OrderSide;
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
  delivery_reason?: "initial" | "live_refresh" | "reconnect" | "recovery";
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
  commandId: string | null;
  commandSequence: number | null;
  httpStatus: number;
  correlationId: string | null;
  location: string | null;
  status: CommandStatus | null;
  createdAt: string | null;
  completedAt: string | null;
  message: string;
}

export interface CommandResult {
  event_id?: number;
  order_ids?: string[];
  trade_sequences?: number[];
  [key: string]: unknown;
}

export interface CommandReceipt {
  command_id: string;
  correlation_id: string;
  sequence: number;
  command_type: CommandType;
  status: CommandStatus;
  symbol: SymbolCode;
  payload: Record<string, unknown>;
  result: CommandResult | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export type ServiceStatus = "online" | "stale" | "offline";

export interface DiagnosticsSummary {
  generated_at: string;
  services: {
    api: { status: ServiceStatus };
    processor: {
      status: ServiceStatus;
      last_heartbeat_at: string | null;
      age_ms?: number | null;
    };
  };
  queue: {
    depth: number;
    oldest_age_ms: number | null;
  };
  commands: {
    accepted: number;
    completed: number;
    rejected: number;
    latency_ms: {
      p50: number | null;
      p95: number | null;
      p99: number | null;
    };
  };
  market: {
    orders: number;
    trades: number;
    events: number;
    latest_sequence: number;
    sequence_integrity: boolean;
  };
  streams: {
    connected: number;
    recovered_events: number;
    resyncs: number;
  };
}

export interface ClientEvidence {
  messages: number;
  reconnects: number;
  recoveredEvents: number;
  resyncs: number;
  duplicatesIgnored: number;
  lastEventId: number;
}

export type DemoStepStatus = "waiting" | "running" | "complete" | "failed";

export interface GuidedDemoStep {
  id: "observe" | "accept" | "process" | "verify";
  title: string;
  detail: string;
  status: DemoStepStatus;
}

export interface GuidedDemoResult {
  durationMs: number;
  requestsAccepted: number;
  symbol: SymbolCode;
  startingSequence: number;
  endingSequence: number;
  httpStatus: number;
  correlationId: string;
  commandId: string;
  commandSequence: number;
  commandStatus: CommandStatus;
  commandCreatedAt: string;
  commandCompletedAt: string;
  commandEventId: number;
  orderId: string;
  tradeId: string;
  tradeSequence: number;
  makerOrderId: string;
  takerOrderId: string;
  restObservedAt: string;
  websocketTradeId: string;
  websocketEventId: number;
  websocketObservedAt: string;
  price: number;
  quantity: number;
}
