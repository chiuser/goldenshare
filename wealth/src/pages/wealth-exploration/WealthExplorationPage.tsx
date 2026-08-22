import { useEffect, useMemo, useState } from "react";

import {
  buildIndexDetailPath,
  DEFAULT_WEALTH_PATH,
  navigateWealth,
  resolveTopMarketNavPath,
} from "../../app/routes/routerState";
import {
  buildMajorIndicesViewModelFromApi,
  buildTopMarketTickersFromMajorIndices,
} from "../../features/major-indices/api/marketMajorIndicesAdapter";
import { fetchMarketMajorIndices } from "../../features/major-indices/api/marketMajorIndicesApi";
import {
  buildMarketPageContextViewModelFromApi,
  type MarketPageContextViewModel,
} from "../../features/market-context/api/marketPageContextAdapter";
import {
  fetchMarketPageContext,
  readMarketContextRequest,
} from "../../features/market-context/api/marketPageContextApi";
import { useTurnoverInsightController } from "../../features/wealth-exploration/turnover-insight/model/useTurnoverInsightController";
import { TurnoverInsightSection } from "../../features/wealth-exploration/turnover-insight/ui/TurnoverInsightSection";
import { PageBreadcrumb } from "../../shared/ui/page-breadcrumb/PageBreadcrumb";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import type { TopMarketNavKey, TopMarketTicker } from "../../shared/ui/top-market-bar/topMarketBarTypes";
import "./wealth-exploration-page.css";

const PAGE_CONTEXT_TIMEOUT_MS = 5000;
const MAJOR_INDICES_TIMEOUT_MS = 5000;

type PageContextState =
  | { kind: "loading" }
  | { kind: "ready"; value: MarketPageContextViewModel }
  | { kind: "error"; message: string };

interface WealthExplorationPageProps {
  search?: string;
}

export function WealthExplorationPage({ search }: WealthExplorationPageProps) {
  const routeSearch = search ?? (typeof window === "undefined" ? "" : window.location.search);
  const contextRequest = useMemo(() => readMarketContextRequest(routeSearch), [routeSearch]);
  const debug = contextRequest.debug;
  const [contextAttempt, setContextAttempt] = useState(0);
  const [pageContext, setPageContext] = useState<PageContextState>({ kind: "loading" });
  const [tickers, setTickers] = useState<readonly TopMarketTicker[]>([]);
  const [toast, setToast] = useState("");

  useEffect(() => {
    let canceled = false;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), PAGE_CONTEXT_TIMEOUT_MS);
    setPageContext({ kind: "loading" });
    setTickers([]);

    fetchMarketPageContext(contextRequest, { signal: controller.signal })
      .then((payload) => {
        if (!canceled) setPageContext({ kind: "ready", value: buildMarketPageContextViewModelFromApi(payload) });
      })
      .catch((error) => {
        if (canceled) return;
        const timedOut = error instanceof DOMException && error.name === "AbortError";
        setPageContext({
          kind: "error",
          message: timedOut
            ? "页面时间上下文请求超时，请稍后重试。"
            : error instanceof Error ? error.message : "页面时间上下文加载失败。",
        });
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      canceled = true;
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [contextRequest.market, contextRequest.tradeDate, contextAttempt]);

  const resolvedContext = pageContext.kind === "ready" ? pageContext.value : null;

  useEffect(() => {
    if (!resolvedContext) {
      setTickers([]);
      return;
    }
    let canceled = false;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), MAJOR_INDICES_TIMEOUT_MS);
    setTickers([]);

    fetchMarketMajorIndices({
      market: resolvedContext.market,
      tradeDate: resolvedContext.tradeDate,
      debug,
    }, { signal: controller.signal })
      .then((payload) => {
        if (canceled) return;
        const viewModel = buildMajorIndicesViewModelFromApi(payload);
        setTickers(buildTopMarketTickersFromMajorIndices(viewModel));
      })
      .catch(() => {
        if (!canceled) setTickers([]);
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      canceled = true;
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [debug, resolvedContext?.market, resolvedContext?.tradeDate]);

  const turnoverRequest = useMemo(() => resolvedContext ? {
    market: resolvedContext.market,
    tradeDate: resolvedContext.tradeDate,
    debug,
  } : null, [debug, resolvedContext]);
  const turnover = useTurnoverInsightController(turnoverRequest);

  function handleTopNavigate(target: TopMarketNavKey) {
    const path = resolveTopMarketNavPath(target);
    if (path) {
      navigateWealth(path);
      return;
    }
    setToast("该入口暂未开放");
    window.setTimeout(() => setToast(""), 1800);
  }

  const contextFailed = pageContext.kind === "error";
  const sectionState = contextFailed ? "error" : turnover.viewState;
  const sectionError = contextFailed ? pageContext.message : turnover.errorMessage ?? undefined;

  return (
    <div className="market-terminal wealth-exploration-page">
      <TopMarketBar
        activeNav="exploration"
        onNavigate={handleTopNavigate}
        onTickerSelect={(tsCode) => navigateWealth(buildIndexDetailPath(tsCode))}
        tickers={tickers}
      />
      <main className="page-shell wealth-exploration-shell">
        <PageBreadcrumb
          items={[
            { label: "财势乾坤", path: DEFAULT_WEALTH_PATH },
            { label: "财势探查" },
          ]}
          onNavigate={navigateWealth}
          sessionStatus={resolvedContext?.sessionStatus ?? "CLOSED"}
        />
        <TurnoverInsightSection
          errorMessage={sectionError}
          model={contextFailed ? null : turnover.model}
          onRetry={contextFailed ? () => setContextAttempt((value) => value + 1) : turnover.retry}
          viewState={sectionState}
        />
        <div data-module-slot="sector-radar" />
      </main>
      {toast ? <div id="toast">{toast}</div> : null}
    </div>
  );
}
