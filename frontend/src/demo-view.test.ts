import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "./App";
import { DemoEvidence, GuidedDemo } from "./components/GuidedDemo";
import { OrderBookPanel } from "./components/OrderBookPanel";
import { TradeTape } from "./components/TradeTape";
import { createGuidedDemoSteps } from "./demo";
import type { GuidedDemoResult, OrderBook, PracticeOffer } from "./types";

const book: OrderBook = {
  symbol: "NOVA", sequence: 10,
  bids: [{ price: 101, quantity: 20, order_count: 2 }],
  asks: [{ price: 103, quantity: 8, order_count: 2 }],
};
const result: GuidedDemoResult = {
  symbol: "NOVA", price: 103, quantity: 2, durationMs: 600, requestsAccepted: 1,
  startingSequence: 10, endingSequence: 11, httpStatus: 202,
  correlationId: "correlation-11", commandId: "command-11", commandSequence: 11,
  commandStatus: "completed", commandCreatedAt: "2026-09-09T12:00:00Z",
  commandCompletedAt: "2026-09-09T12:00:01Z", commandEventId: 11,
  orderId: "buyer-11", tradeId: "trade-7", tradeSequence: 7,
  makerOrderId: "resting-order", takerOrderId: "incoming-order",
  restObservedAt: "2026-09-09T12:00:01Z", websocketTradeId: "trade-7",
  websocketEventId: 12, websocketObservedAt: "2026-09-09T12:00:02Z",
};
const view = (overrides: Partial<ComponentProps<typeof GuidedDemo>> = {}) => renderToStaticMarkup(
  createElement(GuidedDemo, {
    symbol: "NOVA", book, steps: createGuidedDemoSteps(), result: null,
    running: false, canRun: true, disabledReason: "Waiting for the live connection.",
    practice: null, hasSetupOffer: false, matchReceipt: null, stage: 0, error: null,
    onStage: () => undefined, onPractice: () => undefined, onCheckPractice: () => undefined,
    onCancelPractice: () => undefined, onRestart: () => undefined, onEnd: () => undefined,
    onRun: () => undefined, ...overrides,
  }),
);

describe("market-first demo presentation", () => {
  it("shows the graph and manual trading before the closed optional sections", () => {
    const html = renderToStaticMarkup(createElement(App));
    const disclosures = html.match(/<details\b[^>]*>/g) ?? [];
    expect(disclosures).toHaveLength(2);
    expect(disclosures.every((tag) => !/\bopen(?:[ =>])/.test(tag))).toBe(true);
    expect(html).toContain("See how the backend works");
    expect(html).toContain("Want a guided example?");
    const visibleMarket = html.slice(0, html.indexOf("<details"));
    expect(visibleMarket).toContain("Price history");
    expect(visibleMarket).toContain("Place an offer");
    expect(visibleMarket).toMatch(/<button[^>]*>Buy<\/button>/);
    expect(visibleMarket).toMatch(/<button[^>]*>Sell<\/button>/);
    expect(visibleMarket).toContain("Price (ticks)");
    expect(visibleMarket).toContain("Units");
    expect(visibleMarket).toContain("Send buy offer");
    expect(visibleMarket).toContain("Waiting orders");
    expect(visibleMarket).toContain("Trade history");
    expect(visibleMarket).toContain("Loading buy offers");
    expect(visibleMarket).toContain("Loading sell offers");
    expect(visibleMarket).toContain("Loading trade history");
    expect(visibleMarket).not.toContain("No trades yet.");
    expect(visibleMarket).not.toContain("No buy orders yet");
    expect(html).not.toContain("Start the 30-second demo");
  });

  it("distinguishes a loaded empty market from initial loading", () => {
    const emptyBook = renderToStaticMarkup(createElement(OrderBookPanel, { book: { ...book, bids: [], asks: [] } }));
    const emptyTrades = renderToStaticMarkup(createElement(TradeTape, { trades: [], symbol: "NOVA" }));
    expect(emptyBook).toContain("No buy orders yet");
    expect(emptyBook).toContain("No sell orders yet");
    expect(emptyBook).not.toContain("Loading market");
    expect(emptyTrades).toContain("No trades yet.");
    expect(emptyTrades).toContain("guided example below");
  });

  it("explains a lower offer before any order is sent", () => {
    const html = view();
    expect(html).toContain("103 ticks");
    expect(html).toContain("102 ticks");
    expect(html).toContain("1 NOVA unit");
    expect(html).toContain("Place this lower offer");
    expect(html).toContain("Step 1 of 3");
    expect(html).toContain("Nothing advances on a timer.");
    expect(html).not.toContain("Correlation ID");
    expect(html).not.toContain("A trade was made.");
  });

  it("distinguishes loading and handles the minimum legal price honestly", () => {
    const loading = view({ book: null, canRun: false });
    expect(loading).toContain("Loading market");
    expect(loading).not.toContain("No sellers yet");
    expect(loading).toContain("Waiting for the live connection.");
    expect(loading).toContain('aria-describedby="lesson-help"');
    const minimum = view({ book: { ...book, asks: [{ price: 1, quantity: 3, order_count: 1 }] } });
    expect(minimum).toContain("minimum price of 1 tick");
    expect(minimum).toContain("Continue to matching");
    expect(minimum).not.toContain("Place this lower offer");
    expect(minimum).not.toContain("0 ticks");
  });

  it("discloses setup orders when the matching stage has no sellers", () => {
    const html = view({ stage: 2, book: { ...book, asks: [] } });
    expect(html).toContain("No sellers yet");
    expect(html).toContain("we add a seller through the API");
    expect(html).toContain("Both are real demo orders.");
  });

  const practice: PracticeOffer = {
    price: 102, sellerPrice: 103,
    receipt: { orderId: "low-buyer", commandId: "low-command", commandSequence: 12, httpStatus: 202, correlationId: "low-correlation", location: null, status: "queued", createdAt: "2026-09-09T12:00:00Z", completedAt: null, message: "Accepted" },
    order: { order_id: "low-buyer", symbol: "NOVA", side: "buy", price: 102, quantity: 1, remaining_quantity: 1, status: "open", updated_at: "2026-09-09T12:00:01Z" },
  };

  it("pauses on the actual waiting order, preserving its submitted price", () => {
    const html = view({ stage: 1, practice, book: { ...book, asks: [{ price: 200, quantity: 9, order_count: 1 }] } });
    expect(html).toContain("1 NOVA unit at 102 ticks");
    expect(html).toContain("wanted 103 ticks");
    expect(html).not.toContain("200 ticks");
    expect(html).toContain("still waiting when checked");
    expect(html).toContain("Next: meet a seller");
    expect(html).toContain("Cancel practice offer");
    expect(html).not.toContain("Send the matching buyer");
    expect(html).not.toContain("confirmed trade");
  });

  it("reports a competing seller filling the low offer instead of pretending it waited", () => {
    const html = view({ stage: 1, practice: { ...practice, order: { ...practice.order!, status: "filled", remaining_quantity: 0 } } });
    expect(html).toContain("A seller accepted your price");
    expect(html).not.toContain("still waiting when checked");
    expect(html).not.toContain(">Cancel practice offer<");
  });

  it("does not confuse cancelled unfilled units with open units", () => {
    const html = view({ stage: 1, practice: { ...practice, order: { ...practice.order!, status: "cancelled" } } });
    expect(html).toContain("cancelled, not waiting");
    expect(html).toContain("no longer waiting in the market");
    expect(html).not.toContain(">Cancel practice offer<");
  });

  it("keeps an unconfirmed practice offer checkable without offering a second submission", () => {
    const html = view({ stage: 1, practice: { ...practice, order: null }, error: "Confirmation timed out" });
    expect(html).toContain("Check this offer again");
    expect(html).not.toContain("Place this lower offer");
    expect(html).toContain("not create a second offer");
    expect(html).toContain("End lesson and cancel waiting lesson offers");
    expect(html).toContain("Confirmation timed out");
  });

  it("checks the same matching buyer after an uncertain result", () => {
    const html = view({ stage: 2, matchReceipt: practice.receipt });
    expect(html).toContain("Check this trade again");
    expect(html).not.toContain(">Send the matching buyer<");
    expect(html).toContain("No second buyer will be sent");
    expect(html).toContain("End lesson and cancel waiting lesson offers");
  });

  it("keeps confirmed results visible until the visitor advances to the explanation", () => {
    const html = view({ stage: 2, result, book: { ...book, asks: [{ price: 200, quantity: 90, order_count: 1 }] } });
    expect(html).toContain("2 NOVA unit matched at 103 ticks");
    expect(html).not.toContain("200 ticks");
    expect(html).toContain("Next: follow my request");
    expect(html).toContain("Trade #7");
    expect(html).not.toContain('aria-label="Request journey"');
  });

  it("offers request-path explanations without a new-order action", () => {
    const html = view({ stage: 3, result });
    expect(html).toContain('aria-label="Request journey"');
    expect(html).toContain("1. Browser");
    expect(html).toContain("2. API");
    expect(html).toContain("3. Database");
    expect(html).toContain("4. Matching service");
    expect(html).toContain("5. This page");
    expect(html).toContain("They never send another order.");
    expect(html).toContain("Next stop");
    expect(html).not.toContain(">Send the matching buyer<");
  });

  it("does not manufacture success from completed progress flags", () => {
    const html = view({ stage: 2, steps: createGuidedDemoSteps().map((step) => ({ ...step, status: "complete" })) });
    expect(html).not.toContain("Now you have a confirmed trade.");
    expect(html).not.toContain("Same trade received through WebSocket");
  });

  it("keeps complete identifiers and distinct event cursors in optional evidence", () => {
    const html = renderToStaticMarkup(createElement(DemoEvidence, { result, steps: createGuidedDemoSteps() }));
    expect(html).toContain("command-11");
    expect(html).toContain("correlation-11");
    expect(html.match(/trade-7/g)).toHaveLength(2);
    expect(html).toContain("Resting order ID (maker)");
    expect(html).toContain("Incoming order ID (taker)");
    expect(html).toContain("#11");
    expect(html).toContain("#12");
  });
});
