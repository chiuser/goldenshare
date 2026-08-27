import { formatReturnPct } from "../api/sectorMomentumAdapter";
import type { SectorMomentumHistoryPointViewModel } from "../model/sectorMomentumTypes";

export function MomentumLinkedTooltip({
  point,
  index,
  count,
}: {
  point: SectorMomentumHistoryPointViewModel;
  index: number;
  count: number;
}) {
  const ratio = count <= 1 ? 0 : index / (count - 1);
  const left = Math.max(12, Math.min(82, ratio * 100));
  return (
    <div className="momentum-linked-tooltip" role="tooltip" style={{ left: `${left}%` }}>
      <strong>{point.tradeDate}</strong>
      <span>区间涨跌幅 <b className="num">{formatReturnPct(point.returnPct)}</b></span>
      <span>强度排名 <b className="num">{point.strengthRank === null ? "--" : `第 ${point.strengthRank} 名 / ${point.calculableCount} 个可计算行业`}</b></span>
      <span>同组总数 <b className="num">{point.totalCount}</b></span>
    </div>
  );
}

