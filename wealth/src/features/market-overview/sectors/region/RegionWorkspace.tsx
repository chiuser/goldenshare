import { formatSignedPercent } from "../../../../shared/lib/formatters";
import { directionClass, directionFromNumber } from "../../../../shared/lib/marketDirection";
import type { RegionDetail, RegionRankItem as RegionRankItemData, RegionWorkspace as RegionWorkspaceData } from "../api/marketSectorOverviewApi";
import {
  formatAmount,
  formatCount,
  MetricGrid,
  SectorLeaderCard,
  SectorMemberStockList,
  SectorRankLeader,
} from "../detail/SectorDetailPrimitives";

export function RegionWorkspace({
  workspace,
  onSectorSelect,
  onStockSelect,
}: {
  workspace: RegionWorkspaceData;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  return (
    <div className="sector-workspace region-workspace">
      <section className="sector-flat-ranking" role="table" aria-label="地域板块排行">
        <div className="sector-flat-ranking-title"><strong>地域板块排行</strong><span>31 个地域板块 · 独立平铺</span></div>
        <div className="region-rank-grid sector-flat-rank-header" role="row">
          <span role="columnheader">排名 / 地域</span>
          <span role="columnheader">上涨家数</span>
          <span role="columnheader">主力净流入</span>
          <span role="columnheader">涨跌幅</span>
          <span role="columnheader">领涨股</span>
        </div>
        <div className="sector-flat-rank-viewport" data-visible-rows="7">
          {workspace.rows.map((row) => (
            <RegionRankItem
              key={row.sectorCode}
              row={row}
              onSectorSelect={onSectorSelect}
              onStockSelect={onStockSelect}
            />
          ))}
        </div>
      </section>
      <RegionDetailPanel detail={workspace.detail} onStockSelect={onStockSelect} />
    </div>
  );
}

export function RegionRankItem({
  row,
  onSectorSelect,
  onStockSelect,
}: {
  row: RegionRankItemData;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  return (
    <div className={`region-rank-grid region-rank-item ${row.selected ? "selected" : ""}`} role="row">
      <button aria-label={`选择${row.sectorName}`} className="sector-flat-select" title={row.sectorName} type="button" onClick={() => onSectorSelect(row.sectorCode)}>
        <span>{row.rank}</span><strong>{row.sectorName}</strong>
      </button>
      <span className="sector-region-count">{formatCount(row.upCount)} / {formatCount(row.memberCount)}</span>
      <span className={`sector-flat-metric ${directionClass(row.mainNetInflow.direction)}`}>{row.mainNetInflow.displayText}</span>
      <span className={`sector-flat-metric ${directionClass(row.changePct.direction)}`}>{row.changePct.displayText}</span>
      <SectorRankLeader leader={row.leader} onStockSelect={onStockSelect} />
    </div>
  );
}

export function RegionDetailPanel({
  detail,
  onStockSelect,
}: {
  detail: RegionDetail | null;
  onStockSelect: (stockCode: string) => void;
}) {
  if (!detail) return <aside className="sector-detail-panel region-detail-panel"><div className="sector-list-empty">请选择地域</div></aside>;
  const metrics = detail.metrics;
  return (
    <aside className="sector-detail-panel region-detail-panel">
      <div className="sector-detail-eyebrow">当前地域</div>
      <div className="sector-detail-heading">
        <h3>{detail.sectorName}</h3>
        <span className="sector-detail-badge">涨幅 {metrics.changePct == null ? "--" : formatSignedPercent(metrics.changePct)}</span>
      </div>
      <MetricGrid items={[
        { label: "涨跌幅", value: metrics.changePct == null ? "--" : formatSignedPercent(metrics.changePct), className: directionClass(directionFromNumber(metrics.changePct)) },
        { label: "主力净流入", value: formatAmount(metrics.mainNetInflow), className: directionClass(directionFromNumber(metrics.mainNetInflow)) },
        { label: "上涨家数", value: `${formatCount(metrics.upCount)} / ${formatCount(metrics.memberCount)}` },
        { label: "成交额", value: formatAmount(metrics.turnoverAmount) },
      ]} />
      <RegionBreadthDistribution upCount={metrics.upCount} downCount={metrics.downCount} />
      <SectorLeaderCard leader={detail.leader} onStockSelect={onStockSelect} />
      <SectorMemberStockList members={detail.members} title="地域成分股" onStockSelect={onStockSelect} />
    </aside>
  );
}

function RegionBreadthDistribution({ upCount, downCount }: { upCount: number | null; downCount: number | null }) {
  const up = upCount ?? 0;
  const down = downCount ?? 0;
  const total = up + down;
  return (
    <div className="sector-breadth-distribution" aria-label="地域成分涨跌分布">
      <div><span>上涨 {upCount ?? "--"}</span><span>下跌 {downCount ?? "--"}</span></div>
      <div className="sector-breadth-track" aria-hidden="true">
        <span className="up" style={{ flexGrow: total ? up : 0 }} />
        <span className="down" style={{ flexGrow: total ? down : 0 }} />
      </div>
    </div>
  );
}
