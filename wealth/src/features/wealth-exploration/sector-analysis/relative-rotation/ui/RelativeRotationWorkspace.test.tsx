import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WealthRouter } from "../../../../../app/routes/WealthRouter";
import { WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH } from "../../../../../app/routes/routerState";
import { AuthProvider } from "../../../../auth/model/AuthProvider";
import { relativeContextPayload, relativeMajorIndicesPayload, relativeMetaPayload, relativeResultsPayload } from "../api/sectorRelativeRotationTestFixtures";

function jsonResponse(payload: unknown, status = 200): Response { return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }); }

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.clear();
  window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH);
});

describe("RelativeRotationWorkspace", () => {
  it("mounts only the relative-rotation controller on the third exact route", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    expect(screen.getByLabelText("相对轮动加载中")).toBeInTheDocument();
    await screen.findByRole("table", { name: "相对轮动行业完整列表" });
    expect(screen.getByRole("tab", { name: "相对轮动" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("tab", { name: "动量排名" })).toHaveAttribute("aria-pressed", "false");
    expect(requestCount(urls, "/relative-rotation/meta")).toBe(1);
    expect(requestCount(urls, "/relative-rotation/results")).toBe(1);
    expect(urls.some((url) => /\/momentum\/(rankings|history|members)/.test(url) || url.includes("/dual-momentum/"))).toBe(false);
    expect(screen.getByRole("img", { name: "行业相对轮动四象限图" })).toBeInTheDocument();
    await waitFor(() => expect(window.location.search).toContain("sectorCode=BK1001.DC"));
    expect(requestCount(urls, "/relative-rotation/results")).toBe(1);
  });

  it("switches methods with only the three shared query values", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?market=CN_A&debug=1&tradeDate=2026-08-27&scope=level2&period=30&trailLength=60&sectorCode=BK1101.DC&quadrant=all&search=%E7%94%B5%E5%AD%90`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "相对轮动行业完整列表" });
    fireEvent.click(screen.getByRole("tab", { name: "双动量" }));
    expect(window.location.pathname).toContain("/dual-momentum");
    expect(window.location.search).toBe("?debug=1&tradeDate=2026-08-27");
  });

  it("filters only the complete right list while preserving every plot point and request count", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "相对轮动行业完整列表" });
    const baseline = requestCount(urls, "/relative-rotation/results");
    expect(document.querySelectorAll(".relative-rotation-point")).toHaveLength(3);

    const coalPoint = screen.getByRole("button", { name: /煤炭，强度/ });
    fireEvent.focus(coalPoint);
    expect(document.querySelector(".relative-plot-tooltip .title")).toHaveTextContent("煤炭");
    expect(requestCount(urls, "/relative-rotation/results")).toBe(baseline);

    fireEvent.change(screen.getByLabelText("搜索行业"), { target: { value: "煤炭" } });
    expect(await screen.findByRole("button", { name: "选择煤炭" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "选择电子" })).not.toBeInTheDocument();
    expect(document.querySelectorAll(".relative-rotation-point")).toHaveLength(3);
    fireEvent.click(within(screen.getByLabelText("象限筛选")).getByRole("button", { name: "领先且改善" }));
    expect(screen.getByText("没有匹配的行业")).toBeInTheDocument();
    expect(requestCount(urls, "/relative-rotation/results")).toBe(baseline);
  });

  it("requests all five scopes and the frozen period/trail controls through URL state", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "相对轮动行业完整列表" });

    for (const [label, scope] of [["二级总榜", "LEVEL_2"], ["三级总榜", "LEVEL_3"], ["一级内二级", "LEVEL_1_CHILDREN"], ["二级内三级", "LEVEL_2_CHILDREN"], ["一级总榜", "LEVEL_1"]] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("scope")).toBe(scope));
    }
    fireEvent.click(screen.getByRole("button", { name: "10日" }));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("period")).toBe("10"));
    fireEvent.click(within(screen.getByText("轨迹长度").parentElement!).getByRole("button", { name: "60日" }));
    await waitFor(() => expect(lastResultsUrl(urls).searchParams.get("trailLength")).toBe("60"));
  });

  it("keeps the previous selected snapshot atomic until a new selected trail arrives", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    let resolveSelection!: (response: Response) => void;
    const selection = new Promise<Response>((resolve) => { resolveSelection = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/relative-rotation/results") && new URL(url).searchParams.get("sectorCode") === "BK1002.DC") {
        urls.push(url);
        return selection;
      }
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByLabelText("电子相对轮动摘要");

    fireEvent.click(screen.getByRole("button", { name: "选择通信" }));
    await screen.findByText("正在更新所选行业");
    expect(screen.getByLabelText("电子相对轮动摘要")).toBeInTheDocument();
    expect(screen.queryByLabelText("通信相对轮动摘要")).not.toBeInTheDocument();
    resolveSelection(jsonResponse(relativeResultsPayload(new URL(`http://localhost/results?tradeDate=2026-08-27&scope=LEVEL_1&period=20&trailLength=20&sectorCode=BK1002.DC&hierarchyVersion=dc-industry-v1`))));
    expect(await screen.findByLabelText("通信相对轮动摘要")).toBeInTheDocument();
  });

  it("keeps missing coordinates in the list and never creates a false plot point", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27&sectorCode=BK1004.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByLabelText("房地产相对轮动摘要");
    expect(screen.getByText(/当前行业坐标不可计算/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择房地产" })).toBeInTheDocument();
    expect(document.querySelectorAll(".relative-rotation-point")).toHaveLength(3);
    expect(document.querySelectorAll("circle[cx='68'][cy='360.5']")).toHaveLength(0);
  });

  it("renders Small Group objectively and opens the shared-scale dialog without requests", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27&scope=level2`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByText("样本不足，仅展示客观位置");
    expect(document.querySelectorAll(".relative-rotation-point.sample-insufficient")).toHaveLength(2);
    const before = requestCount(urls, "/relative-rotation/results");
    fireEvent.click(screen.getByRole("button", { name: "放大相对轮动图" }));
    expect(screen.getByRole("dialog", { name: "放大的行业相对轮动图" })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "行业相对轮动四象限图" })).toHaveLength(2);
    expect(requestCount(urls, "/relative-rotation/results")).toBe(before);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "放大相对轮动图" })).toHaveFocus();
  });

  it("shows Delayed content and stable Empty/Error states", async () => {
    const urls: string[] = [];
    let mode: "delayed" | "empty" | "error" = "delayed";
    vi.stubGlobal("fetch", buildReadyFetch(urls, (url) => {
      const payload = relativeResultsPayload(url);
      if (mode === "delayed") {
        payload.status = "DELAYED"; payload.pageStatus.status = "DELAYED"; payload.pageStatus.displayText = "数据更新中"; payload.exceptionCode = "SA_SOURCE_DELAYED";
        payload.tradingDay.observedTradeDate = "2026-08-26"; payload.tradingDay.expectedAvailability = "MISSING"; payload.tradingDay.expectedValidSectorCount = 0;
        payload.analysis.selectedTrail.points = [payload.analysis.selectedTrail.points[0]]; payload.analysis.selectedTrail.dateSlotCount = 1;
        return payload;
      }
      payload.status = mode === "empty" ? "EMPTY" : "ERROR"; payload.pageStatus.status = payload.status; payload.analysis = null;
      payload.message = mode === "empty" ? "所选交易日暂无数据。" : "数据读取失败。"; payload.exceptionCode = mode === "empty" ? "SA_SOURCE_EMPTY" : "SA_QUERY_FAILED";
      return payload;
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27`);
    const delayed = render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("当前展示 2026-08-26 盘后数据")).toBeInTheDocument();
    delayed.unmount();
    mode = "empty";
    const empty = render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("所选交易日暂无数据。")).toBeInTheDocument();
    empty.unmount();
    mode = "error";
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("数据读取失败。")).toBeInTheDocument();
  });

  it("stops a repeated hierarchy conflict after exactly one Meta reload", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/relative-rotation/results")) { urls.push(url); return jsonResponse({ code: "SA_FACT_VERSION_MISMATCH", message: "行业分类已更新" }, 409); }
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("行业分类版本持续变化，请稍后重试。")).toBeInTheDocument();
    expect(requestCount(urls, "/relative-rotation/meta")).toBe(2);
    expect(requestCount(urls, "/relative-rotation/results")).toBe(2);
  });

  it("turns the frozen five-second timeout into a retryable safe error", async () => {
    vi.useFakeTimers();
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = String(input);
      if (!raw.includes("/relative-rotation/meta")) return ready(input);
      urls.push(raw);
      return new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(5000); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("请求超时，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("keeps the existing authentication boundary on a 401 response", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = String(input);
      if (raw.includes("/relative-rotation/meta")) {
        urls.push(raw);
        return jsonResponse({ code: "AUTH_REQUIRED", message: "登录已过期" }, 401);
      }
      if (raw.includes("/api/v1/auth/refresh")) return jsonResponse({ code: "AUTH_REQUIRED", message: "登录已过期" }, 401);
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    await waitFor(() => expect(window.location.pathname).toBe("/wealth/login"));
    expect(requestCount(urls, "/relative-rotation/results")).toBe(0);
  });

  it("fails an illegal bookmark before both relative API requests", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH}?scope=level2-children&level1Code=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("二级内三级必须同时选择一级和二级行业。")).toBeInTheDocument();
    expect(requestCount(urls, "/relative-rotation/meta")).toBe(0);
    expect(requestCount(urls, "/relative-rotation/results")).toBe(0);
  });

  it("keeps the frozen responsive geometry and design-token boundary", () => {
    const css = readFileSync(`${process.cwd()}/src/features/wealth-exploration/sector-analysis/relative-rotation/ui/sector-relative-rotation.css`, "utf8");
    expect(css).toContain("grid-template-columns: minmax(0, 2.344827586fr) 12px minmax(360px, 1fr)");
    expect(css).toMatch(/\.relative-rotation-toolbar\s*\{[^}]*height:\s*128px[^}]*padding:\s*var\(--cs-space-12\)/s);
    expect(css).toMatch(/\.relative-rotation-ready-grid\s*\{[^}]*height:\s*866px/s);
    expect(css).toMatch(/\.relative-list-table\s*\{[^}]*height:\s*694px/s);
    expect(css).toMatch(/\.relative-list-viewport\s*\{[^}]*overflow-y:\s*auto[^}]*scrollbar-gutter:\s*stable/s);
    expect(css).not.toMatch(/width:\s*1564px/);
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(css).not.toContain("overflow-x: auto");
  });
});

function buildReadyFetch(urls: string[], override?: (url: URL) => any) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const raw = String(input);
    const url = new URL(raw);
    urls.push(raw);
    if (raw.includes("/wealth/market/context")) return jsonResponse(relativeContextPayload(url.searchParams.get("tradeDate") ?? "2026-08-27"));
    if (raw.includes("/wealth/market/major-indices")) return jsonResponse(relativeMajorIndicesPayload());
    if (raw.includes("/relative-rotation/meta")) return jsonResponse(relativeMetaPayload());
    if (raw.includes("/relative-rotation/results")) return jsonResponse(override ? override(url) : relativeResultsPayload(url));
    if (raw.includes("/sector-analysis/meta") || raw.includes("/dual-momentum/")) return jsonResponse({ message: "wrong controller" }, 500);
    return jsonResponse({ message: "unexpected request" }, 404);
  });
}
function requestCount(urls: string[], fragment: string) { return urls.filter((url) => url.includes(fragment)).length; }
function lastResultsUrl(urls: string[]) { return new URL(urls.filter((url) => url.includes("/relative-rotation/results")).at(-1)!); }
