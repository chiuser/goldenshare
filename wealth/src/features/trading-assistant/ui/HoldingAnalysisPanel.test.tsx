import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { HoldingContributions, PositionsAnalysis, PositionsResponse } from "../api/generatedContracts";
import { HoldingAnalysisPanel } from "./HoldingAnalysisPanel";
import { contributionPresentation } from "../model/holdingAnalysisPresentation";
import { validPositionCombination } from "../api/positionContractSemantics";

const mock = vi.hoisted(() => ({ data: null as PositionsAnalysis | null }));
vi.mock("../model/useHoldingAnalysis", () => ({ useHoldingAnalysis: () => ({ data: mock.data, error: false, retry: vi.fn() }) }));
const contribution: HoldingContributions = { maxPositive: { stockRef: { tsCode: "001201.SZ", name: "股票甲" }, profitAmount: "100.00" }, maxNegative: null,
  positiveCount: 1, negativeCount: 0, flatCount: 0, positiveAmount: "100.00", negativeAmount: "0.00", unknownCount: 0, dataStatus: "Ready", reason: null };
const parent = { readContext: { contextToken: "one" }, items: [{ valuationDate: "2026-09-11" }], summary: { stockMarketValue: "1100.00" } } as PositionsResponse;
describe("formal current holding analysis", () => {
  it("keeps all industries, switches already returned contributions, and returns", () => {
    mock.data = { scope: { accounts: [{ name: "主账户" }] }, coverage: { reason: null }, cashAmount: "1000.00", cashWeightPct: "47.62", top3WeightPct: "100.00", top5WeightPct: "100.00", largestPosition: null,
      industries: Array.from({ length: 11 }, (_, i) => ({ industryCode: String(i), industryName: `行业${i}`, marketValue: "100.00", weightPct: "9.09", classificationStatus: "CLASSIFIED" })),
      cumulative: contribution, daily: { ...contribution, maxPositive: null, positiveAmount: "0.00", positiveCount: 0, flatCount: 1 },
    } as PositionsAnalysis;
    const back = vi.fn();
    const { container } = render(<HoldingAnalysisPanel selected="ALL" parent={parent} onReturn={back} onRefresh={vi.fn()} />);
    expect(container.querySelectorAll(".ta-analysis-industry")).toHaveLength(11);
    expect(container.querySelectorAll(".ta-position-metric")).toHaveLength(4);
    expect(screen.getByText("股票甲 · 001201.SZ")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "当日" }));
    expect(screen.getByText(/上涨贡献 0 只 · 下跌贡献 0 只 · 持平 1 只/)).toBeInTheDocument();
    expect(screen.queryByText("股票甲 · 001201.SZ")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "返回持仓列表" })); expect(back).toHaveBeenCalledOnce();
    expect(container.textContent).not.toMatch(/[¥￥$]/);
  });
  it("does not display all unknown as actual zero and matches signed contract rules", () => {
    const unknown: HoldingContributions = { ...contribution, maxPositive: null, positiveCount: 0, positiveAmount: "0.00", unknownCount: 2, dataStatus: "Partial" };
    const view = contributionPresentation(unknown, true);
    expect(view.positiveTotal).toBe("—"); expect(view.positive.name).toBe("待计算"); expect(view.structure).toContain("待计算 2 只");
    expect(validPositionCombination("HoldingContributions", { ...unknown, dataStatus: "Ready" })).toBe(false);
    expect(validPositionCombination("HoldingContributions", { ...contribution, negativeAmount: "1.00" })).toBe(false);
    expect(validPositionCombination("IndustryAllocation", { classificationStatus: "CLASSIFIED", industryCode: null })).toBe(false);
  });
});
