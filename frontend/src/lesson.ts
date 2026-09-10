import { ApiResponseError, cancelOrder, getCommand, getOrder, idempotencyKey, placeOrder } from "./api";
import type { CommandReceipt, OrderBook, OrderReceipt, OrderSide, PracticeOffer, StoredOrder, SymbolCode } from "./types";

export interface LessonSubmission {
  input: { symbol: SymbolCode; side: OrderSide; price: number; quantity: number };
  key: string;
  receipt: OrderReceipt | null;
  ambiguous?: boolean;
  rejected?: boolean;
}

export const newLessonSubmission = (input: LessonSubmission["input"]): LessonSubmission => ({ input, key: idempotencyKey(), receipt: null });
export const submitLessonOrder = async (submission: LessonSubmission): Promise<OrderReceipt> => {
  if (submission.receipt) return submission.receipt;
  try {
    submission.receipt = await placeOrder(submission.input, submission.key);
    submission.rejected = false;
    return submission.receipt;
  } catch (error) {
    const definitelyRejected = error instanceof ApiResponseError && (
      [400, 401, 403, 404, 413, 422, 429].includes(error.status)
      || (error.status === 503 && error.message === "command queue is at the public demo limit")
    );
    if (!definitelyRejected) submission.ambiguous = true;
    submission.rejected = definitelyRejected && !submission.ambiguous;
    throw error;
  }
};
export const pendingReceipt = (): OrderReceipt => ({ orderId: null, commandId: null, commandSequence: null, httpStatus: 0, correlationId: null, location: null, status: null, createdAt: null, completedAt: null, message: "Awaiting the original response" });

export const lowerOfferPrice = (book: OrderBook): number | null => {
  const lowestAsk = book.asks[0]?.price;
  if (lowestAsk === 1) return null;
  return lowestAsk === undefined ? (book.bids[0]?.price ?? 1) : lowestAsk - 1;
};

export const isOrderOpen = (order: StoredOrder): boolean => (
  order.status === "open" || order.status === "partially_filled"
);

export const waitForCommand = async (id: string): Promise<CommandReceipt> => {
  const deadline = Date.now() + 15_000;
  while (true) {
    const command = await getCommand(id);
    if (command.status !== "queued") return command;
    if (Date.now() >= deadline) throw new Error("This order is still being processed. Check its status before sending another.");
    await new Promise((resolve) => setTimeout(resolve, 180));
  }
};

export const readPracticeOffer = async (practice: PracticeOffer): Promise<StoredOrder | null> => {
  if (!practice.receipt.commandId || !practice.receipt.orderId) {
    throw new Error("The API did not return the identifiers needed to check this offer. Check trade history before sending another.");
  }
  const command = await waitForCommand(practice.receipt.commandId);
  if (command.status === "rejected") return null;
  return getOrder(practice.receipt.orderId);
};

// Never replace a possibly open order until its cancellation is confirmed.
// A filled order needs no cancellation, including a fill racing the cancel.
export const clearPracticeOffer = async (practice: PracticeOffer): Promise<StoredOrder | null> => {
  const order = await readPracticeOffer(practice);
  if (!order) return null;
  if (!isOrderOpen(order)) return order;
  practice.cancellation ??= { key: idempotencyKey(), command: null };
  practice.cancellation.command ??= await cancelOrder(order.order_id, order.symbol, practice.cancellation.key);
  const cancellation = practice.cancellation.command;
  if (!cancellation.command_id) throw new Error("Cancellation was not confirmed. Your practice offer may still be waiting.");
  const command = await waitForCommand(cancellation.command_id);
  const current = await getOrder(order.order_id);
  if (isOrderOpen(current)) {
    throw new Error(command.error_message ?? "The practice offer is still open. No replacement buyer was sent.");
  }
  return current;
};

export const endLessonSubmission = async (submission: LessonSubmission, practice: PracticeOffer): Promise<StoredOrder | null> => {
  // A definite first-request rejection created no order. Ending must not retry it.
  // A rejection after an earlier lost response cannot erase that uncertainty.
  if (submission.rejected && !submission.ambiguous) return null;
  practice.receipt = await submitLessonOrder(submission);
  return clearPracticeOffer(practice);
};
