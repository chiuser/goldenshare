import { describe, expect, it } from "vitest";

import {
  buildTurnoverInsightGeometry,
  indexForX,
  xForIndex,
  yForValue,
} from "./turnoverInsightGeometry";

const axis = {
  minYi: -2400,
  maxYi: 2400,
  zeroYi: 0,
  ticks: [],
};

describe("turnoverInsightGeometry", () => {
  it.each([1564, 1330])("keeps upper and lower plots on one x geometry at %ipx", (width) => {
    const geometry = buildTurnoverInsightGeometry(width);
    const firstX = xForIndex(geometry, 0, 241);
    const middleX = xForIndex(geometry, 120, 241);
    const lastX = xForIndex(geometry, 240, 241);

    expect(firstX).toBe(geometry.plotLeft);
    expect(lastX).toBe(geometry.plotRight);
    expect(indexForX(geometry, middleX, 241)).toBe(120);
    expect(geometry.plotRight).toBeLessThan(width);
    expect(geometry.upperBottom).toBeLessThan(geometry.lowerTop);
  });

  it("maps zero to the same proportional position within any plot", () => {
    const geometry = buildTurnoverInsightGeometry(1330);
    const y = yForValue(0, axis, geometry.lowerTop, geometry.lowerBottom);
    expect(y).toBe((geometry.lowerTop + geometry.lowerBottom) / 2);
  });

  it("rejects a zero-span axis contract", () => {
    expect(() => yForValue(1, { ...axis, minYi: 1, maxYi: 1 }, 0, 100)).toThrow("zero span");
  });
});
