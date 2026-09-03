import { describe, expect, it } from "vitest";
import { buildSectorMemberBreadthDetailsViewModel, buildSectorMemberBreadthMetaViewModel, buildSectorMemberBreadthRankingsViewModel, SectorMemberBreadthContractError } from "./sectorMemberBreadthAdapter";
import { breadthDetailsPayload, breadthMetaPayload, breadthRankingsPayload } from "./sectorMemberBreadthTestFixtures";

const rankingRequest = { market: "CN_A", tradeDate: "2026-08-27", scope: "LEVEL_1", direction: "UP", metric: "MEMBER_COUNT", maPeriod: 20, hierarchyVersion: "dc-industry-v1" } as const;
const detailsRequest = { market: "CN_A", tradeDate: "2026-08-27", sectorCode: "BK1001.DC", direction: "UP", maPeriod: 20, historyRange: 20, hierarchyVersion: "dc-industry-v1" } as const;

describe("sectorMemberBreadthAdapter", () => {
  it.each(["PARTIAL", "MISSING"])("keeps the server-selected published %s day without fallback", (availability) => {
    const payload = breadthMetaPayload();
    Object.assign(payload.tradeDates.at(-1)!, { availability, validSectorCount: availability === "PARTIAL" ? 2 : 0 });
    const result = buildSectorMemberBreadthMetaViewModel(payload);
    expect(result.dateContext.defaultStatus).toBe("READY");
    expect(result.dateContext.defaultTradeDate).toBe("2026-08-27");
    payload.dateContext.defaultStatus = "DELAYED";
    expect(() => buildSectorMemberBreadthMetaViewModel(payload)).toThrow(/日期与状态/);
  });

  it.each([1, 2])("preserves stored rank %s when rounded percentages coincide", (secondRank) => {
    const payload = breadthRankingsPayload(new URL("http://localhost/rankings"));
    payload.rows.forEach((row, index) => Object.assign(row, {
      rank: index === 0 ? 1 : secondRank, rankTotal: 2, metricValuePct: 33.3333,
      sourceMemberCount: 6, calculableCount: 6, coveragePct: 100,
      qualificationStatus: "ELIGIBLE", reasonCodes: [],
    }));
    Object.assign(payload, { eligibleSectorCount: 2, ineligibleSectorCount: 0 });
    payload.availability.eligibleSectorCount = 2;
    const result = buildSectorMemberBreadthRankingsViewModel(payload, rankingRequest);
    expect(result.kind).toBe("ready");
    if (result.kind === "ready") expect(result.data.rows[1]!.rank).toBe(secondRank);
    payload.rows[1]!.rank = 3;
    expect(() => buildSectorMemberBreadthRankingsViewModel(payload, rankingRequest)).toThrow(/竞争排名/);
  });

  it("accepts an unavailable zero-amount composition despite sufficient count and coverage", () => {
    const payload = breadthDetailsPayload(new URL("http://localhost/details"));
    Object.assign(payload.compositions[1]!, {
      eligible: false, positivePct: null, neutralPct: null, negativePct: null,
      reasonCodes: ["AMOUNT_NON_POSITIVE"],
    });
    const result = buildSectorMemberBreadthDetailsViewModel(payload, detailsRequest);
    expect(result.kind).toBe("ready");
    if (result.kind === "ready") expect(result.data.compositions[1]!.positivePct).toBeNull();
  });

  it("accepts the full unavailable pool in an EMPTY rankings response", () => {
    const payload = breadthRankingsPayload(new URL("http://localhost/rankings"), { allIneligible: true });
    Object.assign(payload, { status: "EMPTY", exceptionCode: "SA_SOURCE_EMPTY" });
    Object.assign(payload.availability, { calculableSectorCount: 0, status: "UNAVAILABLE" });
    expect(buildSectorMemberBreadthRankingsViewModel(payload, rankingRequest).kind).toBe("empty");
  });

  it.each([
    { counts: [2, 2, 2], percentages: [33.3333, 33.3333, 33.3333] },
    { counts: [1, 1, 4], percentages: [16.6667, 16.6667, 66.6667] },
    { counts: [2, 2, 2], percentages: [100 / 3, 100 / 3, 100 / 3] },
  ])("accepts normal composition rounding without changing the values: $percentages", ({ counts, percentages }) => {
    const payload = breadthDetailsPayload(new URL("http://localhost/details"));
    for (const row of payload.compositions) {
      Object.assign(row, {
        sourceCount: 6, calculableCount: 6, coveragePct: 100, eligible: true,
        positiveCount: counts[0], neutralCount: counts[1], negativeCount: counts[2],
        positivePct: percentages[0], neutralPct: percentages[1], negativePct: percentages[2],
      });
    }
    const result = buildSectorMemberBreadthDetailsViewModel(payload, detailsRequest);
    expect(result.kind).toBe("ready");
    if (result.kind === "ready") {
      for (const row of result.data.compositions) {
        expect([row.positivePct, row.neutralPct, row.negativePct]).toEqual(percentages);
      }
    }
  });

  it.each([
    [33.3332, 33.3333, 33.3333],
    [33.3334, 33.3334, 33.3334],
  ])("rejects composition totals beyond rounding allowance: %s, %s, %s", (positivePct, neutralPct, negativePct) => {
    const payload = breadthDetailsPayload(new URL("http://localhost/details"));
    Object.assign(payload.compositions[0]!, { positivePct, neutralPct, negativePct });
    expect(() => buildSectorMemberBreadthDetailsViewModel(payload, detailsRequest)).toThrow(/百分比之和/);
  });

  it.each([
    { sourceCount: 6, calculableCount: 5, coveragePct: 83.3333, accepted: true },
    { sourceCount: 9, calculableCount: 8, coveragePct: 88.8889, accepted: true },
    { sourceCount: 6, calculableCount: 5, coveragePct: 100 * 5 / 6, accepted: true },
    { sourceCount: 6, calculableCount: 5, coveragePct: 83.3334, accepted: false },
    { sourceCount: 9, calculableCount: 8, coveragePct: 88.8888, accepted: false },
  ])("checks rounding for both ranking and composition coverage: $coveragePct", ({ sourceCount, calculableCount, coveragePct, accepted }) => {
    const rankings = breadthRankingsPayload(new URL("http://localhost/rankings"));
    Object.assign(rankings.rows[0]!, { sourceMemberCount: sourceCount, calculableCount, coveragePct });
    const details = breadthDetailsPayload(new URL("http://localhost/details"));
    Object.assign(details.compositions[0]!, {
      sourceCount, calculableCount, coveragePct, eligible: true,
      positiveCount: calculableCount, neutralCount: 0, negativeCount: 0,
      positivePct: 100, neutralPct: 0, negativePct: 0,
    });
    if (!accepted) {
      expect(() => buildSectorMemberBreadthRankingsViewModel(rankings, rankingRequest)).toThrow(/覆盖率与数量/);
      expect(() => buildSectorMemberBreadthDetailsViewModel(details, detailsRequest)).toThrow(/覆盖率与数量/);
      return;
    }
    const rankingResult = buildSectorMemberBreadthRankingsViewModel(rankings, rankingRequest);
    const detailsResult = buildSectorMemberBreadthDetailsViewModel(details, detailsRequest);
    expect(rankingResult.kind).toBe("ready");
    expect(detailsResult.kind).toBe("ready");
    if (rankingResult.kind === "ready") expect(rankingResult.data.rows[0]!.coveragePct).toBe(coveragePct);
    if (detailsResult.kind === "ready") expect(detailsResult.data.compositions[0]!.coveragePct).toBe(coveragePct);
  });

  it.each([
    { positivePct: Number.NaN },
    { positivePct: Number.POSITIVE_INFINITY },
    { positivePct: -0.00001 },
    { positivePct: 100.00001 },
    { positivePct: null },
    { positiveCount: 13 },
  ])("still rejects invalid composition fields: %j", (changes) => {
    const payload = breadthDetailsPayload(new URL("http://localhost/details"));
    Object.assign(payload.compositions[0]!, changes);
    expect(() => buildSectorMemberBreadthDetailsViewModel(payload, detailsRequest)).toThrow(SectorMemberBreadthContractError);
  });

  it("accepts the frozen Meta, Rankings and Details contracts without computing business facts", () => {
    const meta = buildSectorMemberBreadthMetaViewModel(breadthMetaPayload());
    const rankings = buildSectorMemberBreadthRankingsViewModel(breadthRankingsPayload(new URL("http://localhost/rankings?tradeDate=2026-08-27&scope=LEVEL_1&direction=UP&metric=MEMBER_COUNT&maPeriod=20")), rankingRequest);
    const details = buildSectorMemberBreadthDetailsViewModel(breadthDetailsPayload(new URL("http://localhost/details?tradeDate=2026-08-27&sectorCode=BK1001.DC&direction=UP&maPeriod=20&historyRange=20"), { maUnavailable: true }), detailsRequest);
    expect(meta.maPeriods).toEqual([5, 10, 15, 20, 30, 60]);
    expect(rankings.kind).toBe("ready");
    expect(details.kind).toBe("ready");
    if (details.kind === "ready") expect(details.data.compositions[2]?.positivePct).toBeNull();
  });

  it("rejects unknown fields, composition drift, request mismatch and fake continuity", () => {
    expect(() => buildSectorMemberBreadthMetaViewModel({ ...breadthMetaPayload(), unexpected: true })).toThrow(SectorMemberBreadthContractError);
    const invalidComposition = breadthDetailsPayload(new URL("http://localhost/details?tradeDate=2026-08-27&sectorCode=BK1001.DC&direction=UP&maPeriod=20&historyRange=20"));
    invalidComposition.compositions[0]!.positivePct = 90;
    expect(() => buildSectorMemberBreadthDetailsViewModel(invalidComposition, detailsRequest)).toThrow(/百分比之和/);
    const wrongDate = breadthRankingsPayload(new URL("http://localhost/rankings?tradeDate=2026-08-26&scope=LEVEL_1&direction=UP&metric=MEMBER_COUNT&maPeriod=20"));
    expect(() => buildSectorMemberBreadthRankingsViewModel(wrongDate, rankingRequest)).toThrow(/tradeDate/);
    const duplicateSlot = breadthDetailsPayload(new URL("http://localhost/details?tradeDate=2026-08-27&sectorCode=BK1001.DC&direction=UP&maPeriod=20&historyRange=20"));
    duplicateSlot.trend[0]!.tradeDate = "2026-08-27";
    expect(() => buildSectorMemberBreadthDetailsViewModel(duplicateSlot, detailsRequest)).toThrow(/趋势日期槽/);
  });

  it("rejects rankings request-echo drift, unstable order and invalid safe shells", () => {
    const wrongScope = breadthRankingsPayload(new URL("http://localhost/rankings?tradeDate=2026-08-27&scope=LEVEL_1&direction=UP&metric=MEMBER_COUNT&maPeriod=20"));
    wrongScope.scope = "LEVEL_2";
    expect(() => buildSectorMemberBreadthRankingsViewModel(wrongScope, rankingRequest)).toThrow(/scope/);

    const wrongParent = breadthRankingsPayload(new URL("http://localhost/rankings?tradeDate=2026-08-27&scope=LEVEL_1&direction=UP&metric=MEMBER_COUNT&maPeriod=20"));
    wrongParent.parentSelection.level1Code = "BK1001.DC";
    wrongParent.parentSelection.level1Name = "电子";
    expect(() => buildSectorMemberBreadthRankingsViewModel(wrongParent, rankingRequest)).toThrow(/父级选择/);

    const wrongOrder = breadthRankingsPayload(new URL("http://localhost/rankings?tradeDate=2026-08-27&scope=LEVEL_1&direction=UP&metric=MEMBER_COUNT&maPeriod=20"));
    wrongOrder.rows.reverse(); wrongOrder.rows.forEach((row, index) => { row.listPosition = index + 1; });
    expect(() => buildSectorMemberBreadthRankingsViewModel(wrongOrder, rankingRequest)).toThrow(/无资格行业必须位于/);

    const invalidEmpty = { ...breadthRankingsPayload(new URL("http://localhost/rankings?tradeDate=2026-08-27&scope=LEVEL_1&direction=UP&metric=MEMBER_COUNT&maPeriod=20")), status: "EMPTY", exceptionCode: "SA_BREADTH_QUERY_FAILED" };
    expect(() => buildSectorMemberBreadthRankingsViewModel(invalidEmpty, rankingRequest)).toThrow(/EMPTY Rankings/);
  });

  it("rejects coverage, qualification and member-order drift", () => {
    const wrongCoverage = breadthRankingsPayload(new URL("http://localhost/rankings?tradeDate=2026-08-27&scope=LEVEL_1&direction=UP&metric=MEMBER_COUNT&maPeriod=20"));
    wrongCoverage.rows[0]!.coveragePct = 89;
    expect(() => buildSectorMemberBreadthRankingsViewModel(wrongCoverage, rankingRequest)).toThrow(/覆盖率与数量/);

    const wrongQualification = breadthDetailsPayload(new URL("http://localhost/details?tradeDate=2026-08-27&sectorCode=BK1001.DC&direction=UP&maPeriod=20&historyRange=20"));
    wrongQualification.compositions[0]!.eligible = false;
    expect(() => buildSectorMemberBreadthDetailsViewModel(wrongQualification, detailsRequest)).toThrow(/资格与5\+80%/);

    const wrongMembers = breadthDetailsPayload(new URL("http://localhost/details?tradeDate=2026-08-27&sectorCode=BK1001.DC&direction=UP&maPeriod=20&historyRange=20"));
    wrongMembers.members.reverse();
    expect(() => buildSectorMemberBreadthDetailsViewModel(wrongMembers, detailsRequest)).toThrow(/成员未按冻结次序/);
  });
});
