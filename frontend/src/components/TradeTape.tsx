import { TICK_EXPLAINED } from "../instruments";
import type { SymbolCode, Trade } from "../types";

const formatRecorded = (value: string): { date: string; time: string } | null => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? null
    : {
      date: date.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" }),
      time: date.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }),
    };
};

interface TradeTapeProps {
  trades: Trade[];
  symbol?: SymbolCode;
  highlightedTradeId?: string | null;
  loading?: boolean;
}

export const TradeTape = ({ trades, symbol, highlightedTradeId, loading = false }: TradeTapeProps) => {
  const visibleSymbol = symbol ?? trades[0]?.symbol;

  return (
    <section className="panel trades-panel" aria-labelledby="trade-tape-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{visibleSymbol ?? "Market"} · completed matches</p>
          <h2 id="trade-tape-heading">Trade history</h2>
        </div>
        <span className="record-count">{loading && !trades.length ? "Loading…" : `${Math.min(trades.length, 9)} recent ${trades.length === 1 ? "trade" : "trades"}`}</span>
      </div>
      <p className="panel-explainer">
        Completed matches, newest first. Your demo trade is marked when it appears in this list.
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
          const recorded = formatRecorded(trade.created_at);
          return (
            <div className={`trade-row ${highlighted ? "trade-row--highlighted" : ""}`} role="row" key={trade.id}>
              <span className="trade-sequence" role="cell">
                <span>#{trade.sequence.toLocaleString()}</span>
                {highlighted && <b>Your demo trade</b>}
              </span>
              <strong role="cell">{trade.price.toLocaleString()}</strong>
              <span role="cell">{trade.quantity.toLocaleString()}</span>
              {recorded ? (
                <time className="trade-recorded" role="cell" dateTime={trade.created_at} title="Your local date and time">
                  <span>{recorded.time}</span>
                  <span className="trade-date">{recorded.date}</span>
                </time>
              ) : <span role="cell">Unavailable</span>}
            </div>
          );
        }) : (
          <div className="trade-empty">
            <strong>{loading ? "Loading trade history…" : "No trades yet."}</strong>
            <span>{loading ? "Waiting for recorded matches." : "Place a matching offer, or open the guided example below."}</span>
          </div>
        )}
      </div>
      <p className="panel-footnote">{TICK_EXPLAINED}</p>
    </section>
  );
};
