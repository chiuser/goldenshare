import type { TurnoverInsightChartPoint } from "../model/turnoverInsightTypes";

interface TurnoverInsightTooltipProps {
  point: TurnoverInsightChartPoint;
  left: number;
  top: number;
}

export function TurnoverInsightTooltip({ point, left, top }: TurnoverInsightTooltipProps) {
  return (
    <div className="turnover-insight-tooltip" style={{ left, top }} role="tooltip">
      <strong>{point.time}</strong>
      <span><i className="tooltip-dot tooltip-dot--current" />当日累计<b className="num">{point.currentDisplayText}</b></span>
      <span><i className="tooltip-dot tooltip-dot--previous" />昨日累计<b className="num">{point.previousDisplayText}</b></span>
      <span><i className={`tooltip-dot tooltip-dot--${point.deltaDirection}`} />累计增减<b className="num">{point.deltaDisplayText}</b></span>
    </div>
  );
}
