import type { ReactNode } from "react";

interface MarketNewsPanelGroupProps {
  marketNews: ReactNode;
  stockNews: ReactNode;
  marketSummary: ReactNode;
  majorIndices: ReactNode;
}

export function MarketNewsPanelGroup({ marketNews, stockNews, marketSummary, majorIndices }: MarketNewsPanelGroupProps) {
  return (
    <div className="summary-index-row" aria-label="新闻、今日市场客观总结与主要指数组合">
      <div className="summary-column">
        {marketNews}
        {marketSummary}
      </div>
      <div className="summary-column">
        {stockNews}
        {majorIndices}
      </div>
    </div>
  );
}
