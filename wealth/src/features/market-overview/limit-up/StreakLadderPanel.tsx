import { Panel } from "../../../shared/ui/Panel";
import type { MarketOverview } from "../api/marketOverviewTypes";

interface StreakLadderPanelProps {
  overview: MarketOverview;
  onAction: (message: string) => void;
}

export function StreakLadderPanel({ overview, onAction }: StreakLadderPanelProps) {
  return (
    <Panel
      title="连板天梯"
      help="独立模块，紧跟涨跌停统计之后；横向展示首板、二板、三板、四板、五板及以上，每层显示股票数量和股票卡片。"
      meta={<span className="secondary">点击股票卡片进入个股详情</span>}
    >
      <div className="ladder">
        {overview.ladder.map((level) => (
          <div className="ladder-level" key={level.level}>
            <div className="ladder-head">
              <span className="ladder-title">{level.level}</span>
              <span className="ladder-count">{level.count} 只</span>
            </div>
            {level.stocks.map((stock) => (
              <article className="stock-card" key={stock.code} onClick={() => onAction(`进入详情：${stock.code}`)}>
                <div className="stock-name">
                  <span>{stock.name}</span>
                  <span className="up num">{stock.changePct}</span>
                </div>
                <div className="stock-meta">
                  <span>{stock.code}</span>
                  <span>{stock.theme}</span>
                </div>
                <div className="stock-price">
                  <span>{stock.price}</span>
                  <span className="secondary">开板 {stock.openTimes} 次</span>
                </div>
              </article>
            ))}
          </div>
        ))}
      </div>
    </Panel>
  );
}
