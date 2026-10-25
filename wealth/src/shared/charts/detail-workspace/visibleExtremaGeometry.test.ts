import { describe, expect, it } from "vitest";

import {
  EXTREMA_EDGE_PADDING,
  EXTREMA_LINE_LENGTH,
  EXTREMA_MIN_LINE_LENGTH,
  EXTREMA_TEXT_GAP,
  measureVisibleExtremaMarker,
  visibleExtremaFont,
  resolveVisibleExtremaMarkerLayout,
} from "./visibleExtremaGeometry";

describe("visibleExtremaGeometry", () => {
  it("shares the actual formatted text, font and enclosing rectangle with both primitives", () => {
    const labels: string[] = [];
    expect(visibleExtremaFont("Test Number")).toBe("600 12px Test Number");
    const result = measureVisibleExtremaMarker({ anchorX: 100, y: 80, value: 50,
      mediaWidth: 300, mediaHeight: 200, measureTextWidth: (label) => { labels.push(label); return 28; } });
    expect(labels).toEqual(["50.00"]);
    expect(result?.rect).toEqual({ left: 99.25, top: 74, width: 64.75, height: 12 });
    expect(result?.layout.textX).toBe(136);
    expect(result?.label).toBe("50.00");
    expect(measureVisibleExtremaMarker({ anchorX: 250, y: 80, value: 50,
      mediaWidth: 300, mediaHeight: 200, measureTextWidth: () => 28 })?.rect)
      .toEqual({ left: 186, top: 74, width: 64.75, height: 12 });
  });

  it("rejects vertically clipped or unmeasurable extrema instead of reserving fictional labels", () => {
    expect(measureVisibleExtremaMarker({ anchorX: 100, y: 2, value: 50,
      mediaWidth: 300, mediaHeight: 200, measureTextWidth: () => 28 })).toBeNull();
    expect(measureVisibleExtremaMarker({ anchorX: 100, y: 80, value: 50,
      mediaWidth: 300, mediaHeight: 200, measureTextWidth: () => Number.NaN })).toBeNull();
  });

  it("extends right from a left-side anchor and keeps the arrow tip on the K line", () => {
    expect(resolveVisibleExtremaMarkerLayout({
      anchorX: 100,
      mediaWidth: 400,
      textWidth: 40,
      y: 80,
    })).toEqual({
      arrowTipX: 100,
      direction: "extend-right",
      lineEndX: 100 + EXTREMA_LINE_LENGTH,
      lineStartX: 100,
      textAlign: "left",
      textX: 100 + EXTREMA_LINE_LENGTH + EXTREMA_TEXT_GAP,
      y: 80,
    });
  });

  it("extends left from a right-side anchor with the price on the opposite end", () => {
    expect(resolveVisibleExtremaMarkerLayout({
      anchorX: 330,
      mediaWidth: 400,
      textWidth: 40,
      y: 120,
    })).toEqual({
      arrowTipX: 330,
      direction: "extend-left",
      lineEndX: 330 - EXTREMA_LINE_LENGTH,
      lineStartX: 330,
      textAlign: "right",
      textX: 330 - EXTREMA_LINE_LENGTH - EXTREMA_TEXT_GAP,
      y: 120,
    });
  });

  it("flips away from the preferred side when that side cannot fit", () => {
    expect(resolveVisibleExtremaMarkerLayout({
      anchorX: 250,
      mediaWidth: 400,
      textWidth: 130,
      y: 80,
    })?.direction).toBe("extend-left");
  });

  it("shortens the line while preserving the text and edge padding", () => {
    const layout = resolveVisibleExtremaMarkerLayout({
      anchorX: 70,
      mediaWidth: 140,
      textWidth: 42,
      y: 60,
    });

    expect(layout).not.toBeNull();
    expect(Math.abs(layout!.lineEndX - layout!.lineStartX)).toBeGreaterThanOrEqual(EXTREMA_MIN_LINE_LENGTH);
    expect(Math.abs(layout!.lineEndX - layout!.lineStartX)).toBeLessThan(EXTREMA_LINE_LENGTH);
    if (layout!.direction === "extend-right") {
      expect(layout!.textX + 42).toBeLessThanOrEqual(140 - EXTREMA_EDGE_PADDING);
    } else {
      expect(layout!.textX - 42).toBeGreaterThanOrEqual(EXTREMA_EDGE_PADDING);
    }
  });

  it("returns null when neither side can fit the minimum line and text", () => {
    expect(resolveVisibleExtremaMarkerLayout({
      anchorX: 40,
      mediaWidth: 80,
      textWidth: 50,
      y: 40,
    })).toBeNull();
  });

  it("keeps the line and text exactly on the supplied price coordinate", () => {
    const layout = resolveVisibleExtremaMarkerLayout({
      anchorX: 100,
      mediaWidth: 400,
      textWidth: 40,
      y: 67.5,
    });

    expect(layout?.y).toBe(67.5);
  });

  it("rejects invalid geometry inputs", () => {
    expect(resolveVisibleExtremaMarkerLayout({
      anchorX: Number.NaN,
      mediaWidth: 400,
      textWidth: 40,
      y: 80,
    })).toBeNull();
    expect(resolveVisibleExtremaMarkerLayout({
      anchorX: 40,
      mediaWidth: 0,
      textWidth: 40,
      y: 80,
    })).toBeNull();
  });
});
