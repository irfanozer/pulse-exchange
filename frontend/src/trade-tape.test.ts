import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TradeTape } from "./components/TradeTape";
import type { Trade } from "./types";

const trade: Trade = {
  id: "trade-12", symbol: "NOVA", sequence: 12, price: 103, quantity: 8,
  created_at: "2026-09-10T03:00:32Z",
};

describe("trade history recorded timestamps", () => {
  it("shows the stored timestamp as a local date and time, preserving the original instant", () => {
    const html = renderToStaticMarkup(createElement(TradeTape, { trades: [trade] }));
    const date = new Date(trade.created_at);
    const expectedDate = date.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
    const expectedTime = date.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
    expect(html).toContain(`dateTime="${trade.created_at}"`);
    expect(html).toContain(`>${expectedTime}</span>`);
    expect(html).toContain(`<span class="trade-date">${expectedDate}</span>`);
    expect(html).toContain('title="Your local date and time"');
  });

  it("distinguishes trades recorded on different days without changing their order", () => {
    const earlier = { ...trade, id: "trade-11", sequence: 11, created_at: "2026-09-09T03:00:32Z" };
    const html = renderToStaticMarkup(createElement(TradeTape, { trades: [trade, earlier] }));
    const dates = [trade, earlier].map((item) => new Date(item.created_at).toLocaleDateString([], {
      year: "numeric", month: "short", day: "numeric",
    }));
    expect(dates[0]).not.toBe(dates[1]);
    expect(html.indexOf(dates[0])).toBeGreaterThan(-1);
    expect(html.indexOf(dates[1])).toBeGreaterThan(html.indexOf(dates[0]));
    expect(html.indexOf("#12")).toBeLessThan(html.indexOf("#11"));
  });

  it("does not invent a date or render an invalid machine-readable timestamp", () => {
    const html = renderToStaticMarkup(createElement(TradeTape, { trades: [{ ...trade, created_at: "invalid" }] }));
    expect(html).toContain('role="cell">Unavailable</span>');
    expect(html).not.toContain("Invalid Date");
    expect(html).not.toContain("<time");
  });
});
