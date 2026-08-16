import type {
  ConceptRankMetric,
  IndustryRankMetric,
  RegionRankMetric,
  SectorOverviewView,
  SectorRankMetric,
} from "./api/marketSectorOverviewApi";

const RANK_OPTIONS: {
  INDUSTRY: Array<[IndustryRankMetric, string]>;
  CONCEPT: Array<[ConceptRankMetric, string]>;
  REGION: Array<[RegionRankMetric, string]>;
} = {
  INDUSTRY: [
    ["CHANGE_PCT_UP", "涨幅榜"],
    ["CHANGE_PCT_DOWN", "跌幅榜"],
    ["MAIN_NET_INFLOW", "主力净流入"],
    ["UP_COUNT", "上涨家数"],
  ],
  CONCEPT: [
    ["HEAT_SCORE", "综合热度"],
    ["HEAT_DELTA_1D", "热度变化"],
    ["CHANGE_PCT", "涨跌幅"],
    ["MAIN_NET_INFLOW", "主力净流入"],
  ],
  REGION: [
    ["CHANGE_PCT", "涨跌幅"],
    ["MAIN_NET_INFLOW", "主力净流入"],
    ["UP_COUNT", "上涨家数"],
  ],
};

export function SectorRankingToolbar({
  view,
  rankMetric,
  onRankChange,
}: {
  view: SectorOverviewView;
  rankMetric: SectorRankMetric;
  onRankChange: (rankMetric: SectorRankMetric) => void;
}) {
  return (
    <div className="sector-ranking-toolbar">
      <div className="sector-rank-options">
        <span>排序维度</span>
        {RANK_OPTIONS[view].map(([key, label]) => (
          <button
            aria-pressed={rankMetric === key}
            className={rankMetric === key ? "active" : ""}
            key={key}
            type="button"
            onClick={() => onRankChange(key)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
