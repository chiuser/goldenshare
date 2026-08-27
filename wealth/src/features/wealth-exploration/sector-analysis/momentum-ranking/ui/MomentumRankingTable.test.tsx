import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SectorRankingRowViewModel } from "../model/sectorMomentumTypes";
import { MomentumRankingTable } from "./MomentumRankingTable";

describe("MomentumRankingTable", () => {
  it("renders the complete level-two pool in one native scroll viewport", () => {
    const rows = Array.from({ length: 128 }, (_, index): SectorRankingRowViewModel => ({
      listPosition: index + 1,
      strengthRank: index + 1,
      sectorCode: `BK${String(2000 + index).padStart(4, "0")}.DC`,
      sectorName: `二级行业${index + 1}`,
      industryLevel: 2,
      parentSectorCode: "BK1001.DC",
      parentSectorName: "一级行业",
      hierarchyPath: `一级行业/二级行业${index + 1}`,
      returnPct: 2 - index / 100,
      percentile: 100 - index / 127 * 100,
      canDrillDown: true,
      returnText: `${(2 - index / 100).toFixed(2)}%`,
      returnBarWidthPct: Math.abs(2 - index / 100) / 2 * 50,
      percentileText: `${(100 - index / 127 * 100).toFixed(1)}%`,
      strengthRankText: String(index + 1),
      directionClass: index < 100 ? "up" : "down",
    }));
    const { container } = render(
      <MomentumRankingTable rows={rows} selectedCode={rows[0]!.sectorCode} onSelect={vi.fn()} onDrillDown={vi.fn()} />,
    );

    expect(screen.getAllByRole("button", { name: /^选择二级行业/ })).toHaveLength(128);
    expect(container.querySelectorAll(".momentum-ranking-row")).toHaveLength(128);
    expect(container.querySelector(".momentum-ranking-viewport")).toBeInTheDocument();
    expect(container.querySelector(".momentum-ranking-header")).toBeInTheDocument();
  });
});
