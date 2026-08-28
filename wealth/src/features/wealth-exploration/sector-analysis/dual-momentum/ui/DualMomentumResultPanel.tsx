import { useLayoutEffect, useRef, useState } from "react";

import type { SectorDualMomentumController } from "../model/useSectorDualMomentumController";
import type { SectorDualMomentumRowViewModel } from "../model/sectorDualMomentumTypes";

export function DualMomentumResultPanel({ controller }: { controller: SectorDualMomentumController }) {
  const { viewState, urlState } = controller;
  if ((viewState.kind !== "ready" && viewState.kind !== "delayed") || !urlState) return null;
  const analysis = viewState.results.analysis;
  const scopeTitle = buildScopeTitle(analysis.scope, analysis.parentSelection);
  return (
    <section className="dual-result-panel">
      <header className="dual-result-header">
        <div><strong>{scopeTitle}</strong><span className="momentum-period-chip">{analysis.period}日 · ≥{analysis.leadingThreshold}%</span></div>
        <div className="dual-result-view" aria-label="结果视图">
          <button aria-pressed={urlState.resultView === "qualified"} className={urlState.resultView === "qualified" ? "active" : ""} type="button" onClick={() => controller.selectResultView("qualified")}>符合条件</button>
          <button aria-pressed={urlState.resultView === "all"} className={urlState.resultView === "all" ? "active" : ""} type="button" onClick={() => controller.selectResultView("all")}>全部行业</button>
        </div>
      </header>
      <div className="dual-result-counts" aria-label="双动量结果统计">
        <CountCard label="比较池" value={analysis.totalCount} />
        <CountCard label="可计算" value={analysis.calculableCount} />
        <CountCard label="符合条件" value={analysis.qualifiedCount} />
        <CountCard label="数据不足" value={analysis.insufficientCount} />
      </div>
      <div className="dual-result-table" role="table" aria-label="双动量行业完整结果">
        <div className="dual-result-grid dual-result-table-header" role="row">
          <span role="columnheader">行业</span>
          <span role="columnheader">所属路径</span>
          <SortButton active={controller.sortColumn === "returnPct"} direction={controller.sortDirection} label="区间涨跌幅" onClick={() => controller.selectSort("returnPct")} />
          <span role="columnheader">强度排名</span>
          <SortButton active={controller.sortColumn === "percentile"} direction={controller.sortDirection} label="强度百分位" onClick={() => controller.selectSort("percentile")} />
          <span role="columnheader">当前状态</span>
          <span aria-hidden="true" />
        </div>
        <div className="dual-result-viewport">
          {controller.displayRows.length === 0 && urlState.resultView === "qualified" ? (
            <div className="dual-no-qualified" role="status">
              <strong>当前没有符合条件的行业</strong>
              <span>可以切换到全部行业查看当前比较池。</span>
              <button type="button" onClick={() => controller.selectResultView("all")}>查看全部行业</button>
            </div>
          ) : controller.displayRows.map((row, index) => (
            <DualMomentumRow controller={controller} index={index + 1} key={row.sectorCode} row={row} selected={row.sectorCode === viewState.selectedCode} />
          ))}
        </div>
      </div>
    </section>
  );
}

function DualMomentumRow({ controller, index, row, selected }: { controller: SectorDualMomentumController; index: number; row: SectorDualMomentumRowViewModel; selected: boolean }) {
  return (
    <div className={`dual-result-grid dual-result-row ${selected ? "selected" : ""}`} role="row">
      <button aria-label={`选择${row.sectorName}，当前视图第${index}位`} className="dual-result-row-select" type="button" onClick={() => controller.selectSector(row.sectorCode)}>
        <OverflowText className="dual-sector-name" text={row.sectorName} />
        <OverflowText className="dual-sector-path" text={row.hierarchyPath} />
        <span className={`num ${row.directionClass}`}>{row.returnText}</span>
        <span className="num">{row.rankText}</span>
        <span className="num">{row.percentileText}</span>
        <span className={`dual-status-chip ${row.statusClass}`}>{row.statusText}</span>
      </button>
      {row.canDrillDown ? <button aria-label={`下钻${row.sectorName}`} className="dual-drill-button" type="button" onClick={() => controller.drillDown(row)}>›</button> : <span />}
    </div>
  );
}

function CountCard({ label, value }: { label: string; value: number }) {
  return <div><span>{label}</span><strong className="num">{value}</strong></div>;
}

function SortButton({ active, direction, label, onClick }: { active: boolean; direction: "asc" | "desc"; label: string; onClick: () => void }) {
  return <button aria-label={`按${label}排序`} aria-sort={active ? (direction === "desc" ? "descending" : "ascending") : "none"} role="columnheader" type="button" onClick={onClick}>{label}{active ? (direction === "desc" ? " ↓" : " ↑") : " ↕"}</button>;
}

function OverflowText({ className, text }: { className: string; text: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [overflow, setOverflow] = useState(false);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => setOverflow(element.scrollWidth > element.clientWidth);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text]);
  return <span className={className} ref={ref} title={overflow ? text : undefined}>{text}</span>;
}

function buildScopeTitle(scope: string, parent: { level1Name: string | null; level2Name: string | null }) {
  if (scope === "LEVEL_1") return "一级行业总榜";
  if (scope === "LEVEL_2") return "二级行业总榜";
  if (scope === "LEVEL_3") return "三级行业总榜";
  if (scope === "LEVEL_1_CHILDREN") return `${parent.level1Name ?? "当前一级行业"}内二级行业`;
  return `${parent.level2Name ?? "当前二级行业"}内三级行业`;
}
