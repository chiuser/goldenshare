import { useEffect, useMemo, useState } from "react";

import { buildIndexDetailPath, DEFAULT_WEALTH_PATH, navigateWealth, returnToWealthOverview } from "../../app/routes/routerState";
import { IndexChartWorkspace } from "../../features/index-detail/chart/IndexChartWorkspace";
import { IndexMinuteChartWorkspace } from "../../features/index-detail/chart/IndexMinuteChartWorkspace";
import { useIndexDetailController } from "../../features/index-detail/controller/useIndexDetailController";
import { useIndexMinuteSeries } from "../../features/index-detail/controller/useIndexMinuteSeries";
import { useIndexWeights } from "../../features/index-detail/controller/useIndexWeights";
import { IndexBreadcrumbActionBar } from "../../features/index-detail/layout/IndexBreadcrumbActionBar";
import { IndexChartToolbar } from "../../features/index-detail/layout/IndexChartToolbar";
import { getIndexShellIdentity, getIndexShellPeriods, normalizeIndexTsCode } from "../../features/index-detail/model/indexDetailState";
import type { IndexInfoTab, IndexPeriodKey } from "../../features/index-detail/model/indexDetailTypes";
import { IndexInfoRail } from "../../features/index-detail/sidebar/IndexInfoRail";
import { IndexDetailLoadingSkeleton } from "../../features/index-detail/state/IndexDetailLoadingSkeleton";
import { IndexDetailPageState } from "../../features/index-detail/state/IndexDetailPageState";
import { IndexDetailToast } from "../../features/index-detail/ui/IndexDetailToast";
import { fetchMarketMajorIndices } from "../../features/market-overview/indices/api/marketMajorIndicesApi";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import type { TopMarketTicker } from "../../shared/ui/top-market-bar/topMarketBarTypes";
import "./index-detail-page.css";

interface IndexDetailPageProps { search: string; tsCode: string; }

export function IndexDetailPage({ search, tsCode }: IndexDetailPageProps) {
  const controller = useIndexDetailController(tsCode, search);
  const [activePeriod, setActivePeriod] = useState<IndexPeriodKey>("day");
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

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 1800);
  }

  function handleTopBarAction(message: string) {
    if (message === "跳转：/market/overview") {
      navigateWealth(DEFAULT_WEALTH_PATH);
      return;
    }
    if (message.startsWith("进入详情：")) {
      navigateWealth(buildIndexDetailPath(message.slice("进入详情：".length)));
      return;
    }
    showToast(message);
  }

  function showRecentTradeDay() {
    const params = new URLSearchParams(search);
    params.delete("tradeDate");
    const query = params.toString();
    navigateWealth(`${buildIndexDetailPath(normalizedTsCode)}${query ? `?${query}` : ""}`, { replace: true });
    if (!new URLSearchParams(search).has("tradeDate")) controller.retry();
  }

  const pageShell = <>
    <TopMarketBar onAction={handleTopBarAction} tickers={tickers} />
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
          activePeriod === "day" ? (
            <IndexChartWorkspace trend={controller.trend} trendPhase={controller.trendPhase} viewModel={viewModel} />
          ) : (
            <IndexMinuteChartWorkspace
              data={minute.data}
              errorMessage={minute.errorMessage}
              onRetry={minute.retry}
              phase={minute.phase}
            />
          )
        )}
        <IndexInfoRail
          activeTab={activeTab}
          onAction={showToast}
          onTabChange={setActiveTab}
          onTrendRetry={controller.retryTrend}
          pagePhase={controller.phase}
          partialReasons={controller.partialReasons}
          trend={controller.trend}
          trendPhase={controller.trendPhase}
          viewModel={viewModel}
          weights={displayedWeights}
        />
      </main>
      <IndexDetailToast message={toast} />
    </div>
  );
}

function useTopMarketTickers(): TopMarketTicker[] {
  const [tickers, setTickers] = useState<TopMarketTicker[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    fetchMarketMajorIndices({ market: "CN_A" }, { signal: controller.signal })
      .then((payload) => setTickers(payload.majorIndices.rows.flatMap((row) => {
        if (!Number.isFinite(row.point) || !Number.isFinite(row.changePct)) return [];
        return [{
          code: row.subject.subjectCode,
          name: row.subject.subjectName ?? row.subject.subjectCode,
          point: row.point as number,
          pct: row.changePct as number,
          direction: row.direction,
        }];
      })))
      .catch(() => { if (!controller.signal.aborted) setTickers([]); });
    return () => controller.abort();
  }, []);
  return tickers;
}
