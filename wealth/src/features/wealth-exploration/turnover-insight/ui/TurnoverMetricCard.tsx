import type { TurnoverInsightAmountViewModel } from "../model/turnoverInsightTypes";

interface TurnoverMetricCardProps {
  label: string;
  value: TurnoverInsightAmountViewModel;
  accent?: "default" | "avg5d" | "avg20d";
}

export function TurnoverMetricCard({ label, value, accent = "default" }: TurnoverMetricCardProps) {
  return (
    <div
      className={`turnover-insight-metric turnover-insight-metric--${value.direction} turnover-insight-metric--${accent}`}
    >
      <span>{label}</span>
      <strong className="num">{value.displayText}</strong>
    </div>
  );
}
