import { describe, expect, it } from "vitest";

import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { NineTurnMarkerDto } from "../api/nineTurnApiTypes";
import { buildNineTurnRenderMarkers } from "./nineTurnChartAdapter";

describe("buildNineTurnRenderMarkers", () => {
  it("anchors UP to high and DOWN to low without computing sequence values", () => {
    const points = [point("2026-08-12", 12, 8), point("2026-08-13", 13, 9)];
    const markers: NineTurnMarkerDto[] = [
      marker("2026-08-12", "UP", 8),
      marker("2026-08-13", "DOWN", 9),
    ];

    expect(buildNineTurnRenderMarkers(markers, points, "daily")).toEqual({
      droppedMarkerCount: 0,
      markers: [
        { anchorPrice: 12, direction: "UP", sequenceNumber: 8, time: "2026-08-12" },
        { anchorPrice: 9, direction: "DOWN", sequenceNumber: 9, time: "2026-08-13" },
      ],
    });
  });

  it("drops markers when a bar key is missing or duplicated", () => {
    const points = [point("2026-08-12", 12, 8), point("2026-08-12", 13, 9)];
    const markers = [marker("2026-08-12", "UP", 2), marker("2026-08-13", "DOWN", 3)];

    expect(buildNineTurnRenderMarkers(markers, points, "daily")).toEqual({
      droppedMarkerCount: 2,
      markers: [],
    });
  });
});

function marker(
  tradeDate: string,
  direction: NineTurnMarkerDto["direction"],
  sequenceNumber: NineTurnMarkerDto["sequenceNumber"],
): NineTurnMarkerDto {
  return {
    completed: sequenceNumber === 9,
    direction,
    sequenceNumber,
    tradeDate,
    tradeTime: null,
  };
}

function point(time: string, high: number, low: number): DetailChartPoint {
  return {
    amount: 1,
    amplitude: 1,
    close: 10,
    d: 1,
    dea: 1,
    dif: 1,
    fullDate: time,
    high,
    j: 1,
    k: 1,
    low,
    macd: 1,
    open: 10,
    overlays: {},
    preClose: 10,
    time,
    turnoverRate: 1,
    volume: 1,
    volumeDisplay: null,
    changePct: 1,
  };
}
