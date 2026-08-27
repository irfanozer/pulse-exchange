import { describe, expect, it } from "vitest";
import {
  marketSpread,
  mergeTrades,
  normalizeOrderBook,
  normalizeTrade,
  shouldApplyBookSnapshot,
  shouldApplyMarketUpdate,
  unseenRecoveredEvents,
} from "./market";
import type { Trade } from "./types";

const trade = (id: string, sequence: number): Trade => ({
  id,
  symbol: "NOVA",
  sequence,
  price: 102,
  quantity: 5,
  buy_order_id: `buy-${id}`,
  sell_order_id: `sell-${id}`,
  created_at: "2026-08-25T18:00:00Z",
});

describe("market data transformations", () => {
  it("normalizes numeric strings and sorts both sides by market priority", () => {
    const book = normalizeOrderBook(
      {
        symbol: "NOVA",
        sequence: 8,
        bids: [
          { price: 100, quantity: 4, order_count: 1 },
          { price: 101, quantity: 2, order_count: 1 },
        ],
        asks: [
          { price: 104, quantity: 3, order_count: 1 },
          { price: 103, quantity: 6, order_count: 2 },
        ],
      },
      "NOVA",
    );

    expect(book.bids.map((level) => level.price)).toEqual([101, 100]);
    expect(book.asks.map((level) => level.price)).toEqual([103, 104]);
    expect(marketSpread(book)).toBe(2);
  });

  it("deduplicates trades and keeps the newest sequence first", () => {
    expect(mergeTrades([trade("one", 1), trade("two", 2)], [trade("two", 2), trade("three", 3)]))
      .toEqual([trade("three", 3), trade("two", 2), trade("one", 1)]);
  });

  it("adapts the backend trade envelope into stable UI fields", () => {
    expect(normalizeTrade({
      trade_id: 42,
      trade_sequence: 12,
      command_sequence: 14,
      symbol: "NOVA",
      maker_order_id: "maker",
      taker_order_id: "taker",
      price: 103,
      quantity: 4,
      created_at: "2026-08-25T18:00:00Z",
    })).toMatchObject({
      id: "42",
      sequence: 12,
      price: 103,
      quantity: 4,
      maker_order_id: "maker",
      taker_order_id: "taker",
    });
  });

  it("does not invent a spread for an empty book", () => {
    expect(marketSpread(normalizeOrderBook(undefined, "ORBIT"))).toBeNull();
  });

  it("rejects duplicate market updates and stale book snapshots", () => {
    expect(shouldApplyMarketUpdate(12, 12)).toBe(false);
    expect(shouldApplyMarketUpdate(11, 12)).toBe(false);
    expect(shouldApplyMarketUpdate(13, 12)).toBe(true);

    expect(shouldApplyBookSnapshot(11, 12, 10)).toBe(false);
    expect(shouldApplyBookSnapshot(12, 12, 10)).toBe(true);
    expect(shouldApplyBookSnapshot(12, 12, 12)).toBe(false);
  });

  it("does not let a fast REST book suppress its same-sequence WebSocket event", () => {
    const lastEventSequence = -1;

    expect(shouldApplyBookSnapshot(20, lastEventSequence, -1)).toBe(true);
    // Applying that REST book advances only lastBookSequence, not lastEventSequence.
    expect(shouldApplyMarketUpdate(20, lastEventSequence)).toBe(true);
    expect(shouldApplyBookSnapshot(20, 20, 20)).toBe(false);
  });

  it("filters and orders durable reconnect outcomes after the last received event", () => {
    const recovered = [
      { event_id: 13, sequence: 8, event_type: "order_cancelled", payload: {}, created_at: "2026-08-25T18:00:03Z" },
      { event_id: 11, sequence: 6, event_type: "order_accepted", payload: {}, created_at: "2026-08-25T18:00:01Z" },
      { event_id: 12, sequence: 7, event_type: "command_rejected", payload: {}, created_at: "2026-08-25T18:00:02Z" },
    ];

    expect(unseenRecoveredEvents(recovered, 11).map((event) => event.event_id)).toEqual([12, 13]);
  });
});
