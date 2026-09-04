import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../../features/auth/model/AuthProvider";
import { WealthRouter } from "../../app/routes/WealthRouter";
import { insightJson, insightMeta, insightSnapshot } from "../../features/wealth-exploration/sector-analysis/daily-insight/testFixtures";
import { SectorAnalysisPage } from "./SectorAnalysisPage";

const PATH = "/wealth/exploration/sector-analysis/daily-insight";
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); });
function fetchRoutes() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/context")) return insightJson({ pageContext: { market: "CN_A", tradeDate: url.searchParams.get("tradeDate") ?? "2025-08-25", prevTradeDate: "2025-08-22", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai", generatedAt: "2025-08-25T21:00:00Z", source: "default" } });
    if (url.pathname.endsWith("/major-indices")) return insightJson({ pageStatus: { status: "READY", displayText: "已就绪" }, majorIndices: { rows: [] } });
    if (url.pathname.endsWith("/daily-insight/meta")) return insightJson(insightMeta());
    if (url.pathname.endsWith("/daily-insight/snapshot")) return insightJson(insightSnapshot(Number(url.searchParams.get("industryLevel")) as 1 | 2 | 3));
    return insightJson({}, 500);
  });
}
describe("Daily Insight routing and inactive-method isolation", () => {
  it("direct URL restores level/date, uses only two daily endpoints, and ordinary navigation keeps only date", async () => {
    const fetch = fetchRoutes(); vi.stubGlobal("fetch", fetch);
    window.history.replaceState({}, "", `${PATH}?tradeDate=2025-08-25&level=3`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "头部上涨完整列表" });
    expect(screen.getAllByRole("tab")).toHaveLength(6);
    const dailyCalls = fetch.mock.calls.map(([url]) => String(url)).filter((url) => url.includes("sector-analysis"));
    expect(dailyCalls).toHaveLength(2); expect(dailyCalls.every((url) => url.includes("daily-insight/"))).toBe(true);
    expect(screen.getByRole("button", { name: "三级行业" })).toHaveAttribute("aria-pressed", "true");
    const tables = screen.getAllByRole("table"); expect(tables).toHaveLength(4);
    fireEvent.click(screen.getByRole("tab", { name: "相对轮动" }));
    expect(window.location.pathname).toBe("/wealth/exploration/sector-analysis/relative-rotation");
    expect(window.location.search).toBe("?tradeDate=2025-08-25");
    expect(screen.queryByRole("table", { name: "头部上涨完整列表" })).not.toBeInTheDocument();
  });
  it("industry navigation preserves the fact date, selected global level and sector", async () => {
    vi.stubGlobal("fetch", fetchRoutes()); window.history.replaceState({}, "", `${PATH}?level=2`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    const table = await screen.findByRole("table", { name: "头部上涨完整列表" });
    fireEvent.click(within(table).getByRole("button", { name: "通信网络设备及器件" }));
    expect(window.location.pathname).toBe("/wealth/exploration/sector-analysis/momentum-ranking");
    expect(Object.fromEntries(new URLSearchParams(window.location.search))).toEqual({ tradeDate: "2025-08-25", scope: "level2", period: "20", sectorCode: "BK1000.DC" });
  });
  it.each(["momentum-ranking", "dual-momentum", "relative-rotation", "member-breadth", "price-volume"] as const)("%s does not mount or fetch daily insight", async (method) => {
    const fetch = fetchRoutes(); vi.stubGlobal("fetch", fetch);
    render(<SectorAnalysisPage method={method} search="?tradeDate=2025-08-25" />);
    await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).includes("sector-analysis"))).toBe(true));
    expect(fetch.mock.calls.some(([url]) => String(url).includes("daily-insight"))).toBe(false);
    expect(document.querySelector(".daily-insight-workspace")).not.toBeInTheDocument();
  });
  it("unknown daily subpath is not mistaken for the daily route", async () => {
    const { resolveWealthExplorationRoute } = await import("../../app/routes/routerState");
    expect(resolveWealthExplorationRoute(`${PATH}/other`)).toEqual({ kind: "not-exploration" });
  });
});
