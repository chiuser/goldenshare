import type {
  AutoscaleInfo, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive,
  SeriesAttachedParameter, Time,
} from "lightweight-charts";

import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { buildCandlestickData } from "../../../shared/charts/detail-workspace/detailChartSeries";
import { resolveMainPriceScaleMargins } from "../../../shared/charts/detail-workspace/detailChartViewport";
import { resolveVisibleExtrema } from "../../../shared/charts/detail-workspace/detailChartVisibleExtrema";
import { resolveExtremaFontFamily } from "../../../shared/charts/detail-workspace/VisibleExtremaPrimitive";
import { measureVisibleExtremaMarker, visibleExtremaFont } from "../../../shared/charts/detail-workspace/visibleExtremaGeometry";
import { resolveNineTurnMarkerRect } from "../../../shared/charts/detail-workspace/nineTurnMarkerGeometry";
import type { NineTurnRenderMarker } from "../../../shared/charts/detail-workspace/nineTurnMarkerTypes";
import { resolveDailyWaveMarkerLayout } from "./markerGeometry";
import type { DailyWaveMarkerInput, DailyWaveMarkerIssue, DailyWaveMarkerRect } from "./markerGeometry";

export interface DailyWavePrimitiveData {
  points: readonly DetailChartPoint[];
  markers: readonly DailyWaveMarkerInput[];
  nineTurnMarkers: readonly NineTurnRenderMarker[];
  onIssues: (issues: readonly DailyWaveMarkerIssue[]) => void;
}

export class DailyWavePrimitive implements ISeriesPrimitive<Time> {
  private attachedParameters: SeriesAttachedParameter<Time> | null = null;
  private data: DailyWavePrimitiveData | null = null;
  private candles: ReturnType<typeof buildCandlestickData> = [];
  private readonly view = new DailyWavePaneView(this);
  private readonly views: readonly IPrimitivePaneView[] = [this.view];
  private pendingFrame: number | null = null;
  private deliveredIssues = "";
  private readonly requestLayout = () => this.attachedParameters?.requestUpdate();

  setData(data: DailyWavePrimitiveData): void {
    if (this.data?.points !== data.points) this.candles = buildCandlestickData([...data.points]);
    this.data = data;
    this.cancelIssueFrame();
    this.attachedParameters?.requestUpdate();
  }

  attached(parameters: SeriesAttachedParameter<Time>): void {
    this.detached();
    this.attachedParameters = parameters;
    parameters.chart.timeScale().subscribeVisibleLogicalRangeChange(this.requestLayout);
    parameters.chart.timeScale().subscribeSizeChange(this.requestLayout);
    this.deliveredIssues = "";
    parameters.requestUpdate();
  }

  detached(): void {
    const attached = this.attachedParameters;
    if (attached) {
      attached.chart.timeScale().unsubscribeVisibleLogicalRangeChange(this.requestLayout);
      attached.chart.timeScale().unsubscribeSizeChange(this.requestLayout);
    }
    this.cancelIssueFrame();
    this.attachedParameters = null;
  }

  paneViews(): readonly IPrimitivePaneView[] { return this.views; }
  autoscaleInfo(): AutoscaleInfo | null { return null; }

  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]): void {
    const attached = this.attachedParameters;
    const data = this.data;
    if (!attached || !data) return;
    const timeScale = attached.chart.timeScale();
    const range = timeScale.getVisibleLogicalRange();
    const dates = timeScale.getVisibleRange();
    if (!range || !dates) { this.reportIssues([]); return; }
    // Logical indices span every main-chart series, including dates without OHLC.
    const first = calendarDate(dates.from);
    const last = calendarDate(dates.to);
    const visible = data.markers.filter((marker) => marker.date >= first && marker.date <= last);
    if (!visible.length) { this.reportIssues([]); return; }
    const candlesByDate = new Map(this.candles.map((point) => [calendarDate(point.time), point]));
    const coordinates = visible.map((marker) => {
      const point = candlesByDate.get(marker.date);
      return { ...marker, x: point ? timeScale.timeToCoordinate(point.time) : null,
        anchorY: point ? attached.series.priceToCoordinate(marker.direction === "UP" ? point.low : point.high) : null };
    });
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      if (!resolveMainPriceScaleMargins(mediaSize.height, { top: 44, bottom: 44 })) {
        this.reportIssues(visible.map((marker) => ({ ...marker, reason: "SPACE_UNAVAILABLE" })));
        return;
      }
      context.save();
      context.font = visibleExtremaFont(resolveExtremaFontFamily());
      const occupied: DailyWaveMarkerRect[] = [];
      for (const marker of data.nineTurnMarkers) {
        const date = calendarDate(marker.time);
        if (date < first || date > last) continue;
        const x = timeScale.timeToCoordinate(marker.time);
        const y = attached.series.priceToCoordinate(marker.anchorPrice);
        if (x !== null && y !== null) occupied.push(resolveNineTurnMarkerRect(x, y, marker.direction));
      }
      const extrema = resolveVisibleExtrema(this.candles, range);
      for (const extremum of [extrema.high, extrema.low]) {
        if (!extremum || (extremum === extrema.low && extrema.high?.index === extremum.index &&
            extrema.high.value === extremum.value)) continue;
        const x = timeScale.timeToCoordinate(extremum.time);
        const y = attached.series.priceToCoordinate(extremum.value);
        if (x === null || y === null) continue;
        const measured = measureVisibleExtremaMarker({ anchorX: x, y, value: extremum.value,
          mediaWidth: mediaSize.width, mediaHeight: mediaSize.height,
          measureTextWidth: (label) => context.measureText(label).width });
        if (measured) occupied.push(measured.rect);
      }
      const placed = resolveDailyWaveMarkerLayout({ markers: coordinates, occupied,
        width: mediaSize.width, height: mediaSize.height });
      for (const marker of placed.layouts) {
        const { left, top, width, height } = marker.rect;
        context.fillStyle = marketColor(marker.direction);
        context.beginPath();
        if (marker.direction === "UP") {
          context.moveTo(left + width / 2, top);
          context.lineTo(left + width, top + height);
          context.lineTo(left, top + height);
        } else {
          context.moveTo(left + width / 2, top + height);
          context.lineTo(left + width, top);
          context.lineTo(left, top);
        }
        context.closePath();
        context.fill();
      }
      context.restore();
      this.reportIssues(placed.issues);
    });
  }

  private reportIssues(issues: readonly DailyWaveMarkerIssue[]): void {
    const signature = JSON.stringify(issues);
    if (signature === this.deliveredIssues) { this.cancelIssueFrame(); return; }
    this.cancelIssueFrame();
    const data = this.data;
    this.pendingFrame = window.requestAnimationFrame(() => {
      this.pendingFrame = null;
      if (!this.attachedParameters || this.data !== data) return;
      this.deliveredIssues = signature;
      data?.onIssues(issues);
    });
  }

  private cancelIssueFrame(): void {
    if (this.pendingFrame !== null) window.cancelAnimationFrame(this.pendingFrame);
    this.pendingFrame = null;
  }
}

function calendarDate(time: Time): string {
  return typeof time === "object"
    ? `${time.year.toString().padStart(4, "0")}-${time.month.toString().padStart(2, "0")}-${time.day.toString().padStart(2, "0")}`
    : String(time);
}

class DailyWavePaneView implements IPrimitivePaneView {
  constructor(private readonly primitive: DailyWavePrimitive) {}
  zOrder() { return "top" as const; }
  renderer(): IPrimitivePaneRenderer { return { draw: (target) => this.primitive.draw(target) }; }
}

function marketColor(direction: "UP" | "DOWN"): string {
  const token = direction === "UP" ? "--cs-color-market-up" : "--cs-color-market-down";
  const fallback = direction === "UP" ? "#ff4d5a" : "#15c784";
  return typeof document === "undefined" || typeof getComputedStyle === "undefined" ? fallback
    : getComputedStyle(document.documentElement).getPropertyValue(token).trim() || fallback;
}
