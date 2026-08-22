import type { TurnoverInsightAmountViewModel } from "../model/turnoverInsightTypes";

interface TurnoverMetricCardProps {
  label: string;
  value: TurnoverInsightAmountViewModel;
}

export function TurnoverMetricCard({ label, value }: TurnoverMetricCardProps) {
  return (
    <div className={`turnover-insight-metric turnover-insight-metric--${value.direction}`}>
      <span>{label}</span>
      <strong className="num">{value.displayText}</strong>
    </div>
  );
}
