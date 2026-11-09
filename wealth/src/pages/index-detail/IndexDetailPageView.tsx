import { useCallback, useEffect, useRef, useState, type ComponentType } from "react";

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
import { useDetailChartIndicatorControls } from "../../shared/charts/detail-workspace/useDetailChartIndicatorControls";
import { isXxmPeriod } from "../../features/index-detail/xxm/types";
import { unsupportedNineTurnLayer } from "../../features/nine-turn/model/nineTurnAdapter";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import type { TopMarketNavKey, TopMarketTicker } from "../../shared/ui/top-market-bar/topMarketBarTypes";
import "./index-detail-page.css";

import type { IndexChartAddonProps } from "../../features/index-detail/chart/IndexChartWorkspace";
import type { XxmLayerProps } from "../../features/index-detail/xxm/IndexXxmLayer";
import type { IndexDetailRequestScheduler } from "../../features/index-detail/api/indexDetailRequestScheduler";
import type { fetchIndexDetailKline, fetchIndexDetailPageInit, fetchIndexDetailWeights } from "../../features/index-detail/api/indexDetailApiClient";
import type { loadIndexNineTurnSeries } from "../../features/index-detail/api/indexNineTurnLoader";

export interface IndexForecastProps {
  active: boolean;
  enabled: boolean;
  tsCode: string;
  historicalDate?: string;
  minutes: boolean;
}
interface IndexDetailPageViewProps {
  tradeDate?: string;
  tsCode: string;
  onRecentDay: () => void;
  loadPageInit: typeof fetchIndexDetailPageInit;
  loadDailyKline: typeof fetchIndexDetailKline;
  loadWeights: typeof fetchIndexDetailWeights;
  weightsEndpoint: string;
  loadNineTurn: typeof loadIndexNineTurnSeries;
  requests?: IndexDetailRequestScheduler;
  SignalLayer?: ComponentType<XxmLayerProps>;
  MainChartAddon?: ComponentType<IndexChartAddonProps>;
  Forecast: ComponentType<IndexForecastProps>;
  showAlignmentDiagnostics?: boolean;
}

const EMPTY_NINE_TURN_PERIODS: NineTurnPeriod[] = [];
export function IndexDetailPageView({
  tradeDate, tsCode, onRecentDay, loadPageInit, loadDailyKline, loadWeights, weightsEndpoint,
  loadNineTurn, requests, SignalLayer, MainChartAddon, Forecast, showAlignmentDiagnostics,
}: IndexDetailPageViewProps) {
  const [activePeriod, setActivePeriod] = useState<IndexPeriodKey>("day");
  const controller = useIndexDetailController(tsCode, tradeDate, activePeriod === "day", loadPageInit, loadDailyKline, loadNineTurn);
  const [activeTab, setActiveTab] = useState<IndexInfoTab>("basic");
  const [toast, setToast] = useState("");
  const toastTimer = useRef<number | undefined>(undefined);
  const tickers = useTopMarketTickers();
  const normalizedTsCode = normalizeIndexTsCode(tsCode);
  const hasData = controller.phase === "ready" || controller.phase === "delayed" || controller.phase === "partial";
  const weights = useIndexWeights({
    active: activeTab === "weights" && hasData,
    asOfTradeDate: controller.viewModel?.asOfTradeDate ?? null,
    endpoint: weightsEndpoint,
    load: loadWeights,
    tsCode: normalizedTsCode,
  });
  const viewModel = controller.viewModel;
  const identity = viewModel?.identity ?? getIndexShellIdentity(normalizedTsCode);
  const periods = viewModel?.periods ?? getIndexShellPeriods();
  const nineTurnRegistry = useNineTurnSeriesRegistry({
    dailyLimit: DAILY_CHART_PAGE_SIZE,
    endDate: viewModel?.asOfTradeDate ?? null,
    load: loadNineTurn,
    subjectType: "index",
    supportedPeriods: viewModel?.capabilities.nineTurnPeriods ?? EMPTY_NINE_TURN_PERIODS,
    supportsNineTurn: viewModel?.capabilities.supportsNineTurn ?? false,
    tsCode: normalizedTsCode,
  });
  const recognitionEnabled = resolveIndexRecognitionAvailability({
    development: import.meta.env.DEV, tsCode: normalizedTsCode,
    validatedTsCode: hasData && viewModel?.identity.tsCode === normalizedTsCode ? normalizedTsCode : null,
  });
  const activeNineTurnPeriod = nineTurnPeriodFromIndexPeriod(activePeriod);
  const nineTurnLayer = activeNineTurnPeriod === null
    ? unsupportedNineTurnLayer("1")
    : nineTurnRegistry.stateFor(activeNineTurnPeriod);
  const minute = useIndexMinuteSeries({
    activePeriod,
    requests,
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

  const showToast = useCallback((message: string) => {
    window.clearTimeout(toastTimer.current);
    setToast(message);
    toastTimer.current = window.setTimeout(() => setToast(current => current === message ? "" : current), 1800);
  }, []);
  useEffect(() => () => window.clearTimeout(toastTimer.current), []);
  const showIndicatorLimit = useCallback(() => showToast("最多展示3个技术指标，请取消一个后再打开"), [showToast]);
  const quantitativeStructureAvailable = recognitionEnabled && isXxmPeriod(activePeriod)
    && (activePeriod === "day" || (viewModel?.capabilities.supportsMinute === true
      && minute.data?.tsCode === normalizedTsCode && `m${minute.data.freq}` === activePeriod));
  const indicatorControls = useDetailChartIndicatorControls(normalizedTsCode, quantitativeStructureAvailable, showIndicatorLimit);

  function handleTopNavigate(target: TopMarketNavKey) {
    const path = resolveTopMarketNavPath(target);
    if (path) {
      navigateWealth(path);
      return;
    }
    showToast("该入口暂未开放");
  }

  function showRecentTradeDay() {
    onRecentDay();
    if (tradeDate === undefined) controller.retry();
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
              recognitionEnabled={recognitionEnabled}
              SignalLayer={SignalLayer}
              MainChartAddon={MainChartAddon}
              showAlignmentDiagnostics={showAlignmentDiagnostics}
              indicatorControls={indicatorControls}
              nineTurnLayer={nineTurnLayer}
              onNineTurnRetry={() => {
                if (activeNineTurnPeriod !== null) void nineTurnRegistry.retry(activeNineTurnPeriod);
              }}
              history={controller.history}
              trend={controller.trend}
              trendPhase={controller.trendPhase}
              viewModel={viewModel}
            />
          ) : (
            <IndexMinuteChartWorkspace
              recognitionEnabled={recognitionEnabled}
              SignalLayer={SignalLayer}
              showAlignmentDiagnostics={showAlignmentDiagnostics}
              data={minute.data}
              errorMessage={minute.errorMessage}
              indicatorControls={indicatorControls}
              nineTurnLayer={nineTurnLayer}
              onNineTurnRetry={() => {
                if (activeNineTurnPeriod !== null) void nineTurnRegistry.retry(activeNineTurnPeriod);
              }}
              onRetry={minute.retry}
              phase={minute.phase}
            />
          )}
          </div>
        )}
        <IndexInfoRail
          forecast={recognitionEnabled && activeTab === "technical" ? <Forecast active={hasData}
            enabled={recognitionEnabled} tsCode={normalizedTsCode}
            historicalDate={tradeDate === undefined ? undefined : viewModel.asOfTradeDate ?? undefined}
            minutes={import.meta.env.DEV && viewModel.capabilities.supportsMinute} /> : undefined}
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
