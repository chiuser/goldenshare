import type {
  TurnoverInsightViewModel,
  TurnoverInsightViewState,
} from "../model/turnoverInsightTypes";
import { TurnoverInsightChart } from "./TurnoverInsightChart";
import { TurnoverInsightSummary } from "./TurnoverInsightSummary";
import "./turnover-insight.css";

interface TurnoverInsightSectionProps {
  viewState: TurnoverInsightViewState;
  model: TurnoverInsightViewModel | null;
  errorMessage?: string;
  onRetry: () => void;
}

export function TurnoverInsightSection({ viewState, model, errorMessage, onRetry }: TurnoverInsightSectionProps) {
  const chartReady = model?.upperAxis && model.points.length > 0;
  return (
    <section className="turnover-insight-section" aria-labelledby="turnover-insight-title">
      <header className="turnover-insight-header">
        <div>
          <h1 id="turnover-insight-title">成交额洞察</h1>
          <p>当日与上一交易日全市场一分钟累计成交额对比</p>
        </div>
        {model?.asOf ? <span className="turnover-insight-asof num">截至 {formatAsOf(model.asOf)}</span> : null}
      </header>
      <div className="turnover-insight-panel">
        {viewState === "loading" ? <TurnoverInsightLoading /> : null}
        {(viewState === "ready" || viewState === "delayed" || viewState === "partial") && model ? (
          <>
            <TurnoverInsightSummary model={model} />
            {viewState === "delayed" ? <p className="turnover-insight-notice">{model.message}</p> : null}
            {chartReady ? (
              <TurnoverInsightChart
                deltaAxis={model.deltaAxis}
                points={model.points}
                upperAxis={model.upperAxis!}
              />
            ) : null}
            {viewState === "partial" ? (
              <p className="turnover-insight-partial-note">{model.message ?? "上一交易日数据暂不完整，差值对比暂不可用。"}</p>
            ) : null}
          </>
        ) : null}
        {viewState === "empty" ? (
          <TurnoverInsightState title="暂无成交额数据" message={model?.message ?? "当前交易日没有可展示的一分钟成交额快照。"} />
        ) : null}
        {viewState === "error" ? (
          <TurnoverInsightState
            title="成交额洞察加载失败"
            message={errorMessage ?? model?.message ?? "请稍后重试。"}
            onRetry={onRetry}
          />
        ) : null}
      </div>
    </section>
  );
}

function TurnoverInsightLoading() {
  return (
    <div className="turnover-insight-loading" aria-label="成交额洞察加载中">
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

function formatAsOf(value: string): string {
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : value;
}
