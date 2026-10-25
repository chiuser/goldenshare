import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { NineTurnRenderMarker } from "../../../shared/charts/detail-workspace/nineTurnMarkerTypes";
import { DailyWavePrimitive } from "./DailyWavePrimitive";
import type { DailyWaveMarkerInput } from "./markerGeometry";

const active: DailyWavePrimitive[] = [];
const marker: DailyWaveMarkerInput = { date: "2025-12-01", direction: "UP", segmentIds: ["a", "b"] };

describe("DailyWavePrimitive", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    active.splice(0).forEach((primitive) => primitive.detached());
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("uses a stable pane view without changing price autoscale", () => {
    const primitive = new DailyWavePrimitive();
    expect(primitive.paneViews()).toBe(primitive.paneViews());
    expect(primitive.paneViews()[0]?.zOrder?.()).toBe("top");
    expect(primitive.autoscaleInfo()).toBeNull();
  });

  it("draws solid red up and green down triangles on the true date center in CSS pixels", () => {
    const { primitive, onIssues } = prepare({ markers: [marker, { ...marker, direction: "DOWN" }] });
    const { context, target } = drawTarget();
    primitive.draw(target);
    expect(context.moveTo.mock.calls).toEqual([[100, 72], [100, 128]]);
    expect(context.lineTo.mock.calls).toEqual([[104, 66], [96, 66], [104, 134], [96, 134]]);
    expect(context.fill).toHaveBeenCalledTimes(2);
    expect(context.fillStyles).toEqual(["#15c784", "#ff4d5a"]);
    expect(onIssues).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(onIssues).toHaveBeenCalledWith([]);
  });

  it("uses all visible nine-turn rectangles, including the neighboring K line", () => {
    const { primitive } = prepare({ points: [point("2025-12-01"), point("2025-12-02")],
      nineTurnMarkers: [nineTurn("2025-12-02", "DOWN", 80)] });
    const { context, target } = drawTarget();
    primitive.draw(target);
    expect(context.moveTo).toHaveBeenCalledWith(100, 148);
    expect(context.moveTo).not.toHaveBeenCalledWith(104, 148);
  });

  it("does not confuse nine-turn UP above high with wave UP below low", () => {
    const { primitive } = prepare({ nineTurnMarkers: [nineTurn("2025-12-01", "UP", 120)] });
    const { context, target } = drawTarget();
    primitive.draw(target);
    expect(context.moveTo).toHaveBeenCalledWith(100, 128);
  });

  it("uses the same actual extrema text measurement for neighboring label collisions", () => {
    const { primitive } = prepare({ points: [point("2025-12-01"), { ...point("2025-12-02"), low: 70 }],
      coordinates: (date) => date === "2025-12-01" ? 100 : 60 });
    const { context, target } = drawTarget(300, 200, 40);
    primitive.draw(target);
    expect(context.fontValues).toEqual(['600 12px "DIN Alternate", "Roboto Mono", "SF Mono", monospace']);
    expect(context.measureText).toHaveBeenCalledWith("70.00");
    expect(context.moveTo).toHaveBeenCalledWith(100, 136);
  });

  it("reports unavailable coordinates but ignores dates outside the visible range", () => {
    const first = prepare({ coordinates: () => null });
    first.primitive.draw(drawTarget().target);
    vi.runAllTimers();
    expect(first.onIssues).toHaveBeenCalledWith([{ ...marker, reason: "COORDINATE_UNAVAILABLE" }]);

    const second = prepare({ points: [point("2025-12-01"), point("2025-12-02")], range: { from: 1, to: 1 } });
    const drawing = drawTarget();
    second.primitive.draw(drawing.target);
    vi.runAllTimers();
    expect(drawing.context.fill).not.toHaveBeenCalled();
    expect(second.onIssues).toHaveBeenCalledWith([]);
  });

  it("reports only visible markers when the main pane cannot provide the required padding", () => {
    const { primitive, onIssues } = prepare();
    const { context, target } = drawTarget(300, 80);
    primitive.draw(target);
    vi.runAllTimers();
    expect(context.fill).not.toHaveBeenCalled();
    expect(onIssues).toHaveBeenCalledWith([{ ...marker, reason: "SPACE_UNAVAILABLE" }]);
  });

  it("reports clipping without drawing into the price axis or the next pane", () => {
    const { primitive, onIssues } = prepare({ coordinates: () => 2 });
    const { context, target } = drawTarget();
    primitive.draw(target);
    vi.runAllTimers();
    expect(context.fill).not.toHaveBeenCalled();
    expect(onIssues).toHaveBeenCalledWith([{ ...marker, reason: "SPACE_UNAVAILABLE" }]);
  });

  it("updates an attached instance and redraws for range and size changes", () => {
    const fixture = prepare();
    expect(fixture.requestUpdate).toHaveBeenCalledTimes(1);
    fixture.rangeHandlers[0]?.();
    fixture.sizeHandlers[0]?.();
    fixture.primitive.setData({ points: [point("2025-12-01")], markers: [marker],
      nineTurnMarkers: [], onIssues: fixture.onIssues });
    expect(fixture.requestUpdate).toHaveBeenCalledTimes(4);
  });

  it("only reports changed issues after drawing, and clears a recovered position", () => {
    const blockers = [nineTurn("2025-12-01", "DOWN", 80), nineTurn("2025-12-01", "DOWN", 70),
      nineTurn("2025-12-01", "DOWN", 60)];
    const { primitive, onIssues } = prepare({ nineTurnMarkers: blockers });
    primitive.draw(drawTarget().target);
    primitive.draw(drawTarget().target);
    expect(onIssues).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(onIssues).toHaveBeenCalledTimes(1);
    expect(onIssues).toHaveBeenLastCalledWith([{ ...marker, reason: "SPACE_UNAVAILABLE" }]);
    primitive.draw(drawTarget().target);
    vi.runAllTimers();
    expect(onIssues).toHaveBeenCalledTimes(1);
    primitive.setData({ points: [point("2025-12-01")], markers: [marker], nineTurnMarkers: [], onIssues });
    primitive.draw(drawTarget().target);
    vi.runAllTimers();
    expect(onIssues).toHaveBeenCalledTimes(2);
    expect(onIssues).toHaveBeenLastCalledWith([]);
  });

  it("removes subscriptions and pending issue callbacks on detach", () => {
    const fixture = prepare({ coordinates: () => null });
    fixture.primitive.draw(drawTarget().target);
    fixture.primitive.detached();
    vi.runAllTimers();
    expect(fixture.onIssues).not.toHaveBeenCalled();
    expect(fixture.rangeHandlers).toEqual([]);
    expect(fixture.sizeHandlers).toEqual([]);
    const before = fixture.requestUpdate.mock.calls.length;
    fixture.primitive.setData({ points: [point("2025-12-01")], markers: [marker],
      nineTurnMarkers: [], onIssues: fixture.onIssues });
    expect(fixture.requestUpdate).toHaveBeenCalledTimes(before);
    const drawing = drawTarget();
    fixture.primitive.draw(drawing.target);
    expect(drawing.context.fill).not.toHaveBeenCalled();
  });

  it("cancels a pending failure when the same view recovers before its callback", () => {
    let x: number | null = 100;
    const { primitive, onIssues } = prepare({ coordinates: () => x });
    primitive.draw(drawTarget().target);
    vi.runAllTimers();
    expect(onIssues).toHaveBeenCalledTimes(1);
    x = null;
    primitive.draw(drawTarget().target);
    x = 100;
    primitive.draw(drawTarget().target);
    vi.runAllTimers();
    expect(onIssues).toHaveBeenCalledTimes(1);
    expect(onIssues).toHaveBeenLastCalledWith([]);
  });

  it("does not fabricate a candle from a known close when its OHLC is missing", () => {
    const missingCandle = { ...point("2025-12-02"), open: null };
    const { primitive, onIssues } = prepare({
      points: [point("2025-12-01"), missingCandle, point("2025-12-03")],
      markers: [{ ...marker, date: "2025-12-02" }],
    });
    const { context, target } = drawTarget();
    primitive.draw(target);
    vi.runAllTimers();
    expect(context.fill).not.toHaveBeenCalled();
    expect(onIssues).toHaveBeenCalledWith([{ ...marker, date: "2025-12-02", reason: "COORDINATE_UNAVAILABLE" }]);
  });

  it("uses chart dates when an earlier OHLC gap changes candle-array indices", () => {
    const { primitive, onIssues } = prepare({
      points: [{ ...point("2025-12-01"), open: null }, point("2025-12-02"), point("2025-12-03")],
      range: { from: 1, to: 2 },
      markers: [{ ...marker, date: "2025-12-02" }],
      visibleDates: { from: { year: 2025, month: 12, day: 2 }, to: { year: 2025, month: 12, day: 3 } },
    });
    const { context, target } = drawTarget();
    primitive.draw(target);
    vi.runAllTimers();
    expect(context.moveTo).toHaveBeenCalledWith(104, 128);
    expect(onIssues).toHaveBeenCalledWith([]);
  });

  it("reports a missing first candle within the chart's visible dates without hiding the following candle", () => {
    const { primitive, onIssues } = prepare({
      points: [{ ...point("2025-12-01"), open: null }, point("2025-12-02")],
      markers: [marker, { ...marker, date: "2025-12-02" }],
    });
    const { context, target } = drawTarget();
    primitive.draw(target);
    vi.runAllTimers();
    expect(context.moveTo).toHaveBeenCalledWith(104, 128);
    expect(onIssues).toHaveBeenCalledWith([{ ...marker, reason: "COORDINATE_UNAVAILABLE" }]);
  });
});

function point(date: string): DetailChartPoint {
  return { time: date, fullDate: date, open: 99, high: 120, low: 80, close: 100, preClose: 99,
    changePct: 1, amplitude: 40, volume: 10, volumeDisplay: "10", amount: 100, turnoverRate: 1,
    macd: 1, dif: 2, dea: 1.5, k: 10, d: 20, j: 0, overlays: {} };
}

function nineTurn(date: string, direction: "UP" | "DOWN", anchorPrice: number): NineTurnRenderMarker {
  return { time: date, direction, anchorPrice, sequenceNumber: 9 };
}

function prepare(options: {
  points?: DetailChartPoint[]; markers?: DailyWaveMarkerInput[]; nineTurnMarkers?: NineTurnRenderMarker[];
  range?: { from: number; to: number }; coordinates?: (date: string) => number | null;
  visibleDates?: { from: { year: number; month: number; day: number }; to: { year: number; month: number; day: number } };
} = {}) {
  const primitive = new DailyWavePrimitive();
  active.push(primitive);
  const points = options.points ?? [point("2025-12-01")];
  const onIssues = vi.fn();
  primitive.setData({ points, markers: options.markers ?? [marker], nineTurnMarkers: options.nineTurnMarkers ?? [], onIssues });
  const rangeHandlers: Array<() => void> = [];
  const sizeHandlers: Array<() => void> = [];
  const requestUpdate = vi.fn();
  const timeScale = {
    getVisibleLogicalRange: () => options.range ?? { from: 0, to: points.length - 1 },
    getVisibleRange: () => options.visibleDates ?? {
      from: points[Math.max(0, Math.ceil(options.range?.from ?? 0))]!.time,
      to: points[Math.min(points.length - 1, Math.floor(options.range?.to ?? points.length - 1))]!.time,
    },
    timeToCoordinate: (date: string) => options.coordinates ? options.coordinates(date)
      : date === "2025-12-01" ? 100 : 104,
    subscribeVisibleLogicalRangeChange: (handler: () => void) => rangeHandlers.push(handler),
    unsubscribeVisibleLogicalRangeChange: (handler: () => void) => rangeHandlers.splice(rangeHandlers.indexOf(handler), 1),
    subscribeSizeChange: (handler: () => void) => sizeHandlers.push(handler),
    unsubscribeSizeChange: (handler: () => void) => sizeHandlers.splice(sizeHandlers.indexOf(handler), 1),
  };
  primitive.attached({ chart: { timeScale: () => timeScale }, requestUpdate,
    series: { priceToCoordinate: (price: number) => 200 - price } } as never);
  return { primitive, onIssues, requestUpdate, rangeHandlers, sizeHandlers };
}

function drawTarget(width = 300, height = 200, textWidth = 28) {
  const context = { beginPath: vi.fn(), closePath: vi.fn(), fill: vi.fn(), lineTo: vi.fn(),
    measureText: vi.fn(() => ({ width: textWidth })), moveTo: vi.fn(), restore: vi.fn(), save: vi.fn(),
    fillStyles: [] as string[], fontValues: [] as string[] };
  Object.defineProperty(context, "fillStyle", { set: (value: string) => context.fillStyles.push(value) });
  Object.defineProperty(context, "font", { set: (value: string) => context.fontValues.push(value) });
  return { context, target: { useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({
    context, mediaSize: { width, height },
  }) } as never };
}
