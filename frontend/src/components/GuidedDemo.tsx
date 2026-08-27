import type { GuidedDemoResult, GuidedDemoStep } from "../types";

interface GuidedDemoProps {
  steps: GuidedDemoStep[];
  result: GuidedDemoResult | null;
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

export const GuidedDemo = ({ steps, result, running, canRun, onRun }: GuidedDemoProps) => (
  <section className="guided-demo" aria-labelledby="guided-demo-heading">
    <div className="guided-demo__intro">
      <div>
        <p className="eyebrow">Recommended first look</p>
        <h2 id="guided-demo-heading">Prove the engine in one run.</h2>
      </div>
      <p>
        This sends five real orders through the public API, waits for the ordered processor,
        and confirms a newly persisted trade. Nothing below is preloaded UI data.
      </p>
      <button className="guided-demo__run" type="button" onClick={onRun} disabled={!canRun}>
        <span>{running ? "Following the live run..." : result ? "Run another proof" : "Run the guided proof"}</span>
        <span aria-hidden="true">{running ? "•••" : "→"}</span>
      </button>
      {!canRun && !running && (
        <small className="guided-demo__hint">Wait for the live WebSocket connection before starting.</small>
      )}
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

    <div className={`guided-demo__receipt ${result ? "guided-demo__receipt--ready" : ""}`}>
      <p className="eyebrow">Run receipt</p>
      {result ? (
        <>
          <strong>Trade #{result.tradeSequence.toLocaleString()} verified from backend state.</strong>
          <dl>
            <div><dt>REST accepted</dt><dd>{result.requestsAccepted} commands</dd></div>
            <div><dt>Sequence</dt><dd>+{result.endingSequence - result.startingSequence}</dd></div>
            <div><dt>Matched</dt><dd>{result.quantity} @ {result.price}</dd></div>
            <div><dt>Completed in</dt><dd>{(result.durationMs / 1_000).toFixed(1)} s</dd></div>
          </dl>
          <small>Trade ID {result.tradeId}</small>
        </>
      ) : (
        <>
          <strong>The receipt appears only after a new trade is read back.</strong>
          <span>It will include command count, sequence advance, match details, and duration.</span>
        </>
      )}
    </div>
  </section>
);
