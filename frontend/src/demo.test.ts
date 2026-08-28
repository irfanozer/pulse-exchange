import { describe, expect, it } from "vitest";
import {
  createGuidedDemoSteps,
  findNewTrade,
  isSamePersistedTrade,
  tradeIncludesOrder,
  updateDemoStep,
} from "./demo";
import type { Trade } from "./types";

const trade = (id: string, sequence: number, takerOrderId?: string): Trade => ({
  id,
  symbol: "NOVA",
  sequence,
  price: 103,
  quantity: 5,
  taker_order_id: takerOrderId,
  created_at: "2026-08-27T12:00:00Z",
});

describe("guided demo state", () => {
  it("begins with four plain-language waiting steps", () => {
    const steps = createGuidedDemoSteps();
    expect(steps.map((step) => step.id)).toEqual(["observe", "accept", "process", "verify"]);
    expect(steps.every((step) => step.status === "waiting")).toBe(true);
    expect(steps.map((step) => step.title)).toEqual([
      "Read a waiting seller",
      "Send one buyer",
      "Store and match",
      "Prove the same trade",
    ]);
  });

  it("updates only the selected step and can replace its evidence text", () => {
    const steps = updateDemoStep(createGuidedDemoSteps(), "process", "complete", "Command 42 completed.");
    expect(steps[2]).toMatchObject({ status: "complete", detail: "Command 42 completed." });
    expect(steps[0].status).toBe("waiting");
    expect(steps[1].status).toBe("waiting");
    expect(steps[3].status).toBe("waiting");
  });

  it("finds a persisted trade that did not exist before the run", () => {
    expect(findNewTrade([trade("old", 1), trade("new", 2)], new Set(["old"]))?.id).toBe("new");
    expect(findNewTrade([trade("old", 1)], new Set(["old"]))).toBeNull();
  });

  it("can require the new trade to contain the guided order", () => {
    const trades = [trade("other", 3, "another-order"), trade("proof", 2, "guided-order")];
    expect(findNewTrade(trades, new Set(), "guided-order")?.id).toBe("proof");
    expect(findNewTrade(trades, new Set(), "missing-order")).toBeNull();
  });

  it("recognizes the proof order and requires REST and WebSocket to name the same trade", () => {
    const persisted = trade("trade-9", 9, "guided-order");
    expect(tradeIncludesOrder(persisted, "guided-order")).toBe(true);
    expect(tradeIncludesOrder(persisted, "other-order")).toBe(false);
    expect(isSamePersistedTrade(persisted, "trade-9")).toBe(true);
    expect(isSamePersistedTrade(persisted, "trade-10")).toBe(false);
    expect(isSamePersistedTrade(persisted, null)).toBe(false);
  });
});
