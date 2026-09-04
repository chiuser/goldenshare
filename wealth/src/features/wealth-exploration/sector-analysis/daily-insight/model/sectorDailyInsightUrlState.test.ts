import { describe, expect, it } from "vitest";
import { buildSectorDailyInsightSearch, parseSectorDailyInsightUrlState } from "./sectorDailyInsightUrlState";
import { dailyInsightDestination } from "./sectorDailyInsightNavigation";
import { buildSectorDailyInsightSnapshotViewModel } from "../api/sectorDailyInsightAdapter";
import { insightRequest, insightSnapshot } from "../testFixtures";
import { parseSectorMomentumUrlState } from "../../momentum-ranking/model/sectorMomentumUrlState";
import { parseSectorDualMomentumUrlState } from "../../dual-momentum/model/sectorDualMomentumUrlState";
import { parseSectorRelativeRotationUrlState } from "../../relative-rotation/model/sectorRelativeRotationUrlState";
import { parseSectorMemberBreadthUrlState } from "../../member-breadth/model/sectorMemberBreadthUrlState";
import { parseSectorPriceVolumeUrlState } from "../../price-volume/model/sectorPriceVolumeUrlState";

describe("daily URL and existing method builders", () => {
  it("defaults only to level 1 and public date", () => {
    const parsed = parseSectorDailyInsightUrlState("");
    expect(parsed).toEqual({ ok: true, value: { market: "CN_A", tradeDate: null, level: 1 } });
    if (parsed.ok) expect(buildSectorDailyInsightSearch(parsed.value)).toBe("");
  });
  it.each(["?debug=1", "?batchKey=x", "?market=SW", "?level=1&level=2", "?level=1.0", "?level=4", "?tradeDate=2025-02-30", "?tradeDate=", "?sectorCode=BK1000.DC", "?unknown=<script>"])("rejects unsupported selection %s", (query) => expect(parseSectorDailyInsightUrlState(query).ok).toBe(false));
  it.each([1, 2, 3] as const)("reuses all method contracts for global level %s", (level) => {
    const row = buildSectorDailyInsightSnapshotViewModel(insightSnapshot(level), insightRequest(level)).headGainers[0];
    const cases = [
      [undefined, parseSectorMomentumUrlState], ["DUAL_MOMENTUM", parseSectorDualMomentumUrlState], ["RELATIVE_ROTATION", parseSectorRelativeRotationUrlState],
      ["MEMBER_BREADTH", parseSectorMemberBreadthUrlState], ["TURNOVER_BREADTH", parseSectorMemberBreadthUrlState], ["MA20_BREADTH", parseSectorMemberBreadthUrlState], ["PRICE_VOLUME", parseSectorPriceVolumeUrlState],
    ] as const;
    for (const [evidence, parse] of cases) {
      const destination = dailyInsightDestination(row, "2025-08-25", evidence);
      const result = parse(destination.search);
      expect(result.ok).toBe(true);
      if (result.ok) expect(result.value).toMatchObject({ tradeDate: "2025-08-25", scope: `level${level}`, sectorCode: row.sectorCode, level1Code: null, level2Code: null });
      expect(destination.search).not.toMatch(/batch|hierarchy|debug/);
    }
    expect(parseSectorDualMomentumUrlState(dailyInsightDestination(row, "2025-08-25", "DUAL_MOMENTUM").search)).toMatchObject({ value: { resultView: "all", period: 20, threshold: 80 } });
    expect(parseSectorMomentumUrlState(dailyInsightDestination(row, "2025-08-25").search)).toMatchObject({ value: { period: 20, range: 20, direction: "gainers" } });
  });
});
