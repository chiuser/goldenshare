import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { idleNineTurnLayer } from "../model/nineTurnAdapter";
import { useNineTurnChartLayer } from "./useNineTurnChartLayer";

describe("useNineTurnChartLayer shared render markers", () => {
  it("exposes the same adapted date and high anchor for occupancy while retaining the primitive", () => {
    const points: DetailChartPoint[] = [{ time: "2025-12-01", fullDate: "2025-12-01", open: 99,
      high: 120, low: 80, close: 100, preClose: 99, changePct: 1, amplitude: 40,
      volume: 10, volumeDisplay: "10", amount: 100, turnoverRate: 1,
      macd: 1, dif: 2, dea: 1.5, k: 10, d: 20, j: 0, overlays: {} }];
    const layer = { ...idleNineTurnLayer("day"), markers: [{ tradeDate: "2025-12-01", tradeTime: null,
      direction: "UP" as const, completed: true, sequenceNumber: 9 as const }] };
    const { result, rerender } = renderHook(() => useNineTurnChartLayer({
      dataKey: "index:000001.SH:day", points, layer, timeMode: "daily",
    }));
    const primitive = result.current.mainPrimitives[0];
    expect(result.current.markers).toEqual([{ time: "2025-12-01", anchorPrice: 120, direction: "UP", sequenceNumber: 9 }]);
    expect(result.current.droppedMarkerCount).toBe(0);
    rerender();
    expect(result.current.mainPrimitives[0]).toBe(primitive);
  });
});
