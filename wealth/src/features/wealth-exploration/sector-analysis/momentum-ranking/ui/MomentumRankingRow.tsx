import { useEffect, useRef, useState } from "react";

import type { SectorRankingRowViewModel } from "../model/sectorMomentumTypes";
import { MomentumReturnBar } from "./MomentumReturnBar";

interface MomentumRankingRowProps {
  row: SectorRankingRowViewModel;
  selected: boolean;
  onSelect: (sectorCode: string) => void;
  onDrillDown: (row: SectorRankingRowViewModel) => void;
}

export function MomentumRankingRow({
  row,
  selected,
  onSelect,
  onDrillDown,
}: MomentumRankingRowProps) {
  return (
    <div className={`momentum-ranking-row ${selected ? "selected" : ""}`} role="row">
      <button
        aria-label={`选择${row.sectorName}`}
        className="momentum-ranking-row-select"
        type="button"
        onClick={() => onSelect(row.sectorCode)}
      >
        <span className="momentum-list-position num" role="cell">{row.listPosition}</span>
        <OverflowText className="momentum-sector-name" text={row.sectorName} />
        <OverflowText className="momentum-hierarchy-path" text={row.hierarchyPath} />
        <span role="cell">
          <MomentumReturnBar value={row.returnPct} widthPct={row.returnBarWidthPct} label={row.returnText} />
        </span>
        <span className="momentum-percentile num" role="cell">{row.percentileText}</span>
      </button>
      {row.canDrillDown ? (
        <button
          aria-label={`下钻${row.sectorName}`}
          className="momentum-drill-button"
          title={`查看${row.sectorName}下级行业`}
          type="button"
          onClick={() => onDrillDown(row)}
        >
          ›
        </button>
      ) : <span className="momentum-drill-placeholder" aria-hidden="true" />}
    </div>
  );
}

function OverflowText({ className, text }: { className: string; text: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => setOverflowing(element.scrollWidth > element.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text]);

  return (
    <span className={className} ref={ref} role="cell" title={overflowing ? text : undefined}>
      {text}
    </span>
  );
}
