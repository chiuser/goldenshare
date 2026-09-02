import type {
  TurnoverInsightPanelViewModel,
  TurnoverInsightViewState,
} from "../model/turnoverInsightTypes";
import { TurnoverInsightChart } from "./TurnoverInsightChart";
import { TurnoverInsightSummary } from "./TurnoverInsightSummary";
import type { TurnoverInsightLayout } from "./turnoverInsightGeometry";

interface TurnoverInsightPanelProps {
  layout: TurnoverInsightLayout;
  viewState: TurnoverInsightViewState;
  model: TurnoverInsightPanelViewModel | null;
  errorMessage?: string;
  onRetry: () => void;
  loadingLabel?: string;
  emptyTitle?: string;
  errorTitle?: string;
}

export function TurnoverInsightPanel({
  layout,
  viewState,
  model,
  errorMessage,
  onRetry,
  loadingLabel = "成交额洞察加载中",
  emptyTitle = "暂无成交额数据",
  errorTitle = "成交额洞察加载失败",
}: TurnoverInsightPanelProps) {
  const chartReady = model?.upperAxis && model.points.length > 0;
  return (
    <div className={`turnover-insight-panel turnover-insight-panel--${layout}`}>
      {viewState === "loading" ? <TurnoverInsightLoading label={loadingLabel} layout={layout} /> : null}
      {(viewState === "ready" || viewState === "delayed" || viewState === "partial") && model ? (
        <>
          <TurnoverInsightSummary layout={layout} model={model} />
          {viewState === "delayed" ? <p className="turnover-insight-notice">{model.message}</p> : null}
          {chartReady ? (
            <TurnoverInsightChart
              avg5d={model.summary.avg5d}
              avg20d={model.summary.avg20d}
              deltaAxis={model.deltaAxis}
              layout={layout}
              points={model.points}
              upperAxis={model.upperAxis!}
            />
          ) : null}
          {viewState === "partial" ? (
            <p className="turnover-insight-partial-note">
              {model.message ?? "上一交易日数据暂不完整，差值对比暂不可用。"}
            </p>
          ) : null}
        </>
      ) : null}
      {viewState === "empty" ? (
        <TurnoverInsightState
          title={emptyTitle}
          message={model?.message ?? "当前交易日没有可展示的一分钟成交额快照。"}
        />
      ) : null}
      {viewState === "error" ? (
        <TurnoverInsightState
          title={errorTitle}
          message={errorMessage ?? model?.message ?? "请稍后重试。"}
          onRetry={onRetry}
        />
      ) : null}
    </div>
  );
}

function TurnoverInsightLoading({ label, layout }: { label: string; layout: TurnoverInsightLayout }) {
  return (
    <div className={`turnover-insight-loading turnover-insight-loading--${layout}`} aria-label={label}>
      <div className="turnover-insight-loading__cards" />
      <div className="turnover-insight-loading__chart" />
    </div>
  );
}

function TurnoverInsightState({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <div className="turnover-insight-state">
      <strong>{title}</strong>
      <span>{message}</span>
      {onRetry ? <button type="button" onClick={onRetry}>重试</button> : null}
    </div>
  );
}
