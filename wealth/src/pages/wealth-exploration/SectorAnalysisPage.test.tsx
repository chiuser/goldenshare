import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  it("renders the real momentum contract with a full ranking and two linked SVG charts", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    const { container } = render(<SectorAnalysisPage method="momentum-ranking" search="?market=CN_A&tradeDate=2026-08-21" />);

    expect(screen.getByLabelText("动量排名加载中")).toBeInTheDocument();
    await screen.findByRole("table", { name: "行业动量完整排名" });
    await waitFor(() => expect(urls.filter((url) => url.includes("sector-analysis"))).toHaveLength(3));
    expect(screen.getByText("板块分析", { selector: ".current" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /板块分析/ })).toHaveClass("selected");
    expect(screen.getByRole("tab", { name: "动量排名" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("tab")).toHaveLength(5);
    const table = screen.getByRole("table", { name: "行业动量完整排名" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getAllByText("一级行业甲")).toHaveLength(2);
    expect(table.querySelectorAll(".momentum-missing-value, .momentum-percentile")).not.toHaveLength(0);
    expect(screen.getByText("2 个行业")).toBeInTheDocument();
    expect(screen.getByText("1 / 1", { selector: ".momentum-summary-metric strong" })).toBeInTheDocument();
    expect(container.querySelectorAll("canvas")).toHaveLength(0);
    expect(container.querySelectorAll(".momentum-chart-card svg")).toHaveLength(2);
    expect(screen.getByRole("img", { name: /1日区间涨跌幅历史趋势/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /历史强度排名趋势/ })).toBeInTheDocument();
    const dateOptions = within(screen.getByLabelText("分析日期")).getAllByRole("option");
    expect(dateOptions.map((option) => option.textContent)).toEqual([
      "按公共行情日期",
      "2026-08-19 · 完整 · 5/5",
      "2026-08-20 · 部分缺失 · 4/5",
      "2026-08-21 · 完整 · 5/5",
    ]);
  });

  it("keeps selection, direction, range, and drill-down in the frozen URL/request boundaries", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH}?tradeDate=2026-08-21`);
    const replaceState = vi.spyOn(window.history, "replaceState");
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    await screen.findByRole("table", { name: "行业动量完整排名" });
    expect(requestCount(urls, "/momentum/rankings")).toBe(1);
    expect(requestCount(urls, "/momentum/history")).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "选择一级行业乙" }));
    await waitFor(() => expect(window.location.search).toContain("sectorCode=BK1002.DC"));
    await waitFor(() => expect(requestCount(urls, "/momentum/history")).toBe(2));
    expect(requestCount(urls, "/momentum/rankings")).toBe(1);
    expect(replaceState.mock.calls.some((call) => String(call[2]).includes("sectorCode=BK1002.DC"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "跌幅榜" }));
    await waitFor(() => expect(requestCount(urls, "/momentum/rankings")).toBe(2));
    expect(requestCount(urls, "/momentum/history")).toBe(2);

    const rangeControl = screen.getByLabelText("历史显示范围");
    fireEvent.click(within(rangeControl).getByRole("button", { name: "30日" }));
    await waitFor(() => expect(requestCount(urls, "/momentum/history")).toBe(3));
    expect(requestCount(urls, "/momentum/rankings")).toBe(2);

    fireEvent.click(screen.getByRole("button", { name: "下钻一级行业甲" }));
    await waitFor(() => expect(window.location.search).toContain("scope=level1-children"));
    await waitFor(() => expect(requestCount(urls, "/momentum/rankings")).toBe(3));
    await waitFor(() => expect(requestCount(urls, "/momentum/history")).toBe(4));
    expect(screen.getByText("一级行业甲内二级行业")).toBeInTheDocument();
    replaceState.mockRestore();
  });

  it("supports all five comparison scopes and exposes parent selectors only where required", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH}?tradeDate=2026-08-21`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "行业动量完整排名" });

    fireEvent.click(screen.getByRole("button", { name: "二级总榜" }));
    await screen.findByText("二级行业总榜");
    expect(screen.queryByLabelText("一级行业")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "三级总榜" }));
    await screen.findByText("三级行业总榜");
    await screen.findByRole("table", { name: "三级行业成分股明细" });
    expect(requestCount(urls, "/momentum/members")).toBe(1);
    expect(document.querySelector(".momentum-left-workspace")).toBeInTheDocument();
    expect(document.querySelector(".momentum-ranking-panel-compact")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "一级内二级" }));
    await screen.findByText("一级行业甲内二级行业");
    expect(screen.queryByRole("table", { name: "三级行业成分股明细" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("一级行业")).toBeInTheDocument();
    expect(screen.queryByLabelText("二级行业")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "二级内三级" }));
    await screen.findByText("二级行业甲一内三级行业");
    expect(screen.getByLabelText("一级行业")).toBeInTheDocument();
    expect(screen.getByLabelText("二级行业")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /下钻三级行业甲一一/ })).not.toBeInTheDocument();
    await screen.findByRole("table", { name: "三级行业成分股明细" });
    expect(requestCount(urls, "/momentum/members")).toBe(2);
  });

  it("keeps member requests independent from range and refreshes them for direction", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState(
      {},
      "",
      `${WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH}?tradeDate=2026-08-21&scope=level3`,
    );
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    await screen.findByRole("table", { name: "三级行业成分股明细" });
    expect(requestCount(urls, "/momentum/members")).toBe(1);
    expect(screen.getByText("2 只 · 收盘 1 · 可算 1")).toBeInTheDocument();
    expect(screen.getByText("股票甲")).toBeInTheDocument();
    expect(screen.getByText("000001.SZ")).toBeInTheDocument();

    fireEvent.click(within(screen.getByLabelText("历史显示范围")).getByRole("button", { name: "60日" }));
    await waitFor(() => expect(requestCount(urls, "/momentum/history")).toBe(2));
    expect(requestCount(urls, "/momentum/members")).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "跌幅榜" }));
    await waitFor(() => expect(requestCount(urls, "/momentum/members")).toBe(2));
    expect(requestCount(urls, "/momentum/history")).toBe(2);
  });

  it("keeps member failure local and retries only the member request", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    let memberAttempt = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/momentum/members") && memberAttempt++ === 0) {
        urls.push(url);
        return jsonResponse(memberErrorPayload(new URL(url)));
      }
      return ready(input);
    }));
    render(<SectorAnalysisPage method="momentum-ranking" search="?tradeDate=2026-08-21&scope=level3" />);

    expect(await screen.findByText("成分股数据读取失败，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "行业动量完整排名" })).toBeInTheDocument();
    expect(document.querySelectorAll(".momentum-chart-card svg")).toHaveLength(2);
    const counts = {
      meta: requestCount(urls, "/sector-analysis/meta"),
      rankings: requestCount(urls, "/momentum/rankings"),
      history: requestCount(urls, "/momentum/history"),
    };
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "重试" }));
    await waitFor(() => expect(requestCount(urls, "/momentum/members")).toBe(2));
    expect(requestCount(urls, "/sector-analysis/meta")).toBe(counts.meta);
    expect(requestCount(urls, "/momentum/rankings")).toBe(counts.rankings);
    expect(requestCount(urls, "/momentum/history")).toBe(counts.history);
    expect(await screen.findByText("股票甲")).toBeInTheDocument();
  });

  it("reloads all sector facts after a member hierarchy-version conflict", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    let memberAttempt = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/momentum/members") && memberAttempt++ === 0) {
        urls.push(url);
        return jsonResponse(
          { code: "SA_MEMBER_FACT_MISMATCH", message: "行业分类已更新" },
          409,
        );
      }
      return ready(input);
    }));
    render(<SectorAnalysisPage method="momentum-ranking" search="?tradeDate=2026-08-21&scope=level3" />);

    await waitFor(() => expect(requestCount(urls, "/sector-analysis/meta")).toBe(2));
    await waitFor(() => expect(requestCount(urls, "/momentum/members")).toBe(2));
    expect(await screen.findByText("股票甲")).toBeInTheDocument();
  });

  it("drops a late member response after selecting another level-three industry", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    let resolveFirst!: (value: Response) => void;
    const firstMember = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const parsed = new URL(url);
      if (url.includes("/momentum/members")
          && parsed.searchParams.get("sectorCode") === "BK1201.DC") {
        urls.push(url);
        return firstMember;
      }
      return ready(input);
    }));
    window.history.replaceState(
      {},
      "",
      `${WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH}?tradeDate=2026-08-21&scope=level3`,
    );
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    await screen.findByRole("button", { name: "选择三级行业甲一二" });
    fireEvent.click(screen.getByRole("button", { name: "选择三级行业甲一二" }));
    expect(await screen.findByText("股票乙")).toBeInTheDocument();
    resolveFirst(jsonResponse(memberPayload(new URL(
      "http://localhost/api/v1/wealth/market/sector-analysis/momentum/members"
      + "?market=CN_A&tradeDate=2026-08-21&hierarchyVersion=2026-08-21-v1"
      + "&sectorCode=BK1201.DC&period=1&direction=GAINERS",
    ))));
    await waitFor(() => expect(screen.getByText("股票乙")).toBeInTheDocument());
    expect(screen.queryByText("股票甲")).not.toBeInTheDocument();
    expect(screen.getByText("三级行业甲一二成分股")).toBeInTheDocument();
  });

  it("keeps explicit PARTIAL dates in READY and names missing industry facts", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/momentum/rankings")) {
        urls.push(url);
        return jsonResponse(partialRankingsPayload(new URL(url)));
      }
      if (url.includes("/momentum/history")) {
        urls.push(url);
        return jsonResponse(partialHistoryPayload(new URL(url)));
      }
      return ready(input);
    }));
    render(<SectorAnalysisPage method="momentum-ranking" search="?tradeDate=2026-08-20" />);

    await screen.findByRole("table", { name: "行业动量完整排名" });
    expect(screen.getByText(/当前日期部分行业缺少数据：4\/5/)).toBeInTheDocument();
    expect(document.querySelectorAll(".momentum-chart-card svg")).toHaveLength(2);
    expect(screen.queryByText("当前条件下暂无可计算数据")).not.toBeInTheDocument();
  });

  it("rejects invalid URL syntax before any sector business request", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    render(<SectorAnalysisPage method="momentum-ranking" search="?period=15" />);

    expect(await screen.findByText("统计周期参数无效。")).toBeInTheDocument();
    await waitFor(() => expect(requestCount(urls, "/wealth/market/context")).toBe(1));
    expect(urls.some((url) => url.includes("sector-analysis"))).toBe(false);
  });

  it("waits for the matching public pageContext before requesting a newly selected date", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    let resolveContext!: (value: Response) => void;
    const pendingContext = new Promise<Response>((resolve) => { resolveContext = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const parsed = new URL(url);
      if (url.includes("/wealth/market/context") && parsed.searchParams.get("tradeDate") === "2026-08-20") {
        urls.push(url);
        return pendingContext;
      }
      if (url.includes("/momentum/rankings") && parsed.searchParams.get("tradeDate") === "2026-08-20") {
        urls.push(url);
        return jsonResponse(partialRankingsPayload(parsed));
      }
      if (url.includes("/momentum/history") && parsed.searchParams.get("tradeDate") === "2026-08-20") {
        urls.push(url);
        return jsonResponse(partialHistoryPayload(parsed));
      }
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH}?tradeDate=2026-08-21`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "行业动量完整排名" });
    expect(requestCount(urls, "/momentum/rankings")).toBe(1);

    fireEvent.change(screen.getByLabelText("分析日期"), { target: { value: "2026-08-20" } });
    await waitFor(() => expect(window.location.search).toContain("tradeDate=2026-08-20"));
    await waitFor(() => expect(requestCount(urls, "/wealth/market/context")).toBe(2));
    expect(requestCount(urls, "/momentum/rankings")).toBe(1);

    resolveContext(jsonResponse(contextPayload("2026-08-20")));
    await waitFor(() => expect(requestCount(urls, "/momentum/rankings")).toBe(2));
    expect(await screen.findByText(/当前日期部分行业缺少数据：4\/5/)).toBeInTheDocument();
  });

  it("drops a late response from an obsolete period", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    let resolveFive!: (value: Response) => void;
    const fiveResponse = new Promise<Response>((resolve) => { resolveFive = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/momentum/rankings") && new URL(url).searchParams.get("period") === "5") {
        urls.push(url);
        return fiveResponse;
      }
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH}?tradeDate=2026-08-21`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "行业动量完整排名" });

    fireEvent.click(screen.getByRole("button", { name: "5日" }));
    await waitFor(() => expect(window.location.search).toContain("period=5"));
    fireEvent.click(screen.getByRole("button", { name: "10日" }));
    await waitFor(() => expect(window.location.search).toContain("period=10"));
    await waitFor(() => expect(screen.getByText("10日", { selector: ".momentum-period-chip" })).toBeInTheDocument());
    resolveFive(jsonResponse(rankingsPayload(new URL("http://localhost?scope=LEVEL_1&period=5&direction=GAINERS&tradeDate=2026-08-21"))));
    await Promise.resolve();
    expect(screen.getByText("10日", { selector: ".momentum-period-chip" })).toBeInTheDocument();
    expect(screen.queryByText("5日", { selector: ".momentum-period-chip" })).not.toBeInTheDocument();
  });

  it("keeps delayed content visible and names the actual盘后 date", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/momentum/rankings")) {
        urls.push(url);
        return jsonResponse(delayedRankingsPayload(new URL(url)));
      }
      if (url.includes("/momentum/history")) {
        urls.push(url);
        return jsonResponse(delayedHistoryPayload(new URL(url)));
      }
      return ready(input);
    }));
    render(<SectorAnalysisPage method="momentum-ranking" />);

    await screen.findByRole("table", { name: "行业动量完整排名" });
    expect(screen.getByText(/当前展示 2026-08-20 盘后数据/)).toBeInTheDocument();
    expect(screen.getByText("数据更新中，当前展示上一交易日盘后数据")).toBeInTheDocument();
    expect(document.querySelectorAll(".momentum-chart-card svg")).toHaveLength(2);
  });

  it("shows EMPTY without requesting history for an explicitly missing date", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/momentum/rankings")) {
        urls.push(url);
        return jsonResponse(emptyRankingsPayload());
      }
      return ready(input);
    }));
    render(<SectorAnalysisPage method="momentum-ranking" search="?tradeDate=2026-08-20" />);

    expect(await screen.findByText("当前条件下暂无可计算数据")).toBeInTheDocument();
    expect(screen.getByText("所选交易日没有行业行情数据。")).toBeInTheDocument();
    expect(requestCount(urls, "/momentum/history")).toBe(0);
    expect(document.querySelectorAll(".momentum-chart-card svg")).toHaveLength(0);
  });

  it("retries only the failed ranking chain", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    let rankingAttempt = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/momentum/rankings") && rankingAttempt++ === 0) {
        urls.push(url);
        return jsonResponse({ code: "SA_QUERY_FAILED", message: "榜单查询失败" }, 500);
      }
      return ready(input);
    }));
    render(<SectorAnalysisPage method="momentum-ranking" search="?tradeDate=2026-08-21" />);

    expect(await screen.findByText("榜单查询失败")).toBeInTheDocument();
    expect(requestCount(urls, "/sector-analysis/meta")).toBe(1);
    expect(requestCount(urls, "/momentum/rankings")).toBe(1);
    expect(requestCount(urls, "/momentum/history")).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    await screen.findByRole("table", { name: "行业动量完整排名" });
    expect(requestCount(urls, "/sector-analysis/meta")).toBe(1);
    expect(requestCount(urls, "/momentum/rankings")).toBe(2);
    expect(requestCount(urls, "/momentum/history")).toBe(1);
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

function buildReadyFetch(urls: string[]) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    urls.push(url);
    if (url.includes("/wealth/market/context")) {
      return jsonResponse(contextPayload(new URL(url).searchParams.get("tradeDate") ?? "2026-08-21"));
    }
    if (url.includes("/wealth/market/major-indices")) return jsonResponse(majorIndicesPayload());
    if (url.includes("/sector-analysis/meta")) return jsonResponse(metaPayload());
    if (url.includes("/sector-analysis/momentum/rankings")) {
      return jsonResponse(rankingsPayload(new URL(url)));
    }
    if (url.includes("/sector-analysis/momentum/history")) return jsonResponse(historyPayload(new URL(url)));
    if (url.includes("/sector-analysis/momentum/members")) return jsonResponse(memberPayload(new URL(url)));
    return jsonResponse({ message: "unexpected request" }, 404);
  });
}

function contextPayload(tradeDate = "2026-08-21") {
  return {
    pageContext: {
      market: "CN_A",
      tradeDate,
      prevTradeDate: tradeDate === "2026-08-21" ? "2026-08-20" : "2026-08-19",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: "2026-08-22T09:15:00+08:00",
      source: "explicit",
    },
  };
}

function majorIndicesPayload() {
  return {
    tradingDay: { tradeDate: "2026-08-21", market: "CN_A", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai" },
    pageStatus: { status: "READY", displayText: "已就绪" },
    majorIndices: { definition: { definitionKey: "major", version: "1", fixedCount: 10 }, rows: [] },
  };
}

function hierarchyNodes() {
  return [
    { sectorCode: "BK1001.DC", sectorName: "一级行业甲", industryLevel: 1, parentSectorCode: null, parentSectorName: null, rootSectorCode: "BK1001.DC", rootSectorName: "一级行业甲", hierarchyPath: "一级行业甲", displayOrder: 1, isLeaf: false },
    { sectorCode: "BK1002.DC", sectorName: "一级行业乙", industryLevel: 1, parentSectorCode: null, parentSectorName: null, rootSectorCode: "BK1002.DC", rootSectorName: "一级行业乙", hierarchyPath: "一级行业乙", displayOrder: 2, isLeaf: false },
    { sectorCode: "BK1101.DC", sectorName: "二级行业甲一", industryLevel: 2, parentSectorCode: "BK1001.DC", parentSectorName: "一级行业甲", rootSectorCode: "BK1001.DC", rootSectorName: "一级行业甲", hierarchyPath: "一级行业甲/二级行业甲一", displayOrder: 3, isLeaf: false },
    { sectorCode: "BK1201.DC", sectorName: "三级行业甲一一", industryLevel: 3, parentSectorCode: "BK1101.DC", parentSectorName: "二级行业甲一", rootSectorCode: "BK1001.DC", rootSectorName: "一级行业甲", hierarchyPath: "一级行业甲/二级行业甲一/三级行业甲一一", displayOrder: 4, isLeaf: true },
    { sectorCode: "BK1202.DC", sectorName: "三级行业甲一二", industryLevel: 3, parentSectorCode: "BK1101.DC", parentSectorName: "二级行业甲一", rootSectorCode: "BK1001.DC", rootSectorName: "一级行业甲", hierarchyPath: "一级行业甲/二级行业甲一/三级行业甲一二", displayOrder: 5, isLeaf: true },
  ];
}

function metaPayload() {
  return {
    formula: {
      formulaKey: "sector-cross-sectional-momentum",
      formulaVersion: 1,
      periods: [1, 5, 10, 20, 30],
      historyRanges: [20, 30, 60],
      scopes: ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"],
      directions: ["GAINERS", "LOSERS"],
    },
    hierarchy: { hierarchyVersion: "2026-08-21-v1", publishedAt: "2026-08-21T20:30:00+08:00", nodes: hierarchyNodes() },
    coverageStartDate: "2026-08-19",
    coverageEndDate: "2026-08-21",
    tradeDates: [
      { tradeDate: "2026-08-19", availability: "COMPLETE", expectedSectorCount: 5, validSectorCount: 5 },
      { tradeDate: "2026-08-20", availability: "PARTIAL", expectedSectorCount: 5, validSectorCount: 4 },
      { tradeDate: "2026-08-21", availability: "COMPLETE", expectedSectorCount: 5, validSectorCount: 5 },
    ],
  };
}

function tradingDayPayload() {
  return {
    expectedTradeDate: "2026-08-21",
    observedTradeDate: "2026-08-21",
    expectedAvailability: "COMPLETE",
    expectedSectorCount: 5,
    expectedValidSectorCount: 5,
    observedAvailability: "COMPLETE",
    observedValidSectorCount: 5,
  };
}

function pageStatusPayload() {
  return { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-08-21T20:31:00+08:00" };
}

function rankingRows() {
  return [
    { listPosition: 1, strengthRank: 1, sectorCode: "BK1001.DC", sectorName: "一级行业甲", industryLevel: 1, parentSectorCode: null, parentSectorName: null, hierarchyPath: "一级行业甲", returnPct: 2.35, percentile: 100, canDrillDown: true },
    { listPosition: 2, strengthRank: null, sectorCode: "BK1002.DC", sectorName: "一级行业乙", industryLevel: 1, parentSectorCode: null, parentSectorName: null, hierarchyPath: "一级行业乙", returnPct: null, percentile: null, canDrillDown: true },
  ];
}

function rankingsPayload(url = new URL("http://localhost?scope=LEVEL_1&period=1&direction=GAINERS&tradeDate=2026-08-21")) {
  const direction = url.searchParams.get("direction") === "LOSERS" ? "LOSERS" : "GAINERS";
  const scope = url.searchParams.get("scope") ?? "LEVEL_1";
  const period = Number(url.searchParams.get("period") ?? 1);
  const level1Code = url.searchParams.get("level1Code");
  const level2Code = url.searchParams.get("level2Code");
  const sourceRows = rowsForScope(scope);
  const rows = direction === "GAINERS" ? sourceRows : [...sourceRows].reverse().map((row, index) => ({ ...row, listPosition: index + 1 }));
  return {
    status: "READY",
    tradingDay: tradingDayPayload(),
    pageStatus: pageStatusPayload(),
    ranking: {
      formulaKey: "sector-cross-sectional-momentum",
      formulaVersion: 1,
      hierarchyVersion: "2026-08-21-v1",
      scope,
      period,
      direction,
      parentSelection: {
        level1Code: scope === "LEVEL_1_CHILDREN" || scope === "LEVEL_2_CHILDREN" ? level1Code : null,
        level1Name: scope === "LEVEL_1_CHILDREN" || scope === "LEVEL_2_CHILDREN" ? "一级行业甲" : null,
        level2Code: scope === "LEVEL_2_CHILDREN" ? level2Code : null,
        level2Name: scope === "LEVEL_2_CHILDREN" ? "二级行业甲一" : null,
      },
      totalCount: rows.length,
      calculableCount: rows.filter((row) => row.returnPct !== null).length,
      rows,
    },
    message: null,
    exceptionCode: null,
  };
}

function rowsForScope(scope: string) {
  if (scope === "LEVEL_1") return rankingRows();
  if (scope === "LEVEL_2" || scope === "LEVEL_1_CHILDREN") {
    return [{ listPosition: 1, strengthRank: 1, sectorCode: "BK1101.DC", sectorName: "二级行业甲一", industryLevel: 2, parentSectorCode: "BK1001.DC", parentSectorName: "一级行业甲", hierarchyPath: "一级行业甲/二级行业甲一", returnPct: 1.8, percentile: 100, canDrillDown: true }];
  }
  return [
    { listPosition: 1, strengthRank: 1, sectorCode: "BK1201.DC", sectorName: "三级行业甲一一", industryLevel: 3, parentSectorCode: "BK1101.DC", parentSectorName: "二级行业甲一", hierarchyPath: "一级行业甲/二级行业甲一/三级行业甲一一", returnPct: 1.2, percentile: 100, canDrillDown: false },
    { listPosition: 2, strengthRank: 2, sectorCode: "BK1202.DC", sectorName: "三级行业甲一二", industryLevel: 3, parentSectorCode: "BK1101.DC", parentSectorName: "二级行业甲一", hierarchyPath: "一级行业甲/二级行业甲一/三级行业甲一二", returnPct: 0.8, percentile: 0, canDrillDown: false },
  ];
}

function historyPayload(url = new URL("http://localhost?scope=LEVEL_1&period=1&historyRange=20&sectorCode=BK1001.DC&tradeDate=2026-08-21")) {
  const sectorCode = url.searchParams.get("sectorCode") ?? "BK1001.DC";
  const row = hierarchyNodes().find((item) => item.sectorCode === sectorCode) ?? hierarchyNodes()[0]!;
  const scope = url.searchParams.get("scope") ?? "LEVEL_1";
  return {
    status: "READY",
    tradingDay: tradingDayPayload(),
    pageStatus: pageStatusPayload(),
    detail: {
      sectorCode: row.sectorCode,
      sectorName: row.sectorName,
      industryLevel: row.industryLevel,
      hierarchyPath: row.hierarchyPath,
      scopeTitle: scopeTitle(scope),
      returnPct: 2.35,
      percentile: 100,
      currentScopeStrengthRank: 1,
      currentScopeCalculableCount: 1,
      currentScopeTotalCount: 2,
      globalLevelStrengthRank: 1,
      globalLevelCalculableCount: 1,
      globalLevelTotalCount: 2,
      parentStrengthRank: row.industryLevel === 1 ? null : 1,
      parentCalculableCount: row.industryLevel === 1 ? null : 1,
      parentTotalCount: row.industryLevel === 1 ? null : 1,
      formulaKey: "sector-cross-sectional-momentum",
      formulaVersion: 1,
      hierarchyVersion: "2026-08-21-v1",
    },
    rollingReturns: [
      { tradeDate: "2026-08-19", returnPct: 0.8 },
      { tradeDate: "2026-08-20", returnPct: null },
      { tradeDate: "2026-08-21", returnPct: 2.35 },
    ],
    historicalRanks: [
      { tradeDate: "2026-08-19", strengthRank: 2, calculableCount: 2, totalCount: 2, percentile: 0 },
      { tradeDate: "2026-08-20", strengthRank: null, calculableCount: 1, totalCount: 2, percentile: null },
      { tradeDate: "2026-08-21", strengthRank: 1, calculableCount: 1, totalCount: 2, percentile: 100 },
    ],
    message: null,
    exceptionCode: null,
  };
}

function memberPayload(url: URL) {
  const direction = url.searchParams.get("direction") === "LOSERS" ? "LOSERS" : "GAINERS";
  const sectorCode = url.searchParams.get("sectorCode") ?? "BK1201.DC";
  const isSecond = sectorCode === "BK1202.DC";
  const rows = isSecond
    ? [{ stockName: "股票乙", stockCode: "000002.SZ", close: 12, returnPct: 1.2 }]
    : [
        { stockName: "股票甲", stockCode: "000001.SZ", close: null, returnPct: 2.35 },
        { stockName: null, stockCode: "200001.SZ", close: 8, returnPct: null },
      ];
  return {
    status: "READY",
    message: null,
    exceptionCode: null,
    tradeDate: url.searchParams.get("tradeDate") ?? "2026-08-21",
    hierarchyVersion: url.searchParams.get("hierarchyVersion") ?? "2026-08-21-v1",
    sectorCode,
    sectorName: isSecond ? "三级行业甲一二" : "三级行业甲一一",
    period: Number(url.searchParams.get("period") ?? 1),
    direction,
    totalMemberCount: rows.length,
    closeAvailableCount: rows.filter((row) => row.close !== null).length,
    calculableCount: rows.filter((row) => row.returnPct !== null).length,
    rows,
  };
}

function memberErrorPayload(url: URL) {
  return {
    status: "ERROR",
    message: "成分股数据读取失败，请稍后重试。",
    exceptionCode: "SA_MEMBER_QUERY_FAILED",
    tradeDate: url.searchParams.get("tradeDate") ?? "2026-08-21",
    hierarchyVersion: url.searchParams.get("hierarchyVersion") ?? "2026-08-21-v1",
    sectorCode: url.searchParams.get("sectorCode") ?? "BK1201.DC",
    sectorName: "三级行业甲一一",
    period: Number(url.searchParams.get("period") ?? 1),
    direction: url.searchParams.get("direction") === "LOSERS" ? "LOSERS" : "GAINERS",
    totalMemberCount: 0,
    closeAvailableCount: 0,
    calculableCount: 0,
    rows: [],
  };
}

function scopeTitle(scope: string) {
  if (scope === "LEVEL_1") return "一级行业总榜";
  if (scope === "LEVEL_2") return "二级行业总榜";
  if (scope === "LEVEL_3") return "三级行业总榜";
  if (scope === "LEVEL_1_CHILDREN") return "一级行业甲内二级行业";
  return "二级行业甲一内三级行业";
}

function requestCount(urls: string[], fragment: string) {
  return urls.filter((url) => url.includes(fragment)).length;
}

function delayedTradingDayPayload() {
  return {
    expectedTradeDate: "2026-08-21",
    observedTradeDate: "2026-08-20",
    expectedAvailability: "PARTIAL",
    expectedSectorCount: 5,
    expectedValidSectorCount: 4,
    observedAvailability: "COMPLETE",
    observedValidSectorCount: 5,
  };
}

function delayedRankingsPayload(url: URL) {
  const payload = rankingsPayload(url);
  return {
    ...payload,
    status: "DELAYED",
    tradingDay: delayedTradingDayPayload(),
    pageStatus: { status: "DELAYED", displayText: "数据更新中，当前展示上一交易日盘后数据", asOfTime: "2026-08-21T19:30:00+08:00" },
    exceptionCode: "SA_SOURCE_DELAYED",
  };
}

function delayedHistoryPayload(url: URL) {
  const payload = historyPayload(url);
  return {
    ...payload,
    status: "DELAYED",
    tradingDay: delayedTradingDayPayload(),
    pageStatus: { status: "DELAYED", displayText: "数据更新中，当前展示上一交易日盘后数据", asOfTime: "2026-08-21T19:30:00+08:00" },
    exceptionCode: "SA_SOURCE_DELAYED",
  };
}

function emptyRankingsPayload() {
  return {
    status: "EMPTY",
    tradingDay: {
      expectedTradeDate: "2026-08-20",
      observedTradeDate: null,
      expectedAvailability: "MISSING",
      expectedSectorCount: 5,
      expectedValidSectorCount: 0,
      observedAvailability: null,
      observedValidSectorCount: 0,
    },
    pageStatus: { status: "EMPTY", displayText: "当前日期暂无数据", asOfTime: "2026-08-20T20:00:00+08:00" },
    ranking: null,
    message: "所选交易日没有行业行情数据。",
    exceptionCode: "SA_SOURCE_EMPTY",
  };
}

function partialTradingDayPayload() {
  return {
    expectedTradeDate: "2026-08-20",
    observedTradeDate: "2026-08-20",
    expectedAvailability: "PARTIAL",
    expectedSectorCount: 5,
    expectedValidSectorCount: 4,
    observedAvailability: "PARTIAL",
    observedValidSectorCount: 4,
  };
}

function partialRankingsPayload(url: URL) {
  const payload = rankingsPayload(url);
  return { ...payload, tradingDay: partialTradingDayPayload() };
}

function partialHistoryPayload(url: URL) {
  const payload = historyPayload(url);
  return { ...payload, tradingDay: partialTradingDayPayload() };
}
