import { describe, expect, it } from "vitest";

import { TrendChannelPanePrimitive } from "./TrendChannelPanePrimitive";
import type { TrendChannelLine } from "./trendChannelGeometry";

describe("TrendChannelPanePrimitive autoscale", () => {
  it("ignores extreme channel values outside the visible logical range", () => {
    const lines: TrendChannelLine[] = [
      line(0, 1, 1_000_000, 2_000_000),
      line(100, 110, 10, 20),
      line(111, 120, 15, 25),
    ];
    const primitive = new TrendChannelPanePrimitive(lines);

    expect(primitive.autoscaleInfo(100 as never, 120 as never)).toEqual({
      priceRange: { minValue: 10, maxValue: 25 },
    });
  });

  it("updates lines on the same primitive and clears unavailable trend data", () => {
    const primitive = new TrendChannelPanePrimitive([line(0, 1, 10, 20)]);
    primitive.setLines([line(0, 1, 30, 40)]);
    expect(primitive.autoscaleInfo(0 as never, 1 as never)).toEqual({ priceRange: { minValue: 30, maxValue: 40 } });
    primitive.setLines([]);
    expect(primitive.autoscaleInfo(0 as never, 1 as never)).toBeNull();
  });
});

function line(fromLogical: number, toLogical: number, fromValue: number, toValue: number): TrendChannelLine {
  return {
    color: "#fff",
    fromLogical,
    fromTime: "2026-01-01",
    fromValue,
    toLogical,
    toTime: "2026-01-02",
    toValue,
    tone: "short-above",
  };
}
