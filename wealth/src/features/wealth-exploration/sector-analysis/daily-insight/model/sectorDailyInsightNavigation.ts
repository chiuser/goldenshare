import { buildSectorMomentumSearch } from "../../momentum-ranking/model/sectorMomentumUrlState";
import { buildSectorDualMomentumSearch, DEFAULT_DUAL_MOMENTUM_URL_STATE } from "../../dual-momentum/model/sectorDualMomentumUrlState";
import { buildSectorRelativeRotationSearch, DEFAULT_RELATIVE_ROTATION_URL_STATE } from "../../relative-rotation/model/sectorRelativeRotationUrlState";
import { buildSectorMemberBreadthSearch, DEFAULT_SECTOR_MEMBER_BREADTH_URL_STATE } from "../../member-breadth/model/sectorMemberBreadthUrlState";
import { buildSectorPriceVolumeSearch, DEFAULT_PRICE_VOLUME_URL_STATE } from "../../price-volume/model/sectorPriceVolumeUrlState";
import type { DailyInsightEvidence, DailyInsightRowViewModel } from "../api/sectorDailyInsightTypes";
import type { SectorAnalysisMethod } from "../../navigation/SectorAnalysisMethodBar";

export interface DailyInsightDestination { method: SectorAnalysisMethod; search: string }
export const DAILY_EVIDENCE_LABELS: Record<DailyInsightEvidence, string> = {
  PRICE_VOLUME: "量价分布", MEMBER_BREADTH: "成员广度", TURNOVER_BREADTH: "成交额广度", MA20_BREADTH: "均线位置广度", DUAL_MOMENTUM: "双动量", RELATIVE_ROTATION: "相对轮动",
};
export function dailyInsightDestination(row: DailyInsightRowViewModel, tradeDate: string, evidence?: DailyInsightEvidence): DailyInsightDestination {
  const identity = { tradeDate, scope: `level${row.industryLevel}` as "level1" | "level2" | "level3", sectorCode: row.sectorCode, level1Code: null, level2Code: null };
  if (evidence === "DUAL_MOMENTUM") return { method: "dual-momentum", search: buildSectorDualMomentumSearch({ ...DEFAULT_DUAL_MOMENTUM_URL_STATE, ...identity, period: 20, threshold: 80, resultView: "all" }) };
  if (evidence === "RELATIVE_ROTATION") return { method: "relative-rotation", search: buildSectorRelativeRotationSearch({ ...DEFAULT_RELATIVE_ROTATION_URL_STATE, ...identity, period: 20, trailLength: 20, quadrant: "all" }) };
  if (evidence === "PRICE_VOLUME") return { method: "price-volume", search: buildSectorPriceVolumeSearch({ ...DEFAULT_PRICE_VOLUME_URL_STATE, ...identity, period: 20, stateFilter: "all", sortBy: "price-momentum", sortDirection: "desc", historyRange: 20 }) };
  if (evidence) return { method: "member-breadth", search: buildSectorMemberBreadthSearch({ ...DEFAULT_SECTOR_MEMBER_BREADTH_URL_STATE, ...identity, direction: "up", metric: "member-count", maPeriod: 20, historyRange: 20 }) };
  return { method: "momentum-ranking", search: buildSectorMomentumSearch({ ...identity, market: "CN_A", debug: false, period: 20, direction: "gainers", range: 20 }) };
}
