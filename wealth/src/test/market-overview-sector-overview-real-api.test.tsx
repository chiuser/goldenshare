import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { marketOverviewModuleSources } from "../features/market-overview/api/moduleSources";
import { MarketOverviewPage } from "../pages/market-overview/MarketOverviewPage";

const moduleSourcesSnapshot = { ...marketOverviewModuleSources };

const pageContextPayload = {
  pageContext: {
    market: "CN_A",
    tradeDate: "2026-05-11",
    prevTradeDate: "2026-05-08",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
    generatedAt: "2026-05-11T15:05:00+08:00",
    source: "default",
  },
};

const commonResponse = {
  tradingDay: {
    tradeDate: "2026-05-11",
    prevTradeDate: "2026-05-08",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-05-11T20:00:00+08:00" },
  debugInfo: {
    modules: [{ moduleKey: "sectorOverview", expectedTradeDate: "2026-05-11", observedTradeDate: "2026-05-11", lagDays: 0, status: "READY", note: "facts ready" }],
    exceptions: [],
  },
};

function metric(value: number, displayText = `+${value.toFixed(2)}%`) {
  return { value, displayText, direction: "UP" };
}

function rankItem(code: string, name: string, rank: number, selected = false, withHeat = false) {
  return {
    rank,
    sectorCode: code,
    sectorName: name,
    primaryMetric: metric(6 - rank),
    leader: { stockCode: "000001.SZ", stockName: `${name}领涨股`, changePct: 9.98 },
    ...(withHeat
      ? {
          heat: {
            heatStatus: "VALID",
            invalidReason: null,
            heatScore: 91 - rank,
            heatLevel: "BOILING",
            heatDelta1d: rank,
            heatTrend: "HEATING",
            heatRank: rank,
            scoreVersion: "concept-heat-eod-v1",
            tradeDate: "2026-05-11",
            calculatedAt: "2026-05-11T20:00:00+08:00",
          },
        }
      : {}),
    selected,
  };
}

function detail(code: string, name: string, sectorType: "INDUSTRY" | "CONCEPT" | "REGION", withHeat = false) {
  return {
    sectorCode: code,
    sectorName: name,
    sectorType,
    ...(sectorType === "INDUSTRY" ? { hierarchyPath: `一级 / 二级 / ${name}` } : {}),
    metrics: {
      changePct: 3.21,
      upCount: 18,
      downCount: 4,
      sourceMemberCount: 23,
      memberCount: 22,
      suspendedCount: 1,
      quoteEligibleCount: 21,
      validQuoteCount: 21,
      missingQuoteCount: 0,
      mainNetInflow: 1280000000,
      turnoverAmount: 8520000000,
      quoteCoverage: 1,
    },
    ...(withHeat
      ? {
          heat: rankItem(code, name, 1, true, true).heat,
          heatHistory: Array.from({ length: 20 }, (_, index) => ({
            tradeDate: `2026-04-${String(index + 1).padStart(2, "0")}`,
            heatScore: 70 + index,
            heatRank: index + 1,
            heatLevel: index > 17 ? "BOILING" : "HOT",
          })),
        }
      : {}),
    leader: { stockCode: "000001.SZ", stockName: `${name}领涨股`, changePct: 9.98 },
    members: Array.from({ length: 5 }, (_, index) => ({
      stockCode: `00000${index + 1}.SZ`,
      stockName: `成分股${index + 1}`,
      changePct: 5 - index,
      direction: "UP",
    })),
  };
}

const industryPayload = {
  ...commonResponse,
  sectorOverview: {
    tradeDate: "2026-05-11",
    status: "READY",
    view: "INDUSTRY",
    asOf: "2026-05-11T20:00:00+08:00",
    industry: {
      rankMetric: "CHANGE_PCT",
      selection: { level1Code: "BK0001.DC", level2Code: "BK0101.DC", level3Code: "BK0201.DC", detailSectorCode: "BK0201.DC" },
      columns: [
        { level: 1, parentSectorCode: null, rows: Array.from({ length: 5 }, (_, index) => rankItem(`BK000${index + 1}.DC`, `一级行业${index + 1}`, index + 1, index === 0)) },
        { level: 2, parentSectorCode: "BK0001.DC", rows: Array.from({ length: 5 }, (_, index) => rankItem(`BK010${index + 1}.DC`, `二级行业${index + 1}`, index + 1, index === 0)) },
        { level: 3, parentSectorCode: "BK0101.DC", rows: Array.from({ length: 5 }, (_, index) => rankItem(`BK020${index + 1}.DC`, `三级行业${index + 1}`, index + 1, index === 0)) },
      ],
      detail: detail("BK0201.DC", "三级行业1", "INDUSTRY"),
    },
  },
};

const conceptPayload = {
  ...commonResponse,
  sectorOverview: {
    tradeDate: "2026-05-11",
    status: "READY",
    view: "CONCEPT",
    asOf: "2026-05-11T20:00:00+08:00",
    concept: {
      rankMetric: "HEAT_SCORE",
      selectedConceptCode: "BK1001.DC",
      rows: Array.from({ length: 20 }, (_, index) => rankItem(`BK10${String(index + 1).padStart(2, "0")}.DC`, `概念板块${index + 1}`, index + 1, index === 0, true)),
      detail: detail("BK1001.DC", "概念板块1", "CONCEPT", true),
    },
  },
};

const regionPayload = {
  ...commonResponse,
  sectorOverview: {
    tradeDate: "2026-05-11",
    status: "READY",
    view: "REGION",
    asOf: "2026-05-11T20:00:00+08:00",
    region: {
      rankMetric: "CHANGE_PCT",
      selectedRegionCode: "BK2001.DC",
      rows: Array.from({ length: 31 }, (_, index) => rankItem(`BK20${String(index + 1).padStart(2, "0")}.DC`, `地域板块${index + 1}`, index + 1, index === 0)),
      detail: detail("BK2001.DC", "地域板块1", "REGION"),
    },
  },
};

function responseJson(payload: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as Response;
}

function urlOf(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
}

describe("market-overview sector-overview V2 real api", () => {
  beforeEach(() => {
    Object.keys(marketOverviewModuleSources).forEach((key) => {
      marketOverviewModuleSources[key as keyof typeof marketOverviewModuleSources] = key === "sectors" ? "real" : "mock";
    });
  });

  afterEach(() => {
    Object.assign(marketOverviewModuleSources, moduleSourcesSnapshot);
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.history.pushState({}, "", "/");
  });

  it("renders industry hierarchy, leader and members without V1 matrix fields", async () => {
    const requestUrls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlOf(input);
      requestUrls.push(url);
      if (url.includes("/context")) return responseJson(pageContextPayload);
      if (url.includes("/sector-overview")) return responseJson(industryPayload);
      throw new Error(`unexpected url: ${url}`);
    });
    const rendered = render(<MarketOverviewPage />);
    await act(async () => Promise.resolve());
    const panel = rendered.container.querySelector<HTMLElement>('[aria-label="板块速览"]');
    expect(panel).not.toBeNull();
    if (!panel) throw new Error("sector-overview panel not found");
    expect(await within(panel).findByText("一级行业1")).toBeInTheDocument();
    expect(within(panel).getAllByText("三级行业1").length).toBeGreaterThan(0);
    expect(within(panel).getAllByText("三级行业1领涨股").length).toBeGreaterThan(0);
    expect(within(panel).getByText("成分股1")).toBeInTheDocument();
    expect(within(panel).queryByText("板块热力图")).not.toBeInTheDocument();
    const request = new URL(requestUrls.find((url) => url.includes("/sector-overview")) as string);
    expect(request.searchParams.get("view")).toBe("INDUSTRY");
    expect(request.searchParams.get("industryRankMetric")).toBe("CHANGE_PCT");
    await waitFor(() => expect(requestUrls.filter((url) => url.includes("/sector-overview"))).toHaveLength(1));
  });

  it("switches tabs with independent requests and renders heat and the 31-region workspace", async () => {
    const requestUrls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlOf(input);
      requestUrls.push(url);
      if (url.includes("/context")) return responseJson(pageContextPayload);
      if (url.includes("/sector-overview")) {
        const view = new URL(url).searchParams.get("view");
        return responseJson(view === "CONCEPT" ? conceptPayload : view === "REGION" ? regionPayload : industryPayload);
      }
      throw new Error(`unexpected url: ${url}`);
    });
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    await within(panel).findByText("一级行业1");

    const industryTab = within(panel).getByRole("tab", { name: "行业" });
    fireEvent.keyDown(industryTab, { key: "ArrowRight" });
    expect(within(panel).getByRole("tab", { name: "概念" })).toHaveFocus();
    expect(within(panel).queryByText("一级行业1")).not.toBeInTheDocument();
    expect((await within(panel).findAllByText("概念板块1")).length).toBeGreaterThan(0);
    expect(within(panel).getAllByText("沸腾 · 升温").length).toBeGreaterThan(0);
    expect(within(panel).getByLabelText("最近20日热度").children).toHaveLength(20);

    fireEvent.keyDown(within(panel).getByRole("tab", { name: "概念" }), { key: "ArrowRight" });
    expect(within(panel).getByRole("tab", { name: "地域" })).toHaveFocus();
    expect(await within(panel).findByText("地域板块31")).toBeInTheDocument();
    expect(within(panel).getByLabelText("地域板块排行").querySelectorAll(".sector-rank-card")).toHaveLength(31);
    const breadth = within(panel).getByLabelText("地域成分涨跌分布");
    expect(within(breadth).getByText("上涨 18")).toBeInTheDocument();
    expect(within(breadth).getByText("下跌 4")).toBeInTheDocument();
    expect(requestUrls.some((url) => url.includes("view=CONCEPT") && url.includes("conceptRankMetric=HEAT_SCORE"))).toBe(true);
    expect(requestUrls.some((url) => url.includes("view=REGION") && url.includes("regionRankMetric=CHANGE_PCT"))).toBe(true);
  });

  it("ignores a stale response after a fast tab switch", async () => {
    let resolveIndustry: ((value: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlOf(input);
      if (url.includes("/context")) return responseJson(pageContextPayload);
      if (url.includes("/sector-overview")) {
        const view = new URL(url).searchParams.get("view");
        if (view === "INDUSTRY") return new Promise<Response>((resolve) => { resolveIndustry = resolve; });
        return responseJson(conceptPayload);
      }
      throw new Error(`unexpected url: ${url}`);
    });
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    await waitFor(() => expect(resolveIndustry).toBeTypeOf("function"));
    fireEvent.click(within(panel).getByRole("tab", { name: "概念" }));
    expect((await within(panel).findAllByText("概念板块1")).length).toBeGreaterThan(0);
    resolveIndustry?.(responseJson(industryPayload));
    await act(async () => Promise.resolve());
    expect(within(panel).getAllByText("概念板块1").length).toBeGreaterThan(0);
    expect(within(panel).queryByText("一级行业1")).not.toBeInTheDocument();
  });

  it("maps HTTP 403 to the stable forbidden state", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlOf(input);
      if (url.includes("/context")) return responseJson(pageContextPayload);
      if (url.includes("/sector-overview")) return responseJson({ code: "forbidden", message: "Forbidden" }, 403);
      throw new Error(`unexpected url: ${url}`);
    });
    const rendered = render(<MarketOverviewPage />);
    await act(async () => Promise.resolve());
    const panel = rendered.container.querySelector<HTMLElement>('[aria-label="板块速览"]');
    expect(panel).not.toBeNull();
    if (!panel) throw new Error("sector-overview panel not found");
    expect(await within(panel).findByText("无查看权限")).toBeInTheDocument();
  });

  it("uses debug and shows timeout with retry", async () => {
    vi.useFakeTimers();
    const requestUrls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = urlOf(input);
      requestUrls.push(url);
      if (url.includes("/context")) return Promise.resolve(responseJson(pageContextPayload));
      const signal = init?.signal;
      return new Promise<Response>((_, reject) => signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
    });
    window.history.pushState({}, "", "/market/overview?debug=1");
    const rendered = render(<MarketOverviewPage />);
    await act(async () => Promise.resolve());
    const panel = rendered.container.querySelector<HTMLElement>('[aria-label="板块速览"]');
    expect(panel).not.toBeNull();
    if (!panel) throw new Error("sector-overview panel not found");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(panel).getByText("请求超时：/api/v1/wealth/market/sector-overview")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(requestUrls.some((url) => url.includes("/sector-overview") && new URL(url).searchParams.get("debug") === "1")).toBe(true);
  }, 15000);
});
