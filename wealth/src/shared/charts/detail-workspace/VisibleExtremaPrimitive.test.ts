import { describe, expect, it, vi } from "vitest";

import type { DetailChartVisibleCandle } from "./detailChartVisibleExtrema";
import { VisibleExtremaPrimitive } from "./VisibleExtremaPrimitive";

describe("VisibleExtremaPrimitive", () => {
  it("uses a stable top pane view and never contributes to autoscale", () => {
    const primitive = new VisibleExtremaPrimitive([point("2026-08-12", 50, 10)]);

    expect(primitive.paneViews()).toBe(primitive.paneViews());
    expect(primitive.paneViews()[0]?.zOrder?.()).toBe("top");
    expect(primitive.autoscaleInfo()).toBeNull();
  });

  it("draws open arrow lines at the exact high and low coordinates", () => {
    const primitive = new VisibleExtremaPrimitive([
      point("2026-08-11", 40, 12),
      point("2026-08-12", 50, 10),
    ]);
    const timeToCoordinate = vi.fn((time: unknown) => time === "2026-08-12" ? 100 : 200);
    const priceToCoordinate = vi.fn((price: number) => price === 50 ? 80 : 120);
    attach(primitive, { from: 0, to: 1 }, timeToCoordinate, priceToCoordinate);
    const { context, target } = drawingTarget();

    primitive.draw(target);

    expect(timeToCoordinate).toHaveBeenCalledTimes(2);
    expect(priceToCoordinate).toHaveBeenNthCalledWith(1, 50);
    expect(priceToCoordinate).toHaveBeenNthCalledWith(2, 10);
    expect(context.moveTo).toHaveBeenCalledWith(106, 76);
    expect(context.lineTo).toHaveBeenCalledWith(100, 80);
    expect(context.lineTo).toHaveBeenCalledWith(106, 84);
    expect(context.fillText).toHaveBeenCalledWith("50.00", 136, 80);
    expect(context.fillText).toHaveBeenCalledWith("10.00", 136, 120);
    expect(context.stroke).toHaveBeenCalledTimes(2);
    expect(context.fill).not.toHaveBeenCalled();
    expect(context.closePath).not.toHaveBeenCalled();
  });

  it("draws one marker when high and low are the same index and price", () => {
    const primitive = new VisibleExtremaPrimitive([point("2026-08-12", 20, 20)]);
    attach(primitive, { from: 0, to: 0 }, vi.fn(() => 100), vi.fn(() => 80));
    const { context, target } = drawingTarget();

    primitive.draw(target);

    expect(context.fillText).toHaveBeenCalledTimes(1);
    expect(context.fillText).toHaveBeenCalledWith("20.00", 136, 80);
    expect(context.stroke).toHaveBeenCalledTimes(1);
  });

  it("skips missing ranges, missing coordinates, clipped vertical positions, and narrow plots", () => {
    const points = [point("2026-08-12", 20, 10)];
    const noRange = new VisibleExtremaPrimitive(points);
    attach(noRange, null, vi.fn(() => 100), vi.fn(() => 80));
    const noRangeTarget = drawingTarget();
    noRange.draw(noRangeTarget.target);
    expect(noRangeTarget.context.fillText).not.toHaveBeenCalled();

    const noCoordinate = new VisibleExtremaPrimitive(points);
    attach(noCoordinate, { from: 0, to: 0 }, vi.fn(() => null), vi.fn(() => 80));
    const noCoordinateTarget = drawingTarget();
    noCoordinate.draw(noCoordinateTarget.target);
    expect(noCoordinateTarget.context.fillText).not.toHaveBeenCalled();

    const clipped = new VisibleExtremaPrimitive(points);
    attach(clipped, { from: 0, to: 0 }, vi.fn(() => 100), vi.fn(() => 2));
    const clippedTarget = drawingTarget();
    clipped.draw(clippedTarget.target);
    expect(clippedTarget.context.fillText).not.toHaveBeenCalled();

    const narrow = new VisibleExtremaPrimitive(points);
    attach(narrow, { from: 0, to: 0 }, vi.fn(() => 20), vi.fn(() => 80));
    const narrowTarget = drawingTarget(40);
    narrow.draw(narrowTarget.target);
    expect(narrowTarget.context.fillText).not.toHaveBeenCalled();
  });

  it("uses fallback visual tokens and releases attached state on detach", () => {
    const primitive = new VisibleExtremaPrimitive([point("2026-08-12", 20, 10)]);
    attach(primitive, { from: 0, to: 0 }, vi.fn(() => 100), vi.fn(() => 80));
    const { context, target } = drawingTarget();

    primitive.draw(target);

    expect(context.fontValues).toContain('600 12px "DIN Alternate", "Roboto Mono", "SF Mono", monospace');
    expect(context.strokeStyleValues).toContain("#e5eef9");
    expect(context.fillStyleValues).toContain("#e5eef9");

    primitive.detached();
    context.fillText.mockClear();
    primitive.draw(target);
    expect(context.fillText).not.toHaveBeenCalled();
  });

  it("reuses cached extrema until the normalized visible indexes change", () => {
    let highReadCount = 0;
    const observed = point("2026-08-12", 40, 8);
    Object.defineProperty(observed, "high", {
      configurable: true,
      get: () => {
        highReadCount += 1;
        return 40;
      },
    });
    const primitive = new VisibleExtremaPrimitive([
      point("2026-08-11", 30, 10),
      observed,
      point("2026-08-13", 50, 7),
    ]);
    let range = { from: 0.2, to: 1.8 };
    attach(
      primitive,
      () => range,
      vi.fn(() => 100),
      vi.fn(() => 80),
    );
    const { target } = drawingTarget();

    primitive.draw(target);
    const firstDrawReads = highReadCount;
    primitive.draw(target);
    expect(highReadCount).toBe(firstDrawReads);

    range = { from: 0, to: 2 };
    primitive.draw(target);
    expect(highReadCount).toBeGreaterThan(firstDrawReads);
  });
});

type VisibleRange = { from: number; to: number } | null;

function attach(
  primitive: VisibleExtremaPrimitive,
  range: VisibleRange | (() => VisibleRange),
  timeToCoordinate: ReturnType<typeof vi.fn>,
  priceToCoordinate: ReturnType<typeof vi.fn>,
) {
  primitive.attached({
    chart: {
      timeScale: () => ({
        getVisibleLogicalRange: () => typeof range === "function" ? range() : range,
        timeToCoordinate,
      }),
    },
    requestUpdate: vi.fn(),
    series: { priceToCoordinate },
  } as never);
}

function drawingTarget(width = 300) {
  const context = {
    beginPath: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    fillStyleValues: [] as string[],
    fillText: vi.fn(),
    fontValues: [] as string[],
    lineTo: vi.fn(),
    measureText: vi.fn(() => ({ width: 28 })),
    moveTo: vi.fn(),
    restore: vi.fn(),
    save: vi.fn(),
    stroke: vi.fn(),
    strokeStyleValues: [] as string[],
  };
  Object.defineProperty(context, "fillStyle", {
    set: (value: string) => context.fillStyleValues.push(value),
  });
  Object.defineProperty(context, "font", {
    set: (value: string) => context.fontValues.push(value),
  });
  Object.defineProperty(context, "lineCap", { set: vi.fn() });
  Object.defineProperty(context, "lineJoin", { set: vi.fn() });
  Object.defineProperty(context, "lineWidth", { set: vi.fn() });
  Object.defineProperty(context, "strokeStyle", {
    set: (value: string) => context.strokeStyleValues.push(value),
  });
  Object.defineProperty(context, "textAlign", { set: vi.fn() });
  Object.defineProperty(context, "textBaseline", { set: vi.fn() });

  return {
    context,
    target: {
      useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({
        context,
        mediaSize: { height: 200, width },
      }),
    } as never,
  };
}

function point(time: string, high: number, low: number): DetailChartVisibleCandle {
  return { high, low, time };
}
