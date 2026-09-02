import type { TurnoverInsightPanelViewModel } from "../model/turnoverInsightTypes";
import type { TurnoverInsightLayout } from "./turnoverInsightGeometry";
import { TurnoverInsightLegend } from "./TurnoverInsightLegend";
import { TurnoverMetricCard } from "./TurnoverMetricCard";

interface TurnoverInsightSummaryProps {
  model: TurnoverInsightPanelViewModel;
  layout?: TurnoverInsightLayout;
}

export function TurnoverInsightSummary({ model, layout = "full" }: TurnoverInsightSummaryProps) {
  return (
    <div className={`turnover-insight-summary turnover-insight-summary--${layout}`}>
      <div className="turnover-insight-summary__cards">
        <TurnoverMetricCard label="当日累计成交额" value={model.summary.current} />
        <TurnoverMetricCard label="昨日累计成交额" value={model.summary.previous} />
        <TurnoverMetricCard label="较昨日累计增减" value={model.summary.delta} />
        <TurnoverMetricCard label="5日成交额均值" value={model.summary.avg5d} accent="avg5d" />
        <TurnoverMetricCard label="20日成交额均值" value={model.summary.avg20d} accent="avg20d" />
      </div>
      <TurnoverInsightLegend />
    </div>
  );
}
