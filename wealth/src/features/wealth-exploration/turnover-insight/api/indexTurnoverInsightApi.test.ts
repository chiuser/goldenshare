import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildIndexTurnoverInsightUrl,
  fetchIndexTurnoverInsight,
} from "./indexTurnoverInsightApi";

afterEach(() => vi.unstubAllGlobals());

describe("indexTurnoverInsightApi", () => {
  it("builds one fixed batch URL without codes or frequency", () => {
    const url = new URL(buildIndexTurnoverInsightUrl({
      market: "CN_A",
      tradeDate: "2026-09-01",
      debug: 1,
    }));

    expect(url.pathname).toBe("/api/v1/wealth/market/turnover-insight/indices");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      market: "CN_A",
      tradeDate: "2026-09-01",
      debug: "1",
    });
  });

  it("preserves HTTP status so only endpoint 404 can mean unsupported", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ code: "ITI_SOURCE_NOT_READY", message: "not ready" }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    )));

    await expect(fetchIndexTurnoverInsight({ market: "CN_A", tradeDate: "2026-09-01" }))
      .rejects.toMatchObject({
        status: 503,
        code: "ITI_SOURCE_NOT_READY",
        message: "not ready",
      });
  });
});
