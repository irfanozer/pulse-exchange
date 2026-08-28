import { getInstrumentProfile, TICK_EXPLAINED } from "../instruments";
import type { GuidedDemoResult, GuidedDemoStep, OrderBook, SymbolCode } from "../types";

type GuidedDemoEvidence = GuidedDemoResult & Partial<{
  symbol: SymbolCode;
  httpStatus: number;
  commandId: string | null;
  correlationId: string | null;
  orderId: string | null;
  commandSequence: number | null;
  commandStatus: "queued" | "completed" | "rejected";
  commandCompletedAt: string | null;
  restObservedAt: string | null;
  websocketEventId: number | null;
  websocketObservedAt: string | null;
  makerOrderId: string | null;
  takerOrderId: string | null;
}>;

interface GuidedDemoProps {
  symbol?: SymbolCode;
  book?: OrderBook | null;
  steps: GuidedDemoStep[];
  result: GuidedDemoEvidence | null;
  running: boolean;
  canRun: boolean;
  onRun: () => void;
}

const stepStatusCopy: Record<GuidedDemoStep["status"], string> = {
  waiting: "Waiting",
  running: "In progress",
  complete: "Verified",
  failed: "Stopped",
};

const shortId = (value?: string | null): string => {
  if (!value) return "Pending";
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
};

const formatEvidenceTime = (value?: string | null): string => {
  if (!value) return "Recorded";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Recorded"
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

export const GuidedDemo = ({
  symbol = "NOVA",
  book,
  steps,
  result,
  running,
  canRun,
  onRun,
}: GuidedDemoProps) => {
  const profile = getInstrumentProfile(symbol);
  const bestSeller = book?.asks[0] ?? null;
  const demoQuantity = bestSeller ? Math.min(5, bestSeller.quantity) : null;

  return (
    <section id="live-demo" className="guided-demo" aria-labelledby="guided-demo-heading">
      <div className="guided-demo__intro">
        <div>
          <p className="eyebrow">30-second live demo</p>
          <h2 id="guided-demo-heading">Press once. Follow every real step.</h2>
        </div>
        <p>
          PulseExchange reads a real seller from the {profile.symbol} order book, sends one
          buyer through the public API, and proves the resulting trade through both REST and
          the live WebSocket stream.
        </p>
        <div className="guided-demo__scope">
          <strong>What you do</strong>
          <span>Press one button.</span>
          <strong>What the system does</strong>
          <span>Accepts, stores, matches, and broadcasts the order.</span>
        </div>
        <button className="guided-demo__run" type="button" onClick={onRun} disabled={!canRun}>
          <span>
            {running
              ? "Following the real request…"
              : result
                ? "Send another buyer and verify it"
                : "Send this buyer and verify the trade"}
          </span>
          <span aria-hidden="true">{running ? "•••" : "→"}</span>
        </button>
        {!canRun && !running && (
          <small className="guided-demo__hint">
            Waiting for the backend and live update connection.
          </small>
        )}
        <small className="guided-demo__secondary-note">
          This is the complete recruiter walkthrough. The order form below is optional.
        </small>
      </div>

      <div className="guided-demo__journey">
        <div className="demo-story" aria-label="Before, action, and result">
          <article className="demo-story__card demo-story__card--before">
            <span>Before</span>
            <strong>{bestSeller ? "A seller is waiting" : "No seller is waiting"}</strong>
            <p>
              {bestSeller
                ? `${bestSeller.quantity.toLocaleString()} units are offered at ${bestSeller.price.toLocaleString()} ticks.`
                : `The ${symbol} book is empty, so this run will first add one real seller through the same public API.`}
            </p>
            {book && <small>Book snapshot #{book.sequence.toLocaleString()}</small>}
          </article>
          <article className="demo-story__card demo-story__card--action">
            <span>Action</span>
            <strong>Send one matching buyer</strong>
            <p>
              {bestSeller && demoQuantity
                ? `POST a buy for ${demoQuantity.toLocaleString()} units at ${bestSeller.price.toLocaleString()} ticks—the seller's price.`
                : "POST the fallback seller, then one buyer at that exact price so the two real orders match."}
            </p>
            <small>Real HTTP request · no browser-only shortcut</small>
          </article>
          <article className={`demo-story__card demo-story__card--result ${result ? "is-complete" : ""}`}>
            <span>Result</span>
            <strong>{result ? `Trade #${result.tradeSequence.toLocaleString()} is stored` : "Prove the same trade twice"}</strong>
            <p>
              {result
                ? `${result.quantity.toLocaleString()} units matched at ${result.price.toLocaleString()} ticks.`
                : "REST reads the stored trade back; WebSocket delivers that exact trade ID to this screen."}
            </p>
            <small>{result ? "REST trade ID = WebSocket trade ID" : TICK_EXPLAINED}</small>
          </article>
        </div>

        <ol className="guided-demo__steps">
          {steps.map((step, index) => (
            <li className={`demo-step demo-step--${step.status}`} key={step.id}>
              <div className="demo-step__rail">
                <span>{String(index + 1).padStart(2, "0")}</span>
                <i aria-hidden="true" />
              </div>
              <div>
                <span className="demo-step__status">{stepStatusCopy[step.status]}</span>
                <strong>{step.title}</strong>
                <small>{step.detail}</small>
              </div>
            </li>
          ))}
        </ol>
      </div>

      <div className={`guided-demo__receipt ${result ? "guided-demo__receipt--ready" : ""}`} aria-live="polite">
        <p className="eyebrow">Concrete backend evidence</p>
        {result ? (
          <>
            <strong>The same stored trade arrived through both read paths.</strong>
            <p className="guided-demo__proof-note">
              This turns green only after the command completes and trade <code title={result.tradeId}>{shortId(result.tradeId)}</code> is found in REST and the live event stream.
            </p>
            <dl className="evidence-grid">
              <div>
                <dt>Public API</dt>
                <dd>HTTP {result.httpStatus ?? 202} accepted</dd>
              </div>
              <div>
                <dt>Command</dt>
                <dd title={result.commandId ?? undefined}>
                  {result.commandSequence == null ? shortId(result.commandId) : `#${result.commandSequence.toLocaleString()}`}
                </dd>
              </div>
              <div>
                <dt>Matching service</dt>
                <dd>{result.commandStatus === "rejected" ? "Rejected" : "Completed"}</dd>
              </div>
              <div>
                <dt>Stored trade</dt>
                <dd>#{result.tradeSequence.toLocaleString()}</dd>
              </div>
              <div>
                <dt>REST read-back</dt>
                <dd>{formatEvidenceTime(result.restObservedAt)}</dd>
              </div>
              <div>
                <dt>WebSocket event</dt>
                <dd>{result.websocketEventId == null ? "Same trade received" : `#${result.websocketEventId.toLocaleString()}`}</dd>
              </div>
            </dl>
            <div className="evidence-identities">
              <div className="evidence-identity">
                <span>Command ID</span>
                <code title={result.commandId ?? undefined}>{shortId(result.commandId)}</code>
              </div>
              <div className="evidence-identity">
                <span>Correlation ID</span>
                <code title={result.correlationId ?? undefined}>{shortId(result.correlationId)}</code>
              </div>
              <div className="evidence-identity">
                <span>Order ID</span>
                <code title={result.orderId ?? undefined}>{shortId(result.orderId)}</code>
              </div>
              <div className="evidence-identity">
                <span>Trade ID · REST = WebSocket</span>
                <code title={result.tradeId}>{result.tradeId}</code>
              </div>
            </div>
            <small>
              Completed end to end in {(result.durationMs / 1_000).toFixed(1)} s. The highlighted trade below came from this run.
            </small>
          </>
        ) : (
          <>
            <strong>No proof has been manufactured in the browser.</strong>
            <span>
              After you run the demo, this panel will show the real HTTP acceptance, command ID,
              stored trade ID, and WebSocket event that carried the same trade.
            </span>
            <div className="evidence-placeholder" aria-hidden="true">
              <i>HTTP</i><i>COMMAND</i><i>DATABASE</i><i>LIVE EVENT</i>
            </div>
          </>
        )}
      </div>
    </section>
  );
};
