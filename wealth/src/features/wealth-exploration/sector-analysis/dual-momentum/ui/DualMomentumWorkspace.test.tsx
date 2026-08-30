import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WealthRouter } from "../../../../../app/routes/WealthRouter";
import { WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH } from "../../../../../app/routes/routerState";
import { AuthProvider } from "../../../../auth/model/AuthProvider";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.clear();
  window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH);
});

describe("DualMomentumWorkspace", () => {
  it("mounts only the dual-momentum controller on its exact route", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildDualReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    expect(screen.getByLabelText("双动量加载中")).toBeInTheDocument();
    await screen.findByRole("table", { name: "双动量行业完整结果" });
    expect(screen.getByRole("tab", { name: "双动量" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("tab", { name: "动量排名" })).toHaveAttribute("aria-pressed", "false");
    expect(requestCount(urls, "/dual-momentum/meta")).toBe(1);
    expect(requestCount(urls, "/dual-momentum/results")).toBe(1);
    expect(urls.some((url) => /\/momentum\/(rankings|history|members)/.test(url))).toBe(false);
    expect(screen.getByRole("img", { name: "行业双动量二维分布图" })).toBeInTheDocument();
  });

  it("navigates between released methods and keeps only shared query state", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildDualReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?debug=1&tradeDate=2026-08-27&period=30&threshold=90&resultView=all`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "双动量行业完整结果" });

    fireEvent.click(screen.getByRole("tab", { name: "动量排名" }));
    await waitFor(() => expect(window.location.pathname).toBe("/wealth/exploration/sector-analysis/momentum-ranking"));
    expect(window.location.search).toBe("?debug=1&tradeDate=2026-08-27");
    expect(screen.getByRole("tab", { name: "动量排名" })).toHaveAttribute("aria-pressed", "true");
  });

  it("navigates to the released price-volume method with only its shared trade date", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildDualReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "双动量行业完整结果" });
    fireEvent.click(screen.getByRole("tab", { name: "量价分布" }));
    await waitFor(() => expect(window.location.pathname).toBe("/wealth/exploration/sector-analysis/price-volume"));
    expect(window.location.search).toBe("?tradeDate=2026-08-27");
    expect(screen.getByRole("tab", { name: "量价分布" })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelectorAll(".dual-scatter-svg")).toHaveLength(0);
  });

  it("keeps result view, selection, sorting and enlarge local with zero requests", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildDualReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "双动量行业完整结果" });
    const count = requestCount(urls, "/dual-momentum/results");

    fireEvent.click(screen.getByRole("button", { name: "全部行业" }));
    expect(await screen.findByRole("button", { name: /选择通信/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /选择通信/ }));
    await waitFor(() => expect(window.location.search).toContain("sectorCode=BK1002.DC"));
    expect(screen.getByLabelText("通信双动量摘要")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("columnheader", { name: /按区间涨跌幅排序/ }));
    const rows = within(screen.getByRole("table", { name: "双动量行业完整结果" })).getAllByRole("row");
    expect(rows.at(-1)).toHaveTextContent("房地产");
    const expandButton = screen.getByRole("button", { name: "放大双动量分布图" });
    fireEvent.click(expandButton);
    expect(screen.getByRole("dialog", { name: "放大的行业双动量分布图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭放大图" })).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(expandButton).toHaveFocus());
    expect(requestCount(urls, "/dual-momentum/results")).toBe(count);
  });

  it("requests all five scopes with only their active parent facts", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildDualReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "双动量行业完整结果" });

    fireEvent.click(screen.getByRole("button", { name: "二级总榜" }));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("scope")).toBe("LEVEL_2"));
    await waitFor(() => expect(screen.getByRole("button", { name: "二级总榜" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.click(screen.getByRole("button", { name: "全部行业" }));
    expect((await screen.findAllByText("样本不足")).length).toBeGreaterThan(0);
    expect(lastResultsUrl(urls).searchParams.has("level1Code")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "三级总榜" }));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("scope")).toBe("LEVEL_3"));
    await waitFor(() => expect(screen.getByRole("button", { name: "三级总榜" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.click(screen.getByRole("button", { name: "一级内二级" }));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("scope")).toBe("LEVEL_1_CHILDREN"));
    await waitFor(() => expect(screen.getByRole("button", { name: "一级内二级" })).toHaveAttribute("aria-pressed", "true"));
    expect(lastResultsUrl(urls).searchParams.get("level1Code")).toBe("BK1001.DC");
    expect(lastResultsUrl(urls).searchParams.has("level2Code")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "二级内三级" }));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("scope")).toBe("LEVEL_2_CHILDREN"));
    await waitFor(() => expect(screen.getByRole("button", { name: "二级内三级" })).toHaveAttribute("aria-pressed", "true"));
    expect(lastResultsUrl(urls).searchParams.get("level1Code")).toBe("BK1001.DC");
    expect(lastResultsUrl(urls).searchParams.get("level2Code")).toBe("BK1101.DC");
  });

  it("renders no-qualified, partial, missing-coordinate and small-group as Ready content states", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildDualReadyFetch(urls, (url) => {
      const payload = resultsPayload(url);
      payload.analysis.items = payload.analysis.items.map((row: any) => row.qualificationStatus === "QUALIFIED"
        ? { ...row, relativeStatus: "NOT_LEADING", qualificationStatus: "NOT_QUALIFIED", displayStatus: "UP_NOT_LEADING" }
        : row);
      payload.analysis.qualifiedCount = 0;
      payload.tradingDay.expectedAvailability = "PARTIAL";
      payload.tradingDay.expectedValidSectorCount = 3;
      payload.tradingDay.observedAvailability = "PARTIAL";
      payload.tradingDay.observedValidSectorCount = 3;
      return payload;
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    expect(await screen.findByText("当前没有符合条件的行业")).toBeInTheDocument();
    expect(screen.getByText("部分数据 3/4")).toBeInTheDocument();
    expect(document.querySelectorAll(".dual-scatter-point")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "查看全部行业" }));
    fireEvent.click(await screen.findByRole("button", { name: /选择房地产/ }));
    expect(screen.getByText("当前行业坐标不可计算")).toBeInTheDocument();
    expect(document.querySelectorAll(".dual-scatter-point")).toHaveLength(3);
  });

  it("shows delayed content and keeps Empty and Error as main states", async () => {
    const urls: string[] = [];
    let mode: "delayed" | "empty" | "error" = "delayed";
    vi.stubGlobal("fetch", buildDualReadyFetch(urls, (url) => {
      const payload = resultsPayload(url);
      if (mode === "delayed") {
        payload.status = "DELAYED";
        payload.pageStatus.status = "DELAYED";
        payload.pageStatus.displayText = "数据更新中";
        payload.tradingDay.observedTradeDate = "2026-08-26";
        payload.tradingDay.expectedAvailability = "MISSING";
        payload.tradingDay.expectedValidSectorCount = 0;
        payload.tradingDay.observedAvailability = "COMPLETE";
        payload.exceptionCode = "SA_SOURCE_DELAYED";
        return payload;
      }
      payload.status = mode === "empty" ? "EMPTY" : "ERROR";
      payload.pageStatus.status = payload.status;
      payload.analysis = null;
      payload.message = mode === "empty" ? "所选交易日暂无数据。" : "数据读取失败。";
      payload.exceptionCode = mode === "empty" ? "SA_SOURCE_EMPTY" : "SA_QUERY_FAILED";
      return payload;
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    const { unmount } = render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("当前展示 2026-08-26 盘后数据")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "双动量行业完整结果" })).toBeInTheDocument();
    unmount();

    mode = "empty";
    const emptyRender = render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("所选交易日暂无数据。")).toBeInTheDocument();
    emptyRender.unmount();

    mode = "error";
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("数据读取失败。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("updates date, period and threshold through URL-backed Results requests", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildDualReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "双动量行业完整结果" });

    fireEvent.click(screen.getByRole("button", { name: "10日" }));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("period")).toBe("10"));
    fireEvent.click(screen.getByRole("button", { name: "90%" }));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("leadingThreshold")).toBe("90"));
    fireEvent.change(screen.getByLabelText("分析日期"), { target: { value: "2026-08-26" } });
    await waitFor(() => expect(window.location.search).toContain("tradeDate=2026-08-26"));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("tradeDate")).toBe("2026-08-26"));
    expect(lastResultsUrl(urls).searchParams.has("resultView")).toBe(false);
    expect(lastResultsUrl(urls).searchParams.has("sectorCode")).toBe(false);
  });

  it("restores the complete dual-momentum state from browser history", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildDualReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "双动量行业完整结果" });

    window.history.pushState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27&scope=level2&period=30&threshold=90&resultView=all`);
    window.dispatchEvent(new PopStateEvent("popstate"));

    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("scope")).toBe("LEVEL_2"));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("period")).toBe("30"));
    expect(lastResultsUrl(urls).searchParams.get("leadingThreshold")).toBe("90");
    expect(screen.getByRole("button", { name: "全部行业" })).toHaveAttribute("aria-pressed", "true");
  });

  it("aborts a Meta request after the frozen five-second timeout", async () => {
    vi.useFakeTimers();
    const urls: string[] = [];
    const ready = buildDualReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = String(input);
      if (!raw.includes("/dual-momentum/meta")) return ready(input);
      urls.push(raw);
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      });
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(requestCount(urls, "/dual-momentum/meta")).toBe(1);
    await act(async () => { vi.advanceTimersByTime(5000); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("请求超时，请稍后重试。")).toBeInTheDocument();
  });

  it("keeps the existing authentication boundary on a 401 response", async () => {
    const urls: string[] = [];
    const ready = buildDualReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = String(input);
      if (raw.includes("/dual-momentum/meta")) {
        urls.push(raw);
        return jsonResponse({ code: "AUTH_REQUIRED", message: "登录已过期" }, 401);
      }
      if (raw.includes("/api/v1/auth/refresh")) return jsonResponse({ code: "AUTH_REQUIRED", message: "登录已过期" }, 401);
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    await waitFor(() => expect(window.location.pathname).toBe("/wealth/login"));
    expect(requestCount(urls, "/dual-momentum/results")).toBe(0);
  });

  it("links scatter focus and keyboard selection to the same selected industry", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildDualReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27&resultView=all`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "双动量行业完整结果" });
    const point = screen.getByRole("button", { name: /煤炭，区间涨跌幅/ });
    fireEvent.focus(point);
    expect(document.querySelector(".dual-scatter-tooltip .title")).toHaveTextContent("煤炭");
    fireEvent.keyDown(point, { key: "Enter" });
    await waitFor(() => expect(window.location.search).toContain("sectorCode=BK1003.DC"));
    expect(screen.getByLabelText("煤炭双动量摘要")).toBeInTheDocument();
  });

  it("drops an obsolete Results response after a rapid period change", async () => {
    const urls: string[] = [];
    const ready = buildDualReadyFetch(urls);
    let resolveTen!: (response: Response) => void;
    const tenResponse = new Promise<Response>((resolve) => { resolveTen = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = String(input);
      if (raw.includes("/dual-momentum/results") && new URL(raw).searchParams.get("period") === "10") {
        urls.push(raw);
        return tenResponse;
      }
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "双动量行业完整结果" });
    fireEvent.click(screen.getByRole("button", { name: "10日" }));
    await waitFor(() => expect(window.location.search).toContain("period=10"));
    fireEvent.click(screen.getByRole("button", { name: "30日" }));
    await waitFor(() => expect(screen.getByText("30日 · ≥80%")).toBeInTheDocument());
    resolveTen(jsonResponse(resultsPayload(new URL(`http://localhost/results?scope=LEVEL_1&period=10&leadingThreshold=80&hierarchyVersion=dc-industry-v1&tradeDate=2026-08-27`))));
    await Promise.resolve();
    expect(screen.getByText("30日 · ≥80%")).toBeInTheDocument();
    expect(screen.queryByText("10日 · ≥80%")).not.toBeInTheDocument();
  });

  it("keeps the frozen responsive grid and existing design-token boundary", () => {
    const css = readFileSync(`${process.cwd()}/src/features/wealth-exploration/sector-analysis/dual-momentum/ui/sector-dual-momentum.css`, "utf8");
    expect(css).toContain("grid-template-columns: minmax(0, 1fr) 12px minmax(0, 1fr)");
    expect(css).toMatch(/\.dual-result-table-header\s*\{[^}]*overflow-y:\s*auto[^}]*scrollbar-gutter:\s*stable/s);
    expect(css).toMatch(/\.dual-result-row-select\s*\{[^}]*column-gap:\s*var\(--cs-space-8\)/s);
    expect(css).toMatch(/\.dual-status-chip\s*\{[^}]*align-items:\s*center[^}]*justify-content:\s*center[^}]*text-align:\s*center/s);
    expect(css).toContain("min-width: 0");
    expect(css).not.toMatch(/width:\s*1564px/);
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(css).not.toContain("overflow-x: auto");
  });

  it("reloads Meta once for a fact-version conflict and stops a repeated conflict", async () => {
    const urls: string[] = [];
    let conflicts = 0;
    const ready = buildDualReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/dual-momentum/results")) {
        urls.push(url);
        conflicts += 1;
        return jsonResponse({ code: "SA_FACT_VERSION_MISMATCH", message: "行业分类已更新" }, 409);
      }
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    expect(await screen.findByText("行业分类版本持续变化，请稍后重试。")).toBeInTheDocument();
    expect(requestCount(urls, "/dual-momentum/meta")).toBe(2);
    expect(conflicts).toBe(2);
  });
});

function buildDualReadyFetch(urls: string[], override?: (url: URL) => any) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const raw = String(input);
    const url = new URL(raw);
    urls.push(raw);
    if (raw.includes("/wealth/market/context")) return jsonResponse(contextPayload(url.searchParams.get("tradeDate") ?? "2026-08-27"));
    if (raw.includes("/wealth/market/major-indices")) return jsonResponse(majorIndicesPayload());
    if (raw.includes("/dual-momentum/meta")) return jsonResponse(metaPayload());
    if (raw.includes("/dual-momentum/results")) return jsonResponse(override ? override(url) : resultsPayload(url));
    if (raw.includes("/sector-analysis/meta")) return jsonResponse({ message: "wrong controller" }, 500);
    return jsonResponse({ message: "unexpected request" }, 404);
  });
}

function contextPayload(tradeDate: string) {
  return { pageContext: { market: "CN_A", tradeDate, prevTradeDate: "2026-08-26", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai", generatedAt: "2026-08-28T09:15:00+08:00", source: "explicit" } };
}

function majorIndicesPayload() {
  return { tradingDay: { tradeDate: "2026-08-27", market: "CN_A", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai" }, pageStatus: { status: "READY", displayText: "已就绪" }, majorIndices: { definition: { definitionKey: "major", version: "1", fixedCount: 10 }, rows: [] } };
}

function metaPayload() {
  return {
    status: "READY", tradingDay: tradingDayPayload(), pageStatus: pageStatusPayload(), message: null, exceptionCode: null, debugInfo: null,
    formula: { formulaKey: "sector-dual-momentum", formulaVersion: 1, basisFormulaKey: "sector-cross-sectional-momentum", basisFormulaVersion: 1, periods: [5, 10, 20, 30], leadingThresholds: [70, 80, 90], minimumGroupSize: 3, scopes: ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"] },
    defaults: { scope: "LEVEL_1", period: 20, leadingThreshold: 80, resultView: "QUALIFIED" },
    hierarchy: { hierarchyVersion: "dc-industry-v1", publishedAt: "2026-08-27T20:30:00+08:00", nodes: hierarchyNodes() },
    coverageStartDate: "2026-08-26", coverageEndDate: "2026-08-27",
    tradeDates: [
      { tradeDate: "2026-08-26", availability: "PARTIAL", expectedSectorCount: 4, validSectorCount: 3 },
      { tradeDate: "2026-08-27", availability: "COMPLETE", expectedSectorCount: 4, validSectorCount: 4 },
    ],
  };
}

function hierarchyNodes() {
  return [
    node("BK1001.DC", "电子", 1, null, "BK1001.DC", false),
    node("BK1002.DC", "通信", 1, null, "BK1002.DC", false),
    node("BK1003.DC", "煤炭", 1, null, "BK1003.DC", false),
    node("BK1004.DC", "房地产", 1, null, "BK1004.DC", false),
    node("BK1101.DC", "电子设备", 2, "BK1001.DC", "BK1001.DC", false),
    node("BK1201.DC", "通信线缆及配套", 3, "BK1101.DC", "BK1001.DC", true),
  ];
}

function node(sectorCode: string, sectorName: string, industryLevel: number, parentSectorCode: string | null, rootSectorCode: string, isLeaf: boolean) {
  const parent = hierarchyName(parentSectorCode);
  const root = hierarchyName(rootSectorCode) ?? sectorName;
  return { sectorCode, sectorName, industryLevel, parentSectorCode, parentSectorName: parent, rootSectorCode, rootSectorName: root, hierarchyPath: parent ? `${root}/${parent}/${sectorName}`.replace(`/${root}/`, "/") : sectorName, displayOrder: Number(sectorCode.slice(2, 6)), isLeaf };
}

function hierarchyName(code: string | null) {
  return { "BK1001.DC": "电子", "BK1002.DC": "通信", "BK1003.DC": "煤炭", "BK1004.DC": "房地产", "BK1101.DC": "电子设备" }[code ?? ""] ?? null;
}

function resultsPayload(url: URL): any {
  const scope = url.searchParams.get("scope") ?? "LEVEL_1";
  const period = Number(url.searchParams.get("period") ?? 20);
  const threshold = Number(url.searchParams.get("leadingThreshold") ?? 80);
  const level1Code = url.searchParams.get("level1Code");
  const level2Code = url.searchParams.get("level2Code");
  const tradeDate = url.searchParams.get("tradeDate") ?? "2026-08-27";
  const tradingDay = tradingDayPayload();
  tradingDay.expectedTradeDate = tradeDate;
  tradingDay.observedTradeDate = tradeDate;
  if (tradeDate === "2026-08-26") {
    tradingDay.expectedAvailability = "PARTIAL";
    tradingDay.expectedValidSectorCount = 3;
    tradingDay.observedAvailability = "PARTIAL";
    tradingDay.observedValidSectorCount = 3;
  }
  const rows = scope === "LEVEL_1" ? level1Rows()
    : scope === "LEVEL_2" || scope === "LEVEL_1_CHILDREN"
      ? [row("BK1101.DC", "电子设备", 2, "BK1001.DC", 2.5, 1, 100, "SAMPLE_INSUFFICIENT", "SAMPLE_INSUFFICIENT", "POSITIVE", "NOT_EVALUATED", true)]
      : [row("BK1201.DC", "通信线缆及配套", 3, "BK1101.DC", 1.8, 1, 100, "SAMPLE_INSUFFICIENT", "SAMPLE_INSUFFICIENT", "POSITIVE", "NOT_EVALUATED", false)];
  const calculableCount = rows.filter((item: any) => item.returnPct !== null).length;
  return {
    status: "READY", tradingDay, pageStatus: pageStatusPayload(),
    analysis: {
      formulaKey: "sector-dual-momentum", formulaVersion: 1, basisFormulaKey: "sector-cross-sectional-momentum", basisFormulaVersion: 1,
      hierarchyVersion: url.searchParams.get("hierarchyVersion") ?? "dc-industry-v1", scope, period, leadingThreshold: threshold, minimumGroupSize: 3,
      parentSelection: { level1Code: scope === "LEVEL_1_CHILDREN" || scope === "LEVEL_2_CHILDREN" ? level1Code : null, level1Name: scope === "LEVEL_1_CHILDREN" || scope === "LEVEL_2_CHILDREN" ? "电子" : null, level2Code: scope === "LEVEL_2_CHILDREN" ? level2Code : null, level2Name: scope === "LEVEL_2_CHILDREN" ? "电子设备" : null },
      totalCount: rows.length, calculableCount, qualifiedCount: rows.filter((item: any) => item.qualificationStatus === "QUALIFIED").length,
      insufficientCount: rows.filter((item: any) => item.qualificationStatus === "NOT_EVALUATED").length,
      plottableCount: rows.filter((item: any) => item.coordinateStatus === "PLOTTABLE").length, items: rows,
    },
    message: null, exceptionCode: null, debugInfo: null,
  };
}

function level1Rows() {
  return [
    row("BK1001.DC", "电子", 1, null, 3.97, 1, 100, "QUALIFIED", "LEADING", "POSITIVE", "QUALIFIED", true),
    row("BK1003.DC", "煤炭", 1, null, -0.5, 2, 80, "NOT_UP_LEADING", "LEADING", "NOT_POSITIVE", "NOT_QUALIFIED", true),
    row("BK1002.DC", "通信", 1, null, 1.2, 3, 66.7, "UP_NOT_LEADING", "NOT_LEADING", "POSITIVE", "NOT_QUALIFIED", true),
    { sectorCode: "BK1004.DC", sectorName: "房地产", industryLevel: 1, parentSectorCode: null, parentSectorName: null, hierarchyPath: "房地产", canDrillDown: true, returnPct: null, strengthRank: null, percentile: null, absoluteStatus: "UNAVAILABLE", relativeStatus: "UNAVAILABLE", qualificationStatus: "NOT_EVALUATED", coordinateStatus: "UNAVAILABLE", displayStatus: "DATA_INSUFFICIENT", missingReason: "HISTORY_INSUFFICIENT" },
  ];
}

function row(code: string, name: string, level: number, parent: string | null, returnPct: number, strengthRank: number, percentile: number, displayStatus: string, relativeStatus: string, absoluteStatus: string, qualificationStatus: string, canDrillDown: boolean) {
  return { sectorCode: code, sectorName: name, industryLevel: level, parentSectorCode: parent, parentSectorName: hierarchyName(parent), hierarchyPath: name, canDrillDown, returnPct, strengthRank, percentile, absoluteStatus, relativeStatus, qualificationStatus, coordinateStatus: "PLOTTABLE", displayStatus, missingReason: null };
}

function tradingDayPayload() {
  return { expectedTradeDate: "2026-08-27", observedTradeDate: "2026-08-27", expectedAvailability: "COMPLETE", expectedSectorCount: 4, expectedValidSectorCount: 4, observedAvailability: "COMPLETE", observedValidSectorCount: 4 };
}

function pageStatusPayload() {
  return { status: "READY", displayText: "2026-08-27 盘后数据", asOfTime: "2026-08-27T20:31:00+08:00" };
}

function requestCount(urls: string[], fragment: string) { return urls.filter((url) => url.includes(fragment)).length; }
function lastResultsUrl(urls: string[]) { return new URL(urls.filter((url) => url.includes("/dual-momentum/results")).at(-1)!); }
