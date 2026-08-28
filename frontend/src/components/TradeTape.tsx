import { TICK_EXPLAINED } from "../instruments";
import type { SymbolCode, Trade } from "../types";

const formatTime = (value: string): string => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "—"
    : date.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

interface TradeTapeProps {
  trades: Trade[];
  symbol?: SymbolCode;
  highlightedTradeId?: string | null;
}

export const TradeTape = ({ trades, symbol, highlightedTradeId }: TradeTapeProps) => {
  const visibleSymbol = symbol ?? trades[0]?.symbol;

  return (
    <section className="panel trades-panel" aria-labelledby="trade-tape-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{visibleSymbol ?? "Market"} · completed matches</p>
          <h2 id="trade-tape-heading">Trade history</h2>
        </div>
        <span className="record-count">Latest {trades.length} stored {trades.length === 1 ? "trade" : "trades"}</span>
      </div>
      <p className="panel-explainer">
        Every row is a completed match returned by the backend. The newest verified demo trade is
        highlighted so it is easy to connect the button press to its result.
      </p>
      <div className="trade-table" role="table" aria-label={`Stored ${visibleSymbol ?? "fictional"} trades`}>
        <div className="trade-row trade-row--heading" role="row">
          <span role="columnheader">Trade #</span>
          <span role="columnheader">Price (ticks)</span>
          <span role="columnheader">Units</span>
          <span role="columnheader">Recorded</span>
        </div>
        {trades.length ? trades.slice(0, 9).map((trade) => {
          const highlighted = trade.id === highlightedTradeId;
          return (
            <div className={`trade-row ${highlighted ? "trade-row--highlighted" : ""}`} role="row" key={trade.id}>
              <span className="trade-sequence" role="cell">
                <span>#{trade.sequence.toLocaleString()}</span>
                {highlighted && <b>Created by live demo</b>}
              </span>
              <strong role="cell">{trade.price.toLocaleString()}</strong>
              <span role="cell">{trade.quantity.toLocaleString()}</span>
              <time role="cell" dateTime={trade.created_at}>{formatTime(trade.created_at)}</time>
            </div>
          );
        }) : (
          <div className="trade-empty">
            <strong>No stored trades for this instrument yet.</strong>
            <span>The primary demo will create one as soon as a seller is waiting.</span>
          </div>
        )}
      </div>
      <p className="panel-footnote">{TICK_EXPLAINED}</p>
    </section>
  );
};
