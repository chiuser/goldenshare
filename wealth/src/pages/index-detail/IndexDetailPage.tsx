import { useXxmForecast } from "../../features/index-detail/xxm-forecast/useXxmForecast";
import { loadIndexNineTurnSeries } from "../../features/index-detail/api/indexNineTurnLoader";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useIndexDebugModule } from "../../features/index-detail/debug/useIndexDebugModule";
import type { IndexRecognitionDebugExtension } from "../../features/index-detail/debug/types";

import {
  buildIndexDetailPath,
  DEFAULT_WEALTH_PATH,
  navigateWealth,
  resolveTopMarketNavPath,
  returnToWealthOverview,
} from "../../app/routes/routerState";
import { IndexChartWorkspace } from "../../features/index-detail/chart/IndexChartWorkspace";
import { IndexMinuteChartWorkspace } from "../../features/index-detail/chart/IndexMinuteChartWorkspace";
import { useIndexDetailController } from "../../features/index-detail/controller/useIndexDetailController";
import { useIndexMinuteSeries } from "../../features/index-detail/controller/useIndexMinuteSeries";
import { useIndexWeights } from "../../features/index-detail/controller/useIndexWeights";
import { IndexBreadcrumbActionBar } from "../../features/index-detail/layout/IndexBreadcrumbActionBar";
import { IndexChartToolbar } from "../../features/index-detail/layout/IndexChartToolbar";
import { getIndexShellIdentity, getIndexShellPeriods, normalizeIndexTsCode } from "../../features/index-detail/model/indexDetailState";
import type { IndexInfoTab, IndexPeriodKey } from "../../features/index-detail/model/indexDetailTypes";
import { INDEX_TECHNICAL_NINE_TURN_PERIODS, type IndexTechnicalNineTurnSummary } from "../../features/index-detail/model/indexTechnicalNineTurnSummary";
import { IndexInfoRail } from "../../features/index-detail/sidebar/IndexInfoRail";
import { IndexDetailLoadingSkeleton } from "../../features/index-detail/state/IndexDetailLoadingSkeleton";
import { IndexDetailPageState } from "../../features/index-detail/state/IndexDetailPageState";
import { IndexDetailToast } from "../../features/index-detail/ui/IndexDetailToast";
import {
  buildMajorIndicesViewModelFromApi,
  buildTopMarketTickersFromMajorIndices,
} from "../../features/major-indices/api/marketMajorIndicesAdapter";
import { fetchMarketMajorIndices } from "../../features/major-indices/api/marketMajorIndicesApi";
import type { NineTurnPeriod } from "../../features/nine-turn/api/nineTurnApiTypes";
import { useNineTurnSeriesRegistry } from "../../features/nine-turn/controller/useNineTurnSeriesRegistry";
import { resolveIndexRecognitionAvailability } from "../../features/index-detail/model/indexRecognitionAvailability";
import { DAILY_CHART_PAGE_SIZE } from "../../shared/charts/dailyChartRequestLimits";
import { unsupportedNineTurnLayer } from "../../features/nine-turn/model/nineTurnAdapter";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import type { TopMarketNavKey, TopMarketTicker } from "../../shared/ui/top-market-bar/topMarketBarTypes";
import "./index-detail-page.css";

interface IndexDetailPageProps { search: string; tsCode: string; }

const EMPTY_NINE_TURN_PERIODS: NineTurnPeriod[] = [];
export function IndexDetailPage({ search, tsCode }: IndexDetailPageProps) {
  const [activePeriod, setActivePeriod] = useState<IndexPeriodKey>("day");
  const controller = useIndexDetailController(tsCode, search, activePeriod === "day");
  const [activeTab, setActiveTab] = useState<IndexInfoTab>("basic");
  const [toast, setToast] = useState("");
  const tickers = useTopMarketTickers();
  const normalizedTsCode = normalizeIndexTsCode(tsCode);
  const debug = useMemo(() => new URLSearchParams(search).get("debug") === "1" ? 1 as const : undefined, [search]);
  const hasData = controller.phase === "ready" || controller.phase === "delayed" || controller.phase === "partial";
  const weights = useIndexWeights({
    active: activeTab === "weights" && hasData,
    asOfTradeDate: controller.viewModel?.asOfTradeDate ?? null,
    debug,
    tsCode: normalizedTsCode,
  });
  const viewModel = controller.viewModel;
  const identity = viewModel?.identity ?? getIndexShellIdentity(normalizedTsCode);
  const periods = viewModel?.periods ?? getIndexShellPeriods();
  const nineTurnRegistry = useNineTurnSeriesRegistry({
    dailyLimit: DAILY_CHART_PAGE_SIZE,
    endDate: viewModel?.asOfTradeDate ?? null,
    load: loadIndexNineTurnSeries,
    subjectType: "index",
    supportedPeriods: viewModel?.capabilities.nineTurnPeriods ?? EMPTY_NINE_TURN_PERIODS,
    supportsNineTurn: viewModel?.capabilities.supportsNineTurn ?? false,
    tsCode: normalizedTsCode,
  });
  const { recognitionEnabled, debugEnabled } = resolveIndexRecognitionAvailability({ development: import.meta.env.DEV,
    tsCode: normalizedTsCode, validatedTsCode: hasData && viewModel?.identity.tsCode === normalizedTsCode ? normalizedTsCode : null, search });
  const debugModule = useIndexDebugModule(debugEnabled);
  const readyModule = debugEnabled && debugModule.phase === "ready" ? debugModule.module : null;
  const effectiveDebug = readyModule ? 1 as const : 0 as const;
  const ownerKey = `${normalizedTsCode}|${activePeriod}|${viewModel?.asOfTradeDate ?? ""}`;
  const debugOwner = useRef<string | null>(null);
  debugOwner.current = readyModule && hasData ? ownerKey : null;
  const [debugExtension, setDebugExtension] = useState<IndexRecognitionDebugExtension | null>(null);
  const onDebugChange = useCallback((owner: string, extension: IndexRecognitionDebugExtension | null) => {
    if (debugOwner.current === owner) setDebugExtension(extension);
  }, []);
  useEffect(() => { if (!readyModule || !hasData) setDebugExtension(null); }, [readyModule, hasData]);
  const extension = readyModule && debugExtension?.ownerKey === ownerKey ? debugExtension : undefined;
  const DebugController = readyModule?.IndexRecognitionDebug;
  const recognition = { recognitionEnabled, debug: effectiveDebug,
    decodeXxmDebug: readyModule?.decodeXxmDebug, renderXxmDetails: readyModule?.renderXxmDetails };
  const forecast = useXxmForecast({
    active: recognitionEnabled && activeTab === "technical" && hasData,
    enabled: recognitionEnabled, debug: effectiveDebug, decodeDebug: readyModule?.decodeForecastDebug,
    tsCode: normalizedTsCode,
    historicalDate: new URLSearchParams(search).has("tradeDate") ? viewModel?.asOfTradeDate ?? undefined : undefined,
    minutes: import.meta.env.DEV && (viewModel?.capabilities.supportsMinute ?? false),
  });
  const activeNineTurnPeriod = nineTurnPeriodFromIndexPeriod(activePeriod);
  const nineTurnLayer = activeNineTurnPeriod === null
    ? unsupportedNineTurnLayer("1")
    : nineTurnRegistry.stateFor(activeNineTurnPeriod);
  const minute = useIndexMinuteSeries({
    activePeriod,
    enabled: viewModel?.capabilities.supportsMinute ?? false,
    endDate: viewModel?.asOfTradeDate ?? null,
    tsCode: normalizedTsCode,
  });

  useEffect(() => {
    if (controller.phase === "loading" || controller.phase === "empty") setActiveTab("basic");
  }, [controller.phase, normalizedTsCode]);

  useEffect(() => {
    setActivePeriod("day");
  }, [normalizedTsCode]);

  useEffect(() => {
    if (viewModel && !viewModel.periods.some((period) => period.key === activePeriod && period.supported)) {
      setActivePeriod("day");
    }
  }, [activePeriod, viewModel]);

  useEffect(() => {
    if (!hasData || activeNineTurnPeriod === null) return;
    void nineTurnRegistry.ensure(activeNineTurnPeriod);
  }, [activeNineTurnPeriod, hasData, nineTurnRegistry.ensure]);

  useEffect(() => {
    if (!hasData || activeTab !== "technical") return;
    INDEX_TECHNICAL_NINE_TURN_PERIODS.forEach(({ period }) => {
      if (viewModel?.capabilities.nineTurnPeriods.includes(period)) {
        void nineTurnRegistry.ensure(period);
      }
    });
  }, [activeTab, hasData, nineTurnRegistry.ensure, viewModel]);

  const historyError = controller.history?.error;
  useEffect(() => {
    if (!historyError) return;
    setToast(historyError);
    const timer = window.setTimeout(() => setToast(current => current === historyError ? "" : current), 1800);
    return () => {
      window.clearTimeout(timer);
      setToast(current => current === historyError ? "" : current);
    };
  }, [historyError]);

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 1800);
  }

  function handleTopNavigate(target: TopMarketNavKey) {
    const path = resolveTopMarketNavPath(target);
    if (path) {
      navigateWealth(path);
      return;
    }
    showToast("该入口暂未开放");
  }

  function showRecentTradeDay() {
    const params = new URLSearchParams(search);
    params.delete("tradeDate");
    const query = params.toString();
    navigateWealth(`${buildIndexDetailPath(normalizedTsCode)}${query ? `?${query}` : ""}`, { replace: true });
    if (!new URLSearchParams(search).has("tradeDate")) controller.retry();
  }

  const pageShell = <>
    <TopMarketBar
      activeNav="market"
      onNavigate={handleTopNavigate}
      onTickerSelect={(tickerCode) => navigateWealth(buildIndexDetailPath(tickerCode))}
      tickers={tickers}
    />
    <IndexBreadcrumbActionBar identity={identity} onReturnHome={returnToWealthOverview} />
    <IndexChartToolbar
      activePeriod={periods.some((period) => period.key === activePeriod && period.supported) ? activePeriod : "day"}
      identity={identity}
      onAction={showToast}
      onPeriodChange={setActivePeriod}
      periods={periods}
    />
  </>;

  if (controller.phase === "loading") {
    return (
      <div className="index-detail-app">
        {pageShell}
        <main className="index-detail-main-content" aria-label="MainContent">
          <IndexDetailLoadingSkeleton supportsTrend={normalizedTsCode === "000001.SH"} />
        </main>
        <IndexDetailToast message={toast} />
      </div>
    );
  }

  if (controller.phase === "error" || controller.phase === "forbidden" || controller.phase === "notFound") {
    const variant = controller.phase === "forbidden"
      ? "forbidden"
      : controller.phase === "notFound" && controller.errorCode === "ID_REQUEST_INVALID"
        ? "requestInvalid"
        : controller.phase === "notFound" ? "notFound" : "error";
    return (
      <div className="index-detail-app">
        {pageShell}
        <main className="index-detail-main-content full" aria-label="MainContent">
          <IndexDetailPageState
            onBack={() => navigateWealth(DEFAULT_WEALTH_PATH)}
            onRetry={controller.phase === "error" ? controller.retry : undefined}
            variant={variant}
          />
        </main>
        <IndexDetailToast message={toast} />
      </div>
    );
  }

  if (!viewModel) return null;
  const displayedWeights = controller.phase === "empty"
    ? { ...weights, data: null, errorMessage: "", phase: "empty" as const }
    : weights;

  return (
    <div className="index-detail-app">
      {pageShell}
      <main className="index-detail-main-content" aria-label="MainContent">
        {controller.phase === "empty" ? (
          <IndexDetailPageState
            onBack={() => navigateWealth(DEFAULT_WEALTH_PATH)}
            onRecentDay={showRecentTradeDay}
            onRetry={controller.retry}
            variant="empty"
          />
        ) : (
          <div className="index-detail-chart-region">
          {activePeriod === "day" ? (
            <IndexChartWorkspace
              recognition={recognition}
              debugExtension={extension}
              nineTurnLayer={nineTurnLayer}
              onNineTurnRetry={() => {
                if (activeNineTurnPeriod !== null) void nineTurnRegistry.retry(activeNineTurnPeriod);
              }}
              onTrendRetry={controller.retryTrend}
              history={controller.history}
              trend={controller.trend}
              trendPhase={controller.trendPhase}
              viewModel={viewModel}
            />
          ) : (
            <IndexMinuteChartWorkspace
              recognition={recognition}
              data={minute.data}
              errorMessage={minute.errorMessage}
              nineTurnLayer={nineTurnLayer}
              onNineTurnRetry={() => {
                if (activeNineTurnPeriod !== null) void nineTurnRegistry.retry(activeNineTurnPeriod);
              }}
              onRetry={minute.retry}
              phase={minute.phase}
            />
          )}
          {DebugController ? <DebugController ownerKey={ownerKey} tsCode={normalizedTsCode}
            activePeriod={activePeriod} ordinaryAsOfDate={viewModel.asOfTradeDate}
            supportsNineTurn={viewModel.capabilities.supportsNineTurn}
            supportsTrend={viewModel.capabilities.supportsTrendChannel} onChange={onDebugChange} /> : null}
          {debugEnabled && (debugModule.phase === "loading" || debugModule.phase === "error") ?
            <div className="index-debug-module-status" role="status">
              {debugModule.phase === "loading" ? "核验工具加载中" : <>{debugModule.errorMessage} · <button type="button" onClick={debugModule.retry}>重试</button></>}
            </div> : null}
          </div>
        )}
        <IndexInfoRail
          forecast={recognitionEnabled ? { ...forecast, renderDebugDetails: readyModule?.renderForecastDetails } : undefined}
          activeTab={activeTab}
          onAction={showToast}
          onTabChange={setActiveTab}
          onNineTurnRetry={(period) => { void nineTurnRegistry.retry(period); }}
          onTrendRetry={controller.retryTrend}
          pagePhase={controller.phase}
          partialReasons={controller.partialReasons}
          trend={controller.trend}
          trendPhase={controller.trendPhase}
          viewModel={viewModel}
          weights={displayedWeights}
          nineTurnSummary={Object.fromEntries(
            INDEX_TECHNICAL_NINE_TURN_PERIODS.map(({ period }) => [period, nineTurnRegistry.stateFor(period)]),
          ) as IndexTechnicalNineTurnSummary}
        />
      </main>
      <IndexDetailToast message={toast} />
    </div>
  );
}

function nineTurnPeriodFromIndexPeriod(period: IndexPeriodKey): NineTurnPeriod | null {
  if (period === "day") return "day";
  const match = /^m(5|15|30|60|90|120)$/.exec(period);
  return match ? match[1] as NineTurnPeriod : null;
}

function useTopMarketTickers(): TopMarketTicker[] {
  const [tickers, setTickers] = useState<TopMarketTicker[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    fetchMarketMajorIndices({ market: "CN_A" }, { signal: controller.signal })
      .then((payload) => setTickers([
        ...buildTopMarketTickersFromMajorIndices(buildMajorIndicesViewModelFromApi(payload)),
      ]))
      .catch(() => { if (!controller.signal.aborted) setTickers([]); });
    return () => controller.abort();
  }, []);
  return tickers;
}
