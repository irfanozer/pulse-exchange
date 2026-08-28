import type { DemoStepStatus, GuidedDemoStep, Trade } from "./types";

export const createGuidedDemoSteps = (): GuidedDemoStep[] => [
  {
    id: "observe",
    title: "Read a waiting seller",
    detail: "GET /book finds the lowest-priced seller before anything is sent.",
    status: "waiting",
  },
  {
    id: "accept",
    title: "Send one buyer",
    detail: "POST /orders returns HTTP 202, a correlation ID, and a durable command ID.",
    status: "waiting",
  },
  {
    id: "process",
    title: "Store and match",
    detail: "PostgreSQL sequences the command; the matching service pairs it with the waiting seller.",
    status: "waiting",
  },
  {
    id: "verify",
    title: "Prove the same trade",
    detail: "REST and WebSocket must report the same persisted trade ID.",
    status: "waiting",
  },
];

export const updateDemoStep = (
  steps: GuidedDemoStep[],
  id: GuidedDemoStep["id"],
  status: DemoStepStatus,
  detail?: string,
): GuidedDemoStep[] => steps.map((step) => (
  step.id === id ? { ...step, status, detail: detail ?? step.detail } : step
));

export const findNewTrade = (
  trades: Trade[],
  previousIds: Set<string>,
  expectedOrderId?: string | null,
): Trade | null => {
  const unseen = trades.filter((trade) => !previousIds.has(trade.id));
  if (!expectedOrderId) return unseen[0] ?? null;
  return unseen.find((trade) => (
    trade.taker_order_id === expectedOrderId
    || trade.maker_order_id === expectedOrderId
    || trade.buy_order_id === expectedOrderId
    || trade.sell_order_id === expectedOrderId
  )) ?? null;
};

export const tradeIncludesOrder = (trade: Trade, orderId: string): boolean => (
  trade.taker_order_id === orderId
  || trade.maker_order_id === orderId
  || trade.buy_order_id === orderId
  || trade.sell_order_id === orderId
);

export const isSamePersistedTrade = (
  restTrade: Trade,
  websocketTradeId: string | null | undefined,
): boolean => websocketTradeId === restTrade.id;
