import type {
  SectorMomentumRankingViewModel,
  SectorRankingRowViewModel,
} from "../model/sectorMomentumTypes";
import { MomentumRankingTable } from "./MomentumRankingTable";

interface MomentumRankingPanelProps {
  ranking: SectorMomentumRankingViewModel;
  selectedCode: string;
  onSelect: (sectorCode: string) => void;
  onDrillDown: (row: SectorRankingRowViewModel) => void;
  compact?: boolean;
}

export function MomentumRankingPanel({
  ranking,
  selectedCode,
  onSelect,
  onDrillDown,
  compact = false,
}: MomentumRankingPanelProps) {
  return (
    <section
      className={`momentum-ranking-panel${compact ? " momentum-ranking-panel-compact" : ""}`}
      aria-label={buildScopeTitle(ranking)}
    >
      <div className="momentum-panel-header">
        <div>
          <strong>{buildScopeTitle(ranking)}</strong>
          <span className="momentum-period-chip">{ranking.period}日</span>
        </div>
        <span>{ranking.totalCount} 个行业</span>
      </div>
      <MomentumRankingTable
        onDrillDown={onDrillDown}
        onSelect={onSelect}
        rows={ranking.rows}
        selectedCode={selectedCode}
      />
    </section>
  );
}

export function buildScopeTitle(ranking: Pick<SectorMomentumRankingViewModel, "scope" | "parentSelection">): string {
  if (ranking.scope === "LEVEL_1") return "一级行业总榜";
  if (ranking.scope === "LEVEL_2") return "二级行业总榜";
  if (ranking.scope === "LEVEL_3") return "三级行业总榜";
  if (ranking.scope === "LEVEL_1_CHILDREN") return `${ranking.parentSelection.level1Name ?? "一级行业"}内二级行业`;
  return `${ranking.parentSelection.level2Name ?? "二级行业"}内三级行业`;
}
