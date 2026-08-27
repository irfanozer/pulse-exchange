import type { DemoStepStatus, GuidedDemoStep, Trade } from "./types";

export const createGuidedDemoSteps = (): GuidedDemoStep[] => [
  {
    id: "accept",
    title: "Accept liquidity",
    detail: "Four POST requests enter the durable command journal.",
    status: "waiting",
  },
  {
    id: "process",
    title: "Build the book",
    detail: "The processor applies commands in one global sequence.",
    status: "waiting",
  },
  {
    id: "match",
    title: "Cross the spread",
    detail: "A fifth order meets the best resting sell by price-time priority.",
    status: "waiting",
  },
  {
    id: "verify",
    title: "Verify the trade",
    detail: "REST and WebSocket state expose the same persisted outcome.",
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
