import { describe, expect, it, vi } from "vitest";

import type { TurnoverInsightAverageViewModel } from "../model/turnoverInsightTypes";
import {
  drawAverageReferenceLabel,
  drawAverageReferenceLine,
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

    expect(context.setLineDash).toHaveBeenCalledWith([8, 6]);
    expect(context.moveTo).toHaveBeenCalledWith(geometry.plotLeft, y);
    expect(context.lineTo).toHaveBeenCalledWith(geometry.plotRight, y);
    expect(context.fillText).not.toHaveBeenCalled();
    expect(context.strokeStyle).toBe("#f7c76b");
  });

  it("draws the backend label two pixels above the reference line", () => {
    const context = contextMock();
    const geometry = buildTurnoverInsightGeometry(1330);
    const y = yForValue(average.amountYi!, axis, geometry.upperTop, geometry.upperBottom);

    drawAverageReferenceLabel(context, geometry, axis, average, "#f7c76b");

    expect(context.fillText).toHaveBeenCalledWith(
      "5日均值 23,771亿",
      geometry.plotRight,
      y - 2,
    );
    expect(context.fillStyle).toBe("#f7c76b");
  });

  it("does not draw a line for a missing average", () => {
    const context = contextMock();
    const geometry = buildTurnoverInsightGeometry(1330);

    drawAverageReferenceLine(context, geometry, axis, { ...average, amountYi: null }, "#f7c76b");
    drawAverageReferenceLabel(context, geometry, axis, { ...average, amountYi: null }, "#f7c76b");

    expect(context.stroke).not.toHaveBeenCalled();
    expect(context.fillText).not.toHaveBeenCalled();
  });
});
