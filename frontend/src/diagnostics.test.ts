import { describe, expect, it } from "vitest";
import { formatMilliseconds, queueAssessment, sequenceAssessment } from "./diagnostics";
import type { DiagnosticsSummary } from "./types";

const summary = (overrides: Partial<DiagnosticsSummary> = {}): DiagnosticsSummary => ({
  generated_at: "2026-08-27T12:00:00Z",
  services: {
    api: { status: "online" },
    processor: { status: "online", last_heartbeat_at: "2026-08-27T12:00:00Z", age_ms: 12 },
  },
  queue: { depth: 0, oldest_age_ms: null },
  commands: { accepted: 10, completed: 10, rejected: 0, latency_ms: { p50: 5, p95: 9, p99: 11 } },
  market: { orders: 8, trades: 2, events: 10, latest_sequence: 10, sequence_integrity: true },
  streams: { connected: 1, recovered_events: 0, resyncs: 0 },
  ...overrides,
});

describe("diagnostics presentation", () => {
  it("formats short, long, and missing durations", () => {
    expect(formatMilliseconds(48.7)).toBe("49 ms");
    expect(formatMilliseconds(1_250)).toBe("1.3 s");
    expect(formatMilliseconds(null)).toBe("No samples");
  });

  it("prioritizes processor health over queue depth", () => {
    expect(queueAssessment(summary())).toBe("Queue drained");
    expect(queueAssessment(summary({ queue: { depth: 3, oldest_age_ms: 50 } }))).toBe(
      "3 commands waiting",
    );
    expect(queueAssessment(summary({
      services: {
        api: { status: "online" },
        processor: { status: "offline", last_heartbeat_at: null, age_ms: null },
      },
    }))).toBe("Matching service offline");
  });

  it("states the persisted sequence integrity result plainly", () => {
    expect(sequenceAssessment(summary())).toBe("Committed commands and events agree");
    expect(sequenceAssessment(summary({
      market: { orders: 8, trades: 2, events: 10, latest_sequence: 10, sequence_integrity: false },
    }))).toBe("Committed sequence state needs review");
  });
});
