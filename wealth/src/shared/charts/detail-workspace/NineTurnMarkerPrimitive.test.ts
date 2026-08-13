import { describe, expect, it, vi } from "vitest";

import { NineTurnMarkerPrimitive } from "./NineTurnMarkerPrimitive";
import {
  resolveNineTurnMarkerRect,
  sliceNineTurnMarkersByTime,
  sortNineTurnMarkers,
} from "./nineTurnMarkerGeometry";
import type { NineTurnRenderMarker } from "./nineTurnMarkerTypes";

describe("NineTurnMarkerPrimitive", () => {
  it("uses the frozen 18px marker and 8px price gap", () => {
    expect(resolveNineTurnMarkerRect(100, 80, "UP")).toEqual({
      height: 18,
      left: 91,
      top: 54,
      width: 18,
    });
    expect(resolveNineTurnMarkerRect(100, 80, "DOWN")).toEqual({
      height: 18,
      left: 91,
      top: 88,
      width: 18,
    });
  });

  it("sorts markers and slices only the visible time interval", () => {
    const markers = sortNineTurnMarkers([
      marker("2026-08-13", 3),
      marker("2026-08-11", 1),
      marker("2026-08-12", 2),
    ]);

    expect(markers.map((item) => item.sequenceNumber)).toEqual([1, 2, 3]);
    expect(
      sliceNineTurnMarkersByTime(markers, "2026-08-12", "2026-08-12")
        .map((item) => item.sequenceNumber),
    ).toEqual([2]);
  });

  it("never contributes to price autoscale", () => {
    const primitive = new NineTurnMarkerPrimitive([marker("2026-08-12", 9)]);

    expect(primitive.autoscaleInfo()).toBeNull();
  });

  it("updates a stable attached instance without adding listeners or actions", () => {
    const requestUpdate = vi.fn();
    const primitive = new NineTurnMarkerPrimitive();
    primitive.attached({ requestUpdate } as never);

    primitive.setMarkers([marker("2026-08-12", 9)]);

    expect(requestUpdate).toHaveBeenCalledTimes(1);
    expect(primitive.paneViews()).toHaveLength(1);
    primitive.detached();
    primitive.setMarkers([marker("2026-08-13", 1)]);
    expect(requestUpdate).toHaveBeenCalledTimes(1);
  });

  it("draws only visible markers and outlines the completed ninth marker", () => {
    const fillText = vi.fn();
    const fillStyle = vi.fn();
    const stroke = vi.fn();
    const timeToCoordinate = vi.fn(() => 100);
    const primitive = new NineTurnMarkerPrimitive([
      marker("2026-08-11", 8),
      marker("2026-08-12", 9),
      marker("2026-08-13", 1),
    ]);
    primitive.attached({
      chart: {
        timeScale: () => ({
          getVisibleLogicalRange: () => ({ from: 1, to: 1 }),
          timeToCoordinate,
        }),
      },
      requestUpdate: vi.fn(),
      series: {
        dataByIndex: () => ({ time: "2026-08-12" }),
        priceToCoordinate: () => 80,
      },
    } as never);
    const context = {
      beginPath: vi.fn(),
      closePath: vi.fn(),
      fillText,
      lineTo: vi.fn(),
      moveTo: vi.fn(),
      quadraticCurveTo: vi.fn(),
      restore: vi.fn(),
      save: vi.fn(),
      stroke,
    };
    Object.defineProperty(context, "fillStyle", { set: fillStyle });

    primitive.draw({
      useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({
        context,
        mediaSize: { height: 200, width: 200 },
      }),
    } as never);

    expect(timeToCoordinate).toHaveBeenCalledTimes(1);
    expect(fillStyle).toHaveBeenCalledWith("#ff4d5a");
    expect(fillText).toHaveBeenCalledWith("9", 100, 63.5);
    expect(stroke).toHaveBeenCalledTimes(1);
  });

  it("uses a neutral text color for sequence one through eight", () => {
    const fillStyle = vi.fn();
    const primitive = new NineTurnMarkerPrimitive([marker("2026-08-12", 8)]);
    primitive.attached({
      chart: {
        timeScale: () => ({
          getVisibleLogicalRange: () => ({ from: 0, to: 0 }),
          timeToCoordinate: () => 100,
        }),
      },
      requestUpdate: vi.fn(),
      series: {
        dataByIndex: () => ({ time: "2026-08-12" }),
        priceToCoordinate: () => 80,
      },
    } as never);
    const context = {
      fillText: vi.fn(),
      restore: vi.fn(),
      save: vi.fn(),
    };
    Object.defineProperty(context, "fillStyle", { set: fillStyle });

    primitive.draw({
      useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({
        context,
        mediaSize: { height: 200, width: 200 },
      }),
    } as never);

    expect(fillStyle).toHaveBeenCalledWith("#94a3b8");
  });
});

function marker(time: string, sequenceNumber: NineTurnRenderMarker["sequenceNumber"]): NineTurnRenderMarker {
  return {
    anchorPrice: 10,
    direction: "UP",
    sequenceNumber,
    time,
  };
}
