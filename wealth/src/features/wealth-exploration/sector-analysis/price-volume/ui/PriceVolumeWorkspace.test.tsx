import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WealthRouter } from "../../../../../app/routes/WealthRouter";
import { WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH } from "../../../../../app/routes/routerState";
import { AuthProvider } from "../../../../auth/model/AuthProvider";
import { relativeContextPayload, relativeMajorIndicesPayload } from "../../relative-rotation/api/sectorRelativeRotationTestFixtures";
import { priceVolumeDetailsPayload, priceVolumeMetaPayload, priceVolumeSnapshotPayload } from "../api/sectorPriceVolumeTestFixtures";

function jsonResponse(payload: unknown, status = 200) { return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }); }

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.clear();
  window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH);
});

describe("PriceVolumeWorkspace", () => {
  it("mounts only the fifth controller and resolves the first complete coordinate", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH);
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    expect(screen.getByLabelText("量价分布加载中")).toBeInTheDocument();
    await screen.findByRole("table", { name: "行业量价分布完整列表" });
    expect(screen.getByRole("tab", { name: "量价分布" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img", { name: "行业区间涨跌幅与成交活跃度二维分布" })).toBeInTheDocument();
    expect(screen.getByLabelText("当前选中行业摘要")).toHaveTextContent("电子");
    expect(count(urls, "/price-volume/meta")).toBe(1);
    expect(count(urls, "/price-volume/snapshot")).toBe(1);
    expect(count(urls, "/price-volume/details")).toBe(1);
    expect(urls.some((url) => url.includes("/member-breadth/") || url.includes("/relative-rotation/") || url.includes("/dual-momentum/") || url.includes("/momentum/"))).toBe(false);
    expect(new URLSearchParams(window.location.search).get("sectorCode")).toBe("BK1001.DC");
    expect(new URLSearchParams(window.location.search).has("tradeDate")).toBe(false);
  });

  it("keeps filter, sort and scatter hover local while history range requests only Details", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "行业量价分布完整列表" });
    const baseline = urls.length;

    fireEvent.click(screen.getByRole("button", { name: "量价共同增强" }));
    fireEvent.click(screen.getByRole("columnheader", { name: "按区间涨跌幅排序" }));
    expect(screen.getByRole("columnheader", { name: "按区间涨跌幅排序" })).toHaveTextContent("↑");
    const point = screen.getByRole("button", { name: /电子，区间涨跌幅/ });
    fireEvent.focus(point);
    expect(screen.getByRole("tooltip")).toHaveTextContent("电子");
    expect(urls).toHaveLength(baseline);

    fireEvent.click(within(screen.getByLabelText("历史显示范围")).getByRole("button", { name: "60日" }));
    await waitFor(() => expect(count(urls, "/price-volume/details")).toBe(2));
    expect(count(urls, "/price-volume/snapshot")).toBe(1);
    expect(lastUrl(urls, "/price-volume/details").searchParams.get("historyRange")).toBe("60");
  });

  it("requests every comparison scope and preserves frozen parent closure", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "行业量价分布完整列表" });

    for (const [label, scope] of [["二级总榜", "LEVEL_2"], ["三级总榜", "LEVEL_3"], ["一级内二级", "LEVEL_1_CHILDREN"], ["二级内三级", "LEVEL_2_CHILDREN"], ["一级总榜", "LEVEL_1"]] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      await waitFor(() => expect(lastUrl(urls, "/price-volume/snapshot").searchParams.get("scope")).toBe(scope));
      await waitFor(() => expect(screen.getByRole("button", { name: label })).toHaveAttribute("aria-pressed", "true"));
    }
    fireEvent.click(within(screen.getByText("统计周期").parentElement!).getByRole("button", { name: "30日" }));
    await waitFor(() => expect(lastUrl(urls, "/price-volume/snapshot").searchParams.get("period")).toBe("30"));
  });

  it("retains a selected industry with a missing coordinate without inventing a plot point", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH}?tradeDate=2026-08-27&sectorCode=BK1002.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "行业量价分布完整列表" });
    expect(screen.getByLabelText("当前选中行业摘要")).toHaveTextContent("通信");
    expect(screen.getByLabelText("当前选中行业摘要")).toHaveTextContent("坐标不完整");
    expect(screen.getByRole("button", { name: "选择通信" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /通信，区间涨跌幅/ })).not.toBeInTheDocument();
  });

  it("shares one hover date across the two history charts and preserves null breaks", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    const chart = await screen.findByRole("img", { name: "滚动20日区间涨跌幅历史趋势" });
    Object.defineProperty(chart, "getBoundingClientRect", { configurable: true, value: () => ({ left: 0, top: 0, width: 924, height: 126, x: 0, y: 0, right: 924, bottom: 126, toJSON: () => ({}) }) });
    fireEvent.mouseMove(chart, { clientX: 476, clientY: 60 });
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08-26");
    expect(screen.getByRole("tooltip")).toHaveTextContent("--");
    expect(document.querySelectorAll(".price-volume-history-svg .history-crosshair")).toHaveLength(2);
    expect(document.querySelectorAll(".price-volume-history-svg polyline")).toHaveLength(3);
  });

  it("shows automatic Delayed, main Empty and safe Error states", async () => {
    const delayedUrls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(delayedUrls, { delayed: true }));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH);
    const delayed = render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("当前展示 2026-08-26 盘后数据")).toBeInTheDocument();
    delayed.unmount();

    const emptyUrls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(emptyUrls, { metaEmpty: true }));
    const empty = render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("当前范围暂无完整量价坐标")).toBeInTheDocument();
    expect(count(emptyUrls, "/price-volume/snapshot")).toBe(0);
    empty.unmount();

    const errorUrls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(errorUrls, { snapshotError: true }));
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("行业层级暂不可用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("keeps an explicitly selected partial or missing date exact instead of applying automatic fallback", async () => {
    const partialUrls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(partialUrls, { delayed: true }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH}?tradeDate=2026-08-27`);
    const partial = render(<AuthProvider><WealthRouter /></AuthProvider>);
    await screen.findByRole("table", { name: "行业量价分布完整列表" });
    expect(screen.queryByText("当前展示 2026-08-26 盘后数据")).not.toBeInTheDocument();
    expect(lastUrl(partialUrls, "/price-volume/snapshot").searchParams.get("tradeDate")).toBe("2026-08-27");
    partial.unmount();

    const missingUrls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(missingUrls, { snapshotEmpty: true }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH}?tradeDate=2026-08-27`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("当前范围暂无完整量价坐标")).toBeInTheDocument();
    expect(lastUrl(missingUrls, "/price-volume/snapshot").searchParams.get("tradeDate")).toBe("2026-08-27");
    expect(count(missingUrls, "/price-volume/details")).toBe(0);
  });

  it("keeps Details failure local and retries only Details", async () => {
    const urls: string[] = [];
    let attempt = 0;
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = String(input);
      if (raw.includes("/price-volume/details") && attempt++ === 0) {
        urls.push(raw);
        return jsonResponse({ status: "ERROR", details: null, message: "历史变化暂不可用", exceptionCode: "SA_QUERY_FAILED", debugInfo: null });
      }
      return ready(input);
    }));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH}?tradeDate=2026-08-27&sectorCode=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("历史变化暂不可用")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "行业量价分布完整列表" })).toBeInTheDocument();
    fireEvent.click(within(screen.getByText("历史变化加载失败").parentElement!).getByRole("button", { name: "重试" }));
    await screen.findByRole("img", { name: "滚动20日区间涨跌幅历史趋势" });
    expect(count(urls, "/price-volume/meta")).toBe(1);
    expect(count(urls, "/price-volume/snapshot")).toBe(1);
    expect(count(urls, "/price-volume/details")).toBe(2);
  });

  it("reloads Meta once on a hierarchy conflict and stops a repeated conflict", async () => {
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = String(input);
      if (raw.includes("/price-volume/snapshot")) {
        urls.push(raw);
        return jsonResponse({ code: "SA_PRICE_VOLUME_FACT_MISMATCH", message: "行业分类已更新" }, 409);
      }
      return ready(input);
    }));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("行业分类版本持续变化，请稍后重试。")).toBeInTheDocument();
    expect(count(urls, "/price-volume/meta")).toBe(2);
    expect(count(urls, "/price-volume/snapshot")).toBe(2);
  });

  it("turns the frozen five-second timeout into a retryable safe error", async () => {
    vi.useFakeTimers();
    const urls: string[] = [];
    const ready = buildReadyFetch(urls);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = String(input);
      if (!raw.includes("/price-volume/meta")) return ready(input);
      urls.push(raw);
      return new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
    }));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH);
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
      if (raw.includes("/price-volume/meta")) { urls.push(raw); return jsonResponse({ code: "AUTH_REQUIRED", message: "登录已过期" }, 401); }
      if (raw.includes("/api/v1/auth/refresh")) return jsonResponse({ code: "AUTH_REQUIRED", message: "登录已过期" }, 401);
      return ready(input);
    }));
    window.history.replaceState({}, "", WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    await waitFor(() => expect(window.location.pathname).toBe("/wealth/login"));
    expect(count(urls, "/price-volume/snapshot")).toBe(0);
  });

  it("rejects an illegal bookmark before all price-volume API requests", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", buildReadyFetch(urls));
    window.history.replaceState({}, "", `${WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH}?scope=level2-children&level1Code=BK1001.DC`);
    render(<AuthProvider><WealthRouter /></AuthProvider>);
    expect(await screen.findByText("二级内三级必须同时选择一级和二级行业。")).toBeInTheDocument();
    expect(count(urls, "/price-volume/")).toBe(0);
  });

  it("keeps the formal responsive geometry and design-token boundary", () => {
    const css = readFileSync(`${process.cwd()}/src/features/wealth-exploration/sector-analysis/price-volume/ui/sector-price-volume.css`, "utf8");
    expect(css).toMatch(/\.price-volume-toolbar\s*\{[^}]*height:\s*128px/s);
    expect(css).toMatch(/\.price-volume-ready-grid,[^{]*\{[^}]*height:\s*866px/s);
    expect(css).toContain("grid-template-columns: minmax(520px, 600fr) minmax(760px, 952fr)");
    expect(css).toContain("grid-template-rows: 100px 430px 312px");
    expect(css).toMatch(/\.price-volume-list-viewport\s*\{[^}]*overflow-y:\s*auto/s);
    expect(css).toMatch(/\.price-volume-status-chip\s*\{[^}]*box-sizing:\s*border-box[^}]*height:\s*24px[^}]*max-height:\s*24px[^}]*min-height:\s*24px/s);
    expect(css).toMatch(/\.price-volume-row-select > \.price-volume-status-chip\s*\{[^}]*align-self:\s*center[^}]*justify-self:\s*center[^}]*max-width:\s*120px/s);
    expect(css).not.toMatch(/width:\s*1564px/);
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(css).not.toContain("overflow-x: auto");
  });
});

function buildReadyFetch(urls: string[], options: { delayed?: boolean; metaEmpty?: boolean; snapshotEmpty?: boolean; snapshotError?: boolean } = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const raw = String(input);
    const url = new URL(raw);
    urls.push(raw);
    if (raw.includes("/wealth/market/context")) return jsonResponse(relativeContextPayload(url.searchParams.get("tradeDate") ?? "2026-08-27"));
    if (raw.includes("/wealth/market/major-indices")) return jsonResponse(relativeMajorIndicesPayload());
    if (raw.includes("/price-volume/meta")) return jsonResponse(priceVolumeMetaPayload({ delayed: options.delayed, empty: options.metaEmpty }));
    if (raw.includes("/price-volume/snapshot")) {
      if (options.snapshotError) return jsonResponse({ status: "ERROR", snapshot: null, message: "行业层级暂不可用", exceptionCode: "SA_HIERARCHY_UNAVAILABLE", debugInfo: null });
      return jsonResponse(priceVolumeSnapshotPayload(url, { empty: options.snapshotEmpty }));
    }
    if (raw.includes("/price-volume/details")) return jsonResponse(priceVolumeDetailsPayload(url));
    if (raw.includes("/member-breadth/") || raw.includes("/relative-rotation/") || raw.includes("/dual-momentum/") || raw.includes("/momentum/")) return jsonResponse({ message: "wrong controller" }, 500);
    return jsonResponse({ message: "unexpected request" }, 404);
  });
}
function count(urls: string[], fragment: string) { return urls.filter((url) => url.includes(fragment)).length; }
function lastUrl(urls: string[], fragment: string) { return new URL(urls.filter((url) => url.includes(fragment)).at(-1)!); }
