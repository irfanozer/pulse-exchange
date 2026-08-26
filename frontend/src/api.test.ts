import { describe, expect, it } from "vitest";
import { marketStreamPath } from "./api";

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
