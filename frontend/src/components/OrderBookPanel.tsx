import type { CSSProperties } from "react";
import { TICK_EXPLAINED } from "../instruments";
import { maxVisibleQuantity, marketSpread } from "../market";
import type { BookLevel, OrderBook } from "../types";

const LevelRows = ({ levels, side, maxQuantity }: {
  levels: BookLevel[];
  side: "bid" | "ask";
  maxQuantity: number;
}) => {
  const visible = levels.slice(0, 8);

  if (!visible.length) {
    return (
      <div className="book-empty">
        No {side === "bid" ? "buy" : "sell"} orders yet
      </div>
    );
  }

  return (
    <div className="level-list">
      {visible.map((level) => (
        <div
          className={`level-row level-row--${side}`}
          key={`${side}-${level.price}`}
          style={{ "--depth": `${Math.max(4, (level.quantity / maxQuantity) * 100)}%` } as CSSProperties}
        >
          <span className="depth-bar" aria-hidden="true" />
          <strong>{level.price.toLocaleString()}</strong>
          <span>{level.quantity.toLocaleString()}</span>
          <span>{level.order_count}</span>
        </div>
      ))}
    </div>
  );
};

export const OrderBookPanel = ({ book }: { book: OrderBook | null }) => {
  const spread = marketSpread(book);
  const maximum = maxVisibleQuantity(book);

  return (
    <section className="panel book-panel" aria-labelledby="order-book-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{book?.symbol ?? "Market"} · waiting orders</p>
          <h2 id="order-book-heading">Who is waiting to buy or sell?</h2>
        </div>
        <div className="spread-readout">
          <span>Gap between prices</span>
          <strong>{spread === null ? "Waiting for both sides" : `${spread} ${spread === 1 ? "tick" : "ticks"}`}</strong>
        </div>
      </div>

      <p className="panel-explainer">
        These orders have not traded yet. A trade happens when a buyer offers the same or a higher
        price than a seller will accept.
      </p>

      <div className="book-grid">
        <div className="book-side">
          <div className="book-side-title book-side-title--bid">
            <strong>Buyers</strong><span>Highest price first</span>
          </div>
          <div className="level-labels"><span>Price (ticks)</span><span>Units</span><span>Orders</span></div>
          <LevelRows levels={book?.bids ?? []} side="bid" maxQuantity={maximum} />
        </div>
        <div className="book-side">
          <div className="book-side-title book-side-title--ask">
            <strong>Sellers</strong><span>Lowest price first</span>
          </div>
          <div className="level-labels"><span>Price (ticks)</span><span>Units</span><span>Orders</span></div>
          <LevelRows levels={book?.asks ?? []} side="ask" maxQuantity={maximum} />
        </div>
      </div>
      <p className="panel-footnote">{TICK_EXPLAINED}</p>
    </section>
  );
};
