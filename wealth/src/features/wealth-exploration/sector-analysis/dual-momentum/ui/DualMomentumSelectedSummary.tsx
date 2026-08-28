import { useLayoutEffect, useRef } from "react";

import type { SectorDualMomentumController } from "../model/useSectorDualMomentumController";

export function DualMomentumSelectedSummary({ controller }: { controller: SectorDualMomentumController }) {
  const { selectedRow, viewState, urlState } = controller;
  const identityRef = useRef<HTMLDivElement>(null);
  const nameRef = useRef<HTMLElement>(null);
  const pathRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const identity = identityRef.current;
    const name = nameRef.current;
    const path = pathRef.current;
    if (!identity || !name || !path) return;
    const update = () => {
      identity.classList.remove("compact", "extra-compact");
      const overflows = () => name.scrollWidth > name.clientWidth || path.scrollWidth > path.clientWidth;
      if (!overflows()) return;
      identity.classList.add("compact");
      if (overflows()) identity.classList.add("extra-compact");
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(identity);
    return () => observer.disconnect();
  }, [selectedRow?.hierarchyPath, selectedRow?.sectorName]);

  if ((viewState.kind !== "ready" && viewState.kind !== "delayed") || !urlState) return null;
  const analysis = viewState.results.analysis;
  if (!selectedRow) {
    return (
      <section className="dual-selected-summary dual-selected-summary-empty" aria-label="未选择行业">
        <strong>当前未选择行业</strong><span>切换到“全部行业”可查看并选择当前比较池。</span>
      </section>
    );
  }
  return (
    <section className="dual-selected-summary" aria-label={`${selectedRow.sectorName}双动量摘要`}>
      <div className="dual-selected-identity" ref={identityRef}>
        <div>
          <strong ref={nameRef}>{selectedRow.sectorName}</strong>
          <span className={`dual-status-chip ${selectedRow.statusClass}`}>{selectedRow.statusText}</span>
        </div>
        <span ref={pathRef} title={selectedRow.hierarchyPath}>{selectedRow.hierarchyPath}</span>
        {selectedRow.canDrillDown ? <button type="button" onClick={() => controller.drillDown(selectedRow)}>查看直属下级行业 →</button> : <i />}
      </div>
      <div className="dual-selected-metrics">
        <Metric className={selectedRow.directionClass} label={`${urlState.period}日区间涨跌幅`} value={selectedRow.returnText} />
        <Metric label="同组强度排名" value={selectedRow.strengthRank === null ? "--" : `${selectedRow.strengthRank} / ${analysis.calculableCount}`} />
        <Metric label="强度百分位" value={selectedRow.percentileText} />
      </div>
    </section>
  );
}

function Metric({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return <div><span>{label}</span><strong className={`num ${className}`}>{value}</strong></div>;
}
