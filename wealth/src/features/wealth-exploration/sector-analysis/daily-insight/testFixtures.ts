import type { DailyInsightItem, DailyInsightMeta, DailyInsightSnapshot, DailyInsightSnapshotRequest } from "./api/sectorDailyInsightTypes";

export const INSIGHT_DAY = "2025-08-25";
export const INSIGHT_BATCH = "3b3393fc-5a55-4b57-a59c-e7aa241ceabc";
export function insightRequest(industryLevel: 1 | 2 | 3 = 1): DailyInsightSnapshotRequest {
  return { tradeDate: INSIGHT_DAY, industryLevel, batchKey: INSIGHT_BATCH, hierarchyVersion: "hierarchy-1" };
}
export function insightMeta(delayed = false): DailyInsightMeta {
  const publishedAt = "2025-08-25T21:00:00Z";
  const requestedTradeDate = delayed ? "2025-08-26" : INSIGHT_DAY;
  return {
    status: delayed ? "DELAYED" : "READY", message: null, exceptionCode: null, contractKey: "sector-daily-insight", contractVersion: 1,
    formulaBundleVersion: "sector-analysis-daily@1", templateVersion: "sector-daily-insight@2", levels: [1, 2, 3], defaultLevel: 1,
    dateContext: { requestedTradeDate, observedTradeDate: INSIGHT_DAY, previousTradeDate: "2025-08-22", mode: "AUTO", isDelayed: delayed, asOf: publishedAt, delayReason: delayed ? "目标日尚未发布" : null },
    coverageStartDate: "2025-08-22", coverageEndDate: requestedTradeDate,
    tradeDates: [
      { tradeDate: "2025-08-22", availability: "MISSING", batchKey: null, hierarchyVersion: null, publishedAt: null },
      { tradeDate: INSIGHT_DAY, availability: "PUBLISHED", batchKey: INSIGHT_BATCH, hierarchyVersion: "hierarchy-1", publishedAt },
      ...(delayed ? [{ tradeDate: requestedTradeDate, availability: "MISSING" as const, batchKey: null, hierarchyVersion: null, publishedAt: null }] : []),
    ], defaultTradeDate: INSIGHT_DAY, defaultBatchKey: INSIGHT_BATCH, hierarchyVersion: "hierarchy-1",
  };
}
export function insightItem(index = 0, level: 1 | 2 | 3 = 1, eventType: DailyInsightItem["eventType"] = "HEAD_GAINER"): DailyInsightItem {
  return {
    sectorCode: `BK${String(1000 + index).padStart(4, "0")}.DC`, sectorName: index === 0 ? "通信网络设备及器件" : `行业${index}`, hierarchyPath: "通信 > 通信设备 > 通信网络设备及器件", industryLevel: level, eventType,
    returnPct1d: 3, returnPct5d: 4, returnPct20d: 10,
    currentRank20d: 1, currentRankableCount20d: 31, currentPercentile20d: 100,
    previousRank20d: 4, previousRankableCount20d: 31, previousPercentile20d: 90, rankChange: 3, percentileChangePp: 10,
    priceVolumeStateCurrent: "JOINT", priceVolumeStatePrevious: "PRICE_ONLY",
    dualQualification20d80Current: "QUALIFIED", dualQualification20d80Previous: "NOT_QUALIFIED",
    rotationStatus20dCurrent: "LEADING_IMPROVING", rotationStatus20dPrevious: "SAMPLE_INSUFFICIENT",
    memberUpPctCurrent: 60, memberUpPctPrevious: 55, turnoverUpPctCurrent: null, turnoverUpPctPrevious: null,
    ma20AbovePctCurrent: 50, ma20AbovePctPrevious: 50,
    primaryEvidenceType: "PRICE_VOLUME", secondaryEvidenceTypes: ["MEMBER_BREADTH"],
    templateKey: "sector-daily-insight", templateVersion: "sector-daily-insight@2",
    renderedText: "当前20日强度从第4/31名升至第1/31名；量价共同增强，上涨成分股占比由55%升至60%。这是后端完整原文，不得裁切或重新解释。",
  };
}
export function insightSnapshot(level: 1 | 2 | 3 = 1, rows = 3): DailyInsightSnapshot {
  return {
    batchKey: INSIGHT_BATCH, hierarchyVersion: "hierarchy-1", industryLevel: level, status: "READY", message: null, exceptionCode: null,
    requestedTradeDate: INSIGHT_DAY, observedTradeDate: INSIGHT_DAY, previousTradeDate: "2025-08-22",
    formulaBundleVersion: "sector-analysis-daily@1", templateVersion: "sector-daily-insight@2",
    publishedAt: "2025-08-25T21:00:00Z", calculatedAt: "2025-08-25T21:00:00Z",
    summary: { sectorCount: 337, calculableCount: rows * 2 + 1, missingCount: 336 - rows * 2, upCount: rows, downCount: rows, flatCount: 1, medianChangePct1d: 0,
      dualMomentumCount20d80: 6, leadingImprovingCount20d5d: 5, priceVolumeJointCount20d: 7, breadthUpShareAbove50Count: 18,
      missingHistoryCount: 0, missingDateCount: 0, missingPriceCount: 336 - rows * 2, missingMemberCount: 0, missingAmountCount: 0,
      missingAdjFactorCount: 0, missingGroupSizeCount: 0, missingCoverageCount: 0, missingPreviousBatchCount: 0, missingOtherCount: 0 },
    headGainers: Array.from({ length: rows }, (_, i) => insightItem(i, level)),
    headLosers: Array.from({ length: rows }, (_, i) => ({ ...insightItem(i + rows, level, "HEAD_LOSER"), returnPct1d: -3 })),
    strengthening: [insightItem(0, level, "STRENGTHENING")], weakening: [],
    missingSectorCount: 336 - rows * 2, missingReasonCounts: [{ reasonCode: "PRICE", count: 336 - rows * 2 }],
  };
}
export function insightJson(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }); }
