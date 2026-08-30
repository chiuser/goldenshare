import type { SectorPriceVolumeController } from "../model/useSectorPriceVolumeController";
import type { PriceVolumeSnapshotRowViewModel } from "../api/sectorPriceVolumeTypes";

export function PriceVolumeIndustryList({ controller }: { controller: SectorPriceVolumeController }) {
  const { urlState, viewState } = controller;
  if ((viewState.kind !== "ready" && viewState.kind !== "delayed") || !urlState) return null;
  const snapshot = viewState.snapshot;
  const scopeTitle = buildScopeTitle(urlState.scope, snapshot, viewState.meta);
  const selectSort = (sortBy: "price-momentum" | "amount-activity") => {
    if (urlState.sortBy === sortBy) {
      controller.selectSortDirection(urlState.sortDirection === "desc" ? "asc" : "desc");
      return;
    }
    controller.selectSortBy(sortBy);
  };
  return (
    <section className="price-volume-industry-list">
      <header><strong>{scopeTitle}</strong><span>{snapshot.totalCount} 个行业 · {snapshot.coordinateCount} 可计算</span></header>
      <div className="price-volume-list-grid price-volume-list-header" role="row">
        <SortHeader active={urlState.sortBy === "price-momentum"} direction={urlState.sortDirection} label="名次" onClick={() => selectSort("price-momentum")} />
        <span role="columnheader">行业 / 路径</span>
        <SortHeader active={urlState.sortBy === "price-momentum"} direction={urlState.sortDirection} label="区间涨跌幅" onClick={() => selectSort("price-momentum")} />
        <SortHeader active={urlState.sortBy === "amount-activity"} direction={urlState.sortDirection} label="成交活跃度" onClick={() => selectSort("amount-activity")} />
        <span role="columnheader">当前状态</span><span aria-hidden="true" />
      </div>
      <div className="price-volume-list-viewport" role="table" aria-label="行业量价分布完整列表">
        {controller.visibleRows.length === 0 ? <div className="price-volume-filter-empty" role="status"><strong>当前筛选没有行业</strong><span>二维图仍保留整个比较池作为背景。</span></div> : controller.visibleRows.map((row) => <IndustryRow controller={controller} key={row.sectorCode} row={row} selected={controller.selectedRow?.sectorCode === row.sectorCode} />)}
      </div>
    </section>
  );
}

function IndustryRow({ controller, row, selected }: { controller: SectorPriceVolumeController; row: PriceVolumeSnapshotRowViewModel; selected: boolean }) {
  const rank = controller.urlState?.sortBy === "amount-activity" ? row.amountRank : row.priceRank;
  const rankable = controller.urlState?.sortBy === "amount-activity" ? row.amountRankableCount : row.priceRankableCount;
  return (
    <div className={`price-volume-list-grid price-volume-list-row ${selected ? "selected" : ""}`} role="row" onMouseLeave={() => controller.setHoveredSector(null)}>
      <button aria-label={`选择${row.sectorName}`} className="price-volume-row-select" type="button" onBlur={() => controller.setHoveredSector(null)} onClick={() => controller.selectSector(row.sectorCode)} onFocus={() => controller.setHoveredSector(row.sectorCode)} onMouseEnter={() => controller.setHoveredSector(row.sectorCode)}>
        <span className="num price-volume-rank">{rank === null ? "--" : `${rank}/${rankable}`}</span>
        <span className="price-volume-row-identity"><strong title={row.sectorName}>{row.sectorName}</strong><small title={row.hierarchyPath}>{row.hierarchyPath}</small></span>
        <span className={`num ${directionClass(row.priceMomentumPct)}`}>{row.priceText}</span>
        <span className="num amount-value">{row.amountText}</span>
        <span className={`price-volume-status-chip ${row.stateClass}`}><i aria-hidden="true" />{row.stateText}</span>
      </button>
      {row.canDrillDown ? <button aria-label={`下钻${row.sectorName}`} className="price-volume-drill" type="button" onClick={(event) => { event.stopPropagation(); controller.drillDown(row); }}>›</button> : <span />}
    </div>
  );
}

function SortHeader({ active, direction, label, onClick }: { active: boolean; direction: "asc" | "desc"; label: string; onClick: () => void }) { return <button aria-label={`按${label}排序`} className={active ? "active" : ""} role="columnheader" type="button" onClick={onClick}>{label}{active ? (direction === "desc" ? " ↓" : " ↑") : ""}</button>; }
function directionClass(value: number | null) { if (value === null) return "muted"; if (value > 0) return "up"; if (value < 0) return "down"; return "flat"; }
function buildScopeTitle(scope: string, snapshot: { level1Code: string | null; level2Code: string | null }, meta: { hierarchy: { nodes: Array<{ sectorCode: string; sectorName: string }> } }) { if (scope === "level1") return "一级行业量价分布"; if (scope === "level2") return "二级行业量价分布"; if (scope === "level3") return "三级行业量价分布"; const parentCode = scope === "level1-children" ? snapshot.level1Code : snapshot.level2Code; const parent = meta.hierarchy.nodes.find((node) => node.sectorCode === parentCode)?.sectorName ?? "所选行业"; return `${parent}内${scope === "level1-children" ? "二级" : "三级"}行业量价分布`; }
