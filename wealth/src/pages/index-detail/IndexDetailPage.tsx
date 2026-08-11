import { useEffect, useMemo, useState } from "react";

import { IndexChartWorkspace } from "../../features/index-detail/chart/IndexChartWorkspace";
import { IndexBreadcrumbActionBar } from "../../features/index-detail/layout/IndexBreadcrumbActionBar";
import { IndexChartToolbar } from "../../features/index-detail/layout/IndexChartToolbar";
import { useIndexDetailController } from "../../features/index-detail/controller/useIndexDetailController";
import { useIndexWeights } from "../../features/index-detail/controller/useIndexWeights";
import type { IndexInfoTab } from "../../features/index-detail/model/indexDetailTypes";
import { IndexInfoRail } from "../../features/index-detail/sidebar/IndexInfoRail";
import { IndexDetailToast } from "../../features/index-detail/ui/IndexDetailToast";
import { fetchMarketMajorIndices } from "../../features/market-overview/indices/api/marketMajorIndicesApi";
import { buildIndexDetailPath, DEFAULT_WEALTH_PATH, navigateWealth } from "../../app/routes/routerState";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import type { TopMarketTicker } from "../../shared/ui/top-market-bar/topMarketBarTypes";
import "./index-detail-page.css";

interface IndexDetailPageProps { search: string; tsCode: string; }

export function IndexDetailPage({ search, tsCode }: IndexDetailPageProps) {
  const controller = useIndexDetailController(tsCode, search);
  const [activeTab, setActiveTab] = useState<IndexInfoTab>("basic");
  const [toast, setToast] = useState("");
  const tickers = useTopMarketTickers();
  const debug = useMemo(() => new URLSearchParams(search).get("debug") === "1" ? 1 as const : undefined, [search]);
  const weights = useIndexWeights({
    active: activeTab === "weights" && controller.phase === "ready",
    asOfTradeDate: controller.viewModel?.asOfTradeDate ?? null,
    debug,
    tsCode,
  });

  useEffect(() => setActiveTab("basic"), [tsCode]);

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

  if (controller.phase !== "ready" || !controller.viewModel) {
    const copy = controller.phase === "loading"
      ? ["正在加载指数详情", "正在读取指数日线与基础行情，请稍候。"]
      : controller.phase === "empty"
        ? ["暂无指数详情数据", "当前日期没有可展示的指数日线行情。"]
        : ["指数详情加载失败", controller.errorMessage];
    return (
      <div className="index-detail-app">
        <TopMarketBar onAction={handleTopBarAction} tickers={tickers} />
        <section className="index-detail-state-panel" aria-label={copy[0]}><strong>{copy[0]}</strong><span>{copy[1]}</span></section>
        <IndexDetailToast message={toast} />
      </div>
    );
  }

  const viewModel = controller.viewModel;
  return (
    <div className="index-detail-app">
      <TopMarketBar onAction={handleTopBarAction} tickers={tickers} />
      <IndexBreadcrumbActionBar identity={viewModel.identity} />
      <IndexChartToolbar onAction={showToast} viewModel={viewModel} />
      <main className="index-detail-main-content" aria-label="MainContent">
        <IndexChartWorkspace trend={controller.trend} trendPhase={controller.trendPhase} viewModel={viewModel} />
        <IndexInfoRail activeTab={activeTab} onAction={showToast} onTabChange={setActiveTab} trend={controller.trend} viewModel={viewModel} weights={weights} />
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
