import type {
  AutoscaleInfo,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
} from "lightweight-charts";

import { formatPriceAxisValue } from "./detailChartFormatters";
import {
  resolveVisibleExtrema,
  resolveVisibleIndexRange,
  type DetailChartVisibleCandle,
  type DetailChartVisibleExtrema,
  type DetailChartVisibleExtremum,
} from "./detailChartVisibleExtrema";
import {
  EXTREMA_ARROW_HALF_HEIGHT,
  EXTREMA_ARROW_WING_LENGTH,
  EXTREMA_FONT_SIZE,
  EXTREMA_LINE_WIDTH,
  resolveVisibleExtremaMarkerLayout,
  type VisibleExtremaMarkerLayout,
} from "./visibleExtremaGeometry";

const EXTREMA_COLOR_FALLBACK = "#e5eef9";
const EXTREMA_FONT_FAMILY_FALLBACK = '"DIN Alternate", "Roboto Mono", "SF Mono", monospace';
const EXTREMA_FONT_WEIGHT = 600;

interface VisibleExtremaCache {
  endIndex: number;
  extrema: DetailChartVisibleExtrema;
  startIndex: number;
}

export class VisibleExtremaPrimitive implements ISeriesPrimitive<Time> {
  private attachedParameters: SeriesAttachedParameter<Time> | null = null;
  private cache: VisibleExtremaCache | null = null;
  private readonly view = new VisibleExtremaPaneView(this);
  private readonly views: readonly IPrimitivePaneView[] = [this.view];

  constructor(private readonly candles: readonly DetailChartVisibleCandle[]) {}

  attached(parameters: SeriesAttachedParameter<Time>): void {
    this.attachedParameters = parameters;
    this.cache = null;
  }

  detached(): void {
    this.attachedParameters = null;
    this.cache = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }

  autoscaleInfo(): AutoscaleInfo | null {
    return null;
  }

  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]): void {
    const attached = this.attachedParameters;
    if (!attached || this.candles.length === 0) return;

    const visibleRange = attached.chart.timeScale().getVisibleLogicalRange();
    const visibleIndexes = resolveVisibleIndexRange(visibleRange, this.candles.length);
    if (!visibleIndexes) return;

    const extrema = this.resolveExtrema(visibleIndexes.startIndex, visibleIndexes.endIndex);
    if (!extrema.high && !extrema.low) return;

    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save();
      context.font = `${EXTREMA_FONT_WEIGHT} ${EXTREMA_FONT_SIZE}px ${resolveExtremaFontFamily()}`;
      context.lineCap = "round";
      context.lineJoin = "round";
      context.lineWidth = EXTREMA_LINE_WIDTH;
      const color = resolveExtremaColor();
      context.strokeStyle = color;
      context.fillStyle = color;
      context.textBaseline = "middle";

      if (extrema.high) {
        this.drawExtremum(context, mediaSize, extrema.high);
      }
      if (extrema.low && !isSameExtremum(extrema.high, extrema.low)) {
        this.drawExtremum(context, mediaSize, extrema.low);
      }

      context.restore();
    });
  }

  private resolveExtrema(startIndex: number, endIndex: number): DetailChartVisibleExtrema {
    if (
      this.cache?.startIndex === startIndex &&
      this.cache.endIndex === endIndex
    ) {
      return this.cache.extrema;
    }

    const extrema = resolveVisibleExtrema(this.candles, { from: startIndex, to: endIndex });
    this.cache = { endIndex, extrema, startIndex };
    return extrema;
  }

  private drawExtremum(
    context: CanvasRenderingContext2D,
    mediaSize: { height: number; width: number },
    extremum: DetailChartVisibleExtremum,
  ): void {
    const attached = this.attachedParameters;
    if (!attached) return;

    const anchorX = attached.chart.timeScale().timeToCoordinate(extremum.time);
    const y = attached.series.priceToCoordinate(extremum.value);
    if (anchorX === null || y === null) return;
    const verticalPadding = Math.max(EXTREMA_FONT_SIZE / 2, EXTREMA_ARROW_HALF_HEIGHT);
    if (y < verticalPadding || y > mediaSize.height - verticalPadding) return;

    const label = formatPriceAxisValue(extremum.value);
    const layout = resolveVisibleExtremaMarkerLayout({
      anchorX,
      mediaWidth: mediaSize.width,
      textWidth: context.measureText(label).width,
      y,
    });
    if (!layout) return;

    drawOpenArrowLine(context, layout);
    context.textAlign = layout.textAlign;
    context.fillText(label, layout.textX, layout.y);
  }
}

class VisibleExtremaPaneView implements IPrimitivePaneView {
  constructor(private readonly primitive: VisibleExtremaPrimitive) {}

  zOrder() {
    return "top" as const;
  }

  renderer(): IPrimitivePaneRenderer {
    return { draw: (target) => this.primitive.draw(target) };
  }
}

function drawOpenArrowLine(
  context: CanvasRenderingContext2D,
  layout: VisibleExtremaMarkerLayout,
): void {
  const wingDirection = layout.direction === "extend-right" ? 1 : -1;
  const wingX = layout.arrowTipX + wingDirection * EXTREMA_ARROW_WING_LENGTH;

  context.beginPath();
  context.moveTo(wingX, layout.y - EXTREMA_ARROW_HALF_HEIGHT);
  context.lineTo(layout.arrowTipX, layout.y);
  context.lineTo(wingX, layout.y + EXTREMA_ARROW_HALF_HEIGHT);
  context.moveTo(layout.lineStartX, layout.y);
  context.lineTo(layout.lineEndX, layout.y);
  context.stroke();
}

function isSameExtremum(
  high: DetailChartVisibleExtremum | null,
  low: DetailChartVisibleExtremum,
): boolean {
  return high?.index === low.index && high.value === low.value;
}

function resolveExtremaColor(): string {
  return resolveRootToken("--cs-color-text-primary", EXTREMA_COLOR_FALLBACK);
}

function resolveExtremaFontFamily(): string {
  return resolveRootToken("--cs-font-family-number", EXTREMA_FONT_FAMILY_FALLBACK);
}

function resolveRootToken(token: string, fallback: string): string {
  if (typeof document === "undefined" || typeof getComputedStyle === "undefined") {
    return fallback;
  }
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim() || fallback;
}
