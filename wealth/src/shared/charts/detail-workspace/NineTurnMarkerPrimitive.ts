import type {
  AutoscaleInfo,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
} from "lightweight-charts";

import {
  resolveNineTurnMarkerRect,
  sliceNineTurnMarkersByTime,
  sortNineTurnMarkers,
} from "./nineTurnMarkerGeometry";
import type { NineTurnRenderDirection, NineTurnRenderMarker } from "./nineTurnMarkerTypes";

const MARKET_COLOR_FALLBACKS = {
  DOWN: "#15c784",
  UP: "#ff4d5a",
} as const;
const NEUTRAL_MARKER_COLOR_FALLBACK = "#94a3b8";

export class NineTurnMarkerPrimitive implements ISeriesPrimitive<Time> {
  private attachedParameters: SeriesAttachedParameter<Time> | null = null;
  private markers: readonly NineTurnRenderMarker[] = [];
  private readonly view = new NineTurnMarkerPaneView(this);

  constructor(markers: readonly NineTurnRenderMarker[] = []) {
    this.markers = sortNineTurnMarkers(markers);
  }

  attached(parameters: SeriesAttachedParameter<Time>) {
    this.attachedParameters = parameters;
  }

  detached() {
    this.attachedParameters = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }

  autoscaleInfo(): AutoscaleInfo | null {
    return null;
  }

  setMarkers(markers: readonly NineTurnRenderMarker[]): void {
    this.markers = sortNineTurnMarkers(markers);
    this.attachedParameters?.requestUpdate();
  }

  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]): void {
    const attached = this.attachedParameters;
    if (!attached || this.markers.length === 0) return;
    const visibleRange = attached.chart.timeScale().getVisibleLogicalRange();
    if (!visibleRange) return;
    const firstBar = attached.series.dataByIndex(Math.ceil(visibleRange.from));
    const lastBar = attached.series.dataByIndex(Math.floor(visibleRange.to));
    if (!firstBar || !lastBar || !("time" in firstBar) || !("time" in lastBar)) return;
    const visibleMarkers = sliceNineTurnMarkersByTime(
      this.markers,
      firstBar.time,
      lastBar.time,
    );
    if (visibleMarkers.length === 0) return;

    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save();
      context.font = "700 12px var(--cs-font-family-number, sans-serif)";
      context.textAlign = "center";
      context.textBaseline = "middle";
      const neutralColor = resolveNeutralMarkerColor();
      const marketColors = {
        DOWN: resolveMarketColor("DOWN"),
        UP: resolveMarketColor("UP"),
      } as const;
      for (const marker of visibleMarkers) {
        const centerX = attached.chart.timeScale().timeToCoordinate(marker.time);
        const anchorY = attached.series.priceToCoordinate(marker.anchorPrice);
        if (centerX === null || anchorY === null) continue;
        const rect = resolveNineTurnMarkerRect(centerX, anchorY, marker.direction);
        if (
          rect.left + rect.width < 0 || rect.left > mediaSize.width ||
          rect.top + rect.height < 0 || rect.top > mediaSize.height
        ) continue;
        const color = marker.sequenceNumber === 9
          ? marketColors[marker.direction]
          : neutralColor;
        if (marker.sequenceNumber === 9) {
          drawRoundedRect(context, rect.left, rect.top, rect.width, rect.height, 2);
          context.lineWidth = 1;
          context.strokeStyle = color;
          context.stroke();
        }
        context.fillStyle = color;
        context.fillText(
          String(marker.sequenceNumber),
          rect.left + rect.width / 2,
          rect.top + rect.height / 2 + 0.5,
        );
      }
      context.restore();
    });
  }
}

class NineTurnMarkerPaneView implements IPrimitivePaneView {
  constructor(private readonly primitive: NineTurnMarkerPrimitive) {}

  zOrder() {
    return "bottom" as const;
  }

  renderer(): IPrimitivePaneRenderer {
    return { draw: (target) => this.primitive.draw(target) };
  }
}

function resolveMarketColor(direction: NineTurnRenderDirection): string {
  if (typeof document === "undefined" || typeof getComputedStyle === "undefined") {
    return MARKET_COLOR_FALLBACKS[direction];
  }
  const token = direction === "UP" ? "--cs-color-market-up" : "--cs-color-market-down";
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim()
    || MARKET_COLOR_FALLBACKS[direction];
}

function resolveNeutralMarkerColor(): string {
  if (typeof document === "undefined" || typeof getComputedStyle === "undefined") {
    return NEUTRAL_MARKER_COLOR_FALLBACK;
  }
  return getComputedStyle(document.documentElement)
    .getPropertyValue("--cs-color-text-secondary")
    .trim() || NEUTRAL_MARKER_COLOR_FALLBACK;
}

function drawRoundedRect(
  context: CanvasRenderingContext2D,
  left: number,
  top: number,
  width: number,
  height: number,
  radius: number,
): void {
  const right = left + width;
  const bottom = top + height;
  context.beginPath();
  context.moveTo(left + radius, top);
  context.lineTo(right - radius, top);
  context.quadraticCurveTo(right, top, right, top + radius);
  context.lineTo(right, bottom - radius);
  context.quadraticCurveTo(right, bottom, right - radius, bottom);
  context.lineTo(left + radius, bottom);
  context.quadraticCurveTo(left, bottom, left, bottom - radius);
  context.lineTo(left, top + radius);
  context.quadraticCurveTo(left, top, left + radius, top);
  context.closePath();
}
