import { useEffect, useMemo, useState } from "react";

import { fetchStockDetailKline, fetchStockDetailPageInit } from "../../features/stock-detail/api/stockDetailApiClient";
import { getStockDetailViewModel } from "../../features/stock-detail/api/stockDetailMockAdapter";
import { buildStockDetailViewModel } from "../../features/stock-detail/api/stockDetailViewModelAdapter";
import { StockChartWorkspace } from "../../features/stock-detail/chart/StockChartWorkspace";
import { StockBreadcrumbActionBar } from "../../features/stock-detail/layout/StockBreadcrumbActionBar";
import { StockChartToolbar } from "../../features/stock-detail/layout/StockChartToolbar";
import { StockInfoRail } from "../../features/stock-detail/sidebar/StockInfoRail";
import { StockDetailToast } from "../../features/stock-detail/ui/StockDetailToast";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import type { StockDetailViewModel } from "../../features/stock-detail/model/stockDetailTypes";
import type { StockPeriodKey } from "../../features/stock-detail/model/stockDetailTypes";
import "./stock-detail-page.css";

interface StockDetailPageProps {
  tsCode: string;
}

export function StockDetailPage({ tsCode }: StockDetailPageProps) {
  const scaffoldViewModel = useMemo(() => getStockDetailViewModel(tsCode), [tsCode]);
  const [viewModel, setViewModel] = useState<StockDetailViewModel | null>(null);
  const [activePeriod, setActivePeriod] = useState<StockPeriodKey>("day");
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [toast, setToast] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const searchParams = new URLSearchParams(window.location.search);
    const tradeDate = searchParams.get("tradeDate") ?? undefined;
    const debug = searchParams.get("debug") === "1" ? 1 : undefined;

    setLoadState("loading");
    setErrorMessage("");
    setViewModel(null);

    async function loadStockDetail() {
      try {
        const pageInit = await fetchStockDetailPageInit({ tsCode, tradeDate, debug }, { signal: controller.signal });
        const kline = await fetchStockDetailKline(
          {
            tsCode,
            period: "day",
            adjustment: "forward",
            endDate: pageInit.pageContext.tradeDate,
            limit: 300,
            debug,
          },
          { signal: controller.signal },
        );
        const nextViewModel = buildStockDetailViewModel(pageInit, kline);
        setViewModel(nextViewModel);
        setActivePeriod(nextViewModel.activePeriod);
        setLoadState("ready");
      } catch (error) {
        if (controller.signal.aborted) return;
        setErrorMessage(error instanceof Error ? error.message : "股票详情数据加载失败");
        setLoadState("error");
      }
    }

    void loadStockDetail();

    return () => controller.abort();
  }, [tsCode]);

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 1800);
  }

  if (loadState !== "ready" || viewModel === null) {
    return (
      <div className="stock-detail-app">
        <TopMarketBar onAction={showToast} tickers={scaffoldViewModel.topMarketTickers} />
        <section className="stock-detail-state-panel" aria-label={loadState === "loading" ? "股票详情加载中" : "股票详情加载失败"}>
          <div className="state-title">{loadState === "loading" ? "正在加载股票详情" : "股票详情加载失败"}</div>
          <div className="state-detail">{loadState === "loading" ? "正在读取真实行情数据，请稍候。" : errorMessage}</div>
        </section>
        <StockDetailToast message={toast} />
      </div>
    );
  }

  return (
    <div className="stock-detail-app">
      <TopMarketBar onAction={showToast} tickers={viewModel.topMarketTickers} />
      <StockBreadcrumbActionBar stock={viewModel.stock} />
      <StockChartToolbar
        activePeriod={activePeriod}
        onAction={showToast}
        onPeriodChange={setActivePeriod}
        periods={viewModel.periods}
        stock={viewModel.stock}
      />
      <main className="stock-detail-main-content" aria-label="MainContent">
        <StockChartWorkspace
          activePeriod={activePeriod}
          candles={viewModel.chart.candles}
          indicatorTabs={viewModel.indicatorTabs}
          onAction={showToast}
        />
        <StockInfoRail onAction={showToast} viewModel={viewModel} />
      </main>
      <StockDetailToast message={toast} />
    </div>
  );
}
