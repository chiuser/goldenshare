import { describe, expect, it } from "vitest";
import { buildSectorDailyInsightMetaViewModel, buildSectorDailyInsightSnapshotViewModel, DAILY_EVENT_LABELS } from "./sectorDailyInsightAdapter";
import { insightMeta, insightRequest, insightSnapshot } from "../testFixtures";

describe("daily insight strict transport and display", () => {
  it.each([1, 2, 3] as const)("keeps all rows, evidence, nulls and full server text at level %s", (level) => {
    const payload = insightSnapshot(level, 120);
    payload.headGainers[0].returnPct5d = null;
    const view = buildSectorDailyInsightSnapshotViewModel(payload, insightRequest(level));
    expect(view.headGainers).toHaveLength(120);
    expect(view.headGainers[0].returns[1].text).toBe("--");
    expect(view.headGainers[0].renderedText).toBe(payload.headGainers[0].renderedText);
    expect(view.headGainers[0].evidence).toEqual(["PRICE_VOLUME", "MEMBER_BREADTH"]);
    expect(view.headGainers[0].rankText).toBe("1 / 31");
    expect(view.facts).toEqual(payload);
  });
  it("has exactly the six approved fact labels", () => expect(Object.values(DAILY_EVENT_LABELS)).toEqual(["头部上涨", "头部下跌", "显著转强", "显著转弱", "逆势抗跌", "上涨滞后"]));
  it.each([0, null])("keeps ordinary strengthening/weakening when the daily return is %s", (value) => {
    const data = insightSnapshot();
    data.strengthening[0].returnPct1d = value;
    data.weakening = [{ ...data.strengthening[0], eventType: "WEAKENING" }];
    const view = buildSectorDailyInsightSnapshotViewModel(data, insightRequest());
    expect(view.strengthening[0].eventLabel).toBe("显著转强");
    expect(view.weakening[0].eventLabel).toBe("显著转弱");
  });
  it.each(["COUNTER_TREND_STRENGTHENING", "RISING_BUT_WEAKENING"] as const)("preserves the backend %s label, independent of text", (eventType) => {
    const data = insightSnapshot();
    const field = eventType === "COUNTER_TREND_STRENGTHENING" ? "strengthening" : "weakening";
    data[field] = [{ ...data.strengthening[0], eventType, renderedText: "后端原文，无需在前端重新分类。" }];
    const view = buildSectorDailyInsightSnapshotViewModel(data, insightRequest());
    expect(view[field][0].eventLabel).toBe(DAILY_EVENT_LABELS[eventType]);
    expect(view[field][0].renderedText).toBe(data[field][0].renderedText);
  });
  it("does not filter server-selected boundary crossings smaller than ten percentage points", () => {
    const data = insightSnapshot();
    Object.assign(data.strengthening[0], { previousPercentile20d: 79, currentPercentile20d: 81, percentileChangePp: 2 });
    data.weakening = [{ ...data.strengthening[0], eventType: "WEAKENING", previousPercentile20d: 21, currentPercentile20d: 19, percentileChangePp: -2 }];
    const view = buildSectorDailyInsightSnapshotViewModel(data, insightRequest());
    expect(view.strengthening).toHaveLength(1); expect(view.weakening).toHaveLength(1);
    expect(view.strengthening[0].eventLabel).toBe("显著转强"); expect(view.weakening[0].eventLabel).toBe("显著转弱");
  });
  it.each([true, false])("uses Meta as the only automatic-date authority (%s)", (delayed) => expect(buildSectorDailyInsightMetaViewModel(insightMeta(delayed)).status).toBe(delayed ? "DELAYED" : "READY"));
  it.each([
    { sql: "private SQL" }, { batchKey: "wrong" }, { observedTradeDate: "2025-08-22" }, { industryLevel: 2 }, { hierarchyVersion: "wrong" },
    { headGainers: [] }, { missingSectorCount: -1 }, { missingReasonCounts: [] },
  ])("rejects bad identity/counts or extra response fields %j", (update) => expect(() => buildSectorDailyInsightSnapshotViewModel({ ...insightSnapshot(), ...update }, insightRequest())).toThrow("每日洞察数据格式"));
  it.each([
    { eventType: "ENTER_TOP20" }, { returnPct1d: "3" }, { returnPct1d: Infinity }, { currentRank20d: 0 }, { currentRankableCount20d: 0 },
    { memberUpPctCurrent: 101 }, { primaryEvidenceType: "UNKNOWN" }, { secondaryEvidenceTypes: ["MEMBER_BREADTH", "DUAL_MOMENTUM"] },
    { primaryEvidenceType: null }, { secondaryEvidenceTypes: ["PRICE_VOLUME"] }, { sectorCode: "850401.SI" }, { templateVersion: "wrong" },
  ])("rejects malformed row %j", (update) => {
    const data = insightSnapshot();
    Object.assign(data.headGainers[0], update);
    expect(() => buildSectorDailyInsightSnapshotViewModel(data, insightRequest())).toThrow("每日洞察数据格式");
  });
  it("does not invent evidence or reject normal unavailable rotation states", () => {
    const data = insightSnapshot();
    data.headGainers[0].primaryEvidenceType = null; data.headGainers[0].secondaryEvidenceTypes = [];
    data.headGainers[0].rotationStatus20dCurrent = "DATA_INSUFFICIENT";
    expect(buildSectorDailyInsightSnapshotViewModel(data, insightRequest()).headGainers[0].evidence).toEqual([]);
  });
  it("rejects duplicate/out-of-order dates and unpublished default identities", () => {
    const meta = insightMeta(); meta.tradeDates.reverse();
    expect(() => buildSectorDailyInsightMetaViewModel(meta)).toThrow();
    expect(() => buildSectorDailyInsightMetaViewModel({ ...insightMeta(), defaultTradeDate: "2025-08-22" })).toThrow();
  });
});
