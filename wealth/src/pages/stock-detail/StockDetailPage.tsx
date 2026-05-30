import { useMemo, useState } from "react";

import { getStockDetailViewModel } from "../../features/stock-detail/api/stockDetailMockAdapter";
import { StockChartWorkspace } from "../../features/stock-detail/chart/StockChartWorkspace";
import { StockBreadcrumbActionBar } from "../../features/stock-detail/layout/StockBreadcrumbActionBar";
import { StockChartToolbar } from "../../features/stock-detail/layout/StockChartToolbar";
import { StockInfoRail } from "../../features/stock-detail/sidebar/StockInfoRail";
import { StockDetailToast } from "../../features/stock-detail/ui/StockDetailToast";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import type { StockPeriodKey } from "../../features/stock-detail/model/stockDetailTypes";
import "./stock-detail-page.css";

interface StockDetailPageProps {
  tsCode: string;
}

export function StockDetailPage({ tsCode }: StockDetailPageProps) {
  const viewModel = useMemo(() => getStockDetailViewModel(tsCode), [tsCode]);
  const [activePeriod, setActivePeriod] = useState<StockPeriodKey>(viewModel.activePeriod);
  const [toast, setToast] = useState("");

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 1800);
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
