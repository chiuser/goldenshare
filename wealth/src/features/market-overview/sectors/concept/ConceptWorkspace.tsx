import { formatSignedPercent } from "../../../../shared/lib/formatters";
import { directionClass, directionFromNumber } from "../../../../shared/lib/marketDirection";
import type { ConceptDetail, ConceptRankItem as ConceptRankItemData, ConceptWorkspace as ConceptWorkspaceData } from "../api/marketSectorOverviewApi";
import {
  ConceptHeatHistory,
  formatAmount,
  formatCount,
  HeatLevelBadge,
  HeatTrendBadge,
  MetricGrid,
  SectorLeaderCard,
  SectorMemberStockList,
  SectorRankLeader,
} from "../detail/SectorDetailPrimitives";

export function ConceptWorkspace({
  workspace,
  onSectorSelect,
  onStockSelect,
}: {
  workspace: ConceptWorkspaceData;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  return (
    <div className="sector-workspace concept-workspace">
      <section className="sector-flat-ranking" role="table" aria-label="概念热度排行">
        <div className="sector-flat-ranking-title"><strong>概念热度排行</strong><span>评分 0–100 · 趋势为较前一交易日</span></div>
        <div className="concept-rank-grid sector-flat-rank-header" role="row">
          <span role="columnheader">排名 / 概念</span>
          <span role="columnheader">等级 / 趋势</span>
          <span role="columnheader">热度 / 变化</span>
          <span role="columnheader">涨跌幅</span>
          <span role="columnheader">领涨股</span>
        </div>
        <div className="sector-flat-rank-viewport" data-visible-rows="7">
          {workspace.rows.map((row) => (
            <ConceptRankItem
              key={row.sectorCode}
              row={row}
              onSectorSelect={onSectorSelect}
              onStockSelect={onStockSelect}
            />
          ))}
        </div>
      </section>
      <ConceptDetailPanel detail={workspace.detail} onStockSelect={onStockSelect} />
    </div>
  );
}

export function ConceptRankItem({
  row,
  onSectorSelect,
  onStockSelect,
}: {
  row: ConceptRankItemData;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  return (
    <div className={`concept-rank-grid concept-rank-item ${row.selected ? "selected" : ""}`} role="row">
      <button aria-label={`选择${row.sectorName}`} className="sector-flat-select" title={row.sectorName} type="button" onClick={() => onSectorSelect(row.sectorCode)}>
        <span>{row.rank}</span><strong>{row.sectorName}</strong>
      </button>
      <div className="sector-heat-badges">
        {row.heatStatus === "INVALID" || row.heatStatus === "UNKNOWN"
          ? <span className="heat-status-unknown">UNKNOWN</span>
          : <><HeatLevelBadge level={row.heatLevel} /><HeatTrendBadge trend={row.heatTrend} /></>}
      </div>
      <div className="sector-heat-metric"><strong>{row.heatScore.displayText}</strong><span>{row.heatDelta1d.displayText}</span></div>
      <span className={`sector-flat-metric ${directionClass(row.changePct.direction)}`}>{row.changePct.displayText}</span>
      <SectorRankLeader leader={row.leader} onStockSelect={onStockSelect} />
    </div>
  );
}

export function ConceptDetailPanel({
  detail,
  onStockSelect,
}: {
  detail: ConceptDetail | null;
  onStockSelect: (stockCode: string) => void;
}) {
  if (!detail) return <aside className="sector-detail-panel concept-detail-panel"><div className="sector-list-empty">请选择概念</div></aside>;
  const metrics = detail.metrics;
  const heat = detail.heat;
  return (
    <aside className="sector-detail-panel concept-detail-panel">
      <div className="sector-detail-eyebrow">当前概念</div>
      <div className="sector-detail-heading">
        <h3>{detail.sectorName}</h3>
        <div className="sector-detail-heat-summary">
          {heat?.heatStatus === "VALID" ? <HeatLevelBadge level={heat.heatLevel} /> : <span className="heat-status-unknown">UNKNOWN</span>}
          {heat?.heatStatus === "VALID" ? <strong>{heat.heatScore ?? "--"}</strong> : null}
        </div>
      </div>
      <MetricGrid items={[
        { label: "热度变化", value: heat?.heatDelta1d == null ? "--" : `${heat.heatDelta1d > 0 ? "+" : ""}${heat.heatDelta1d}` },
        { label: "涨跌幅", value: metrics.changePct == null ? "--" : formatSignedPercent(metrics.changePct), className: directionClass(directionFromNumber(metrics.changePct)) },
        { label: "主力净流入", value: formatAmount(metrics.mainNetInflow), className: directionClass(directionFromNumber(metrics.mainNetInflow)) },
        { label: "上涨家数", value: `${formatCount(metrics.upCount)} / ${formatCount(metrics.memberCount)}` },
      ]} />
      <ConceptHeatHistory points={detail.heatHistory ?? []} />
      <SectorLeaderCard leader={detail.leader} onStockSelect={onStockSelect} />
      <SectorMemberStockList members={detail.members} title="概念成分股" onStockSelect={onStockSelect} />
    </aside>
  );
}
