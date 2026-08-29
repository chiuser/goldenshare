import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SectorMemberBreadthDetailsViewModel } from "../model/sectorMemberBreadthTypes";
import { MemberBreadthTrendChart, type MemberBreadthTrendInspection } from "./MemberBreadthTrendChart";

const VIEW = { width: 920, height: 244, left: 48, right: 18, top: 22, bottom: 30 } as const;

describe("MemberBreadthTrendChart", () => {
  it("starts idle, enters on plot click and snaps all readings to the nearest real trade date", () => {
    render(<TrendHarness details={details()} />);
    const svg = trendSvg();
    mockBounds(svg, { left: 100, top: 50, width: 920, height: 244 });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.click(svg, pointerAtView(100, 50, xForIndex(2.6, 5), 100));

    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08-25");
    expect(screen.getByRole("tooltip")).toHaveTextContent("成分股占比64.0%");
    expect(document.querySelectorAll(".member-breadth-inspection-crosshair")).toHaveLength(2);
    expect(document.querySelectorAll(".member-breadth-inspection-point")).toHaveLength(3);
    expect(svg).toHaveFocus();
  });

  it("changes date only with horizontal movement and changes the y readout with vertical movement", () => {
    render(<TrendHarness details={details()} />);
    const svg = trendSvg();
    mockBounds(svg, { left: 0, top: 0, width: 920, height: 244 });
    fireEvent.click(svg, pointerAtView(0, 0, xForIndex(1, 5), 80));
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08-23");

    fireEvent.pointerMove(svg, pointerAtView(0, 0, xForIndex(1, 5), 160));
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08-23");
    expect(document.querySelectorAll(".member-breadth-inspection-axis-pill")[1]).toHaveTextContent("28.1%");

    fireEvent.pointerMove(svg, pointerAtView(0, 0, xForIndex(4, 5), 160));
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08-26");
  });

  it("keeps null values as missing, draws no false point and preserves active state after pointer leave", () => {
    render(<TrendHarness details={details()} />);
    const svg = trendSvg();
    mockBounds(svg, { left: 0, top: 0, width: 920, height: 244 });
    fireEvent.click(svg, pointerAtView(0, 0, xForIndex(2, 5), 90));

    expect(screen.getByRole("tooltip")).toHaveTextContent("均线位置占比--");
    expect(document.querySelectorAll(".member-breadth-inspection-point")).toHaveLength(2);
    expect(document.querySelector(".member-breadth-inspection-point.ma")).not.toBeInTheDocument();
    fireEvent.pointerLeave(svg);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
  });

  it("places the tooltip away from the selected date and exits through plot-external click or Escape", () => {
    render(<TrendHarness details={details()} />);
    const svg = trendSvg();
    mockBounds(svg, { left: 0, top: 0, width: 920, height: 244 });
    fireEvent.click(svg, pointerAtView(0, 0, xForIndex(1, 5), 90));
    expect(screen.getByRole("tooltip")).toHaveClass("right");
    fireEvent.pointerMove(svg, pointerAtView(0, 0, xForIndex(4, 5), 90));
    expect(screen.getByRole("tooltip")).toHaveClass("left");

    fireEvent.click(svg, pointerAtView(0, 0, 20, 90));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.click(svg, pointerAtView(0, 0, xForIndex(2, 5), 90));
    fireEvent.keyDown(svg, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("maps a non-proportional rendered size to the same viewBox date and performs no request", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<TrendHarness details={details()} />);
    const svg = trendSvg();
    mockBounds(svg, { left: 40, top: 20, width: 736, height: 122 });
    expect(svg).toHaveAttribute("preserveAspectRatio", "none");
    fireEvent.click(svg, pointerAtRenderedView(40, 20, 736, 122, xForIndex(3, 5), 100));
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08-25");
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("does not enter active state when the trend contains no dates", () => {
    render(<TrendHarness details={{ ...details(), trend: [] }} />);
    const svg = trendSvg();
    mockBounds(svg, { left: 0, top: 0, width: 920, height: 244 });
    fireEvent.click(svg, pointerAtView(0, 0, 300, 100));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});

function TrendHarness({ details: model }: { details: SectorMemberBreadthDetailsViewModel }) {
  const [inspection, setInspection] = useState<MemberBreadthTrendInspection>(null);
  return <MemberBreadthTrendChart details={model} inspection={inspection} onInspectionChange={setInspection} />;
}

function trendSvg(): SVGSVGElement {
  return screen.getByRole("img", { name: /成员广度趋势/ }) as unknown as SVGSVGElement;
}

function mockBounds(svg: SVGSVGElement, bounds: { left: number; top: number; width: number; height: number }) {
  Object.defineProperty(svg, "getBoundingClientRect", { configurable: true, value: () => ({ ...bounds, x: bounds.left, y: bounds.top, right: bounds.left + bounds.width, bottom: bounds.top + bounds.height, toJSON: () => ({}) }) });
}

function pointerAtView(left: number, top: number, viewX: number, viewY: number) {
  return { clientX: left + viewX, clientY: top + viewY };
}

function pointerAtRenderedView(left: number, top: number, width: number, height: number, viewX: number, viewY: number) {
  return { clientX: left + viewX / VIEW.width * width, clientY: top + viewY / VIEW.height * height };
}

function xForIndex(index: number, count: number): number {
  const plotWidth = VIEW.width - VIEW.left - VIEW.right;
  return VIEW.left + index / (count - 1) * plotWidth;
}

function details(): SectorMemberBreadthDetailsViewModel {
  return {
    status: "READY", message: null, tradeDate: "2026-08-26", hierarchyVersion: "dc-industry-v1", sectorCode: "BK1001.DC", sectorName: "电子", industryLevel: 1, hierarchyPath: "电子", direction: "UP", maPeriod: 20, historyRange: 20,
    compositions: [], members: [],
    trend: [
      point("2026-08-22", 42, 38, 35),
      point("2026-08-23", 50, 45, 41),
      point("2026-08-24", 58, 52, null),
      point("2026-08-25", 64, 60, 54),
      point("2026-08-26", 72, 68, 65),
    ],
  };
}

function point(tradeDate: string, memberPct: number | null, turnoverPct: number | null, maPositionPct: number | null) {
  return { tradeDate, memberPct, turnoverPct, maPositionPct, memberReasonCodes: [], turnoverReasonCodes: [], maPositionReasonCodes: maPositionPct === null ? ["ADJ_FACTOR_MISSING" as const] : [] };
}
