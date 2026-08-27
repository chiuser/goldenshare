import { useState } from "react";

import type {
  SectorHistoryRange,
  SectorMomentumHistoryViewModel,
  SectorMomentumPeriod,
} from "../model/sectorMomentumTypes";
import { HistoricalRankChart } from "./HistoricalRankChart";
import { MomentumLinkedTooltip } from "./MomentumLinkedTooltip";
import { RollingReturnChart } from "./RollingReturnChart";
import { SelectedSectorSummary } from "./SelectedSectorSummary";

interface MomentumDetailPanelProps {
  history: SectorMomentumHistoryViewModel;
  period: SectorMomentumPeriod;
  range: SectorHistoryRange;
  onRangeChange: (range: SectorHistoryRange) => void;
}

export function MomentumDetailPanel({ history, period, range, onRangeChange }: MomentumDetailPanelProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const activePoint = hoverIndex === null ? null : history.points[hoverIndex] ?? null;
  return (
    <div className="momentum-detail-panel">
      <SelectedSectorSummary detail={history.detail} />
      <div className="momentum-charts-grid">
        {activePoint ? <MomentumLinkedTooltip count={history.points.length} index={hoverIndex!} point={activePoint} /> : null}
        <RollingReturnChart
          hoverIndex={hoverIndex}
          onHoverIndex={setHoverIndex}
          period={period}
          points={history.points}
          rangeControl={(
            <div className="momentum-history-toolbar">
              <span>两图共用</span>
              <div className="momentum-segmented-control" aria-label="历史显示范围">
                {([20, 30, 60] as const).map((value) => (
                  <button
                    aria-pressed={range === value}
                    className={range === value ? "active" : ""}
                    key={value}
                    type="button"
                    onClick={() => onRangeChange(value)}
                  >
                    {value}日
                  </button>
                ))}
              </div>
            </div>
          )}
          scopeTitle={history.detail.scopeTitle}
        />
        <HistoricalRankChart
          hoverIndex={hoverIndex}
          onHoverIndex={setHoverIndex}
          points={history.points}
          scopeTitle={history.detail.scopeTitle}
        />
      </div>
    </div>
  );
}
