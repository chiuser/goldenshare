import type { IndexDetailViewModel } from "../model/indexDetailTypes";

export function IndexChartToolbar({ onAction, viewModel }: { onAction: (message: string) => void; viewModel: IndexDetailViewModel }) {
  return (
    <section className="index-detail-chart-toolbar" aria-label="ChartWorkspaceToolbar">
      <div className="index-detail-toolbar-primary">
        <div className="index-detail-toolbar-identity">
          <b>{viewModel.identity.name}</b><span>{viewModel.identity.tsCode}</span>
        </div>
        <div className="index-detail-periods" aria-label="周期切换">
          <span className="toolbar-title">周期</span>
          {viewModel.periods.map((period) => (
            <button
              aria-pressed={period.key === "day"}
              className={`seg-btn ${period.key === "day" ? "active" : "unsupported"}`}
              disabled={!period.supported}
              key={period.key}
              title={period.supported ? undefined : "当前环境暂不提供该周期"}
              type="button"
            >{period.label}</button>
          ))}
        </div>
      </div>
      <div className="index-detail-toolbar-actions" aria-label="图表操作">
        <button className="btn" type="button" onClick={() => onAction("指数资料请使用右侧页签查看")}>指数资料</button>
        <button className="btn" disabled title="诊股功能暂未开通" type="button">诊股</button>
        <button className="btn" disabled title="图表设置暂未开通" type="button">设置</button>
      </div>
    </section>
  );
}
