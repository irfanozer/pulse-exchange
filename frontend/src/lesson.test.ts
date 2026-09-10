import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiResponseError, cancelOrder, getCommand, getOrder, idempotencyKey, placeOrder } from "./api";
import { clearPracticeOffer, endLessonSubmission, isOrderOpen, lowerOfferPrice, newLessonSubmission, readPracticeOffer, submitLessonOrder } from "./lesson";
import type { CommandReceipt, OrderBook, PracticeOffer, StoredOrder } from "./types";

vi.mock("./api", async (importOriginal) => ({ ...await importOriginal<typeof import("./api")>(), cancelOrder: vi.fn(), getCommand: vi.fn(), getOrder: vi.fn(), placeOrder: vi.fn(), idempotencyKey: vi.fn() }));
const command = (status: CommandReceipt["status"] = "completed"): CommandReceipt => ({ command_id: "command", correlation_id: "correlation", sequence: 1, command_type: "submit_order", status, symbol: "NOVA", payload: {}, result: {}, error_code: null, error_message: null, created_at: "2026-09-09T00:00:00Z", completed_at: null });
const order = (status: StoredOrder["status"] = "open"): StoredOrder => ({ order_id: "practice", symbol: "NOVA", side: "buy", price: 101, quantity: 1, remaining_quantity: status === "filled" ? 0 : 1, status, updated_at: "2026-09-09T00:00:01Z" });
const practice: PracticeOffer = { price: 101, sellerPrice: 102, order: null, receipt: { orderId: "practice", commandId: "original", commandSequence: 1, httpStatus: 202, correlationId: "correlation", location: null, status: "queued", createdAt: "2026-09-09T00:00:00Z", completedAt: null, message: "Accepted" } };
const book: OrderBook = { symbol: "NOVA", sequence: 0, bids: [{ price: 100, quantity: 3, order_count: 1 }], asks: [{ price: 102, quantity: 3, order_count: 1 }] };

beforeEach(() => { vi.resetAllMocks(); delete practice.cancellation; vi.mocked(idempotencyKey).mockReturnValue("stable-lesson-key"); });
describe("user-paced trading lesson safety", () => {
  it("offers one tick below a seller without creating an illegal zero-price buy", () => {
    expect(lowerOfferPrice(book)).toBe(101);
    expect(lowerOfferPrice({ ...book, asks: [{ price: 1, quantity: 1, order_count: 1 }] })).toBeNull();
    expect(lowerOfferPrice({ ...book, asks: [] })).toBe(100);
    expect(lowerOfferPrice({ ...book, asks: [], bids: [] })).toBe(1);
  });

  it("reads a previously accepted practice offer without making any new write", async () => {
    vi.mocked(getCommand).mockResolvedValue(command());
    vi.mocked(getOrder).mockResolvedValue(order());
    expect((await readPracticeOffer(practice))?.status).toBe("open");
    expect(getCommand).toHaveBeenCalledWith("original");
    expect(getOrder).toHaveBeenCalledWith("practice");
    expect(placeOrder).not.toHaveBeenCalled();
    expect(cancelOrder).not.toHaveBeenCalled();
  });

  it("waits for processing before reading an order that might not exist yet", async () => {
    vi.mocked(getCommand).mockResolvedValue(command("rejected"));
    expect(await readPracticeOffer(practice)).toBeNull();
    expect(getOrder).not.toHaveBeenCalled();
  });

  it("does not retry a submission after an uncertain response", async () => {
    vi.mocked(getCommand).mockRejectedValue(new Error("Network unavailable"));
    await expect(readPracticeOffer(practice)).rejects.toThrow("Network unavailable");
    expect(practice.receipt.orderId).toBe("practice");
    expect(placeOrder).not.toHaveBeenCalled();
  });

  it("checks the cancellation command and persisted cancelled status", async () => {
    vi.mocked(getCommand).mockResolvedValue(command());
    vi.mocked(getOrder).mockResolvedValueOnce(order()).mockResolvedValueOnce(order("cancelled"));
    vi.mocked(cancelOrder).mockResolvedValue({ ...command("queued"), command_id: "cancel-command" });
    const cancelled = await clearPracticeOffer(practice);
    expect(cancelOrder).toHaveBeenCalledWith("practice", "NOVA", "stable-lesson-key");
    expect(getCommand).toHaveBeenLastCalledWith("cancel-command");
    expect(cancelled?.remaining_quantity).toBe(1);
    expect(isOrderOpen(cancelled!)).toBe(false);
    expect(placeOrder).not.toHaveBeenCalled();
  });

  it("does not cancel an order that already filled while the visitor was reading", async () => {
    vi.mocked(getCommand).mockResolvedValue(command());
    vi.mocked(getOrder).mockResolvedValue(order("filled"));
    expect((await clearPracticeOffer(practice))?.status).toBe("filled");
    expect(cancelOrder).not.toHaveBeenCalled();
  });

  it("resolves a rejected cancellation by checking whether a fill won the race", async () => {
    vi.mocked(getCommand).mockResolvedValueOnce(command()).mockResolvedValueOnce({ ...command("rejected"), error_code: "UnknownOrderError" });
    vi.mocked(getOrder).mockResolvedValueOnce(order()).mockResolvedValueOnce(order("filled"));
    vi.mocked(cancelOrder).mockResolvedValue({ ...command("queued"), command_id: "cancel-command" });
    expect((await clearPracticeOffer(practice))?.status).toBe("filled");
  });

  it("fails safely while the original offer remains open", async () => {
    vi.mocked(getCommand).mockResolvedValue(command());
    vi.mocked(getOrder).mockResolvedValue(order());
    vi.mocked(cancelOrder).mockResolvedValue({ ...command("queued"), command_id: "cancel-command" });
    await expect(clearPracticeOffer(practice)).rejects.toThrow("No replacement buyer was sent");
    expect(placeOrder).not.toHaveBeenCalled();
  });

  it("recovers a lost submission response using the exact payload and key", async () => {
    const input = { symbol: "NOVA" as const, side: "buy" as const, price: 101, quantity: 1 };
    const submission = newLessonSubmission(input);
    vi.mocked(placeOrder).mockRejectedValueOnce(new Error("Lost response")).mockResolvedValue(practice.receipt);
    await expect(submitLessonOrder(submission)).rejects.toThrow("Lost response");
    expect(await submitLessonOrder(submission)).toEqual(practice.receipt);
    expect(placeOrder).toHaveBeenNthCalledWith(1, input, "stable-lesson-key");
    expect(placeOrder).toHaveBeenNthCalledWith(2, input, "stable-lesson-key");
    await submitLessonOrder(submission);
    expect(placeOrder).toHaveBeenCalledTimes(2);
  });

  it("rechecks a pending cancellation instead of issuing a second one", async () => {
    vi.mocked(getCommand).mockResolvedValueOnce(command()).mockRejectedValueOnce(new Error("Lost connection"));
    vi.mocked(getOrder).mockResolvedValueOnce(order());
    vi.mocked(cancelOrder).mockResolvedValue({ ...command("queued"), command_id: "cancel-command" });
    await expect(clearPracticeOffer(practice)).rejects.toThrow("Lost connection");
    vi.mocked(getCommand).mockResolvedValue(command());
    vi.mocked(getOrder).mockResolvedValueOnce(order()).mockResolvedValueOnce(order("cancelled"));
    expect((await clearPracticeOffer(practice))?.status).toBe("cancelled");
    expect(cancelOrder).toHaveBeenCalledTimes(1);
    expect(getCommand).toHaveBeenLastCalledWith("cancel-command");
  });

  it("reuses the cancellation key when its HTTP response was lost", async () => {
    vi.mocked(getCommand).mockResolvedValue(command());
    vi.mocked(getOrder).mockResolvedValue(order());
    vi.mocked(cancelOrder).mockRejectedValueOnce(new Error("Lost response")).mockResolvedValue({ ...command("queued"), command_id: "cancel-command" });
    await expect(clearPracticeOffer(practice)).rejects.toThrow("Lost response");
    vi.mocked(getOrder).mockResolvedValueOnce(order()).mockResolvedValueOnce(order("cancelled"));
    await clearPracticeOffer(practice);
    expect(cancelOrder).toHaveBeenNthCalledWith(1, "practice", "NOVA", "stable-lesson-key");
    expect(cancelOrder).toHaveBeenNthCalledWith(2, "practice", "NOVA", "stable-lesson-key");
  });

  it.each([429, 422, 503])("does not create an offer when ending after a definite HTTP %s rejection", async (status) => {
    const submission = newLessonSubmission({ symbol: "NOVA", side: "buy", price: 101, quantity: 1 });
    vi.mocked(placeOrder).mockRejectedValue(new ApiResponseError(status, status === 503 ? "command queue is at the public demo limit" : "Rejected"));
    await expect(submitLessonOrder(submission)).rejects.toThrow();
    expect(await endLessonSubmission(submission, practice)).toBeNull();
    expect(placeOrder).toHaveBeenCalledTimes(1);
    expect(cancelOrder).not.toHaveBeenCalled();
  });

  it("preserves uncertainty if a rejected retry follows a lost original response", async () => {
    const submission = newLessonSubmission({ symbol: "NOVA", side: "buy", price: 101, quantity: 1 });
    vi.mocked(placeOrder).mockRejectedValueOnce(new Error("Lost response")).mockRejectedValueOnce(new ApiResponseError(429, "Too many requests")).mockResolvedValue(practice.receipt);
    await expect(submitLessonOrder(submission)).rejects.toThrow();
    await expect(submitLessonOrder(submission)).rejects.toThrow();
    vi.mocked(getCommand).mockResolvedValue(command());
    vi.mocked(getOrder).mockResolvedValue(order("filled"));
    expect((await endLessonSubmission(submission, practice))?.status).toBe("filled");
    expect(placeOrder).toHaveBeenCalledTimes(3);
    expect(submission.ambiguous).toBe(true);
  });
});
