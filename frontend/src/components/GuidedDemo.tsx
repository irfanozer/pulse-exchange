import { useEffect, useRef, useState } from "react";
import { isOrderOpen, lowerOfferPrice } from "../lesson";
import type { GuidedDemoResult, GuidedDemoStep, OrderBook, OrderReceipt, PracticeOffer, SymbolCode } from "../types";

interface GuidedDemoProps {
  symbol: SymbolCode;
  book: OrderBook | null;
  steps: GuidedDemoStep[];
  result: GuidedDemoResult | null;
  running: boolean;
  canRun: boolean;
  disabledReason: string;
  practice: PracticeOffer | null;
  hasSetupOffer: boolean;
  matchReceipt: OrderReceipt | null;
  stage: number;
  error: string | null;
  onStage: (stage: number) => void;
  onPractice: () => void;
  onCheckPractice: () => void;
  onCancelPractice: () => void;
  onRun: () => void;
  onRestart: () => void;
  onEnd: () => void;
}

const stepCopy = {
  observe: { title: "Find a seller", location: "Read the market" },
  accept: { title: "Send your order", location: "Browser to API" },
  process: { title: "Match & save", location: "On the server" },
  verify: { title: "Confirm the trade", location: "Back to this page" },
};
const statusCopy = { waiting: "Waiting", running: "In progress", complete: "Done", failed: "Not confirmed" };
const pathCopy = [
  { title: "Browser", description: "Your browser sent a buy offer with a price limit and a quantity.", evidence: (r: GuidedDemoResult) => `Order ${r.orderId}` },
  { title: "API", description: "The API checked the offer and accepted it for processing. Acceptance alone did not mean it had traded.", evidence: (r: GuidedDemoResult) => `HTTP ${r.httpStatus} · Command #${r.commandSequence}` },
  { title: "Database", description: "PostgreSQL saved the command so the matching service could pick it up.", evidence: (r: GuidedDemoResult) => `Saved at ${r.commandCreatedAt}` },
  { title: "Matching service", description: "This software matched your buyer with an available seller and saved the trade.", evidence: (r: GuidedDemoResult) => `Trade #${r.tradeSequence} · ${r.quantity} unit at ${r.price} ticks` },
  { title: "This page", description: "The page read the saved trade and received the same trade through its live connection. That is why the graph can update without a refresh.", evidence: (r: GuidedDemoResult) => `Saved trade ID ${r.tradeId} = live trade ID ${r.websocketTradeId}` },
];

export const GuidedDemo = ({ symbol, book, steps, result, running, canRun, disabledReason, practice, hasSetupOffer, matchReceipt, stage, error, onStage, onPractice, onCheckPractice, onCancelPractice, onRun, onRestart, onEnd }: GuidedDemoProps) => {
  const [pathIndex, setPathIndex] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const previousStage = useRef(stage);
  useEffect(() => { setPathIndex(0); }, [symbol, result?.orderId]);
  useEffect(() => {
    if (previousStage.current === stage) return;
    previousStage.current = stage;
    if (!heading.current?.closest("details")?.open) return;
    heading.current.focus({ preventScroll: true });
    heading.current.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [stage]);
  const seller = book?.asks[0];
  const lowerPrice = book ? lowerOfferPrice(book) : null;
  const checked = practice?.order;
  const activeStep = steps.find((step) => step.status === "running");
  const lessonStep = stage < 2 ? 1 : stage === 2 ? 2 : 3;
  const primary = (label: string, action: () => void, disabled = false) => (
    <button className="demo-button" type="button" onClick={action} disabled={disabled || running} aria-describedby="lesson-help"><span>{running ? "Checking the server…" : label}</span><span aria-hidden="true">→</span></button>
  );

  return (
    <section id="live-demo" className="guided-demo lesson" aria-labelledby="guided-demo-heading">
      <div className="lesson-header">
        <div><p className="eyebrow">Learn at your own pace</p><h2 ref={heading} tabIndex={-1} id="guided-demo-heading">Why does an offer become a trade?</h2></div>
        <span className="lesson-step-count">Step {lessonStep} of 3</span>
      </div>
      <ol className="lesson-steps" aria-label="Lesson progress">
        {["Try a lower price", "Meet the seller’s price", "Follow the request"].map((title, index) => (
          <li key={title} aria-current={lessonStep === index + 1 ? "step" : undefined}><span>{index + 1}</span>{title}</li>
        ))}
      </ol>
      <div className="demo-main">
        {stage === 0 && !practice && <>
          <h3>First, make an offer that should wait.</h3>
          <p>A buyer sets the most they will pay. A seller sets the least they will accept.</p>
          <div className="trade-preview" aria-label="Current lesson preview">
            <div><span className="preview-label">Cheapest seller</span><strong>{book === null ? "Loading market…" : seller ? `${seller.price} ticks` : "No sellers yet"}</strong><span>{seller ? `${seller.quantity} ${symbol} units available` : "An offer needs a seller to match."}</span></div>
            <span className="match-arrow" aria-hidden="true">≠</span>
            <div><span className="preview-label">Your practice buy</span><strong>{lowerPrice === null ? "Not available" : `${lowerPrice} ticks`}</strong><span>1 {symbol} unit</span></div>
          </div>
          <p className="preview-note">{lowerPrice === null && book ? "The seller is already at the minimum price of 1 tick. Skip to the matching example." : "At this price, your offer should wait. You will check what actually happened before continuing."}</p>
          {lowerPrice !== null ? primary("Place this lower offer", onPractice, !canRun) : primary("Continue to matching", () => onStage(2), book === null)}
        </>}
        {(stage === 1 || (stage === 0 && practice)) && <>
          <h3>{checked ? "Here is what your offer did." : "Check your submitted offer."}</h3>
          <p>You offered to buy <strong>1 {symbol} unit at {practice?.price} ticks</strong>. {practice?.sellerPrice != null ? `The cheapest seller we read wanted ${practice.sellerPrice} ticks.` : "There was no seller when we checked."}</p>
          <p>{checked && isOrderOpen(checked) ? "Your offer was still waiting when checked. Its price was too low for the sellers available then." : checked?.status === "filled" ? "A seller accepted your price before we checked. This is a shared market, so a lower offer can still fill if another visitor sends a compatible sell." : checked?.status === "cancelled" ? "The remaining practice offer was cancelled. It is no longer waiting in the market." : "We have not confirmed this offer’s status. Checking again will recover the original request, not create a second offer."}</p>
          {checked ? primary("Next: meet a seller’s price", () => onStage(2)) : primary("Check this offer again", onCheckPractice, !canRun)}
          <div className="lesson-secondary">
            {checked && <button type="button" onClick={onCheckPractice} disabled={running}>Refresh this order’s status</button>}
            {practice && (!checked || isOrderOpen(checked)) && <button type="button" onClick={onCancelPractice} disabled={running}>Cancel practice offer</button>}
          </div>
        </>}
        {stage === 2 && <>
          <h3>{result ? "Now you have a confirmed trade." : matchReceipt ? "Your matching buyer was sent." : "Now offer a seller’s price."}</h3>
          {result ? <p><strong>{result.quantity} {result.symbol} unit matched at {result.price} ticks.</strong> This is one saved trade, not a browser animation. It also appears in trade history above.</p> : matchReceipt ? <p>We are checking this existing order. If the seller changed before it arrived, your buyer may be waiting. No second buyer will be sent when you check again.</p> : <>
            <div className="trade-preview" aria-label="Matching offer preview">
              <div><span className="preview-label">Cheapest seller now</span><strong>{seller ? `${seller.price} ticks` : "No sellers yet"}</strong><span>{symbol}</span></div>
              <span className="match-arrow" aria-hidden="true">=</span>
              <div><span className="preview-label">Your new buy limit</span><strong>{seller ? `${seller.price} ticks` : "Setup seller’s price"}</strong><span>1 {symbol} unit</span></div>
            </div>
            <p className="preview-note">{practice ? "First we check your practice offer and cancel any unfilled unit. " : ""}{seller ? "Then we send a new buyer at the displayed price. If that quote has changed, we will ask you to review it again." : "With your click, we add a seller through the API and send one matching buyer. Both are real demo orders."}</p>
          </>}
          {result ? primary("Next: follow my request", () => onStage(3)) : primary(matchReceipt ? "Check this trade again" : "Send the matching buyer", onRun, !canRun)}
          <div className="lesson-secondary">
            {practice && <button type="button" onClick={() => onStage(1)} disabled={running}>Review the first offer</button>}
          </div>
        </>}
        {stage === 3 && result && <>
          <h3>Follow your request, one stop at a time.</h3>
          <p>Select a stop to see what it did for this trade. These buttons only explain the result. They never send another order.</p>
          <div className="lesson-path" role="group" aria-label="Request journey">
            {pathCopy.map((stop, index) => <button key={stop.title} type="button" aria-pressed={pathIndex === index} onClick={() => setPathIndex(index)}>{index + 1}. {stop.title}</button>)}
          </div>
          <div className="lesson-explanation" aria-live="polite"><h4>{pathCopy[pathIndex].title}</h4><p>{pathCopy[pathIndex].description}</p><code>{pathCopy[pathIndex].evidence(result)}</code></div>
          {pathIndex < pathCopy.length - 1 ? primary("Next stop", () => setPathIndex(pathIndex + 1)) : <a className="demo-button" href="#custom-order-heading"><span>Try your own buy or sell offer</span><span aria-hidden="true">↑</span></a>}
          <div className="lesson-secondary"><button type="button" onClick={() => onStage(2)}>Review the trade</button><button type="button" onClick={() => { setPathIndex(0); onRestart(); }}>Start a new lesson</button></div>
        </>}
        <p id="lesson-help" className="button-help">{running ? "The server runs normally. We pause the explanation after the result." : !canRun && stage < 3 ? disabledReason : "Continue when you are ready. Nothing advances on a timer."}</p>
        {(practice || matchReceipt || hasSetupOffer) && !result && <div className="lesson-secondary"><button type="button" onClick={onEnd} disabled={running}>End lesson and cancel waiting lesson offers</button></div>}
        {error && <p className="lesson-error" role="alert">{error}</p>}
      </div>
      <aside className={`demo-outcome ${result && stage >= 2 ? "demo-outcome--complete" : ""}`} aria-label="Lesson takeaway">
        <p className="eyebrow">{stage < 2 ? "What to notice" : stage === 2 ? "What changed" : "What you learned"}</p>
        {stage < 2 ? <>
          <h3>{checked?.status === "filled" ? "The market found a seller." : checked && isOrderOpen(checked) ? "Waiting is a valid result." : "An offer is not a trade."}</h3>
          <p>{checked?.status === "filled" ? "A compatible sell arrived, so your buyer traded. The order record confirms the fill." : "Submitting a buy does not guarantee a trade. A seller must accept that price."}</p>
          {checked && <p className="lesson-status">Recorded status: <strong>{checked.status.replaceAll("_", " ")}</strong><br />Unfilled units: {checked.remaining_quantity}{checked.status === "cancelled" ? " (cancelled, not waiting)" : ""}</p>}
          <p>Only completed trades add graph points. A new trade at the same price can leave the line flat.</p>
          {practice && <a href="#market-details">See the order book and trades ↑</a>}
        </> : stage === 2 ? <>
          <h3>{result ? "Buyer and seller agreed." : activeStep && running ? `${stepCopy[activeStep.id].title}…` : "The prices need to meet."}</h3>
          <p>{result ? "The server matched the offers, saved the trade, and sent the result back to this page." : "Your buy limit is the most you will pay. A matching trade can happen at that price or lower."}</p>
          {result && <><p className="result-reference">Trade #{result.tradeSequence} · backend confirmed in {(result.durationMs / 1000).toFixed(1)} seconds</p><ul className="result-checks"><li>Saved in PostgreSQL</li><li>Same trade received through WebSocket</li></ul><a href="#market-details">Find the highlighted trade ↑</a></>}
        </> : <>
          <h3>You set the limit. The server finds the match.</h3>
          <p>An offer may wait. A match creates a saved trade. The live connection brings that result back without refreshing the page.</p>
          <p>You can now use the buy/sell form above to try a different price.</p>
        </>}
      </aside>
    </section>
  );
};

export const DemoEvidence = ({ steps, result }: { steps: GuidedDemoStep[]; result: GuidedDemoResult | null }) => (
  <section className="demo-evidence" aria-labelledby="evidence-heading">
    <h3 id="evidence-heading">What this run returned</h3>
    <ol className="request-log">
      {steps.map((step) => <li key={step.id}><strong>{stepCopy[step.id].title} · {statusCopy[step.status]}</strong><p>{step.detail}</p></li>)}
    </ol>
    {result ? (
      <>
        <p>Success requires a completed command and the same new trade ID in both the saved records and the live WebSocket connection.</p>
        <dl className="evidence-grid">
          <div><dt>API response</dt><dd>HTTP {result.httpStatus}</dd></div>
          <div><dt>Command</dt><dd>#{result.commandSequence} · {result.commandStatus}</dd></div>
          <div><dt>Accepted orders</dt><dd>{result.requestsAccepted}{result.requestsAccepted > 1 ? " (includes a setup seller)" : " buyer"}</dd></div>
          <div><dt>Command ID</dt><dd>{result.commandId}</dd></div>
          <div><dt>Correlation ID</dt><dd>{result.correlationId}</dd></div>
          <div><dt>Buyer order ID</dt><dd>{result.orderId}</dd></div>
          <div><dt>Saved trade ID (REST)</dt><dd>{result.tradeId}</dd></div>
          <div><dt>Received trade ID (WebSocket)</dt><dd>{result.websocketTradeId}</dd></div>
          <div><dt>Committed event</dt><dd>#{result.commandEventId}</dd></div>
          <div><dt>Live stream cursor</dt><dd>#{result.websocketEventId}</dd></div>
          <div><dt>Resting order ID (maker)</dt><dd>{result.makerOrderId}</dd></div>
          <div><dt>Incoming order ID (taker)</dt><dd>{result.takerOrderId}</dd></div>
          <div><dt>Saved record read at</dt><dd>{result.restObservedAt}</dd></div>
          <div><dt>Live update received at</dt><dd>{result.websocketObservedAt}</dd></div>
        </dl>
        <p className="technical-note">A buy can fill across several sellers. The result above shows one verified trade, not necessarily the whole order. The live stream cursor can be newer than the committed event.</p>
      </>
    ) : <p>Run the demo to see the server’s order, command, and trade identifiers here.</p>}
  </section>
);
