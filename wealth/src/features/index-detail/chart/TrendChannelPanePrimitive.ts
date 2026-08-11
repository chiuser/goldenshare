import type {
  AutoscaleInfo,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  Time,
} from "lightweight-charts";

import type { TrendChannelLine } from "./trendChannelGeometry";

export class TrendChannelPanePrimitive implements ISeriesPrimitive<Time> {
  private attachedParameters: SeriesAttachedParameter<Time> | null = null;
  private readonly view = new TrendChannelPaneView(this);

  constructor(private readonly lines: TrendChannelLine[]) {}

  attached(parameters: SeriesAttachedParameter<Time>) {
    this.attachedParameters = parameters;
  }

  detached() {
    this.attachedParameters = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }

  autoscaleInfo(startTimePoint: Logical, endTimePoint: Logical): AutoscaleInfo | null {
    const visibleValues = this.lines.flatMap((line) => {
      if (line.toLogical < startTimePoint || line.fromLogical > endTimePoint) return [];
      return [line.fromValue, line.toValue];
    });
    if (visibleValues.length === 0) return null;
    return { priceRange: { minValue: Math.min(...visibleValues), maxValue: Math.max(...visibleValues) } };
  }

  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]) {
    const attached = this.attachedParameters;
    if (!attached) return;
    target.useMediaCoordinateSpace(({ context }) => {
      context.save();
      context.lineWidth = 1;
      for (const line of this.lines) {
        const fromX = attached.chart.timeScale().timeToCoordinate(line.fromTime as Time);
        const toX = attached.chart.timeScale().timeToCoordinate(line.toTime as Time);
        const fromY = attached.series.priceToCoordinate(line.fromValue);
        const toY = attached.series.priceToCoordinate(line.toValue);
        if (fromX === null || toX === null || fromY === null || toY === null) continue;
        context.beginPath();
        context.strokeStyle = line.color;
        context.globalAlpha = 0.86;
        context.moveTo(fromX, fromY);
        context.lineTo(toX, toY);
        context.stroke();
      }
      context.restore();
    });
  }
}

class TrendChannelPaneView implements IPrimitivePaneView {
  constructor(private readonly primitive: TrendChannelPanePrimitive) {}

  zOrder() {
    return "bottom" as const;
  }

  renderer(): IPrimitivePaneRenderer {
    return { draw: (target) => this.primitive.draw(target) };
  }
}
