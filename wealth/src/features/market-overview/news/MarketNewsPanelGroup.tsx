import type { ReactNode } from "react";

interface MarketNewsPanelGroupProps {
  marketNews: ReactNode;
  newsCommunications: ReactNode;
  marketSummary: ReactNode;
  majorIndices: ReactNode;
}

export function MarketNewsPanelGroup({
  marketNews,
  newsCommunications,
  marketSummary,
  majorIndices,
}: MarketNewsPanelGroupProps) {
  return (
    <div className="summary-index-row" aria-label="新闻、今日市场客观总结与主要指数组合">
      <div className="summary-column">
        {marketNews}
        {marketSummary}
      </div>
      <div className="summary-column">
        {newsCommunications}
        {majorIndices}
      </div>
    </div>
  );
}
