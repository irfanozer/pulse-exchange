import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { chartGeometry, MarketChart, priceHistory } from "./components/MarketChart";
import type { Trade } from "./types";

const trade = (sequence: number, price = 102, overrides: Partial<Trade> = {}): Trade => ({
  id: `trade-${sequence}`, symbol: "NOVA", sequence, price, quantity: 5,
  created_at: "2026-09-09T12:00:00Z", ...overrides,
});
const view = (trades: Trade[], loading = false) => renderToStaticMarkup(
  createElement(MarketChart, { trades, symbol: "NOVA", loading }),
);

describe("recorded market price history", () => {
  it("filters markets and invalid points, removes duplicates, and sorts without mutating input", () => {
    const input = [trade(3, 104), trade(1), trade(2, 48, { symbol: "ORBIT" }),
      trade(3, 104), trade(4, 0), trade(5, Number.NaN), trade(0),
      trade(6, 100, { sequence: Number.POSITIVE_INFINITY })];
    const original = [...input];
    expect(priceHistory(input, "NOVA").map((point) => point.sequence)).toEqual([1, 3]);
    expect(input).toEqual(original);
    expect(priceHistory(input, "ORBIT").map((point) => point.price)).toEqual([48]);
  });

  it("bounds the graph to thirty recent recorded trades", () => {
    const history = priceHistory(Array.from({ length: 35 }, (_, index) => trade(35 - index)), "NOVA");
    expect(history).toHaveLength(30);
    expect(history[0].sequence).toBe(6);
    expect(history[29].sequence).toBe(35);
  });

  it("distinguishes loading from empty history without inventing prices", () => {
    expect(chartGeometry([])).toBeNull();
    expect(view([])).toContain("No completed trades yet");
    expect(view([])).toContain("No price yet");
    expect(view([], true)).toContain("Loading market history");
    expect(view([], true)).not.toContain("No completed trades yet");
    expect(view([])).not.toContain("<svg");
  });

  it("shows one real point without manufacturing a trend", () => {
    const html = view([trade(4, 105)]);
    expect(html.match(/<circle\b/g)).toHaveLength(1);
    expect(html).not.toContain("<path");
    expect(html).toContain("105 ticks");
    expect(html).toContain("1 recent recorded trade.");
    expect(chartGeometry([trade(4, 105)])?.points[0].x).toBe(300);
  });

  it("keeps flat price history finite and labels the latest actual trade", () => {
    const history = priceHistory([trade(3), trade(2), trade(1)], "NOVA");
    const geometry = chartGeometry(history)!;
    expect(geometry.points.every((point) => Number.isFinite(point.x) && Number.isFinite(point.y))).toBe(true);
    expect(new Set(geometry.points.map((point) => point.y)).size).toBe(1);
    expect(geometry.ticks[0]).toBeGreaterThan(geometry.ticks[4]);
    const html = view([trade(3, 108), trade(1, 100), trade(2, 104)]);
    expect(html).toContain("<strong>108 ticks</strong>");
    expect(html).toContain("Trade 1: 100 ticks. Trade 2: 104 ticks. Trade 3: 108 ticks.");
  });

  it("spaces points by trade number, including gaps, rather than pretending equal elapsed time", () => {
    const geometry = chartGeometry([trade(1), trade(2), trade(5)])!;
    expect(geometry.points.map((point) => point.x)).toEqual([8, 154, 592]);
    expect(view([trade(1), trade(2), trade(5)])).toContain("Trade number");
  });

  it("does not create extra graph points when there are no new trades", () => {
    const history = [trade(2), trade(1)];
    expect(view([...history, trade(2)])).toBe(view(history));
    expect(view(history)).toContain("Only completed trades change this graph.");
  });
});
