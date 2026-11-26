import { describe, expect, it, vi } from "vitest";
import { MismatchDirection } from "lightweight-charts";

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
    const requestUpdate = vi.fn();
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
      requestUpdate,
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

    const target = {
      useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({
        context,
        mediaSize: { height: 200, width: 200 },
      }),
    } as never;
    primitive.draw(target);

    expect(timeToCoordinate).toHaveBeenCalledTimes(1);
    expect(fillStyle).toHaveBeenCalledWith("#ff4d5a");
    expect(fillText).toHaveBeenCalledWith("9", 100, 63.5);
    expect(stroke).toHaveBeenCalledTimes(1);

    primitive.setVisible(false);
    primitive.setVisible(false);
    primitive.draw(target);
    expect(requestUpdate).toHaveBeenCalledTimes(1);
    expect(timeToCoordinate).toHaveBeenCalledTimes(1);
    expect(fillText).toHaveBeenCalledTimes(1);
    expect(primitive.autoscaleInfo()).toBeNull();

    primitive.setVisible(true);
    primitive.draw(target);
    expect(requestUpdate).toHaveBeenCalledTimes(2);
    expect(fillText.mock.calls).toEqual([["9", 100, 63.5], ["9", 100, 63.5]]);

    primitive.setVisible(false);
    primitive.setMarkers([marker("2026-08-12", 4)]);
    primitive.draw(target);
    expect(fillText).toHaveBeenCalledTimes(2);
    primitive.setVisible(true);
    primitive.draw(target);
    expect(fillText).toHaveBeenLastCalledWith("4", 100, 63.5);
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

  it.each([
    { name: "normal range", from: 0, to: 1, count: 2, expected: ["8", "9"] },
    { name: "right-side padding", from: 0, to: 4, count: 2, expected: ["8", "9"] },
    { name: "left-side padding", from: -3, to: 1, count: 2, expected: ["8", "9"] },
    { name: "padding on both sides", from: -3, to: 4, count: 2, expected: ["8", "9"] },
    { name: "single bar with padding", from: -1, to: 3, count: 1, expected: ["8"] },
    { name: "one visible bar", from: 1, to: 1, count: 2, expected: ["9"] },
    { name: "range after all bars", from: 3, to: 5, count: 2, expected: [] },
    { name: "range before all bars", from: -5, to: -3, count: 2, expected: [] },
  ])("draws the real visible markers for $name", ({ from, to, count, expected }) => {
    const bars = [
      { time: "2026-08-11", open: 9, high: 11, low: 8, close: 10 },
      { time: "2026-08-12", open: 10, high: 12, low: 9, close: 11 },
    ].slice(0, count);
    // Lightweight Charts dataByIndex: exact misses are null; an explicit
    // direction finds the closest existing bar on that side of the index.
    const dataByIndex = (index: number, direction = MismatchDirection.None) => {
      if (index >= 0 && index < bars.length) return bars[index];
      if (index < 0 && direction === MismatchDirection.NearestRight) return bars[0];
      if (index >= bars.length && direction === MismatchDirection.NearestLeft) return bars.at(-1);
      return null;
    };
    const markers = count === 1
      ? [marker("2026-08-11", 8)]
      : [marker("2026-08-11", 8), marker("2026-08-12", 9)];
    const primitive = new NineTurnMarkerPrimitive(markers);
    primitive.attached({
      chart: { timeScale: () => ({
        getVisibleLogicalRange: () => ({ from, to }),
        timeToCoordinate: () => 100,
      }) },
      requestUpdate: vi.fn(),
      series: { dataByIndex, priceToCoordinate: () => 80 },
    } as never);
    const context = {
      beginPath: vi.fn(), closePath: vi.fn(), fillText: vi.fn(), lineTo: vi.fn(),
      moveTo: vi.fn(), quadraticCurveTo: vi.fn(), restore: vi.fn(), save: vi.fn(), stroke: vi.fn(),
    };
    primitive.draw({
      useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({
        context, mediaSize: { height: 200, width: 200 },
      }),
    } as never);
    expect(context.fillText.mock.calls.map(([text]) => text)).toEqual(expected);
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
