import { useLayoutEffect, useRef } from "react";

import type { SectorRelativeRotationController } from "../model/useSectorRelativeRotationController";

export function RelativeRotationSelectedSummary({ controller }: { controller: SectorRelativeRotationController }) {
  const { selectedRow, viewState } = controller;
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
  if ((viewState.kind !== "ready" && viewState.kind !== "delayed") || !selectedRow) return null;
  return (
    <section className={`relative-selected-summary ${viewState.pending ? "pending" : ""}`} aria-label={`${selectedRow.sectorName}相对轮动摘要`}>
      <div className="relative-selected-identity" ref={identityRef}>
        <div><strong ref={nameRef} title={selectedRow.sectorName}>{selectedRow.sectorName}</strong><span className={`relative-status-chip ${selectedRow.statusClass}`}>{selectedRow.statusText}</span></div>
        <span ref={pathRef} title={selectedRow.hierarchyPath}>{selectedRow.hierarchyPath}</span>
      </div>
      <div className="relative-selected-metrics">
        <Metric label="同组强度百分位" value={selectedRow.percentileText} />
        <Metric className={selectedRow.directionClass} label={`${viewState.results.analysis.period}日区间涨跌幅`} value={selectedRow.returnText} />
        <Metric className={selectedRow.percentileDelta5d === null ? "muted" : selectedRow.percentileDelta5d > 0 ? "up" : selectedRow.percentileDelta5d < 0 ? "down" : "flat"} label="5日强度变化" value={selectedRow.deltaText} />
      </div>
      {viewState.pending ? <span className="relative-selection-pending" role="status">正在更新所选行业</span> : null}
    </section>
  );
}

function Metric({ label, value, className = "" }: { label: string; value: string; className?: string }) { return <div><span>{label}</span><strong className={`num ${className}`}>{value}</strong></div>; }
