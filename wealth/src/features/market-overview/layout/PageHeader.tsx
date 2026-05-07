import { MarketStatusPill } from "../../../shared/ui/MarketStatusPill";

interface PageHeaderProps {
  tradeDate: string;
  updateTime: string;
  onRefresh: () => void;
  refreshing: boolean;
}

export function PageHeader({ tradeDate, updateTime, onRefresh, refreshing }: PageHeaderProps) {
  return (
    <section className="page-header" aria-label="PageHeader">
      <div className="page-title-wrap">
        <h1>市场总览</h1>
        <span className="scope-tag">A 股</span>
        <MarketStatusPill label={`交易日 ${tradeDate}`} />
      </div>
      <div className="header-actions">
        <span>
          数据更新时间：<span className="num">{updateTime}</span>
        </span>
        <button className={refreshing ? "refresh-btn loading" : "refresh-btn"} type="button" onClick={onRefresh}>
          {refreshing ? "刷新中" : "手动刷新"}
        </button>
      </div>
    </section>
  );
}
