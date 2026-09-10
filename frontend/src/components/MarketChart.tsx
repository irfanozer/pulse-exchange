import { useId } from "react";
import type { SymbolCode, Trade } from "../types";

export const priceHistory = (trades: Trade[], symbol: SymbolCode): Trade[] => (
  [...new Map(trades.filter((trade) => (
    trade.symbol === symbol
    && Number.isFinite(trade.price) && trade.price > 0
    && Number.isFinite(trade.sequence) && trade.sequence > 0
  )).map((trade) => [trade.id, trade])).values()]
    .sort((a, b) => a.sequence - b.sequence)
    .slice(-30)
);

export const chartGeometry = (history: Trade[]) => {
  if (!history.length) return null;
  const prices = history.map((trade) => trade.price);
  const bottom = Math.max(0, Math.floor(Math.min(...prices) - 1));
  const step = Math.max(1, Math.ceil((Math.max(...prices) + 1 - bottom) / 4));
  const top = bottom + step * 4;
  const first = history[0].sequence;
  const last = history[history.length - 1].sequence;
  const points = history.map((trade) => ({
    trade,
    x: first === last ? 300 : 8 + ((trade.sequence - first) / (last - first)) * 584,
    y: 8 + ((top - trade.price) / (top - bottom)) * 204,
  }));
  return {
    points,
    ticks: Array.from({ length: 5 }, (_, index) => top - step * index),
    path: points.map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`).join(" "),
  };
};

export const MarketChart = ({ trades, symbol, loading = false }: {
  trades: Trade[];
  symbol: SymbolCode;
  loading?: boolean;
}) => {
  const id = useId();
  const history = priceHistory(trades, symbol);
  const geometry = chartGeometry(history);
  const latest = history[history.length - 1];

  return (
    <section className="panel price-chart" aria-labelledby={`${id}-heading`}>
      <div className="chart-heading">
        <div><p className="eyebrow">{symbol} market</p><h2 id={`${id}-heading`}>Price history</h2></div>
        <div className="last-price"><span>Last traded price</span><strong>{latest ? `${latest.price.toLocaleString()} ticks` : "No price yet"}</strong></div>
      </div>
      {geometry ? (
        <div className="chart-body">
          <div className="chart-axis-title">Price (ticks)</div>
          <div className="chart-plot">
            <div className="chart-scale" aria-hidden="true">{geometry.ticks.map((tick) => <span key={tick}>{tick.toLocaleString()}</span>)}</div>
            <svg viewBox="0 0 600 220" preserveAspectRatio="none" role="img" aria-labelledby={`${id}-title ${id}-description`}>
              <title id={`${id}-title`}>{symbol} recorded trade prices</title>
              <desc id={`${id}-description`}>Prices by trade number, oldest to newest. {history.map((trade) => `Trade ${trade.sequence}: ${trade.price} ticks.`).join(" ")}</desc>
              {geometry.ticks.map((tick, index) => <line key={tick} x1="0" x2="600" y1={8 + index * 51} y2={8 + index * 51} className="chart-gridline" vectorEffect="non-scaling-stroke" />)}
              {geometry.points.length > 1 && <path d={geometry.path} className="chart-line" vectorEffect="non-scaling-stroke" />}
              {geometry.points.map(({ trade, x, y }, index) => (
                <circle key={trade.id} cx={x} cy={y} r={index === geometry.points.length - 1 ? 5 : 3} className={index === geometry.points.length - 1 ? "chart-point chart-point--latest" : "chart-point"}>
                  <title>Trade #{trade.sequence}: {trade.quantity} units at {trade.price} ticks</title>
                </circle>
              ))}
            </svg>
          </div>
          <div className="chart-x-axis"><span>#{history[0].sequence}</span><span>Trade number</span><span>#{latest.sequence}</span></div>
        </div>
      ) : (
        <div className="chart-empty"><strong>{loading ? "Loading market history…" : "No completed trades yet"}</strong><p>{loading ? "Waiting for the market to respond." : "A buyer and seller must match before a price appears here."}</p></div>
      )}
      <p className="chart-caption">{history.length ? `${history.length} recent recorded ${history.length === 1 ? "trade" : "trades"}. ` : ""}Only completed trades change this graph. Waiting offers appear in the order book below.</p>
    </section>
  );
};
