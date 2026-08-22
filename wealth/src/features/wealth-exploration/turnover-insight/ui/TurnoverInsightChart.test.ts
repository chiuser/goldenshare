import { describe, expect, it, vi } from "vitest";

import type { TurnoverInsightAverageViewModel } from "../model/turnoverInsightTypes";
import {
  drawAverageReferenceLabel,
  drawAverageReferenceLine,
  resolveAverageReferenceRenderItems,
} from "./TurnoverInsightChart";
import { buildTurnoverInsightGeometry, yForValue } from "./turnoverInsightGeometry";

function contextMock() {
  return {
    beginPath: vi.fn(),
    fillText: vi.fn(),
    lineTo: vi.fn(),
    moveTo: vi.fn(),
    restore: vi.fn(),
    save: vi.fn(),
    setLineDash: vi.fn(),
    stroke: vi.fn(),
    fillStyle: "",
    lineWidth: 0,
    strokeStyle: "",
    textAlign: "left",
    textBaseline: "alphabetic",
  } as unknown as CanvasRenderingContext2D;
}

const average: TurnoverInsightAverageViewModel = {
  amountYi: 23771,
  displayText: "23,771亿",
  direction: "neutral",
  referenceLabel: "5日均值 23,771亿",
};

const avg20d: TurnoverInsightAverageViewModel = {
  amountYi: 28064,
  displayText: "28,064亿",
  direction: "neutral",
  referenceLabel: "20日均值 28,064亿",
};

const averageColors = { avg5d: "#f7c76b", avg20d: "#a78bfa" };

const axis = {
  minYi: 0,
  maxYi: 32000,
  zeroYi: 0,
  ticks: [],
};

describe("drawAverageReferenceLine", () => {
  it("draws one dashed line across only the upper plot", () => {
    const context = contextMock();
    const geometry = buildTurnoverInsightGeometry(1330);
    const y = yForValue(average.amountYi!, axis, geometry.upperTop, geometry.upperBottom);

    drawAverageReferenceLine(context, geometry, axis, average, "#f7c76b");

    expect(context.setLineDash).toHaveBeenCalledWith([4, 4]);
    expect(context.moveTo).toHaveBeenCalledWith(geometry.plotLeft, y);
    expect(context.lineTo).toHaveBeenCalledWith(geometry.plotRight, y);
    expect(context.fillText).not.toHaveBeenCalled();
    expect(context.strokeStyle).toBe("#f7c76b");
  });

  it("draws the backend label two pixels above the reference line", () => {
    const context = contextMock();
    const geometry = buildTurnoverInsightGeometry(1330);
    const y = yForValue(average.amountYi!, axis, geometry.upperTop, geometry.upperBottom);

    drawAverageReferenceLabel(context, geometry, axis, average, "#f7c76b", "above");

    expect(context.fillText).toHaveBeenCalledWith(
      "5日均值 23,771亿",
      geometry.plotRight,
      y - 2,
    );
    expect(context.fillStyle).toBe("#f7c76b");
    expect(context.textBaseline).toBe("bottom");
  });

  it("draws the lower label two pixels below the reference line", () => {
    const context = contextMock();
    const geometry = buildTurnoverInsightGeometry(1330);
    const y = yForValue(average.amountYi!, axis, geometry.upperTop, geometry.upperBottom);

    drawAverageReferenceLabel(context, geometry, axis, average, "#f7c76b", "below");

    expect(context.fillText).toHaveBeenCalledWith(
      "5日均值 23,771亿",
      geometry.plotRight,
      y + 2,
    );
    expect(context.textBaseline).toBe("top");
  });

  it("does not draw a line for a missing average", () => {
    const context = contextMock();
    const geometry = buildTurnoverInsightGeometry(1330);

    drawAverageReferenceLine(context, geometry, axis, { ...average, amountYi: null }, "#f7c76b");
    drawAverageReferenceLabel(context, geometry, axis, { ...average, amountYi: null }, "#f7c76b", "above");

    expect(context.stroke).not.toHaveBeenCalled();
    expect(context.fillText).not.toHaveBeenCalled();
  });
});

describe("resolveAverageReferenceRenderItems", () => {
  it("places the higher 5-day average above and the lower 20-day average below", () => {
    const result = resolveAverageReferenceRenderItems(
      { ...average, amountYi: 30000 },
      avg20d,
      averageColors,
    );

    expect(result.map(({ key, labelPlacement }) => [key, labelPlacement])).toEqual([
      ["avg5d", "above"],
      ["avg20d", "below"],
    ]);
  });

  it("places the higher 20-day average above and the lower 5-day average below", () => {
    const result = resolveAverageReferenceRenderItems(average, avg20d, averageColors);

    expect(result.map(({ key, labelPlacement }) => [key, labelPlacement])).toEqual([
      ["avg5d", "below"],
      ["avg20d", "above"],
    ]);
  });

  it("uses the stable 5-day-above rule when the averages are equal", () => {
    const result = resolveAverageReferenceRenderItems(
      { ...average, amountYi: 25000 },
      { ...avg20d, amountYi: 25000 },
      averageColors,
    );

    expect(result.map(({ key, labelPlacement }) => [key, labelPlacement])).toEqual([
      ["avg5d", "above"],
      ["avg20d", "below"],
    ]);
  });

  it.each([
    ["avg5d", average, { ...avg20d, amountYi: null }],
    ["avg20d", { ...average, amountYi: null }, avg20d],
  ] as const)("places a lone %s average label above its line", (key, nextAvg5d, nextAvg20d) => {
    const result = resolveAverageReferenceRenderItems(nextAvg5d, nextAvg20d, averageColors);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ key, labelPlacement: "above" });
  });

  it("omits missing averages", () => {
    expect(resolveAverageReferenceRenderItems(
      { ...average, amountYi: null },
      { ...avg20d, amountYi: null },
      averageColors,
    )).toEqual([]);
  });
});
