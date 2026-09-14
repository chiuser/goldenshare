import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PositionRow, PositionsResponse } from "../api/generatedContracts";
import { PositionsCharts } from "./PositionsCharts";

const rows = [70, 30].map((weight, i) => ({ stockRef: { tsCode: `00000${i + 1}.SZ`, name: i ? "短名称" : "特别长的股票名称".repeat(10) },
  stockValueWeightPct: `${weight}.00`, marketValue: `${weight * 10}.00`, holdingProfitAmount: "10.00", holdingReturnPct: "1.00",
}) as PositionRow);
const data = { items: rows, summary: { stockMarketValue: "1000.00" }, allocation: {} } as PositionsResponse;
describe("positions graphics presentation boundaries", () => {
  it("uses the actual largest weight as the shared scale, and keeps full names in details", () => {
    const onDetail = vi.fn();
    const { container } = render(<PositionsCharts data={data} view="bar" onDetail={onDetail} />);
    const bars = container.querySelectorAll<HTMLElement>(".ta-position-bar-track i");
    expect(bars[0].style.width).toBe("100%");
    expect(parseFloat(bars[1].style.width)).toBeCloseTo(30 / 70 * 100, 3);
    expect(container.querySelector(".ta-position-bar-scale")?.textContent).toBe("0%70.00%");
    fireEvent.click(container.querySelector(".ta-position-bar-row")!);
    expect(onDetail).toHaveBeenCalledWith(rows[0]);
  });
  it("hides labels that cannot fit but retains accessible full information", () => {
    const { container } = render(<PositionsCharts data={data} view="map" onDetail={vi.fn()} />);
    const tiles = container.querySelectorAll(".ta-position-map g");
    expect(tiles).toHaveLength(2);
    expect(tiles[0].querySelector("text")).toBeNull();
    expect(tiles[0].getAttribute("aria-label")).toContain(rows[0].stockRef.name);
    expect(tiles[1].querySelector("text")).not.toBeNull();
  });
  it("renders every OTHER member, does not recalculate supplied percentages", () => {
    const members = Array.from({ length: 40 }, (_, i) => ({ stockRef: { tsCode: String(i), name: `股票${i}` }, marketValue: "25.00", weightPct: "2.50" }));
    const pie = { ...data, allocation: { stockValueSlices: [{ kind: "OTHER", stockRef: null, marketValue: "1000.00", weightPct: "100.00", members }] } } as PositionsResponse;
    render(<PositionsCharts data={pie} view="pie" onDetail={vi.fn()} />);
    fireEvent.mouseEnter(screen.getByRole("button", { name: /其他 · 40 只 1,000.00 100.00%/ }));
    const region = screen.getByRole("region", { name: "其他持仓完整明细" });
    expect(region.querySelectorAll("button")).toHaveLength(40);
    expect(region.textContent).not.toMatch(/[¥￥$]/);
  });
});
