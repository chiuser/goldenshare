import type { SectorRelativeRotationController } from "../model/useSectorRelativeRotationController";
import type { SectorRelativeRotationQuadrantFilter, SectorRelativeRotationRowViewModel } from "../model/sectorRelativeRotationTypes";

const FILTERS: ReadonlyArray<{ value: SectorRelativeRotationQuadrantFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "leading-improving", label: "领先且改善" },
  { value: "weak-improving", label: "偏弱但改善" },
  { value: "strong-not-improving", label: "强势未改善" },
  { value: "weak-not-improving", label: "偏弱未改善" },
];

export function RelativeRotationIndustryList({ controller }: { controller: SectorRelativeRotationController }) {
  const { urlState, viewState } = controller;
  if ((viewState.kind !== "ready" && viewState.kind !== "delayed") || !urlState) return null;
  const analysis = viewState.results.analysis;
  return (
    <section className="relative-industry-list">
      <header><div><strong>行业列表</strong><span>{analysis.totalCount} 个行业</span></div><span>{analysis.plottableCount} 可绘制 · {analysis.missingCoordinateCount} 坐标缺失</span></header>
      <div className="relative-list-filters">
        <label><span className="sr-only">搜索行业</span><input aria-label="搜索行业" placeholder="搜索行业名称或代码" type="search" value={urlState.search} onChange={(event) => controller.setSearch(event.target.value)} /></label>
        <div aria-label="象限筛选" className="relative-quadrant-filters">{FILTERS.map((filter) => <button aria-pressed={urlState.quadrant === filter.value} className={urlState.quadrant === filter.value ? "active" : ""} key={filter.value} type="button" onClick={() => controller.selectQuadrant(filter.value)}>{filter.label}</button>)}</div>
      </div>
      <div className="relative-list-table" role="table" aria-label="相对轮动行业完整列表">
        <div className="relative-list-grid relative-list-header" role="row"><span role="columnheader">行业</span><span role="columnheader">强度</span><span role="columnheader">5日变化</span><span role="columnheader">当前状态</span><span aria-hidden="true" /></div>
        <div className="relative-list-viewport">
          {controller.visibleRows.length === 0 ? <div className="relative-filter-empty" role="status"><strong>没有匹配的行业</strong><span>图中仍保留当前比较池的全部行业。</span></div> : controller.visibleRows.map((row) => <RelativeRotationListRow controller={controller} key={row.sectorCode} row={row} selected={row.sectorCode === analysis.selectedSectorCode} />)}
        </div>
      </div>
    </section>
  );
}

function RelativeRotationListRow({ controller, row, selected }: { controller: SectorRelativeRotationController; row: SectorRelativeRotationRowViewModel; selected: boolean }) {
  return (
    <div className={`relative-list-grid relative-list-row ${selected ? "selected" : ""}`} role="row" onMouseLeave={() => controller.setHoveredSector(null)}>
      <button aria-label={`选择${row.sectorName}`} className="relative-list-row-select" type="button" onBlur={() => controller.setHoveredSector(null)} onClick={() => controller.selectSector(row.sectorCode)} onFocus={() => controller.setHoveredSector(row.sectorCode)} onMouseEnter={() => controller.setHoveredSector(row.sectorCode)}>
        <span className="relative-list-name" title={row.sectorName}><strong>{row.sectorName}</strong><small title={row.hierarchyPath}>{row.hierarchyPath}</small></span>
        <span className="num">{row.percentileText}</span><span className="num">{row.deltaText}</span><span className={`relative-status-chip ${row.statusClass}`}>{row.statusText}</span>
      </button>
      {row.canDrillDown ? <button aria-label={`下钻${row.sectorName}`} className="relative-drill-button" type="button" onClick={(event) => { event.stopPropagation(); controller.drillDown(row); }}>›</button> : <span />}
    </div>
  );
}
