import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_WEALTH_PATH } from "../../app/routes/routerState";
import { WealthExplorationLandingPage } from "./WealthExplorationLandingPage";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function contextPayload() {
  return { pageContext: { market: "CN_A", tradeDate: "2026-08-21", prevTradeDate: "2026-08-20", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai", generatedAt: "2026-08-22T09:15:00+08:00", source: "explicit" } };
}

function majorIndicesPayload() {
  return {
    tradingDay: { tradeDate: "2026-08-21", market: "CN_A", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai" },
    pageStatus: { status: "READY", displayText: "已就绪" },
    majorIndices: { definition: { definitionKey: "major", version: "1", fixedCount: 10 }, rows: [] },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", DEFAULT_WEALTH_PATH);
});

describe("WealthExplorationLandingPage", () => {
  it("loads only shared context and tickers and renders two unselected entry cards", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("/wealth/market/context")) return jsonResponse(contextPayload());
      if (url.includes("/wealth/market/major-indices")) return jsonResponse(majorIndicesPayload());
      return jsonResponse({ message: "unexpected request" }, 404);
    }));

    render(<WealthExplorationLandingPage search="?market=CN_A&tradeDate=2026-08-22" />);

    await waitFor(() => expect(urls).toHaveLength(2));
    expect(urls.some((url) => url.includes("turnover-insight"))).toBe(false);
    expect(urls.some((url) => url.includes("sector-analysis"))).toBe(false);
    expect(screen.getByText("财势探查", { selector: ".current" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /成交额洞察/ })).not.toHaveClass("selected");
    expect(screen.getByRole("button", { name: /板块分析/ })).not.toHaveClass("selected");
  });

  it("navigates to a module only after its entry is selected", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/wealth/market/context")) return jsonResponse(contextPayload());
      if (url.includes("/wealth/market/major-indices")) return jsonResponse(majorIndicesPayload());
      return jsonResponse({ message: "unexpected request" }, 404);
    }));
    render(<WealthExplorationLandingPage />);

    fireEvent.click(screen.getByRole("button", { name: /板块分析/ }));
    expect(window.location.pathname).toBe("/wealth/exploration/sector-analysis/daily-insight");
  });
});
