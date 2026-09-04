import type { DailyInsightItem, DailyInsightMeta, DailyInsightSnapshot, DailyInsightSnapshotRequest } from "./sectorDailyInsightContract";
export type { DailyInsightItem, DailyInsightMeta, DailyInsightSnapshot, DailyInsightSnapshotRequest };
export type DailyInsightLevel = 1 | 2 | 3;
export type DailyInsightEvidence = NonNullable<DailyInsightItem["primaryEvidenceType"]>;
export interface DailyInsightUrlState { market: "CN_A"; tradeDate: string | null; level: DailyInsightLevel }
export interface DailyInsightValue { text: string; direction: "up" | "down" | "flat" | "missing" }
export interface DailyInsightRowViewModel {
  sectorCode: string; sectorName: string; hierarchyPath: string; industryLevel: DailyInsightLevel;
  eventType: DailyInsightItem["eventType"]; eventLabel: string; renderedText: string;
  returns: [DailyInsightValue, DailyInsightValue, DailyInsightValue]; rankText: string;
  evidence: DailyInsightEvidence[];
}
export interface DailyInsightSnapshotViewModel {
  facts: DailyInsightSnapshot;
  headGainers: DailyInsightRowViewModel[]; headLosers: DailyInsightRowViewModel[];
  strengthening: DailyInsightRowViewModel[]; weakening: DailyInsightRowViewModel[];
  overview: Array<{ label: string; value: string; note: string; tone: "up" | "brand" | "info" | "flat" }>;
  missingText: string | null;
}
export type DailyInsightViewState = {
  kind: "loading" | "ready" | "delayed" | "empty" | "error";
  meta?: DailyInsightMeta; snapshot?: DailyInsightSnapshotViewModel; message?: string; retryable?: boolean;
};
