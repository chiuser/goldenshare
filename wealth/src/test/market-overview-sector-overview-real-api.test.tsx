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

function metric(value: number | null, displayText?: string) {
  return {
    value,
    displayText: displayText ?? (value == null ? "--" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`),
    direction: value == null ? "UNKNOWN" : value > 0 ? "UP" : value < 0 ? "DOWN" : "FLAT",
  };
}

function leader(name: string) {
  return { stockCode: "000001.SZ", stockName: `${name}领涨股`, changePct: 9.98 };
}

function industryRankItem(code: string, name: string, rank: number, level: 1 | 2 | 3, selected = false) {
  return {
    rank,
    sectorCode: code,
    sectorName: name,
    industryLevel: level,
    primaryMetric: metric(6 - rank),
    leader: leader(name),
    selected,
  };
}

function conceptRankItem(code: string, name: string, rank: number, selected = false) {
  return {
    rank,
    sectorCode: code,
    sectorName: name,
    changePct: metric(rank === 6 ? -0.42 : 3.5 - rank / 10),
    mainNetInflow: metric(4_000_000_000 - rank * 10_000_000, `+${(40 - rank / 10).toFixed(1)}亿`),
    leader: leader(name),
    heatStatus: "VALID",
    heatLevel: rank === 1 ? "BOILING" : rank < 4 ? "HOT" : "ACTIVE",
    heatTrend: rank === 5 ? "STABLE" : rank > 5 ? "COOLING" : "HEATING",
    heatScore: metric(93 - rank, `${93 - rank}`),
    heatDelta1d: metric(19 - rank, `${19 - rank > 0 ? "+" : ""}${19 - rank}`),
    selected,
  };
}

function regionRankItem(code: string, name: string, rank: number, selected = false) {
  return {
    rank,
    sectorCode: code,
    sectorName: name,
    changePct: metric(rank === 6 ? -0.42 : 3.5 - rank / 10),
    mainNetInflow: metric(rank === 6 ? -320_000_000 : 4_300_000_000 - rank * 10_000_000, rank === 6 ? "-3.2亿" : `+${(43 - rank / 10).toFixed(1)}亿`),
    memberCount: 111 + rank,
    upCount: 77 + rank,
    leader: leader(name),
    selected,
  };
}

function detailBase(code: string, name: string, sectorType: "INDUSTRY" | "CONCEPT" | "REGION") {
  return {
    sectorCode: code,
    sectorName: name,
    sectorType,
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
      mainNetInflow: 1_280_000_000,
      turnoverAmount: 8_520_000_000,
      quoteCoverage: 1,
    },
    leader: leader(name),
    members: Array.from({ length: 5 }, (_, index) => ({
      stockCode: `00000${index + 1}.SZ`,
      stockName: `成分股${index + 1}`,
      changePct: 5 - index,
      direction: "UP",
    })),
  };
}

function industryDetail(code: string, name: string) {
  return { ...detailBase(code, name, "INDUSTRY"), hierarchyPath: `一级 / 二级 / ${name}` };
}

function conceptDetail(code: string, name: string) {
  return {
    ...detailBase(code, name, "CONCEPT"),
    heat: {
      heatStatus: "VALID",
      invalidReason: null,
      heatScore: 92,
      heatLevel: "BOILING",
      heatDelta1d: 18,
      heatTrend: "HEATING",
      heatRank: 1,
      scoreVersion: "concept-heat-eod-v1",
      tradeDate: "2026-05-11",
      calculatedAt: "2026-05-11T20:00:00+08:00",
    },
    heatHistory: Array.from({ length: 20 }, (_, index) => ({
      tradeDate: `2026-04-${String(index + 1).padStart(2, "0")}`,
      heatScore: index === 8 ? null : 70 + index,
      heatRank: index === 8 ? null : index + 1,
      heatLevel: index === 8 ? "NONE" : index > 17 ? "BOILING" : "HOT",
    })),
  };
}

function regionDetail(code: string, name: string) {
  return detailBase(code, name, "REGION");
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
        { level: 1, parentSectorCode: null, rows: Array.from({ length: 5 }, (_, index) => industryRankItem(`BK000${index + 1}.DC`, `一级行业${index + 1}`, index + 1, 1, index === 0)) },
        { level: 2, parentSectorCode: "BK0001.DC", rows: Array.from({ length: 5 }, (_, index) => industryRankItem(`BK010${index + 1}.DC`, `二级行业${index + 1}`, index + 1, 2, index === 0)) },
        { level: 3, parentSectorCode: "BK0101.DC", rows: Array.from({ length: 5 }, (_, index) => industryRankItem(`BK020${index + 1}.DC`, `三级行业${index + 1}`, index + 1, 3, index === 0)) },
      ],
      detail: industryDetail("BK0201.DC", "三级行业1"),
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
      rows: Array.from({ length: 20 }, (_, index) => conceptRankItem(`BK10${String(index + 1).padStart(2, "0")}.DC`, `概念板块${index + 1}`, index + 1, index === 0)),
      detail: conceptDetail("BK1001.DC", "概念板块1"),
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
      rows: Array.from({ length: 31 }, (_, index) => regionRankItem(`BK20${String(index + 1).padStart(2, "0")}.DC`, `地域板块${index + 1}`, index + 1, index === 0)),
      detail: regionDetail("BK2001.DC", "地域板块1"),
    },
  },
};

function responseJson(payload: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as Response;
}

function urlOf(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
}

function installFetch(payloadForView: (view: string | null) => unknown = (view) => view === "CONCEPT" ? conceptPayload : view === "REGION" ? regionPayload : industryPayload) {
  const requestUrls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = urlOf(input);
    requestUrls.push(url);
    if (url.includes("/context")) return responseJson(pageContextPayload);
    if (url.includes("/sector-overview")) return responseJson(payloadForView(new URL(url).searchParams.get("view")));
    throw new Error(`unexpected url: ${url}`);
  });
  return requestUrls;
}

const payloadByView = {
  INDUSTRY: industryPayload,
  CONCEPT: conceptPayload,
  REGION: regionPayload,
} as const;

const viewLabel = { INDUSTRY: "行业", CONCEPT: "概念", REGION: "地域" } as const;

type MatrixView = keyof typeof payloadByView;
type MatrixState = "READY" | "PARTIAL" | "DELAYED" | "EMPTY" | "ERROR" | "FORBIDDEN" | "LOADING";

function payloadWithState(view: MatrixView, state: Exclude<MatrixState, "FORBIDDEN" | "LOADING">): unknown {
  const payload = structuredClone(payloadByView[view]) as unknown as {
    pageStatus: { displayText: string };
    sectorOverview: { status: string };
  };
  payload.sectorOverview.status = state;
  payload.pageStatus.displayText = state === "ERROR" ? "板块数据异常" : `板块状态 ${state}`;
  return payload;
}

const viewStateMatrix = (Object.keys(payloadByView) as MatrixView[]).flatMap((view) =>
  (["READY", "PARTIAL", "DELAYED", "EMPTY", "ERROR", "FORBIDDEN", "LOADING"] as MatrixState[])
    .map((state) => ({ view, state })),
);

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

  it("renders the formal industry 3x5 workspace and omits tradeDate on the default request", async () => {
    const requestUrls = installFetch();
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    expect(await within(panel).findByRole("heading", { name: "板块速览 V2" })).toBeInTheDocument();
    for (const label of ["一级行业", "二级行业", "三级行业"]) {
      expect(within(within(panel).getByLabelText(label)).getAllByRole("button", { name: /选择/ })).toHaveLength(5);
    }
    expect(within(panel).getByText("同层级兄弟节点")).toBeInTheDocument();
    expect(within(panel).getAllByText("三级行业1领涨股").length).toBeGreaterThan(0);
    expect(within(panel).getByText("成分股1")).toBeInTheDocument();
    expect(within(panel).queryByText("停牌")).not.toBeInTheDocument();
    expect(within(panel).queryByText("行情覆盖")).not.toBeInTheDocument();
    expect(within(panel).queryByText(/进入.*行情/)).not.toBeInTheDocument();
    const request = new URL(requestUrls.find((url) => url.includes("/sector-overview")) as string);
    expect(request.searchParams.get("view")).toBe("INDUSTRY");
    expect(request.searchParams.get("industryRankMetric")).toBe("CHANGE_PCT");
    expect(request.searchParams.has("tradeDate")).toBe(false);
  });

  it("renders the concept fixed columns, separate badges and a real 20-day gap", async () => {
    installFetch();
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    fireEvent.click(within(panel).getByRole("tab", { name: "概念" }));
    const ranking = await within(panel).findByRole("table", { name: "概念热度排行" });
    expect(within(panel).getByText("等级与趋势由 Heat Model V2 共同决定")).toBeInTheDocument();
    for (const column of ["排名 / 概念", "等级 / 趋势", "热度 / 变化", "涨跌幅", "领涨股"]) {
      expect(within(ranking).getByRole("columnheader", { name: column })).toBeInTheDocument();
    }
    expect(ranking.querySelectorAll(".concept-rank-item")).toHaveLength(20);
    expect(ranking.querySelector(".sector-flat-rank-viewport")).toHaveAttribute("data-visible-rows", "7");
    expect(within(ranking).getAllByText("沸腾").length).toBeGreaterThan(0);
    expect(within(ranking).getAllByText("升温").length).toBeGreaterThan(0);
    expect(within(ranking).queryByText("沸腾 · 升温")).not.toBeInTheDocument();
    const history = within(panel).getByLabelText("近20个交易日热度");
    expect(history.children).toHaveLength(20);
    expect(history.children[8]).toHaveClass("is-gap");
    expect(history.children[8]).not.toHaveAttribute("style");
    expect(within(panel).queryByText("停牌")).not.toBeInTheDocument();
    expect(within(panel).queryByText("行情覆盖")).not.toBeInTheDocument();
  });

  it("renders the region fixed columns, seven-row viewport and breadth", async () => {
    installFetch();
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    fireEvent.click(within(panel).getByRole("tab", { name: "地域" }));
    const ranking = await within(panel).findByRole("table", { name: "地域板块排行" });
    for (const column of ["排名 / 地域", "上涨家数", "主力净流入", "涨跌幅", "领涨股"]) {
      expect(within(ranking).getByRole("columnheader", { name: column })).toBeInTheDocument();
    }
    expect(ranking.querySelectorAll(".region-rank-item")).toHaveLength(31);
    expect(ranking.querySelector(".sector-flat-rank-viewport")).toHaveAttribute("data-visible-rows", "7");
    const breadth = within(panel).getByLabelText("地域成分涨跌分布");
    expect(within(breadth).getByText("上涨 18")).toBeInTheDocument();
    expect(within(breadth).getByText("下跌 4")).toBeInTheDocument();
  });

  it("keeps leader navigation independent from sector selection and member navigation", async () => {
    const requestUrls = installFetch();
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    await within(panel).findByText("一级行业1");
    const before = requestUrls.filter((url) => url.includes("/sector-overview")).length;
    fireEvent.click(within(panel).getAllByRole("button", { name: "进入一级行业1领涨股股票详情" })[0]);
    expect(window.location.pathname).toBe("/wealth/market/stock/000001.SZ");
    expect(requestUrls.filter((url) => url.includes("/sector-overview"))).toHaveLength(before);
  });

  it("shows the approved no-leader copy without a stock navigation target", async () => {
    const payload = structuredClone(industryPayload) as unknown as {
      sectorOverview: {
        industry: {
          columns: Array<{ rows: Array<{ leader: ReturnType<typeof leader> | null }> }>;
          detail: Omit<ReturnType<typeof industryDetail>, "leader"> & { leader: ReturnType<typeof leader> | null };
        };
      };
    };
    payload.sectorOverview.industry.columns[0].rows[0].leader = null;
    payload.sectorOverview.industry.detail.leader = null;
    installFetch(() => payload);
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    expect((await within(panel).findAllByText("暂无领涨股")).length).toBeGreaterThan(0);
    expect(within(panel).queryByRole("button", { name: "进入一级行业1领涨股股票详情" })).not.toBeInTheDocument();
    expect(panel.querySelector(".sector-leader-card.is-empty")).not.toBeNull();
  });

  it("uses an explicit URL tradeDate only for an explicit sector request", async () => {
    const requestUrls = installFetch();
    render(<MarketOverviewPage search="?tradeDate=2026-05-11" />);
    await screen.findByLabelText("板块速览");
    await waitFor(() => {
      const request = requestUrls.find((url) => url.includes("/sector-overview"));
      expect(request).toBeDefined();
      expect(new URL(request as string).searchParams.get("tradeDate")).toBe("2026-05-11");
    });
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
    expect(await within(panel).findByRole("table", { name: "概念热度排行" })).toBeInTheDocument();
    resolveIndustry?.(responseJson(industryPayload));
    await act(async () => Promise.resolve());
    expect(within(panel).getByRole("table", { name: "概念热度排行" })).toBeInTheDocument();
    expect(within(panel).queryByText("一级行业1")).not.toBeInTheDocument();
  });

  it("maps HTTP 403 to the stable forbidden workspace", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlOf(input);
      if (url.includes("/context")) return responseJson(pageContextPayload);
      if (url.includes("/sector-overview")) return responseJson({ code: "forbidden", message: "Forbidden" }, 403);
      throw new Error(`unexpected url: ${url}`);
    });
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    expect(await within(panel).findByText("无查看权限")).toBeInTheDocument();
    expect(within(panel).getByLabelText("行业工作台骨架")).toBeInTheDocument();
  });

  it.each(["ERROR", "UNRECOGNIZED"])("fails closed for %s without leaving the stable workspace", async (status) => {
    const payload = structuredClone(industryPayload) as typeof industryPayload & { sectorOverview: { status: string } };
    payload.sectorOverview.status = status;
    payload.pageStatus.displayText = "板块数据异常";
    installFetch(() => payload);
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    expect(await within(panel).findByText(status === "ERROR" ? "板块数据异常" : "板块速览返回了未知状态")).toBeInTheDocument();
    expect(within(panel).getByLabelText("行业工作台骨架")).toBeInTheDocument();
  });

  it("shows timeout with retry on the stable workspace", async () => {
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
    expect(within(panel).getByLabelText("行业工作台骨架")).toBeInTheDocument();
    expect(requestUrls.some((url) => url.includes("/sector-overview") && new URL(url).searchParams.get("debug") === "1")).toBe(true);
  }, 15000);

  it.each(viewStateMatrix)("S13-A15-P01 keeps the stable $view workspace for $state", async ({ view, state }) => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlOf(input);
      if (url.includes("/context")) return responseJson(pageContextPayload);
      if (!url.includes("/sector-overview")) throw new Error(`unexpected url: ${url}`);
      if (state === "FORBIDDEN") return responseJson({ code: "forbidden", message: "Forbidden" }, 403);
      if (state === "LOADING") return new Promise<Response>(() => undefined);
      const requestedView = (new URL(url).searchParams.get("view") ?? "INDUSTRY") as MatrixView;
      return responseJson(payloadWithState(requestedView, state));
    });

    const rendered = render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    if (view !== "INDUSTRY") fireEvent.click(within(panel).getByRole("tab", { name: viewLabel[view] }));

    const skeletonLabel = `${viewLabel[view]}工作台骨架`;
    if (["EMPTY", "ERROR", "FORBIDDEN", "LOADING"].includes(state)) {
      expect(await within(panel).findByLabelText(skeletonLabel)).toBeInTheDocument();
    } else if (view === "INDUSTRY") {
      expect(await within(panel).findByLabelText("一级行业")).toBeInTheDocument();
    } else {
      expect(await within(panel).findByRole("table", { name: view === "CONCEPT" ? "概念热度排行" : "地域板块排行" })).toBeInTheDocument();
    }

    expect(panel).toHaveClass("sector-overview-v2", `view-${view.toLowerCase()}`);
    if (state === "PARTIAL") expect(within(panel).getByText("部分指标或热度暂不可用，已保留可用事实")).toBeInTheDocument();
    if (state === "DELAYED") expect(within(panel).getByText("当前展示 2026-05-11 盘后数据")).toBeInTheDocument();
    if (state === "EMPTY") expect(within(panel).getByText("暂无数据")).toBeInTheDocument();
    if (state === "ERROR") expect(within(panel).getByText("板块数据异常")).toBeInTheDocument();
    if (state === "FORBIDDEN") expect(within(panel).getByText("无查看权限")).toBeInTheDocument();
    if (state === "LOADING") expect(within(panel).getByText("正在加载")).toBeInTheDocument();
    rendered.unmount();
  });

  it("S13-A10-A11-P01 keeps seven rows scrollable and four approved detail metrics", async () => {
    installFetch();
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");

    for (const view of ["CONCEPT", "REGION"] as const) {
      fireEvent.click(within(panel).getByRole("tab", { name: viewLabel[view] }));
      const ranking = await within(panel).findByRole("table", { name: view === "CONCEPT" ? "概念热度排行" : "地域板块排行" });
      const viewport = ranking.querySelector<HTMLElement>(".sector-flat-rank-viewport");
      expect(viewport).not.toBeNull();
      if (!viewport) throw new Error("rank viewport not found");
      expect(viewport).toHaveAttribute("data-visible-rows", "7");
      expect(viewport).toHaveClass("sector-flat-rank-viewport");
      expect(viewport.querySelectorAll('[role="row"]')).toHaveLength(view === "CONCEPT" ? 20 : 31);
      expect(viewport.contains(within(ranking).getAllByRole("columnheader")[0])).toBe(false);
      fireEvent.scroll(viewport, { target: { scrollTop: 240 } });
      expect(viewport.scrollTop).toBe(240);
      expect(panel.querySelectorAll(".sector-detail-metrics > div")).toHaveLength(4);
    }
  });

  it("S13-A03-A04-A11-A12-A13-PN01 renders long names, nulls, amounts and Heat gaps without invented facts", async () => {
    const payload = structuredClone(conceptPayload) as unknown as {
      sectorOverview: {
        concept: {
          rows: Array<ReturnType<typeof conceptRankItem>>;
          detail: {
            metrics: { changePct: number | null; mainNetInflow: number | null };
            members: Array<{ stockCode: string; stockName: string | null }>;
            heatHistory: Array<{ tradeDate: string; heatScore: number | null; heatRank: number | null; heatLevel: string }>;
          };
        };
      };
    };
    const longName = "超长概念板块名称用于验证单行省略与完整提示";
    payload.sectorOverview.concept.rows[0].sectorName = longName;
    payload.sectorOverview.concept.rows[0].changePct = metric(null);
    payload.sectorOverview.concept.rows[0].mainNetInflow = metric(123_400_000_000, "+1234亿");
    payload.sectorOverview.concept.rows[1].heatLevel = "NONE";
    payload.sectorOverview.concept.rows[1].heatTrend = "STABLE";
    payload.sectorOverview.concept.rows[2].heatStatus = "UNKNOWN";
    payload.sectorOverview.concept.rows[2].heatLevel = "NONE";
    payload.sectorOverview.concept.rows[2].heatTrend = "UNKNOWN";
    payload.sectorOverview.concept.rows[2].heatScore = metric(null);
    payload.sectorOverview.concept.rows[2].heatDelta1d = metric(null);
    payload.sectorOverview.concept.detail.metrics.changePct = null;
    payload.sectorOverview.concept.detail.metrics.mainNetInflow = 123_400_000_000;
    payload.sectorOverview.concept.detail.members[0].stockName = null;

    installFetch((view) => view === "CONCEPT" ? payload : industryPayload);
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    fireEvent.click(within(panel).getByRole("tab", { name: "概念" }));
    const ranking = await within(panel).findByRole("table", { name: "概念热度排行" });

    expect(within(ranking).getByRole("button", { name: `选择${longName}` })).toHaveAttribute("title", longName);
    expect(within(ranking).getAllByText("--").length).toBeGreaterThanOrEqual(3);
    expect(within(ranking).getAllByText("平稳").length).toBeGreaterThan(0);
    expect(within(ranking).getByText("UNKNOWN")).toBeInTheDocument();
    expect(within(ranking).queryByText("NONE")).not.toBeInTheDocument();
    expect(within(panel).getByText("+1234亿")).toBeInTheDocument();
    expect(within(panel).getByText("000001.SZ", { selector: ".sector-members button span" })).toBeInTheDocument();
    const history = within(panel).getByLabelText("近20个交易日热度");
    expect(history.children).toHaveLength(20);
    expect(history.children[8]).toHaveClass("is-gap");
    expect(history.children[8]).not.toHaveAttribute("style");
  });

  it("S13-A14-A16-PN01 keeps sector selection separate from keyboard-accessible stock navigation", async () => {
    const requestUrls = installFetch();
    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    await within(panel).findByText("一级行业1");

    const regionTab = within(panel).getByRole("tab", { name: "地域" });
    const industryTab = within(panel).getByRole("tab", { name: "行业" });
    industryTab.focus();
    fireEvent.keyDown(industryTab, { key: "ArrowRight" });
    expect(within(panel).getByRole("tab", { name: "概念" })).toHaveFocus();
    fireEvent.keyDown(within(panel).getByRole("tab", { name: "概念" }), { key: "End" });
    expect(regionTab).toHaveFocus();
    await within(panel).findByRole("table", { name: "地域板块排行" });

    const sectorButton = within(panel).getByRole("button", { name: "选择地域板块2" });
    sectorButton.focus();
    expect(sectorButton).toHaveFocus();
    fireEvent.click(sectorButton);
    await waitFor(() => expect(requestUrls.some((url) => new URL(url).searchParams.get("selectedRegionCode") === "BK2002.DC")).toBe(true));
    expect(window.location.pathname).toBe("/");

    const memberButton = within(panel).getByRole("button", { name: "进入成分股1股票详情" });
    memberButton.focus();
    expect(memberButton).toHaveFocus();
    fireEvent.click(memberButton);
    expect(window.location.pathname).toBe("/wealth/market/stock/000001.SZ");
    expect(panel.querySelector("button button")).toBeNull();
    expect(within(panel).queryByText(/进入.*行情/)).not.toBeInTheDocument();
  });

  it("S13-A05-A15-P01 retains ready facts while refreshing and reports a failed refresh without mock fallback", async () => {
    let rejectRefresh: ((reason?: unknown) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlOf(input);
      if (url.includes("/context")) return responseJson(pageContextPayload);
      if (!url.includes("/sector-overview")) throw new Error(`unexpected url: ${url}`);
      if (new URL(url).searchParams.get("industryRankMetric") === "MAIN_NET_INFLOW") {
        return new Promise<Response>((_resolve, reject) => { rejectRefresh = reject; });
      }
      return responseJson(industryPayload);
    });

    render(<MarketOverviewPage />);
    const panel = await screen.findByLabelText("板块速览");
    expect(await within(panel).findByText("一级行业1")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "主力净流入" }));
    expect(await within(panel).findByText("正在更新…")).toBeInTheDocument();
    expect(within(panel).getByText("一级行业1")).toBeInTheDocument();

    rejectRefresh?.(new Error("真实接口不可用"));
    expect(await within(panel).findByText("真实接口不可用")).toBeInTheDocument();
    expect(within(panel).getByLabelText("行业工作台骨架")).toBeInTheDocument();
    expect(within(panel).queryByText("行业一")).not.toBeInTheDocument();
  });
});
