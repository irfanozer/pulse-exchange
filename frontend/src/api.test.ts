import { afterEach, describe, expect, it, vi } from "vitest";
import { getCommand, getDiagnosticsSummary, marketStreamPath, placeOrder } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("durable market stream URL", () => {
  it("omits a cursor on the initial subscription", () => {
    expect(marketStreamPath("NOVA")).toBe("/api/v1/markets/NOVA/stream");
  });

  it("communicates the last received event id when reconnecting", () => {
    expect(marketStreamPath("ORBIT", 47)).toBe(
      "/api/v1/markets/ORBIT/stream?after_event_id=47",
    );
  });
});

describe("diagnostics API", () => {
  it("reads the backend summary through the versioned API route", async () => {
    const payload = {
      generated_at: "2026-08-27T12:00:00Z",
      services: { api: { status: "online" }, processor: { status: "online", last_heartbeat_at: null } },
      queue: { depth: 0, oldest_age_ms: null },
      commands: { accepted: 1, completed: 1, rejected: 0, latency_ms: { p50: 2, p95: 3, p99: 4 } },
      market: { orders: 1, trades: 0, events: 1, latest_sequence: 1, sequence_integrity: true },
      streams: { connected: 1, recovered_events: 0, resyncs: 0 },
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getDiagnosticsSummary()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/diagnostics/summary", undefined);
  });
});

describe("durable command receipts", () => {
  it("keeps both command and order identities from an accepted order", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => "idempotency-test-key" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            command_id: "command-123",
            sequence: 42,
            order_id: "order-456",
          }),
          { status: 202 },
        ),
      ),
    );

    await expect(
      placeOrder({ symbol: "NOVA", side: "buy", price: 101, quantity: 2 }),
    ).resolves.toMatchObject({
      commandId: "command-123",
      commandSequence: 42,
      orderId: "order-456",
    });
  });

  it("polls one accepted command by its encoded identity", async () => {
    const payload = {
      command_id: "command/123",
      correlation_id: "request-1",
      sequence: 42,
      status: "completed",
      error_message: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getCommand("command/123")).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/commands/command%2F123", undefined);
  });
});
