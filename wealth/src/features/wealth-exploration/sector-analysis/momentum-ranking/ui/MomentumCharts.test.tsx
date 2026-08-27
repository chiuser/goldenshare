import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SectorMomentumHistoryViewModel } from "../model/sectorMomentumTypes";
import { MomentumDetailPanel } from "./MomentumDetailPanel";
import { buildLinePath } from "./RollingReturnChart";

describe("momentum charts", () => {
  it("breaks the SVG path at null dates instead of bridging or filling them", () => {
    expect(buildLinePath([1, null, 2], (value) => value * 10)).toMatch(/^M[^M]+ M/);
    expect(buildLinePath([1, null, 2], (value) => value * 10)).not.toContain("L");
  });

  it("keeps both charts mounted and shares one keyboard hover index", () => {
    render(<MomentumDetailPanel history={historyViewModel()} period={1} range={20} onRangeChange={vi.fn()} />);
    const charts = screen.getAllByRole("img");
    expect(charts).toHaveLength(2);
    fireEvent.keyDown(charts[0]!, { key: "End" });
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08-21");
    expect(document.querySelectorAll(".momentum-crosshair")).toHaveLength(2);
    const rankPath = document.querySelector(".momentum-rank-line")?.getAttribute("d") ?? "";
    expect(rankPath).toContain("M58.00,312.00");
    expect(rankPath).toContain("M748.00,76.00");
  });
});

function historyViewModel(): SectorMomentumHistoryViewModel {
  return {
    status: "READY",
    tradingDay: { expectedTradeDate: "2026-08-21", observedTradeDate: "2026-08-21", expectedAvailability: "COMPLETE", expectedSectorCount: 2, expectedValidSectorCount: 2, observedAvailability: "COMPLETE", observedValidSectorCount: 2 },
    pageStatus: { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-08-21T20:00:00+08:00" },
    detail: {
      sectorCode: "BK1001.DC", sectorName: "一级甲", industryLevel: 1, hierarchyPath: "一级甲", scopeTitle: "一级行业总榜", returnPct: 2, percentile: 100,
      currentScopeStrengthRank: 1, currentScopeCalculableCount: 3, currentScopeTotalCount: 3,
      globalLevelStrengthRank: 1, globalLevelCalculableCount: 3, globalLevelTotalCount: 3,
      parentStrengthRank: null, parentCalculableCount: null, parentTotalCount: null,
      formulaKey: "sector-cross-sectional-momentum", formulaVersion: 1, hierarchyVersion: "v1",
    },
    points: [
      { tradeDate: "2026-08-19", returnPct: -1, strengthRank: 3, calculableCount: 3, totalCount: 10, percentile: 0 },
      { tradeDate: "2026-08-20", returnPct: null, strengthRank: null, calculableCount: 2, totalCount: 10, percentile: null },
      { tradeDate: "2026-08-21", returnPct: 2, strengthRank: 1, calculableCount: 3, totalCount: 10, percentile: 100 },
    ],
  };
}
