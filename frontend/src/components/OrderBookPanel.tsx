import type { CSSProperties } from "react";
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
          <p className="eyebrow">Live depth</p>
          <h2 id="order-book-heading">Order book</h2>
        </div>
        <div className="spread-readout">
          <span>Spread</span>
          <strong>{spread === null ? "Awaiting both sides" : `${spread} ticks`}</strong>
        </div>
      </div>

      <div className="book-grid">
        <div className="book-side">
          <div className="book-side-title book-side-title--bid">
            <strong>Bids</strong><span>Resting buys</span>
          </div>
          <div className="level-labels"><span>Tick</span><span>Units</span><span>Orders</span></div>
          <LevelRows levels={book?.bids ?? []} side="bid" maxQuantity={maximum} />
        </div>
        <div className="book-side">
          <div className="book-side-title book-side-title--ask">
            <strong>Asks</strong><span>Resting sells</span>
          </div>
          <div className="level-labels"><span>Tick</span><span>Units</span><span>Orders</span></div>
          <LevelRows levels={book?.asks ?? []} side="ask" maxQuantity={maximum} />
        </div>
      </div>
    </section>
  );
};
