import { describe, expect, it } from "vitest";
import { createGuidedDemoSteps, findNewTrade, updateDemoStep } from "./demo";
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
    expect(steps.map((step) => step.id)).toEqual(["accept", "process", "match", "verify"]);
    expect(steps.every((step) => step.status === "waiting")).toBe(true);
  });

  it("updates only the selected step and can replace its evidence text", () => {
    const steps = updateDemoStep(createGuidedDemoSteps(), "process", "complete", "Sequence advanced by 4.");
    expect(steps[1]).toMatchObject({ status: "complete", detail: "Sequence advanced by 4." });
    expect(steps[0].status).toBe("waiting");
    expect(steps[2].status).toBe("waiting");
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
});
