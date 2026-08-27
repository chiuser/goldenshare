import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../features/auth/model/AuthProvider";
import { WealthRouter } from "../../app/routes/WealthRouter";
import {
  WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH,
  WEALTH_EXPLORATION_SECTOR_PATH,
} from "../../app/routes/routerState";
import { SectorAnalysisPage } from "./SectorAnalysisPage";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH);
});

describe("SectorAnalysisPage", () => {
  it("renders the stable shell and method bar without requesting sector data", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("/wealth/market/context")) {
        return jsonResponse({ pageContext: { market: "CN_A", tradeDate: "2026-08-21", prevTradeDate: "2026-08-20", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai", generatedAt: "2026-08-22T09:15:00+08:00", source: "explicit" } });
      }
      if (url.includes("/wealth/market/major-indices")) {
        return jsonResponse({ tradingDay: { tradeDate: "2026-08-21", market: "CN_A", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai" }, pageStatus: { status: "READY", displayText: "已就绪" }, majorIndices: { definition: { definitionKey: "major", version: "1", fixedCount: 10 }, rows: [] } });
      }
      return jsonResponse({ message: "unexpected request" }, 404);
    }));
    const { container } = render(<SectorAnalysisPage search="?market=CN_A&tradeDate=2026-08-21" />);

    await waitFor(() => expect(urls).toHaveLength(2));
    expect(urls.some((url) => url.includes("sector-analysis"))).toBe(false);
    expect(screen.getByText("板块分析", { selector: ".current" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /板块分析/ })).toHaveClass("selected");
    expect(screen.getByRole("tab", { name: "动量排名" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("tab")).toHaveLength(5);
    expect(container.querySelectorAll("canvas, svg")).toHaveLength(0);
  });

  it("keeps URL and active method unchanged when an unavailable method is selected", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ message: "unused" }, 500)));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH}?tradeDate=2026-08-21`);
    render(<SectorAnalysisPage search="?tradeDate=2026-08-21" />);

    ["双动量", "相对轮动", "成员广度", "量价分布"].forEach((label) => {
      fireEvent.click(screen.getByRole("tab", { name: label }));
      expect(screen.getByText("待建设", { selector: "#toast" })).toBeInTheDocument();
    });
    expect(window.location.pathname).toBe(WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH);
    expect(window.location.search).toBe("?tradeDate=2026-08-21");
    expect(screen.getByRole("tab", { name: "动量排名" })).toHaveAttribute("aria-pressed", "true");
  });

  it("replaces the sector root with the momentum route and preserves its query", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ message: "unused" }, 500)));
    window.localStorage.setItem("wealth.auth.access-token", "mock-token");
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_PATH}?tradeDate=2026-08-21&scope=level1`);
    const replaceState = vi.spyOn(window.history, "replaceState");

    render(
      <AuthProvider>
        <WealthRouter />
      </AuthProvider>,
    );

    await waitFor(() => expect(window.location.pathname).toBe(WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH));
    expect(window.location.search).toBe("?tradeDate=2026-08-21&scope=level1");
    expect(replaceState).toHaveBeenCalledWith(
      expect.anything(),
      "",
      `${WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH}?tradeDate=2026-08-21&scope=level1`,
    );
  });
});
