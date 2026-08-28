import type { DiagnosticsSummary } from "./types";

export const formatMilliseconds = (value: number | null): string => {
  if (value === null || !Number.isFinite(value)) return "No samples";
  if (value < 1_000) return `${Math.round(value)} ms`;
  return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} s`;
};

export const queueAssessment = (summary: DiagnosticsSummary): string => {
  if (summary.services.processor.status === "offline") return "Matching service offline";
  if (summary.services.processor.status === "stale") return "Matching-service heartbeat stale";
  if (summary.queue.depth === 0) return "Queue drained";
  return `${summary.queue.depth.toLocaleString()} command${summary.queue.depth === 1 ? "" : "s"} waiting`;
};

export const sequenceAssessment = (summary: DiagnosticsSummary): string =>
  summary.market.sequence_integrity
    ? "Committed commands and events agree"
    : "Committed sequence state needs review";
