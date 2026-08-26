import type { Trade } from "../types";

const formatTime = (value: string): string => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "—"
    : date.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

export const TradeTape = ({ trades }: { trades: Trade[] }) => (
  <section className="panel trades-panel" aria-labelledby="trade-tape-heading">
    <div className="panel-heading">
      <div>
        <p className="eyebrow">Matched by the engine</p>
        <h2 id="trade-tape-heading">Recent trades</h2>
      </div>
      <span className="record-count">{trades.length} records</span>
    </div>
    <div className="trade-table" role="table" aria-label="Recent fictional trades">
      <div className="trade-row trade-row--heading" role="row">
        <span role="columnheader">Sequence</span>
        <span role="columnheader">Tick</span>
        <span role="columnheader">Units</span>
        <span role="columnheader">Time</span>
      </div>
      {trades.length ? trades.slice(0, 9).map((trade) => (
        <div className="trade-row" role="row" key={trade.id}>
          <span role="cell">#{trade.sequence.toLocaleString()}</span>
          <strong role="cell">{trade.price.toLocaleString()}</strong>
          <span role="cell">{trade.quantity.toLocaleString()}</span>
          <time role="cell" dateTime={trade.created_at}>{formatTime(trade.created_at)}</time>
        </div>
      )) : (
        <div className="trade-empty">
          <strong>No trades recorded for this symbol.</strong>
          <span>Use “Cross the spread” or submit an order that meets a resting order.</span>
        </div>
      )}
    </div>
  </section>
);
