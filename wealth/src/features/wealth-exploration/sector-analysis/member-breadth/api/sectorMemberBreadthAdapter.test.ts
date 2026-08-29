import { describe, expect, it } from "vitest";
import { buildSectorMemberBreadthDetailsViewModel, buildSectorMemberBreadthMetaViewModel, buildSectorMemberBreadthRankingsViewModel, SectorMemberBreadthContractError } from "./sectorMemberBreadthAdapter";
import { breadthDetailsPayload, breadthMetaPayload, breadthRankingsPayload } from "./sectorMemberBreadthTestFixtures";

const rankingRequest = { market: "CN_A", tradeDate: "2026-08-27", scope: "LEVEL_1", direction: "UP", metric: "MEMBER_COUNT", maPeriod: 20, hierarchyVersion: "dc-industry-v1" } as const;
const detailsRequest = { market: "CN_A", tradeDate: "2026-08-27", sectorCode: "BK1001.DC", direction: "UP", maPeriod: 20, historyRange: 20, hierarchyVersion: "dc-industry-v1" } as const;

describe("sectorMemberBreadthAdapter", () => {
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
