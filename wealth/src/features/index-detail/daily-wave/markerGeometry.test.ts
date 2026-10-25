import { describe, expect, it } from "vitest";
import { resolveDailyWaveMarkerLayout } from "./markerGeometry";
import type { DailyWaveMarkerCoordinate } from "./markerGeometry";

const up: DailyWaveMarkerCoordinate = { date: "2025-12-01", direction: "UP", segmentIds: ["a", "b"], x: 100, anchorY: 100 };

describe("daily wave triangle geometry", () => {
  it("puts an 8 by 6 red triangle below and a green triangle above the exact K line", () => {
    const result = resolveDailyWaveMarkerLayout({ markers: [up, { ...up, direction: "DOWN" }],
      occupied: [], width: 300, height: 200 });
    expect(result.issues).toEqual([]);
    expect(result.layouts.map((item) => [item.direction, item.rect])).toEqual([
      ["DOWN", { left: 96, top: 86, width: 8, height: 6 }],
      ["UP", { left: 96, top: 108, width: 8, height: 6 }],
    ]);
    expect(result.layouts[1]?.segmentIds).toEqual(["a", "b"]);
  });

  it("checks neighboring text rectangles and moves only outward in four pixel steps", () => {
    const result = resolveDailyWaveMarkerLayout({ markers: [up], width: 300, height: 200,
      occupied: [{ left: 102, top: 100, width: 100, height: 26 }] });
    expect(result.layouts[0]?.rect).toEqual({ left: 96, top: 128, width: 8, height: 6 });
    expect(up).toEqual({ date: "2025-12-01", direction: "UP", segmentIds: ["a", "b"], x: 100, anchorY: 100 });
  });

  it("also avoids triangles already placed, in stable date and direction order", () => {
    const result = resolveDailyWaveMarkerLayout({
      markers: [{ ...up, date: "2025-12-02", x: 104 }, up], occupied: [], width: 300, height: 200,
    });
    expect(result.layouts.map((item) => [item.date, item.rect.left, item.rect.top])).toEqual([
      ["2025-12-01", 96, 108], ["2025-12-02", 100, 116],
    ]);
  });

  it("allows the forty pixel boundary but never moves past it", () => {
    const atLimit = resolveDailyWaveMarkerLayout({ markers: [up], width: 300, height: 200,
      occupied: [{ left: 90, top: 108, width: 30, height: 32 }] });
    expect(atLimit.layouts[0]?.rect.top).toBe(140);
    const blocked = resolveDailyWaveMarkerLayout({ markers: [up], width: 300, height: 200,
      occupied: [{ left: 90, top: 108, width: 30, height: 38 }] });
    expect(blocked.layouts).toEqual([]);
    expect(blocked.issues).toEqual([{ date: "2025-12-01", direction: "UP", segmentIds: ["a", "b"], reason: "SPACE_UNAVAILABLE" }]);
  });

  it.each([
    [{ ...up, x: null }, "COORDINATE_UNAVAILABLE"],
    [{ ...up, anchorY: Number.NaN }, "COORDINATE_UNAVAILABLE"],
    [{ ...up, x: 2 }, "SPACE_UNAVAILABLE"],
    [{ ...up, anchorY: 195 }, "SPACE_UNAVAILABLE"],
    [{ ...up, direction: "DOWN", anchorY: 5 }, "SPACE_UNAVAILABLE"],
  ] as const)("reports missing coordinates and clipping without moving time", (marker, reason) => {
    const result = resolveDailyWaveMarkerLayout({ markers: [marker], occupied: [], width: 300, height: 200 });
    expect(result.layouts).toEqual([]);
    expect(result.issues).toEqual([{ date: marker.date, direction: marker.direction,
      segmentIds: marker.segmentIds, reason }]);
  });
});
