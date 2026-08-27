import type { SectorRankingRowViewModel } from "../model/sectorMomentumTypes";
import { MomentumRankingRow } from "./MomentumRankingRow";

interface MomentumRankingTableProps {
  rows: SectorRankingRowViewModel[];
  selectedCode: string;
  onSelect: (sectorCode: string) => void;
  onDrillDown: (row: SectorRankingRowViewModel) => void;
}

export function MomentumRankingTable({ rows, selectedCode, onSelect, onDrillDown }: MomentumRankingTableProps) {
  return (
    <div className="momentum-ranking-table" role="table" aria-label="行业动量完整排名">
      <div className="momentum-ranking-header" role="row">
        <span role="columnheader">序号</span>
        <span role="columnheader">行业</span>
        <span role="columnheader">上级路径</span>
        <span role="columnheader">区间涨跌幅</span>
        <span role="columnheader">组内分位</span>
        <span aria-hidden="true" />
      </div>
      <div className="momentum-ranking-viewport">
        <div className="momentum-ranking-rows" role="rowgroup">
          {rows.map((row) => (
            <MomentumRankingRow
              key={row.sectorCode}
              onDrillDown={onDrillDown}
              onSelect={onSelect}
              row={row}
              selected={row.sectorCode === selectedCode}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
