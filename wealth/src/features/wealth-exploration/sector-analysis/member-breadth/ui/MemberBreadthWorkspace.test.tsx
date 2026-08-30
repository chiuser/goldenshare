import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WealthRouter } from "../../../../../app/routes/WealthRouter";
import { WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH, WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH } from "../../../../../app/routes/routerState";
import { AuthProvider } from "../../../../auth/model/AuthProvider";
import { relativeContextPayload, relativeMajorIndicesPayload, relativeMetaPayload, relativeResultsPayload } from "../../relative-rotation/api/sectorRelativeRotationTestFixtures";
import { breadthDetailsPayload, breadthMetaPayload, breadthRankingsPayload } from "../api/sectorMemberBreadthTestFixtures";

function jsonResponse(payload: unknown, status = 200) { return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }); }
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); window.localStorage.clear(); window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH); });

describe("MemberBreadthWorkspace", () => {
  it("mounts only the fourth controller and resolves the first eligible sector before the first Details request", async () => {
    const urls: string[] = []; let resolveRankings!: (value: Response) => void; const rankings = new Promise<Response>((resolve) => { resolveRankings = resolve; });
    const regular = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = String(input); const url = new URL(raw);
      if (raw.includes("/member-breadth/rankings")) { urls.push(raw); return rankings; }
      return regular(input);
    }));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await waitFor(() => expect(count(urls, "/member-breadth/rankings")).toBe(1));
    expect(count(urls, "/member-breadth/details")).toBe(0);
    const rankingUrl = new URL(urls.find((url) => url.includes("/member-breadth/rankings"))!);
    resolveRankings(jsonResponse(breadthRankingsPayload(rankingUrl)));
    expect(await screen.findByRole("table", { name: "成员广度完整行业榜" })).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "成员广度成分股完整明细" })).toBeInTheDocument();
    expect(count(urls, "/member-breadth/details")).toBe(1);
    expect(new URL(urls.find((url) => url.includes("/member-breadth/details"))!).searchParams.get("sectorCode")).toBe("BK1001.DC");
    expect(window.location.search).toContain("sectorCode=BK1001.DC");
    expect(screen.getByRole("tab", { name: "成员广度" })).toHaveAttribute("aria-pressed", "true");
    expect(urls.some((url) => url.includes("/dual-momentum/") || url.includes("/relative-rotation/") || url.includes("/momentum/"))).toBe(false);
  });

  it("starts Rankings and Details together after Meta when a legal sector is restored", async () => {
    const urls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-27&sectorCode=BK1002.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "成员广度成分股完整明细" });
    expect(count(urls, "/member-breadth/rankings")).toBe(1); expect(count(urls, "/member-breadth/details")).toBe(1);
    expect(screen.getByLabelText("通信成员广度摘要")).toBeInTheDocument();
  });

  it("keeps automatic date mode out of the canonical URL", async () => {
    const urls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "成员广度成分股完整明细" });
    expect(new URLSearchParams(window.location.search).has("tradeDate")).toBe(false);
    expect(new URLSearchParams(window.location.search).get("sectorCode")).toBe("BK1001.DC");
  });

  it("shows the formal main Empty state without starting Rankings or Details", async () => {
    const urls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(urls, { empty: true }));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("暂无成员广度数据")).toBeInTheDocument();
    expect(screen.getByText("当前没有可用于成员广度分析的完整交易日。")).toBeInTheDocument();
    expect(count(urls, "/member-breadth/rankings")).toBe(0);
    expect(count(urls, "/member-breadth/details")).toBe(0);
  });

  it("rejects an invalid MA parameter before any member breadth request", async () => {
    const urls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?maPeriod=25`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("均线周期参数无效。")).toBeInTheDocument();
    expect(count(urls, "/member-breadth/")).toBe(0);
  });

  it("falls back to the first complete row when no sector qualifies", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls, { allIneligible: true });
    vi.stubGlobal("fetch", ready);
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "成员广度成分股完整明细" });
    expect(new URLSearchParams(window.location.search).get("sectorCode")).toBe("BK1001.DC");
    expect(new URL(urls.find((url) => url.includes("/member-breadth/details"))!).searchParams.get("sectorCode")).toBe("BK1001.DC");
  });

  it("uses the frozen request boundaries for metric, history, MA and direction changes", async () => {
    const urls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>); await screen.findByRole("table", { name: "成员广度成分股完整明细" });
    const baseline = () => [count(urls, "/member-breadth/rankings"), count(urls, "/member-breadth/details")];
    expect(baseline()).toEqual([1, 1]);
    fireEvent.click(screen.getByRole("button", { name: "成交额占比" })); await waitFor(() => expect(baseline()).toEqual([2, 1]));
    fireEvent.click(within(screen.getByText("历史范围").parentElement!).getByRole("button", { name: "60日" })); await waitFor(() => expect(baseline()).toEqual([2, 2]));
    fireEvent.click(screen.getByRole("button", { name: "MA60" })); await waitFor(() => expect(baseline()).toEqual([3, 3]));
    fireEvent.click(screen.getByRole("button", { name: "下跌广度" })); await waitFor(() => expect(baseline()).toEqual([4, 4]));
  });

  it("keeps trend inspection local, preserves it for ranking metric changes and clears it for every Details identity change", async () => {
    const urls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "成员广度成分股完整明细" });

    const activate = () => {
      const svg = screen.getByRole("img", { name: /成员广度趋势/ });
      Object.defineProperty(svg, "getBoundingClientRect", { configurable: true, value: () => ({ left: 0, top: 0, width: 920, height: 244, x: 0, y: 0, right: 920, bottom: 244, toJSON: () => ({}) }) });
      fireEvent.click(svg, { clientX: 475, clientY: 100 });
      expect(screen.getByRole("tooltip")).toBeInTheDocument();
    };
    const expectCleared = async () => waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());

    const requestCount = urls.length;
    const currentUrl = window.location.href;
    activate();
    expect(urls).toHaveLength(requestCount);
    expect(window.location.href).toBe(currentUrl);

    fireEvent.click(screen.getByRole("button", { name: "成交额占比" }));
    await waitFor(() => expect(count(urls, "/member-breadth/rankings")).toBe(2));
    expect(count(urls, "/member-breadth/details")).toBe(1);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    fireEvent.click(within(screen.getByText("历史范围").parentElement!).getByRole("button", { name: "30日" }));
    await waitFor(() => expect(count(urls, "/member-breadth/details")).toBe(2));
    await expectCleared();
    activate();

    fireEvent.click(screen.getByRole("button", { name: "下跌广度" }));
    await waitFor(() => expect(count(urls, "/member-breadth/details")).toBe(3));
    await expectCleared();
    activate();

    fireEvent.click(screen.getByRole("button", { name: "MA60" }));
    await waitFor(() => expect(count(urls, "/member-breadth/details")).toBe(4));
    await expectCleared();
    activate();

    fireEvent.click(screen.getByRole("button", { name: /选择通信/ }));
    await screen.findByLabelText("通信成员广度摘要");
    expect(count(urls, "/member-breadth/details")).toBe(5);
    await expectCleared();
    activate();

    fireEvent.change(screen.getByRole("combobox", { name: "分析日期" }), { target: { value: "2026-08-26" } });
    await waitFor(() => expect(count(urls, "/member-breadth/details")).toBe(6));
    await expectCleared();
  });

  it("supports all scopes, independent missing MA facts and null trend breaks", async () => {
    const urls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(urls, { maUnavailable: true }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>); await screen.findByRole("table", { name: "成员广度成分股完整明细" });
    expect(screen.getByText("样本不足 · 3/20")).toBeInTheDocument();
    expect(screen.getByText("72.0%", { selector: ".member-breadth-compositions header span" })).toBeInTheDocument();
    expect(document.querySelectorAll(".member-breadth-trend-line.member")).not.toHaveLength(0);
    expect(document.querySelectorAll(".member-breadth-trend-line.ma")).toHaveLength(0);
    for (const label of ["二级总榜", "三级总榜", "一级内二级", "二级内三级", "一级总榜"]) { fireEvent.click(screen.getByRole("button", { name: label })); await waitFor(() => expect(screen.getByRole("table", { name: "成员广度完整行业榜" })).toBeInTheDocument()); }
  });

  it("shows automatic Delayed but treats the same explicit historical date as ordinary Ready", async () => {
    const autoUrls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(autoUrls, { delayed: true }));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH);
    const automatic = render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("当前展示 2026-08-26 盘后数据")).toBeInTheDocument(); automatic.unmount();
    const explicitUrls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(explicitUrls, { delayed: true }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-26`);
    render(<AuthProvider><WealthRouter /></AuthProvider>); expect(await screen.findByText("2026-08-26 盘后数据")).toBeInTheDocument(); expect(screen.queryByText("当前展示 2026-08-26 盘后数据")).not.toBeInTheDocument();
  });

  it("keeps Details failure local and retries only Details", async () => {
    const urls: string[] = []; const ready = buildReadyFetch(urls); let attempt = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => { const raw = String(input); if (raw.includes("/member-breadth/details") && attempt++ === 0) { urls.push(raw); return jsonResponse({ status: "ERROR", message: "详情暂不可用", exceptionCode: "SA_BREADTH_QUERY_FAILED", tradeDate: "2026-08-27", hierarchyVersion: "dc-industry-v1", formulaKey: "sector-member-breadth", formulaVersion: 1, sectorCode: "BK1001.DC", sectorName: "电子", industryLevel: 1, hierarchyPath: "电子", direction: "UP", maPeriod: 20, historyRange: 20, compositions: [], trend: [], members: [] }); } return ready(input); }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>); expect(await screen.findByText("详情暂不可用")).toBeInTheDocument(); expect(screen.getByRole("table", { name: "成员广度完整行业榜" })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "重新加载" })); await screen.findByRole("table", { name: "成员广度成分股完整明细" }); expect(count(urls, "/member-breadth/meta")).toBe(1); expect(count(urls, "/member-breadth/rankings")).toBe(1); expect(count(urls, "/member-breadth/details")).toBe(2);
  });

  it("reloads Meta once on a hierarchy conflict and stops a repeated conflict", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = String(input);
      if (raw.includes("/member-breadth/rankings")) {
        urls.push(raw);
        return jsonResponse({ code: "SA_BREADTH_FACT_MISMATCH", message: "行业分类已更新" }, 409);
      }
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("行业分类版本持续变化，请稍后重试。")).toBeInTheDocument();
    expect(count(urls, "/member-breadth/meta")).toBe(2);
    expect(count(urls, "/member-breadth/rankings")).toBe(2);
  });

  it("keeps the Meta five-second timeout as a retryable safe error", async () => {
    vi.useFakeTimers();
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = String(input);
      if (!raw.includes("/member-breadth/meta")) return ready(input);
      urls.push(raw);
      return new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
    }));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(5000); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("请求超时，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("keeps Rankings pending before fifteen seconds and then exposes a retryable main error", async () => {
    vi.useFakeTimers();
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = String(input);
      if (!raw.includes("/member-breadth/rankings")) return ready(input);
      urls.push(raw);
      return new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC&metric=ma-position&maPeriod=60`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
    expect(count(urls, "/member-breadth/rankings")).toBe(1);

    await act(async () => { vi.advanceTimersByTime(14_999); await Promise.resolve(); });
    expect(screen.queryByText("请求超时，请稍后重试。")).not.toBeInTheDocument();

    await act(async () => { vi.advanceTimersByTime(1); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("请求超时，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("keeps Details pending before ten seconds and then exposes a local retry", async () => {
    vi.useFakeTimers();
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = String(input);
      if (!raw.includes("/member-breadth/details")) return ready(input);
      urls.push(raw);
      return new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
    expect(count(urls, "/member-breadth/details")).toBe(1);

    await act(async () => { vi.advanceTimersByTime(9999); await Promise.resolve(); });
    expect(screen.queryByText("请求超时，请稍后重试。")).not.toBeInTheDocument();

    await act(async () => { vi.advanceTimersByTime(1); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("请求超时，请稍后重试。")).toBeInTheDocument();
    expect(within(screen.getByRole("alert")).getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("keeps the existing authentication boundary on a 401 response", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = String(input);
      if (raw.includes("/member-breadth/meta")) { urls.push(raw); return jsonResponse({ code: "AUTH_REQUIRED", message: "登录已过期" }, 401); }
      if (raw.includes("/api/v1/auth/refresh")) return jsonResponse({ code: "AUTH_REQUIRED", message: "登录已过期" }, 401);
      return ready(input);
    }));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await waitFor(() => expect(window.location.pathname).toBe("/wealth/login"));
    expect(count(urls, "/member-breadth/rankings")).toBe(0);
    expect(count(urls, "/member-breadth/details")).toBe(0);
  });

  it("drops an obsolete Details response after a rapid sector change", async () => {
    const urls: string[] = [];
    let resolveOld!: (value: Response) => void;
    const oldDetails = new Promise<Response>((resolve) => { resolveOld = resolve; });
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = String(input);
      const url = new URL(raw);
      if (raw.includes("/member-breadth/details") && url.searchParams.get("sectorCode") === "BK1001.DC") { urls.push(raw); return oldDetails; }
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "成员广度完整行业榜" });
    fireEvent.click(screen.getByRole("button", { name: /选择通信/ }));
    expect(await screen.findByLabelText("通信成员广度摘要")).toBeInTheDocument();
    const staleUrl = new URL(urls.find((item) => item.includes("/member-breadth/details") && item.includes("BK1001.DC"))!);
    resolveOld(jsonResponse(breadthDetailsPayload(staleUrl)));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByLabelText("通信成员广度摘要")).toBeInTheDocument();
    expect(screen.queryByLabelText("电子成员广度摘要")).not.toBeInTheDocument();
  });

  it("does not mount member breadth requests or SVG outside its exact route", async () => {
    const urls: string[] = []; vi.stubGlobal("fetch", buildReadyFetch(urls)); window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>); await screen.findByRole("table", { name: "相对轮动行业完整列表" }); expect(count(urls, "/member-breadth/")).toBe(0); expect(document.querySelectorAll(".member-breadth-trend-svg")).toHaveLength(0);
  });

  it("keeps the responsive grid, independent scrollports and token-only visual boundary", () => {
    const css = readFileSync(`${process.cwd()}/src/features/wealth-exploration/sector-analysis/member-breadth/ui/sector-member-breadth.css`, "utf8");
    expect(css).toContain("grid-template-columns: minmax(480px, 548fr) 12px minmax(0, 1004fr)"); expect(css).toMatch(/\.member-breadth-ready-grid\s*\{[^}]*height:\s*866px/s); expect(css).toMatch(/\.member-breadth-ranking-viewport\s*\{[^}]*overflow-y:\s*auto[^}]*scrollbar-gutter:\s*stable/s); expect(css).toMatch(/\.member-breadth-member-viewport\s*\{[^}]*overflow-y:\s*auto[^}]*scrollbar-gutter:\s*stable/s); expect(css).not.toMatch(/width:\s*1564px/); expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i); expect(css).not.toContain("overflow-x: auto");
  });
});

function buildReadyFetch(urls: string[], options: { delayed?: boolean; empty?: boolean; maUnavailable?: boolean; allIneligible?: boolean } = {}) { return vi.fn(async (input: RequestInfo | URL) => { const raw = String(input); const url = new URL(raw); urls.push(raw); if (raw.includes("/wealth/market/context")) return jsonResponse(relativeContextPayload(url.searchParams.get("tradeDate") ?? "2026-08-27")); if (raw.includes("/wealth/market/major-indices")) return jsonResponse(relativeMajorIndicesPayload()); if (raw.includes("/member-breadth/meta")) return jsonResponse(breadthMetaPayload({ delayed: options.delayed, empty: options.empty })); if (raw.includes("/member-breadth/rankings")) return jsonResponse(breadthRankingsPayload(url, { allIneligible: options.allIneligible })); if (raw.includes("/member-breadth/details")) return jsonResponse(breadthDetailsPayload(url, { maUnavailable: options.maUnavailable })); if (raw.includes("/relative-rotation/meta")) return jsonResponse(relativeMetaPayload()); if (raw.includes("/relative-rotation/results")) return jsonResponse(relativeResultsPayload(url)); return jsonResponse({ message: "unexpected request" }, 404); }); }
function count(urls: string[], fragment: string) { return urls.filter((url) => url.includes(fragment)).length; }
