import { useEffect, useMemo, useState } from "react";
import { marketOverviewModuleSources } from "../../features/market-overview/api/moduleSources";
import { fetchMarketOverviewMock } from "../../features/market-overview/api/marketOverviewMockAdapter";
import type { MarketOverview, QuoteItem } from "../../features/market-overview/api/marketOverviewTypes";
import { MarketBreadthPanel } from "../../features/market-overview/breadth/MarketBreadthPanel";
import {
  buildBreadthViewModelFromApi,
  buildBreadthViewModelFromMock,
  type MarketBreadthViewModel,
} from "../../features/market-overview/breadth/api/marketBreadthAdapter";
import { fetchMarketBreadth, type BreadthDebugInfo } from "../../features/market-overview/breadth/api/marketBreadthApi";
import {
  buildMarketPageContextViewModelFromApi,
  type MarketPageContextViewModel,
} from "../../features/market-overview/context/api/marketPageContextAdapter";
import { fetchMarketPageContext } from "../../features/market-overview/context/api/marketPageContextApi";
import { MajorIndexPanel } from "../../features/market-overview/indices/MajorIndexPanel";
import {
  buildMajorIndicesViewModelFromApi,
  buildMajorIndicesViewModelFromMock,
  type MarketMajorIndicesViewModel,
} from "../../features/market-overview/indices/api/marketMajorIndicesAdapter";
import { fetchMarketMajorIndices, type MajorIndicesDebugInfo } from "../../features/market-overview/indices/api/marketMajorIndicesApi";
import { Breadcrumb } from "../../features/market-overview/layout/Breadcrumb";
import { PageHeader } from "../../features/market-overview/layout/PageHeader";
import { ShortcutBar } from "../../features/market-overview/layout/ShortcutBar";
import { TopMarketBar } from "../../features/market-overview/layout/TopMarketBar";
import { LeaderboardPanel } from "../../features/market-overview/leaderboards/LeaderboardPanel";
import {
  buildLeaderboardsViewModelFromApi,
  buildLeaderboardsViewModelFromMock,
  type MarketLeaderboardsViewModel,
} from "../../features/market-overview/leaderboards/api/marketLeaderboardsAdapter";
import { fetchMarketLeaderboards, type LeaderboardsDebugInfo } from "../../features/market-overview/leaderboards/api/marketLeaderboardsApi";
import { LimitBoardPanel } from "../../features/market-overview/limit-up/LimitBoardPanel";
import { StreakLadderPanel } from "../../features/market-overview/limit-up/StreakLadderPanel";
import {
  buildLimitUpViewModelFromApi,
  buildLimitUpViewModelFromMock,
  type MarketLimitUpViewModel,
} from "../../features/market-overview/limit-up/api/marketLimitUpAdapter";
import { fetchMarketLimitUp, type LimitUpDebugInfo } from "../../features/market-overview/limit-up/api/marketLimitUpApi";
import { buildStreakLadderViewModelFromApi } from "../../features/market-overview/limit-up/api/marketStreakLadderAdapter";
import {
  fetchMarketStreakLadder,
  type StreakLadderDebugInfo,
} from "../../features/market-overview/limit-up/api/marketStreakLadderApi";
import { MarketMoneyFlowPanel } from "../../features/market-overview/money-flow/MarketMoneyFlowPanel";
import {
  buildMoneyFlowViewModelFromApi,
  buildMoneyFlowViewModelFromMock,
  type MarketMoneyFlowViewModel,
} from "../../features/market-overview/money-flow/api/marketMoneyFlowAdapter";
import { fetchMarketMoneyFlow, type MoneyFlowDebugInfo } from "../../features/market-overview/money-flow/api/marketMoneyFlowApi";
import { MarketNewsPanel } from "../../features/market-overview/news/MarketNewsPanel";
import { MarketNewsPanelGroup } from "../../features/market-overview/news/MarketNewsPanelGroup";
import {
  buildNewsBriefsViewModelFromApi,
  buildStockNewsViewModelFromApi,
  type MarketNewsPanelViewModel,
} from "../../features/market-overview/news/api/marketNewsAdapter";
import {
  fetchMarketNewsBriefs,
  fetchStockNews,
  type MarketNewsDebugInfo,
} from "../../features/market-overview/news/api/marketNewsApi";
import { SectorOverviewPanel } from "../../features/market-overview/sectors/SectorOverviewPanel";
import {
  buildSectorOverviewViewModelFromApi,
  buildSectorOverviewViewModelFromMock,
  type MarketSectorOverviewViewModel,
} from "../../features/market-overview/sectors/api/marketSectorOverviewAdapter";
import {
  fetchMarketSectorOverview,
  type SectorOverviewDebugInfo,
} from "../../features/market-overview/sectors/api/marketSectorOverviewApi";
import { MarketStylePanel } from "../../features/market-overview/style/MarketStylePanel";
import {
  buildStyleViewModelFromApi,
  buildStyleViewModelFromMock,
  type MarketStyleViewModel,
} from "../../features/market-overview/style/api/marketStyleAdapter";
import { fetchMarketStyle, type StyleDebugInfo } from "../../features/market-overview/style/api/marketStyleApi";
import { MarketSummaryPanel } from "../../features/market-overview/summary/MarketSummaryPanel";
import { buildSummaryViewModelFromApi, buildSummaryViewModelFromMock, type MarketSummaryViewModel } from "../../features/market-overview/summary/api/marketSummaryAdapter";
import { fetchMarketSummary, type SummaryDebugInfo } from "../../features/market-overview/summary/api/marketSummaryApi";
import { TurnoverOverviewPanel } from "../../features/market-overview/turnover/TurnoverOverviewPanel";
import {
  buildTurnoverViewModelFromApi,
  buildTurnoverViewModelFromMock,
  type MarketTurnoverViewModel,
} from "../../features/market-overview/turnover/api/marketTurnoverAdapter";
import { fetchMarketTurnover, type TurnoverDebugInfo } from "../../features/market-overview/turnover/api/marketTurnoverApi";
import { SkeletonBlock } from "../../shared/ui/SkeletonBlock";
import "./market-overview-page.css";

const SUMMARY_FETCH_TIMEOUT_MS = 5000;
const MAJOR_INDICES_FETCH_TIMEOUT_MS = 5000;
const BREADTH_FETCH_TIMEOUT_MS = 5000;
const STYLE_FETCH_TIMEOUT_MS = 5000;
const TURNOVER_FETCH_TIMEOUT_MS = 5000;
const MONEY_FLOW_FETCH_TIMEOUT_MS = 5000;
const NEWS_FETCH_TIMEOUT_MS = 5000;
const LEADERBOARDS_FETCH_TIMEOUT_MS = 5000;
const LIMIT_UP_FETCH_TIMEOUT_MS = 5000;
const STREAK_LADDER_FETCH_TIMEOUT_MS = 5000;
const SECTOR_OVERVIEW_FETCH_TIMEOUT_MS = 5000;
const PAGE_CONTEXT_FETCH_TIMEOUT_MS = 5000;

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function buildHeaderTickers(
  overview: MarketOverview | null,
  majorIndices: MarketMajorIndicesViewModel | null,
): QuoteItem[] {
  const fallback = overview?.tickers ?? [];
  if (!majorIndices?.indices.length) return fallback;

  const mapped = majorIndices.indices.flatMap<QuoteItem>((row) => {
    if (!isFiniteNumber(row.point) || !isFiniteNumber(row.change) || !isFiniteNumber(row.pct)) {
      return [];
    }
    return [
      {
        code: row.code,
        name: row.name,
        point: row.point,
        change: row.change,
        pct: row.pct,
        direction: row.direction,
      },
    ];
  });

  return mapped.length > 0 ? mapped : fallback;
}

export function MarketOverviewPage() {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [pageContext, setPageContext] = useState<MarketPageContextViewModel | null>(null);
  const [pageContextViewState, setPageContextViewState] = useState<"loading" | "ready" | "error">("loading");
  const [pageContextErrorMessage, setPageContextErrorMessage] = useState<string | null>(null);
  const [summary, setSummary] = useState<MarketSummaryViewModel | null>(null);
  const [summaryViewState, setSummaryViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.summary === "real" ? "loading" : "ready",
  );
  const [summaryErrorMessage, setSummaryErrorMessage] = useState<string | null>(null);
  const [summaryDebugInfo, setSummaryDebugInfo] = useState<SummaryDebugInfo | null>(null);
  const [majorIndices, setMajorIndices] = useState<MarketMajorIndicesViewModel | null>(null);
  const [majorIndicesViewState, setMajorIndicesViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.majorIndices === "real" ? "loading" : "ready",
  );
  const [majorIndicesErrorMessage, setMajorIndicesErrorMessage] = useState<string | null>(null);
  const [majorIndicesDebugInfo, setMajorIndicesDebugInfo] = useState<MajorIndicesDebugInfo | null>(null);
  const [breadth, setBreadth] = useState<MarketBreadthViewModel | null>(null);
  const [breadthViewState, setBreadthViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.breadth === "real" ? "loading" : "ready",
  );
  const [breadthErrorMessage, setBreadthErrorMessage] = useState<string | null>(null);
  const [breadthDebugInfo, setBreadthDebugInfo] = useState<BreadthDebugInfo | null>(null);
  const [style, setStyle] = useState<MarketStyleViewModel | null>(null);
  const [styleViewState, setStyleViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.style === "real" ? "loading" : "ready",
  );
  const [styleErrorMessage, setStyleErrorMessage] = useState<string | null>(null);
  const [styleDebugInfo, setStyleDebugInfo] = useState<StyleDebugInfo | null>(null);
  const [turnover, setTurnover] = useState<MarketTurnoverViewModel | null>(null);
  const [turnoverViewState, setTurnoverViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.turnover === "real" ? "loading" : "ready",
  );
  const [turnoverErrorMessage, setTurnoverErrorMessage] = useState<string | null>(null);
  const [turnoverDebugInfo, setTurnoverDebugInfo] = useState<TurnoverDebugInfo | null>(null);
  const [moneyFlow, setMoneyFlow] = useState<MarketMoneyFlowViewModel | null>(null);
  const [moneyFlowViewState, setMoneyFlowViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.moneyFlow === "real" ? "loading" : "ready",
  );
  const [moneyFlowErrorMessage, setMoneyFlowErrorMessage] = useState<string | null>(null);
  const [moneyFlowDebugInfo, setMoneyFlowDebugInfo] = useState<MoneyFlowDebugInfo | null>(null);
  const [newsBriefs, setNewsBriefs] = useState<MarketNewsPanelViewModel | null>(null);
  const [newsBriefsViewState, setNewsBriefsViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.news === "real" ? "loading" : "ready",
  );
  const [newsBriefsErrorMessage, setNewsBriefsErrorMessage] = useState<string | null>(null);
  const [newsBriefsDebugInfo, setNewsBriefsDebugInfo] = useState<MarketNewsDebugInfo | null>(null);
  const [stockNews, setStockNews] = useState<MarketNewsPanelViewModel | null>(null);
  const [stockNewsViewState, setStockNewsViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.news === "real" ? "loading" : "ready",
  );
  const [stockNewsErrorMessage, setStockNewsErrorMessage] = useState<string | null>(null);
  const [stockNewsDebugInfo, setStockNewsDebugInfo] = useState<MarketNewsDebugInfo | null>(null);
  const [leaderboards, setLeaderboards] = useState<MarketLeaderboardsViewModel | null>(null);
  const [leaderboardsViewState, setLeaderboardsViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.leaderboards === "real" ? "loading" : "ready",
  );
  const [leaderboardsErrorMessage, setLeaderboardsErrorMessage] = useState<string | null>(null);
  const [leaderboardsDebugInfo, setLeaderboardsDebugInfo] = useState<LeaderboardsDebugInfo | null>(null);
  const [limitUp, setLimitUp] = useState<MarketLimitUpViewModel | null>(null);
  const [limitUpViewState, setLimitUpViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.limitUp === "real" ? "loading" : "ready",
  );
  const [limitUpErrorMessage, setLimitUpErrorMessage] = useState<string | null>(null);
  const [limitUpDebugInfo, setLimitUpDebugInfo] = useState<LimitUpDebugInfo | null>(null);
  const [streakLadder, setStreakLadder] = useState<MarketOverview["ladderV5"] | null>(null);
  const [streakLadderViewState, setStreakLadderViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.streakLadder === "real" ? "loading" : "ready",
  );
  const [streakLadderErrorMessage, setStreakLadderErrorMessage] = useState<string | null>(null);
  const [streakLadderDebugInfo, setStreakLadderDebugInfo] = useState<StreakLadderDebugInfo | null>(null);
  const [sectorOverview, setSectorOverview] = useState<MarketSectorOverviewViewModel | null>(null);
  const [sectorOverviewViewState, setSectorOverviewViewState] = useState<"loading" | "ready" | "error">(
    marketOverviewModuleSources.sectors === "real" ? "loading" : "ready",
  );
  const [sectorOverviewErrorMessage, setSectorOverviewErrorMessage] = useState<string | null>(null);
  const [sectorOverviewDebugInfo, setSectorOverviewDebugInfo] = useState<SectorOverviewDebugInfo | null>(null);
  const [toast, setToast] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const headerTickers = useMemo(() => buildHeaderTickers(overview, majorIndices), [overview, majorIndices]);
  const pageDebugEnabled = useMemo(() => {
    if (!import.meta.env.DEV) return false;
    if (typeof window === "undefined") return false;
    return new URLSearchParams(window.location.search).get("debug") === "1";
  }, []);
  const overviewDebugInfo = useMemo(() => {
    if (!pageDebugEnabled) return null;
    const moduleItems = [
      ...(summaryDebugInfo?.modules ?? []),
      ...(majorIndicesDebugInfo?.modules ?? []),
      ...(breadthDebugInfo?.modules ?? []),
      ...(styleDebugInfo?.modules ?? []),
      ...(turnoverDebugInfo?.modules ?? []),
      ...(moneyFlowDebugInfo?.modules ?? []),
      ...(newsBriefsDebugInfo?.modules ?? []),
      ...(stockNewsDebugInfo?.modules ?? []),
      ...(leaderboardsDebugInfo?.modules ?? []),
      ...(limitUpDebugInfo?.modules ?? []),
      ...(streakLadderDebugInfo?.modules ?? []),
      ...(sectorOverviewDebugInfo?.modules ?? []),
    ];
    const exceptionItems = [
      ...(summaryDebugInfo?.exceptions ?? []),
      ...(majorIndicesDebugInfo?.exceptions ?? []),
      ...(breadthDebugInfo?.exceptions ?? []),
      ...(styleDebugInfo?.exceptions ?? []),
      ...(turnoverDebugInfo?.exceptions ?? []),
      ...(moneyFlowDebugInfo?.exceptions ?? []),
      ...(newsBriefsDebugInfo?.exceptions ?? []),
      ...(stockNewsDebugInfo?.exceptions ?? []),
      ...(leaderboardsDebugInfo?.exceptions ?? []),
      ...(limitUpDebugInfo?.exceptions ?? []),
      ...(streakLadderDebugInfo?.exceptions ?? []),
      ...(sectorOverviewDebugInfo?.exceptions ?? []),
    ];
    if (!moduleItems.length && !exceptionItems.length) return null;
    return { modules: moduleItems, exceptions: exceptionItems };
  }, [
    pageDebugEnabled,
    summaryDebugInfo,
    majorIndicesDebugInfo,
    breadthDebugInfo,
    styleDebugInfo,
    turnoverDebugInfo,
    moneyFlowDebugInfo,
    newsBriefsDebugInfo,
    stockNewsDebugInfo,
    leaderboardsDebugInfo,
    limitUpDebugInfo,
    streakLadderDebugInfo,
    sectorOverviewDebugInfo,
  ]);

  useEffect(() => {
    let canceled = false;
    const abortController = new AbortController();
    const timeoutId = window.setTimeout(() => abortController.abort(), PAGE_CONTEXT_FETCH_TIMEOUT_MS);
    setPageContext(null);
    setPageContextViewState("loading");
    setPageContextErrorMessage(null);

    fetchMarketPageContext({ market: "CN_A" }, { signal: abortController.signal })
      .then((payload) => {
        if (!canceled) {
          setPageContext(buildMarketPageContextViewModelFromApi(payload));
          setPageContextViewState("ready");
          setPageContextErrorMessage(null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? "请求超时：/api/v1/wealth/market/context"
            : error instanceof Error
              ? error.message
              : "页面时间上下文加载失败";
          setPageContext(null);
          setPageContextViewState("error");
          setPageContextErrorMessage(message);
          showToast(`页面时间上下文异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, []);

  useEffect(() => {
    fetchMarketOverviewMock().then((response) => {
      setOverview(response.data);
      if (marketOverviewModuleSources.summary === "mock") {
        setSummary(buildSummaryViewModelFromMock(response.data));
        setSummaryViewState("ready");
      } else {
        setSummary(null);
        setSummaryViewState("loading");
        setSummaryErrorMessage(null);
      }
      if (marketOverviewModuleSources.majorIndices === "mock") {
        setMajorIndices(buildMajorIndicesViewModelFromMock(response.data.indices));
        setMajorIndicesViewState("ready");
      } else {
        setMajorIndices(null);
        setMajorIndicesViewState("loading");
        setMajorIndicesErrorMessage(null);
      }
      if (marketOverviewModuleSources.breadth === "mock") {
        setBreadth(buildBreadthViewModelFromMock(response.data));
        setBreadthViewState("ready");
      } else {
        setBreadth(null);
        setBreadthViewState("loading");
        setBreadthErrorMessage(null);
      }
      if (marketOverviewModuleSources.style === "mock") {
        setStyle(buildStyleViewModelFromMock(response.data));
        setStyleViewState("ready");
      } else {
        setStyle(null);
        setStyleViewState("loading");
        setStyleErrorMessage(null);
      }
      if (marketOverviewModuleSources.turnover === "mock") {
        setTurnover(buildTurnoverViewModelFromMock(response.data));
        setTurnoverViewState("ready");
      } else {
        setTurnover(null);
        setTurnoverViewState("loading");
        setTurnoverErrorMessage(null);
      }
      if (marketOverviewModuleSources.moneyFlow === "mock") {
        setMoneyFlow(buildMoneyFlowViewModelFromMock(response.data));
        setMoneyFlowViewState("ready");
      } else {
        setMoneyFlow(null);
        setMoneyFlowViewState("loading");
        setMoneyFlowErrorMessage(null);
      }
      if (marketOverviewModuleSources.leaderboards === "mock") {
        setLeaderboards(buildLeaderboardsViewModelFromMock(response.data));
        setLeaderboardsViewState("ready");
      } else {
        setLeaderboards(null);
        setLeaderboardsViewState("loading");
        setLeaderboardsErrorMessage(null);
      }
      if (marketOverviewModuleSources.news === "real") {
        setNewsBriefs(null);
        setNewsBriefsViewState("loading");
        setNewsBriefsErrorMessage(null);
        setStockNews(null);
        setStockNewsViewState("loading");
        setStockNewsErrorMessage(null);
      }
      if (marketOverviewModuleSources.limitUp === "mock") {
        setLimitUp(buildLimitUpViewModelFromMock(response.data));
        setLimitUpViewState("ready");
      } else {
        setLimitUp(null);
        setLimitUpViewState("loading");
        setLimitUpErrorMessage(null);
      }
      if (marketOverviewModuleSources.streakLadder === "mock") {
        setStreakLadder(response.data.ladderV5 ?? null);
        setStreakLadderViewState("ready");
      } else {
        setStreakLadder(null);
        setStreakLadderViewState("loading");
        setStreakLadderErrorMessage(null);
      }
      if (marketOverviewModuleSources.sectors === "mock") {
        setSectorOverview(buildSectorOverviewViewModelFromMock(response.data));
        setSectorOverviewViewState("ready");
      } else {
        setSectorOverview(null);
        setSectorOverviewViewState("loading");
        setSectorOverviewErrorMessage(null);
      }
    });
  }, []);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.news !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setNewsBriefs(null);
    setNewsBriefsViewState("loading");
    setNewsBriefsErrorMessage(null);
    setNewsBriefsDebugInfo(null);
    setStockNews(null);
    setStockNewsViewState("loading");
    setStockNewsErrorMessage(null);
    setStockNewsDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), NEWS_FETCH_TIMEOUT_MS);

    const requestParams = { market: "CN_A" as const, tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? (1 as const) : (0 as const) };
    const briefsPromise = fetchMarketNewsBriefs(requestParams, { signal: abortController.signal })
      .then((payload) => {
        if (!canceled) {
          setNewsBriefs(buildNewsBriefsViewModelFromApi(payload));
          setNewsBriefsViewState("ready");
          setNewsBriefsErrorMessage(null);
          setNewsBriefsDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/news/briefs`
            : error instanceof Error
              ? error.message
              : "新闻速览加载失败";
          setNewsBriefs(null);
          setNewsBriefsViewState("error");
          setNewsBriefsErrorMessage(message);
          setNewsBriefsDebugInfo(null);
          showToast(`新闻速览模块异常：${message}`);
        }
      });

    const stocksPromise = fetchStockNews(requestParams, { signal: abortController.signal })
      .then((payload) => {
        if (!canceled) {
          setStockNews(buildStockNewsViewModelFromApi(payload));
          setStockNewsViewState("ready");
          setStockNewsErrorMessage(null);
          setStockNewsDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/news/stocks`
            : error instanceof Error
              ? error.message
              : "个股新闻加载失败";
          setStockNews(null);
          setStockNewsViewState("error");
          setStockNewsErrorMessage(message);
          setStockNewsDebugInfo(null);
          showToast(`个股新闻模块异常：${message}`);
        }
      });

    Promise.allSettled([briefsPromise, stocksPromise]).finally(() => {
      window.clearTimeout(timeoutId);
    });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.summary !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setSummary(null);
    setSummaryViewState("loading");
    setSummaryErrorMessage(null);
    setSummaryDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), SUMMARY_FETCH_TIMEOUT_MS);

    fetchMarketSummary(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setSummary(buildSummaryViewModelFromApi(payload));
          setSummaryViewState("ready");
          setSummaryErrorMessage(null);
          setSummaryDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout ? `请求超时：/api/v1/wealth/market/summary` : error instanceof Error ? error.message : "客观总结加载失败";
          setSummaryDebugInfo(null);
          setSummary(null);
          setSummaryViewState("error");
          setSummaryErrorMessage(message);
          showToast(`客观总结模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.limitUp !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setLimitUp(null);
    setLimitUpViewState("loading");
    setLimitUpErrorMessage(null);
    setLimitUpDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), LIMIT_UP_FETCH_TIMEOUT_MS);

    fetchMarketLimitUp(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setLimitUp(buildLimitUpViewModelFromApi(payload));
          setLimitUpViewState("ready");
          setLimitUpErrorMessage(null);
          setLimitUpDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/limit-up/summary`
            : error instanceof Error
              ? error.message
              : "涨跌停统计与分布加载失败";
          setLimitUp(null);
          setLimitUpViewState("error");
          setLimitUpErrorMessage(message);
          setLimitUpDebugInfo(null);
          showToast(`涨跌停统计与分布模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.streakLadder !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setStreakLadder(null);
    setStreakLadderViewState("loading");
    setStreakLadderErrorMessage(null);
    setStreakLadderDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), STREAK_LADDER_FETCH_TIMEOUT_MS);

    fetchMarketStreakLadder(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setStreakLadder(buildStreakLadderViewModelFromApi(payload));
          setStreakLadderViewState("ready");
          setStreakLadderErrorMessage(null);
          setStreakLadderDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/streak-ladder`
            : error instanceof Error
              ? error.message
              : "连板天梯加载失败";
          setStreakLadder(null);
          setStreakLadderViewState("error");
          setStreakLadderErrorMessage(message);
          setStreakLadderDebugInfo(null);
          showToast(`连板天梯模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.breadth !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setBreadth(null);
    setBreadthViewState("loading");
    setBreadthErrorMessage(null);
    setBreadthDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), BREADTH_FETCH_TIMEOUT_MS);

    fetchMarketBreadth(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setBreadth(buildBreadthViewModelFromApi(payload));
          setBreadthViewState("ready");
          setBreadthErrorMessage(null);
          setBreadthDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout ? `请求超时：/api/v1/wealth/market/breadth` : error instanceof Error ? error.message : "涨跌分布加载失败";
          setBreadth(null);
          setBreadthViewState("error");
          setBreadthErrorMessage(message);
          setBreadthDebugInfo(null);
          showToast(`涨跌分布模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.majorIndices !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setMajorIndices(null);
    setMajorIndicesViewState("loading");
    setMajorIndicesErrorMessage(null);
    setMajorIndicesDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), MAJOR_INDICES_FETCH_TIMEOUT_MS);

    fetchMarketMajorIndices(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setMajorIndices(buildMajorIndicesViewModelFromApi(payload));
          setMajorIndicesViewState("ready");
          setMajorIndicesErrorMessage(null);
          setMajorIndicesDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/major-indices`
            : error instanceof Error
              ? error.message
              : "主要指数加载失败";
          setMajorIndices(null);
          setMajorIndicesViewState("error");
          setMajorIndicesErrorMessage(message);
          setMajorIndicesDebugInfo(null);
          showToast(`主要指数模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.style !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setStyle(null);
    setStyleViewState("loading");
    setStyleErrorMessage(null);
    setStyleDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), STYLE_FETCH_TIMEOUT_MS);

    fetchMarketStyle(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setStyle(buildStyleViewModelFromApi(payload));
          setStyleViewState("ready");
          setStyleErrorMessage(null);
          setStyleDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout ? `请求超时：/api/v1/wealth/market/style` : error instanceof Error ? error.message : "市场风格加载失败";
          setStyle(null);
          setStyleViewState("error");
          setStyleErrorMessage(message);
          setStyleDebugInfo(null);
          showToast(`市场风格模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.turnover !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setTurnover(null);
    setTurnoverViewState("loading");
    setTurnoverErrorMessage(null);
    setTurnoverDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), TURNOVER_FETCH_TIMEOUT_MS);

    fetchMarketTurnover(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setTurnover(buildTurnoverViewModelFromApi(payload));
          setTurnoverViewState("ready");
          setTurnoverErrorMessage(null);
          setTurnoverDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/turnover`
            : error instanceof Error
              ? error.message
              : "成交额总览加载失败";
          setTurnover(null);
          setTurnoverViewState("error");
          setTurnoverErrorMessage(message);
          setTurnoverDebugInfo(null);
          showToast(`成交额总览模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.leaderboards !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setLeaderboards(null);
    setLeaderboardsViewState("loading");
    setLeaderboardsErrorMessage(null);
    setLeaderboardsDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), LEADERBOARDS_FETCH_TIMEOUT_MS);

    fetchMarketLeaderboards(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setLeaderboards(buildLeaderboardsViewModelFromApi(payload));
          setLeaderboardsViewState("ready");
          setLeaderboardsErrorMessage(null);
          setLeaderboardsDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/leaderboards`
            : error instanceof Error
              ? error.message
              : "榜单速览加载失败";
          setLeaderboards(null);
          setLeaderboardsViewState("error");
          setLeaderboardsErrorMessage(message);
          setLeaderboardsDebugInfo(null);
          showToast(`榜单速览模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.moneyFlow !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setMoneyFlow(null);
    setMoneyFlowViewState("loading");
    setMoneyFlowErrorMessage(null);
    setMoneyFlowDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), MONEY_FLOW_FETCH_TIMEOUT_MS);

    fetchMarketMoneyFlow(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setMoneyFlow(buildMoneyFlowViewModelFromApi(payload));
          setMoneyFlowViewState("ready");
          setMoneyFlowErrorMessage(null);
          setMoneyFlowDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/money-flow`
            : error instanceof Error
              ? error.message
              : "大盘资金流向加载失败";
          setMoneyFlow(null);
          setMoneyFlowViewState("error");
          setMoneyFlowErrorMessage(message);
          setMoneyFlowDebugInfo(null);
          showToast(`大盘资金流向模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  useEffect(() => {
    if (!overview || !pageContext) return;
    if (marketOverviewModuleSources.sectors !== "real") return;

    let canceled = false;
    const abortController = new AbortController();
    setSectorOverview(null);
    setSectorOverviewViewState("loading");
    setSectorOverviewErrorMessage(null);
    setSectorOverviewDebugInfo(null);
    const timeoutId = window.setTimeout(() => abortController.abort(), SECTOR_OVERVIEW_FETCH_TIMEOUT_MS);

    fetchMarketSectorOverview(
      { market: "CN_A", tradeDate: pageContext.tradeDate, debug: pageDebugEnabled ? 1 : 0 },
      { signal: abortController.signal },
    )
      .then((payload) => {
        if (!canceled) {
          setSectorOverview(buildSectorOverviewViewModelFromApi(payload));
          setSectorOverviewViewState("ready");
          setSectorOverviewErrorMessage(null);
          setSectorOverviewDebugInfo(pageDebugEnabled ? payload.debugInfo ?? null : null);
        }
      })
      .catch((error) => {
        if (!canceled) {
          const timeout = error instanceof DOMException && error.name === "AbortError";
          const message = timeout
            ? `请求超时：/api/v1/wealth/market/sector-overview`
            : error instanceof Error
              ? error.message
              : "板块速览加载失败";
          setSectorOverview(null);
          setSectorOverviewViewState("error");
          setSectorOverviewErrorMessage(message);
          setSectorOverviewDebugInfo(null);
          showToast(`板块速览模块异常：${message}`);
        }
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      canceled = true;
      abortController.abort();
    };
  }, [overview, pageContext, pageDebugEnabled]);

  function showToast(message: string) {
    setToast(message);
    window.clearTimeout(window.__wealthToastTimer);
    window.__wealthToastTimer = window.setTimeout(() => setToast(""), 1800);
  }

  function refresh() {
    setRefreshing(true);
    window.setTimeout(() => {
      setRefreshing(false);
      showToast(`市场总览已刷新：${pageContext?.updateTime ?? "页面时间上下文未就绪"}`);
    }, 900);
  }

  if (pageContextViewState === "error") {
    return (
      <main className="page-shell">
        <div className="state-block error-box">
          <strong>页面时间上下文加载失败</strong>
          <br />
          <span>{pageContextErrorMessage ?? "请稍后重试"}</span>
        </div>
        {toast ? <div id="toast">{toast}</div> : null}
      </main>
    );
  }

  if (!overview || !pageContext) {
    return (
      <main className="page-shell">
        <SkeletonBlock />
      </main>
    );
  }

  return (
    <div className="market-terminal">
      <TopMarketBar dataDelayText={overview.dataDelayText} onAction={showToast} statusText={overview.statusText} tickers={headerTickers} />
      <main className="page-shell">
        <Breadcrumb onAction={showToast} />
        <PageHeader refreshing={refreshing} tradeDate={pageContext.tradeDate} updateTime={pageContext.updateTime} onRefresh={refresh} />
        <ShortcutBar onAction={showToast} />
        <div className="content-grid">
          <MarketNewsPanelGroup
            marketNews={
              <MarketNewsPanel
                title="新闻速览"
                viewState={newsBriefsViewState}
                panel={newsBriefs}
                errorMessage={newsBriefsErrorMessage ?? undefined}
              />
            }
            stockNews={
              <MarketNewsPanel
                title="个股新闻"
                viewState={stockNewsViewState}
                panel={stockNews}
                errorMessage={stockNewsErrorMessage ?? undefined}
              />
            }
            marketSummary={
              <MarketSummaryPanel
                viewState={summaryViewState}
                facts={summary?.facts}
                layoutVariant={summary?.layoutVariant}
                statusLabel={summary?.statusLabel}
                statusTone={summary?.statusTone}
                textContent={summary?.textContent}
                textTitle={summary?.textTitle}
                errorMessage={summaryErrorMessage ?? undefined}
              />
            }
            majorIndices={
              <MajorIndexPanel
                viewState={majorIndicesViewState}
                indices={majorIndices?.indices}
                errorMessage={majorIndicesErrorMessage ?? undefined}
                onAction={showToast}
              />
            }
          />
          {overviewDebugInfo ? <OverviewDebugPanel debugInfo={overviewDebugInfo} /> : null}
          <div className="row-three">
            <MarketBreadthPanel
              viewState={breadthViewState}
              metrics={breadth?.metrics}
              chartsByRange={breadth?.chartsByRange}
              errorMessage={breadthErrorMessage ?? undefined}
            />
            <MarketStylePanel
              viewState={styleViewState}
              metrics={style?.metrics}
              chartsByRange={style?.chartsByRange}
              errorMessage={styleErrorMessage ?? undefined}
            />
            <TurnoverOverviewPanel
              viewState={turnoverViewState}
              turnover={turnover ?? undefined}
              errorMessage={turnoverErrorMessage ?? undefined}
            />
          </div>
          <div className="row-two">
            <MarketMoneyFlowPanel
              viewState={moneyFlowViewState}
              moneyFlow={moneyFlow ?? undefined}
              errorMessage={moneyFlowErrorMessage ?? undefined}
            />
            <LeaderboardPanel
              viewState={leaderboardsViewState}
              leaderboards={leaderboards ?? undefined}
              errorMessage={leaderboardsErrorMessage ?? undefined}
              onAction={showToast}
            />
          </div>
          <LimitBoardPanel
            viewState={limitUpViewState}
            limitUp={limitUp ?? undefined}
            errorMessage={limitUpErrorMessage ?? undefined}
          />
          <StreakLadderPanel
            overview={overview}
            ladder={streakLadder ?? undefined}
            viewState={streakLadderViewState}
            errorMessage={streakLadderErrorMessage ?? undefined}
            onAction={showToast}
          />
          <SectorOverviewPanel
            sectorOverview={sectorOverview}
            viewState={sectorOverviewViewState}
            errorMessage={sectorOverviewErrorMessage ?? undefined}
            onAction={showToast}
          />
          <StateBaselinePanel />
        </div>
      </main>
      {toast ? <div id="toast">{toast}</div> : null}
    </div>
  );
}

interface OverviewDebugInfo {
  modules: Array<{
    moduleKey: string;
    expectedTradeDate: string;
    observedTradeDate?: string | null;
    lagDays?: number | null;
    status: string;
    note?: string | null;
  }>;
  exceptions: Array<{
    module: string;
    code: string;
    severity: "info" | "warn" | "error";
    message: string;
  }>;
}

function OverviewDebugPanel({ debugInfo }: { debugInfo: OverviewDebugInfo }) {
  return (
    <section className="panel summary-debug-panel" aria-label="页面调试信息">
      <div className="section-header">
        <div className="section-title">页面调试信息（本地 DEV）</div>
      </div>
      <div className="summary-debug-grid">
        {debugInfo.modules.map((module) => (
          <div className="summary-debug-card" key={module.moduleKey}>
            <div className="summary-debug-title">{module.moduleKey}</div>
            <div className="summary-debug-line">expectedTradeDate: {module.expectedTradeDate}</div>
            <div className="summary-debug-line">observedTradeDate: {module.observedTradeDate ?? "-"}</div>
            <div className="summary-debug-line">lagDays: {module.lagDays ?? "-"}</div>
            <div className="summary-debug-line">status: {module.status}</div>
            <div className="summary-debug-line">note: {module.note ?? "-"}</div>
          </div>
        ))}
      </div>
      {debugInfo.exceptions.length ? (
        <div className="summary-debug-exceptions">
          {debugInfo.exceptions.map((exception, index) => (
            <div className="summary-debug-line" key={`${exception.module}-${exception.code}-${index}`}>
              [{exception.severity}] {exception.module} / {exception.code} - {exception.message}
            </div>
          ))}
        </div>
      ) : (
        <div className="summary-debug-line summary-debug-empty">exceptions: []</div>
      )}
    </section>
  );
}

function StateBaselinePanel() {
  return (
    <section className="panel" aria-label="状态样式基线">
      <div className="section-header">
        <div className="section-title">
          状态样式基线
          <span
            className="help"
            data-tip="供 Codex 和前端工程师落地时复用：loading、empty、error、hover、active、selected、data delayed。"
            title="供 Codex 和前端工程师落地时复用：loading、empty、error、hover、active、selected、data delayed。"
          >
            ?
          </span>
        </div>
        <span className="secondary">展示基础状态，不参与业务判断</span>
      </div>
      <div className="state-lab">
        <SkeletonBlock />
        <div className="state-block empty-box">
          <span>—</span>
          <span>empty：当前筛选条件下暂无数据，可切换最近交易日。</span>
        </div>
        <div className="state-block error-box">
          <strong>error</strong>
          <br />
          <span>503001 数据源不可用，可点击重试。</span>
        </div>
        <div className="state-block delayed-box">
          <strong>data delayed</strong>
          <br />
          <span>盘中源延迟 90s，历史数据已就绪。</span>
        </div>
      </div>
    </section>
  );
}

declare global {
  interface Window {
    __wealthToastTimer?: number;
  }
}
