import { formatSignedPercent } from "../../../../shared/lib/formatters";
import { directionClass, directionFromNumber } from "../../../../shared/lib/marketDirection";
import type { IndustryDetail, IndustryRankItem as IndustryRankItemData, IndustryWorkspace as IndustryWorkspaceData } from "../api/marketSectorOverviewApi";
import {
  formatAmount,
  formatCount,
  MetricGrid,
  SectorLeaderCard,
  SectorMemberStockList,
  SectorRankLeader,
} from "../detail/SectorDetailPrimitives";

const LEVEL_LABELS = { 1: "一级行业", 2: "二级行业", 3: "三级行业" } as const;
const LEVEL_CONTEXT = { 1: "全市场", 2: "所选一级直属", 3: "所选二级直属" } as const;

export function IndustryWorkspace({
  workspace,
  onSectorSelect,
  onStockSelect,
}: {
  workspace: IndustryWorkspaceData;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  const detailRow = workspace.columns.flatMap((column) => column.rows).find((row) => row.sectorCode === workspace.selection.detailSectorCode);
  return (
    <div className="sector-workspace industry-workspace">
      <div className="industry-columns">
        {workspace.columns.map((column) => (
          <section aria-label={LEVEL_LABELS[column.level]} className="industry-level-column" key={column.level}>
            <header>
              <strong>{LEVEL_LABELS[column.level]}</strong>
              <span>{LEVEL_CONTEXT[column.level]}</span>
            </header>
            <div className="industry-ranking-list">
              {column.rows.map((row) => (
                <IndustryRankItem
                  key={row.sectorCode}
                  row={row}
                  onSectorSelect={onSectorSelect}
                  onStockSelect={onStockSelect}
                />
              ))}
              {!column.rows.length ? <div className="sector-list-empty">暂无下级行业</div> : null}
            </div>
          </section>
        ))}
      </div>
      <IndustryDetailPanel detail={workspace.detail} detailRow={detailRow} onStockSelect={onStockSelect} />
    </div>
  );
}

export function IndustryRankItem({
  row,
  onSectorSelect,
  onStockSelect,
}: {
  row: IndustryRankItemData;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  return (
    <article className={`industry-rank-item ${row.selected ? "selected" : ""}`}>
      <button
        aria-label={`选择${row.sectorName}`}
        className="industry-rank-select"
        title={row.sectorName}
        type="button"
        onClick={() => onSectorSelect(row.sectorCode)}
      >
        <span className="sector-rank-number">{row.rank}</span>
        <strong>{row.sectorName}</strong>
        <em className={directionClass(row.primaryMetric.direction)}>{row.primaryMetric.displayText}</em>
      </button>
      <div className="industry-rank-leader">
        <span className="sector-leader-label">领涨股</span>
        <SectorRankLeader leader={row.leader} onStockSelect={onStockSelect} />
      </div>
    </article>
  );
}

export function IndustryDetailPanel({
  detail,
  detailRow,
  onStockSelect,
}: {
  detail: IndustryDetail | null;
  detailRow?: IndustryRankItemData;
  onStockSelect: (stockCode: string) => void;
}) {
  if (!detail) return <aside className="sector-detail-panel industry-detail-panel"><div className="sector-list-empty">请选择行业</div></aside>;
  const metrics = detail.metrics;
  return (
    <aside className="sector-detail-panel industry-detail-panel">
      <div className="sector-detail-eyebrow">当前选择</div>
      <div className="sector-detail-path" title={detail.hierarchyPath || detail.sectorName}>{detail.hierarchyPath || detail.sectorName}</div>
      <div className="sector-detail-heading">
        <h3>{detail.sectorName}</h3>
        {detailRow ? <span className="sector-detail-badge">{LEVEL_LABELS[detailRow.industryLevel]} · 同层第 {detailRow.rank}</span> : null}
      </div>
      <MetricGrid items={[
        { label: "涨跌幅", value: metrics.changePct == null ? "--" : formatSignedPercent(metrics.changePct), className: directionClass(directionFromNumber(metrics.changePct)) },
        { label: "上涨家数", value: `${formatCount(metrics.upCount)} / ${formatCount(metrics.memberCount)}` },
        { label: "主力净流入", value: formatAmount(metrics.mainNetInflow), className: directionClass(directionFromNumber(metrics.mainNetInflow)) },
        { label: "成交额", value: formatAmount(metrics.turnoverAmount) },
      ]} />
      <SectorLeaderCard leader={detail.leader} onStockSelect={onStockSelect} />
      <SectorMemberStockList members={detail.members} title="成分股表现" onStockSelect={onStockSelect} />
    </aside>
  );
}
