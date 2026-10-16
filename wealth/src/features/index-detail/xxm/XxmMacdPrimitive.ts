import type { AutoscaleInfo, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from "lightweight-charts";
import { DETAIL_CHART_COLORS } from "../../../shared/charts/detail-workspace/detailChartSeries";
import { layoutXxmLabels, XXM_MARKER_STYLE } from "./markerGeometry";
import type { XxmEvent, XxmMarker } from "./types";

function color(event: XxmEvent): string {
  const token = event.type === "DULL" ? "--cs-color-warning" : event.type === "STRUCTURE" ? "--cs-color-purple"
    : event.type === "RESEARCH_HISTORICAL_WITHDRAWAL" ? "--cs-color-market-down" : "--cs-color-text-secondary";
  const fallback = event.type === "DULL" ? DETAIL_CHART_COLORS.amber : event.type === "STRUCTURE" ? DETAIL_CHART_COLORS.purple
    : event.type === "RESEARCH_HISTORICAL_WITHDRAWAL" ? DETAIL_CHART_COLORS.down : DETAIL_CHART_COLORS.text;
  return typeof document === "undefined" ? fallback : getComputedStyle(document.documentElement).getPropertyValue(token).trim() || fallback;
}

export class XxmMacdPrimitive implements ISeriesPrimitive<Time> {
  private attachedParameters: SeriesAttachedParameter<Time> | null = null;
  private markers: readonly XxmMarker[] = [];
  private readonly view: IPrimitivePaneView = {
    zOrder: () => "top",
    renderer: () => ({ draw: target => this.draw(target) }),
  };
  attached(parameters: SeriesAttachedParameter<Time>) { this.attachedParameters = parameters; }
  detached() { this.attachedParameters = null; }
  paneViews(): readonly IPrimitivePaneView[] { return [this.view]; }
  autoscaleInfo(): AutoscaleInfo | null { return null; }
  setMarkers(markers: readonly XxmMarker[]) { this.markers = markers; this.attachedParameters?.requestUpdate(); }
  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]) {
    const attached = this.attachedParameters;
    if (!attached || !this.markers.length) return;
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save(); context.beginPath(); context.rect(0, 0, mediaSize.width, mediaSize.height); context.clip();
      const family = getComputedStyle(document.documentElement).getPropertyValue("--cs-font-family-base").trim() || "sans-serif";
      context.font = `${XXM_MARKER_STYLE.fontWeight} ${XXM_MARKER_STYLE.fontSize}px ${family}`;
      context.textAlign = "left"; context.textBaseline = "top";
      const positioned = this.markers.flatMap(marker => {
        const x = attached.chart.timeScale().timeToCoordinate(marker.time);
        const y = attached.series.priceToCoordinate(marker.dif);
        return x === null || y === null || x < 0 || x > mediaSize.width || y < 0 || y > mediaSize.height ? [] : [{ marker, x, y }];
      });
      const labels = layoutXxmLabels(positioned, mediaSize.width, mediaSize.height, label => context.measureText(label).width);
      context.lineWidth = XXM_MARKER_STYLE.leaderWidth;
      for (const label of labels) {
        if (!label.leader) continue;
        context.strokeStyle = color(label.marker.event); context.beginPath();
        context.moveTo(label.leader.fromX, label.leader.fromY);
        for (const point of label.leader.via) context.lineTo(point.x, point.y);
        context.lineTo(label.leader.toX, label.leader.toY); context.stroke();
      }
      for (const position of positioned) {
        context.fillStyle = color(position.marker.event); context.beginPath();
        context.arc(position.x, position.y, XXM_MARKER_STYLE.dotRadius, 0, Math.PI * 2); context.fill();
      }
      for (const label of labels) {
        context.fillStyle = label.label.startsWith("+")
          ? getComputedStyle(document.documentElement).getPropertyValue("--cs-color-text-secondary").trim() || DETAIL_CHART_COLORS.text
          : color(label.marker.event);
        context.fillText(label.label, label.left, label.top + (XXM_MARKER_STYLE.lineHeight - XXM_MARKER_STYLE.fontSize) / 2);
      }
      context.restore();
    });
  }
}
