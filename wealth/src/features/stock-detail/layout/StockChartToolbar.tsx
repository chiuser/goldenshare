import type { StockIdentity, StockPeriodKey, StockPeriodOption } from "../model/stockDetailTypes";

interface StockChartToolbarProps {
  stock: StockIdentity;
  periods: StockPeriodOption[];
  activePeriod: StockPeriodKey;
  onPeriodChange: (period: StockPeriodKey) => void;
  onAction: (message: string) => void;
}

export function StockChartToolbar({ stock, periods, activePeriod, onPeriodChange, onAction }: StockChartToolbarProps) {
  return (
    <section className="stock-detail-chart-toolbar" aria-label="ChartWorkspaceToolbar">
      <div className="stock-detail-toolbar-primary">
        <div className="stock-detail-toolbar-stock" aria-label="股票识别信息">
          <div className="stock-detail-toolbar-stock-main">
            <b>{stock.name}</b>
            <span className="stock-code">{stock.tsCode}</span>
            <span className="stock-sector">{stock.sector}</span>
          </div>
          <div className="stock-detail-toolbar-stock-sub">乾坤行情 / 个股详情 / P0 Mock 行情</div>
        </div>
        <div className="stock-detail-periods" aria-label="周期切换">
          <span className="toolbar-title">周期</span>
          {periods.map((period) => (
            <button
              className={period.key === activePeriod ? "seg-btn active" : "seg-btn"}
              key={period.key}
              type="button"
              onClick={() => onPeriodChange(period.key)}
            >
              {period.label}
            </button>
          ))}
        </div>
      </div>
      <div className="stock-detail-toolbar-actions" aria-label="图表操作">
        <button className="btn" type="button" onClick={() => onAction("前复权：首版仅保留展示状态")}>
          前复权
        </button>
        <button className="btn" type="button" onClick={() => onAction("股票资料：请使用右侧资料页签查看")}>
          股票资料
        </button>
        <button className="btn" disabled title="诊股功能暂未开通" type="button">
          诊股
        </button>
        <button className="icon-btn gear-btn" title="图表设置" type="button" onClick={() => onAction("图表设置暂未开通")}>
          设置
        </button>
      </div>
    </section>
  );
}
