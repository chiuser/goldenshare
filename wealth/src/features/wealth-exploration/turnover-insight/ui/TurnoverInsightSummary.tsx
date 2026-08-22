import type { TurnoverInsightViewModel } from "../model/turnoverInsightTypes";
import { TurnoverInsightLegend } from "./TurnoverInsightLegend";
import { TurnoverMetricCard } from "./TurnoverMetricCard";

interface TurnoverInsightSummaryProps {
  model: TurnoverInsightViewModel;
}

export function TurnoverInsightSummary({ model }: TurnoverInsightSummaryProps) {
  return (
    <div className="turnover-insight-summary">
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
