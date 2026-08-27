import { formatMilliseconds, queueAssessment, sequenceAssessment } from "../diagnostics";
import type {
  ClientEvidence,
  ConnectionState,
  DiagnosticsSummary,
} from "../types";

interface DiagnosticsPanelProps {
  summary: DiagnosticsSummary | null;
  connection: ConnectionState;
  sequence: number;
  tradeCount: number;
  client: ClientEvidence;
}

const statusCopy: Record<ConnectionState, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Recovering",
  offline: "Offline",
};

const Diagnostic = ({ value, label, detail, tone = "neutral" }: {
  value: string;
  label: string;
  detail: string;
  tone?: "good" | "warn" | "neutral";
}) => (
  <div className={`diagnostic diagnostic--${tone}`}>
    <span>{label}</span>
    <strong>{value}</strong>
    <small>{detail}</small>
  </div>
);

export const DiagnosticsPanel = ({
  summary,
  connection,
  sequence,
  tradeCount,
  client,
}: DiagnosticsPanelProps) => {
  if (!summary) {
    return (
      <section className="diagnostics-panel" aria-labelledby="diagnostics-heading">
        <div className="diagnostics-panel__heading">
          <div><p className="eyebrow">Live evidence</p><h2 id="diagnostics-heading">Client-observed diagnostics</h2></div>
          <span className="source-chip">WebSocket fallback</span>
        </div>
        <p className="diagnostics-panel__note">
          Backend diagnostics are temporarily unavailable. These counters are measured by this
          browser from the real stream and automatically upgrade when the service responds again.
        </p>
        <div className="diagnostics-grid">
          <Diagnostic value={statusCopy[connection]} label="Stream" detail="Current WebSocket state" tone={connection === "live" ? "good" : "warn"} />
          <Diagnostic value={`#${sequence.toLocaleString()}`} label="Sequence" detail="Latest backend market state" />
          <Diagnostic value={client.messages.toLocaleString()} label="Messages" detail="Parsed in this browser session" />
          <Diagnostic value={tradeCount.toLocaleString()} label="Trades" detail="REST records merged with stream" />
          <Diagnostic value={client.duplicatesIgnored.toLocaleString()} label="Duplicates ignored" detail="Stale updates blocked in this session" tone="good" />
          <Diagnostic value={client.recoveredEvents.toLocaleString()} label="Recovered" detail={`${client.reconnects} reconnect attempts`} />
        </div>
      </section>
    );
  }

  const processorHealthy = summary.services.processor.status === "online";
  const sequenceHealthy = summary.market.sequence_integrity;
  return (
    <section className="diagnostics-panel" aria-labelledby="diagnostics-heading">
      <div className="diagnostics-panel__heading">
        <div><p className="eyebrow">Measured by the backend</p><h2 id="diagnostics-heading">System diagnostics</h2></div>
        <span className="source-chip source-chip--live">Live service data</span>
      </div>
      <p className="diagnostics-panel__note">
        These values come from the API, processor, command journal, market tables, and active streams.
        They refresh automatically and are not estimated in the browser.
      </p>
      <div className="diagnostics-grid">
        <Diagnostic value={summary.services.processor.status} label="Processor" detail={queueAssessment(summary)} tone={processorHealthy ? "good" : "warn"} />
        <Diagnostic value={summary.queue.depth.toLocaleString()} label="Queue depth" detail={`Oldest: ${formatMilliseconds(summary.queue.oldest_age_ms)}`} tone={summary.queue.depth === 0 ? "good" : "warn"} />
        <Diagnostic value={formatMilliseconds(summary.commands.latency_ms.p95)} label="P95 latency" detail={`P50 ${formatMilliseconds(summary.commands.latency_ms.p50)} · P99 ${formatMilliseconds(summary.commands.latency_ms.p99)}`} />
        <Diagnostic value={`${summary.commands.completed.toLocaleString()} / ${summary.commands.accepted.toLocaleString()}`} label="Completed" detail={`${summary.commands.rejected.toLocaleString()} rejected commands`} />
        <Diagnostic value={sequenceHealthy ? "Verified" : "Needs review"} label="Sequence integrity" detail={sequenceAssessment(summary)} tone={sequenceHealthy ? "good" : "warn"} />
        <Diagnostic value={summary.streams.connected.toLocaleString()} label="Live streams" detail={`${summary.streams.recovered_events} recovered · ${summary.streams.resyncs} resyncs`} />
      </div>
      <div className="diagnostics-panel__footer">
        <span>Market: {summary.market.orders.toLocaleString()} orders · {summary.market.trades.toLocaleString()} trades · {summary.market.events.toLocaleString()} events</span>
        <time dateTime={summary.generated_at}>Snapshot {new Date(summary.generated_at).toLocaleTimeString()}</time>
      </div>
    </section>
  );
};
