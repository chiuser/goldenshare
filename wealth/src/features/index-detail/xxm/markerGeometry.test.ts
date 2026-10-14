import { describe, expect, it, vi } from "vitest";
import { layoutXxmLabels, XXM_MARKER_STYLE } from "./markerGeometry";
import { XxmMacdPrimitive } from "./XxmMacdPrimitive";
import { xxmFixture } from "./xxmFixtures.test-support";
import { buildXxmViewModel } from "./adapter";
import type { SeriesAttachedParameter, Time } from "lightweight-charts";

describe("MACD marker pixel geometry", () => {
  it("places centered bold-label boxes left of the event, including the right edge", () => {
    const { response, points } = xxmFixture();
    const marker = buildXxmViewModel(response, points, "day", "000001.SH").markers[0]!;
    for (const x of [100, 198]) {
      const [label] = layoutXxmLabels([{ marker, x, y: 50 }], 200, 100, text => text.length * 12);
      expect(label).toMatchObject({ label: "钝化", top: 42, width: 24, height: 16 });
      expect(label!.left + label!.width).toBe(x - 4 - 8);
    }
  });
  it("uses the right side only when a label cannot fit on the left boundary", () => {
    const { response, points } = xxmFixture();
    const marker = buildXxmViewModel(response, points, "day", "000001.SH").markers[0]!;
    const [label] = layoutXxmLabels([{ marker, x: 6, y: 50 }], 90, 100, text => text.length * 12);
    expect(label!.left).toBe(6 + 4 + 8);
    expect(label!.left + label!.width).toBeLessThanOrEqual(90);
  });
  it("moves dense labels vertically without covering a neighboring event dot", () => {
    const { response, points } = xxmFixture();
    const marker = buildXxmViewModel(response, points, "day", "000001.SH").markers[0]!;
    const positioned = [{ marker, x: 130, y: 50 }, { marker: { ...marker, time: "2026-10-12" }, x: 106, y: 50 }];
    const result = layoutXxmLabels(positioned, 200, 100, text => text.length * 12);
    expect(result).toHaveLength(2);
    expect(result[0]!.top).not.toBe(42);
    for (const label of result) {
      const position = positioned.find(p => p.marker === label.marker)!;
      expect(label.left + label.width).toBe(position.x - 12);
      for (const dot of positioned) {
        expect(label.left + label.width <= dot.x - 4 || label.left >= dot.x + 4
          || label.top + label.height <= dot.y - 4 || label.top >= dot.y + 4).toBe(true);
      }
    }
    expect(positioned.map(p => [p.x, p.y])).toEqual([[130, 50], [106, 50]]);
  });
  it("compacts same-bar events when full labels cannot share the pane", () => {
    const { response, points } = xxmFixture();
    const markers = buildXxmViewModel(response, points, "day", "000001.SH").markers;
    const positioned = markers.map(marker => ({ marker, x: 100, y: 11 }));
    const result = layoutXxmLabels(positioned, 200, 22, text => text.length * 12);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ label: "+2", left: 64, top: 3, height: 16 });
    expect(positioned).toHaveLength(2);
    expect(positioned.every(marker => marker.x === 100 && marker.y === 11)).toBe(true);
  });
  it("keeps anchors and labels inside pane without collisions at narrow widths", () => {
    const { response, points } = xxmFixture();
    const markers = buildXxmViewModel(response, points, "day", "000001.SH").markers;
    const positioned = markers.map(marker => ({ marker, x: 10, y: 4 }));
    const result = layoutXxmLabels(positioned, 90, 70, text => text.length * 11);
    expect(positioned.every(marker => marker.x === 10 && marker.y === 4)).toBe(true);
    expect(result.length).toBeGreaterThan(0);
    for (const label of result) {
      expect(label.left).toBeGreaterThanOrEqual(0); expect(label.left + label.width).toBeLessThanOrEqual(90);
      expect(label.top).toBeGreaterThanOrEqual(0); expect(label.top + label.height).toBeLessThanOrEqual(70);
    }
    for (let i = 0; i < result.length; i++) for (let j = i + 1; j < result.length; j++) {
      const a = result[i]!, b = result[j]!;
      expect(a.left + a.width <= b.left || b.left + b.width <= a.left || a.top + a.height <= b.top || b.top + b.height <= a.top).toBe(true);
    }
    expect(layoutXxmLabels(positioned, 8, 10, text => text.length * 11)).toEqual([]);
  });
  it("attaches to actual DIF coordinate, retains all event dots, and never changes autoscale", () => {
    const { response, points } = xxmFixture();
    const markers = buildXxmViewModel(response, points, "day", "000001.SH").markers;
    const primitive = new XxmMacdPrimitive();
    const coordinate = vi.fn((_value: number) => 50); const update = vi.fn();
    primitive.attached({ chart: { timeScale: () => ({ timeToCoordinate: () => 40 }) },
      series: { priceToCoordinate: coordinate }, requestUpdate: update } as unknown as SeriesAttachedParameter<Time>);
    primitive.setMarkers(markers);
    const context = { font: "", save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), clip: vi.fn(), arc: vi.fn(), fill: vi.fn(),
      fillText: vi.fn(), measureText: (text: string) => ({ width: text.length * 11 }) };
    primitive.draw({ useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({ context, mediaSize: { width: 200, height: 100 } }) } as never);
    expect(coordinate.mock.calls.map(call => call[0])).toEqual([-1, -1]);
    expect(context.arc).toHaveBeenCalledTimes(2);
    expect(context.arc.mock.calls.every(call => call[0] === 40 && call[1] === 50 && call[2] === 4)).toBe(true);
    expect(context.font).toMatch(/^700 12px /);
    expect(XXM_MARKER_STYLE.lineHeight).toBe(16);
    expect(context.fillText.mock.calls.map(call => call[0])).toEqual(["钝化", "结构消失"]);
    expect(update).toHaveBeenCalled(); expect(primitive.autoscaleInfo()).toBeNull();
    primitive.detached(); primitive.setMarkers([]);
  });
});
