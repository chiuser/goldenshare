import { parseDailyInsightMeta, parseDailyInsightSnapshot } from "./sectorDailyInsightContract";
import type { DailyInsightItem, DailyInsightRowViewModel, DailyInsightSnapshotRequest, DailyInsightSnapshotViewModel, DailyInsightValue } from "./sectorDailyInsightTypes";

export { parseDailyInsightMeta as buildSectorDailyInsightMetaViewModel };
export const DAILY_EVENT_LABELS: Record<DailyInsightItem["eventType"], string> = {
  HEAD_GAINER: "头部上涨", HEAD_LOSER: "头部下跌", STRENGTHENING: "显著转强", WEAKENING: "显著转弱",
  COUNTER_TREND_STRENGTHENING: "逆势抗跌", RISING_BUT_WEAKENING: "上涨滞后",
};
export const DAILY_LEVEL_LABELS = { 1: "一级行业", 2: "二级行业", 3: "三级行业" } as const;
const REASONS: Record<string, string> = { HISTORY: "历史不足", DATE: "日期缺失", PRICE: "价格缺失", MEMBER: "成员缺失", AMOUNT: "成交额缺失", ADJ_FACTOR: "复权因子缺失", GROUP_SIZE: "比较组不足", COVERAGE: "覆盖不足", PREVIOUS_BATCH: "上一交易日不可比较", OTHER: "其他缺失" };

export function dailyInsightPercent(value: number | null): DailyInsightValue {
  return value === null ? { text: "--", direction: "missing" } : { text: `${value > 0 ? "+" : ""}${value.toFixed(2)}%`, direction: value > 0 ? "up" : value < 0 ? "down" : "flat" };
}
export function buildSectorDailyInsightSnapshotViewModel(payload: unknown, request: DailyInsightSnapshotRequest): DailyInsightSnapshotViewModel {
  const facts = parseDailyInsightSnapshot(payload, request);
  const s = facts.summary;
  return {
    facts,
    headGainers: facts.headGainers.map(toRow), headLosers: facts.headLosers.map(toRow), strengthening: facts.strengthening.map(toRow), weakening: facts.weakening.map(toRow),
    overview: [
      { label: "市场结构", value: `${s.upCount}涨 / ${s.downCount}跌 / ${s.flatCount}平`, note: `涨跌幅中位数 ${dailyInsightPercent(s.medianChangePct1d).text}`, tone: "up" },
      { label: "双动量", value: String(s.dualMomentumCount20d80), note: "同时满足绝对与相对动量", tone: "brand" },
      { label: "领先且增强", value: String(s.leadingImprovingCount20d5d), note: "20日强度 · 5日变化", tone: "info" },
      { label: "量价共同增强", value: String(s.priceVolumeJointCount20d), note: "20日涨幅与成交活跃度同强", tone: "brand" },
      { label: "上涨广度 > 50%", value: String(s.breadthUpShareAbove50Count), note: "可计算行业中的数量", tone: "up" },
    ],
    missingText: facts.missingReasonCounts.length ? `${facts.missingSectorCount}个行业存在缺失；${facts.missingReasonCounts.map((r) => `${REASONS[r.reasonCode]} ${r.count}`).join("；")}` : null,
  };
}
function toRow(row: DailyInsightItem): DailyInsightRowViewModel {
  return {
    sectorCode: row.sectorCode, sectorName: row.sectorName, hierarchyPath: row.hierarchyPath, industryLevel: row.industryLevel,
    eventType: row.eventType, eventLabel: DAILY_EVENT_LABELS[row.eventType], renderedText: row.renderedText,
    returns: [dailyInsightPercent(row.returnPct1d), dailyInsightPercent(row.returnPct5d), dailyInsightPercent(row.returnPct20d)],
    rankText: row.currentRank20d === null || row.currentRankableCount20d === null ? "--" : `${row.currentRank20d} / ${row.currentRankableCount20d}`,
    evidence: row.primaryEvidenceType ? [row.primaryEvidenceType, ...row.secondaryEvidenceTypes] : [],
  };
}
