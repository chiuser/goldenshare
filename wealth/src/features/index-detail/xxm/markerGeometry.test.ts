import { describe, expect, it, vi } from "vitest";
import { layoutXxmLabels, XXM_MARKER_STYLE, type PositionedMarker } from "./markerGeometry";
import { XxmMacdPrimitive } from "./XxmMacdPrimitive";
import { xxmFixture } from "./xxmFixtures.test-support";
import { buildXxmViewModel } from "./adapter";
import type { SeriesAttachedParameter, Time } from "lightweight-charts";

function julyMarkers(): PositionedMarker[] {
  const { response, points } = xxmFixture();
  const base = buildXxmViewModel(response, points, "day", "000001.SH").markers[0]!;
  // CSS coordinates recovered from the user's daily-chart screenshot, not invented prices.
  return [
    { time: "2026-07-13", type: "DULL" as const, x: 843, y: 80 },
    { time: "2026-07-15", type: "CANCEL" as const, x: 862.5, y: 83.5 },
    { time: "2026-07-17", type: "DULL" as const, x: 881.5, y: 104.5 },
    { time: "2026-07-20", type: "CANCEL" as const, x: 891, y: 112.5 },
  ].map(({ time, type, x, y }) => ({ x, y, marker: { ...base, time,
    event: { ...base.event, time, type, direction: "BOTTOM" as const } } }));
}

describe("MACD marker pixel geometry", () => {
  it("places centered bold-label boxes left of the event, including the right edge", () => {
    const { response, points } = xxmFixture();
    const marker = buildXxmViewModel(response, points, "day", "000001.SH").markers[0]!;
    for (const x of [100, 198]) {
      const [label] = layoutXxmLabels([{ marker, x, y: 50 }], 200, 100, text => text.length * 12);
      expect(label).toMatchObject({ label: "钝化", top: 42, width: 24, height: 16 });
      expect(label!.left + label!.width).toBe(x - 4 - 8);
      expect(label!.leader).toBeNull();
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
  it("keeps all four July labels near their own nodes through subpixel pane-height changes", () => {
    const positioned = julyMarkers();
    const before = structuredClone(positioned);
    const runs = [114, 114.5, 115].map(height => {
      const labels = layoutXxmLabels(positioned, 1445, height, text => text.length * 12);
      expect(labels.map(label => [label.marker.time, label.label])).toEqual([
        ["2026-07-13", "钝化"], ["2026-07-15", "取消"], ["2026-07-17", "钝化"], ["2026-07-20", "取消"],
      ]);
      for (const [index, label] of labels.entries()) {
        const own = positioned[index]!;
        expect(label.marker).toBe(own.marker);
        expect(Math.abs(label.top + label.height / 2 - own.y)).toBeLessThanOrEqual(XXM_MARKER_STYLE.maxVerticalShift);
        expect(own.x - 12 - label.width - label.left).toBeGreaterThanOrEqual(0);
        expect(own.x - 12 - label.width - label.left).toBeLessThanOrEqual(XXM_MARKER_STYLE.maxHorizontalShift);
        expect(label.top).toBeGreaterThanOrEqual(3);
        expect(label.top + label.height).toBeLessThanOrEqual(height - 3);
        for (const dot of positioned) expect(label.left + label.width <= dot.x - 7 || label.left >= dot.x + 7
          || label.top + label.height <= dot.y - 7 || label.top >= dot.y + 7).toBe(true);
        for (const other of labels) if (other !== label) {
          expect(label.left + label.width + 3 <= other.left || other.left + other.width + 3 <= label.left
            || label.top + label.height + 2 <= other.top || other.top + other.height + 2 <= label.top).toBe(true);
        }
        if (!label.leader) continue;
        const line = label.leader;
        expect(Math.hypot(line.toX - own.x, line.toY - own.y)).toBeCloseTo(4, 8);
        expect(line.fromX).toBe(label.left + label.width);
        expect(line.fromY).toBeGreaterThanOrEqual(label.top);
        expect(line.fromY).toBeLessThanOrEqual(label.top + label.height);
        // The leader must not pass through somebody else's text or event dot.
        const path = [{ x: line.fromX, y: line.fromY }, ...line.via, { x: line.toX, y: line.toY }];
        for (const [i, end] of path.slice(1).entries()) for (let step = 0; step <= 100; step++) {
          const start = path[i]!, t = step / 100, x = start.x + (end.x - start.x) * t, y = start.y + (end.y - start.y) * t;
          expect(y).toBeGreaterThanOrEqual(0); expect(y).toBeLessThanOrEqual(height);
          for (const other of labels) if (other !== label) expect(x < other.left || x > other.left + other.width
            || y < other.top || y > other.top + other.height).toBe(true);
          for (const dot of positioned) if (dot !== own) expect(Math.hypot(x - dot.x, y - dot.y)).toBeGreaterThanOrEqual(4 - 1e-8);
        }
      }
      return labels;
    });
    for (const labels of runs.slice(1)) for (const [i, label] of labels.entries()) {
      expect(label.left).toBe(runs[0]![i]!.left);
      expect(Math.abs(label.top - runs[0]![i]!.top)).toBeLessThanOrEqual(1);
    }
    expect(positioned).toEqual(before);
  });
  it.each(["TOP", "BOTTOM"] as const)("keeps %s edge labels local and connects them to their own point", direction => {
    const point = julyMarkers()[0]!;
    for (const y of [1, 99]) {
      const [label] = layoutXxmLabels([{ ...point, y, marker: { ...point.marker, event: { ...point.marker.event, direction } } }],
        2000, 100, text => text.length * 12);
      expect(label).toBeDefined(); expect(label!.leader).not.toBeNull();
      expect(Math.abs(label!.top + 8 - y)).toBeLessThanOrEqual(40);
      expect(Math.hypot(label!.leader!.toX - point.x, label!.leader!.toY - y)).toBeCloseTo(4, 8);
    }
  });
  it("draws each shifted label's leader before the unchanged event dots", () => {
    const positioned = julyMarkers();
    const primitive = new XxmMacdPrimitive();
    primitive.attached({ chart: { timeScale: () => ({ timeToCoordinate: (time: Time) => positioned.find(p => p.marker.time === time)!.x }) },
      series: { priceToCoordinate: (dif: number) => dif }, requestUpdate: vi.fn() } as unknown as SeriesAttachedParameter<Time>);
    primitive.setMarkers(positioned.map(p => ({ ...p.marker, dif: p.y })));
    const strokes: { color: string; width: number }[] = [];
    const context = { font: "", lineWidth: 0, strokeStyle: "", save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(),
      rect: vi.fn(), clip: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(() => strokes.push({ color: context.strokeStyle, width: context.lineWidth })),
      arc: vi.fn(), fill: vi.fn(), fillText: vi.fn(), measureText: (text: string) => ({ width: text.length * 12 }) };
    primitive.draw({ useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({ context, mediaSize: { width: 1445, height: 114 } }) } as never);
    const labels = layoutXxmLabels(positioned, 1445, 114, text => text.length * 12);
    const shifted = labels.filter(label => label.leader);
    expect(context.moveTo.mock.calls).toEqual(shifted.map(label => [label.leader!.fromX, label.leader!.fromY]));
    expect(context.lineTo.mock.calls).toEqual(shifted.flatMap(label => [...label.leader!.via.map(p => [p.x, p.y]), [label.leader!.toX, label.leader!.toY]]));
    expect(strokes).toHaveLength(4); expect(strokes.every(stroke => stroke.width === 1 && stroke.color.length > 0)).toBe(true);
    expect(strokes[0]!.color).toBe(strokes[2]!.color); expect(strokes[1]!.color).toBe(strokes[3]!.color);
    expect(strokes[0]!.color).not.toBe(strokes[1]!.color);
    expect(context.arc.mock.calls.map(call => call.slice(0, 3))).toEqual(positioned.map(p => [p.x, p.y, 4]));
    expect(context.stroke.mock.invocationCallOrder.at(-1)).toBeLessThan(context.arc.mock.invocationCallOrder[0]!);
    expect(context.fillText.mock.calls.map(call => call[0])).toEqual(["钝化", "取消", "钝化", "取消"]);
    expect(primitive.autoscaleInfo()).toBeNull();
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
