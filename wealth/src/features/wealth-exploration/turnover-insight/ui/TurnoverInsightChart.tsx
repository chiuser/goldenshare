import { useEffect, useMemo, useRef, useState } from "react";

import type {
  TurnoverInsightAverageViewModel,
  TurnoverInsightAxisViewModel,
  TurnoverInsightChartPoint,
} from "../model/turnoverInsightTypes";
import { TurnoverInsightTooltip } from "./TurnoverInsightTooltip";
import {
  buildTurnoverInsightGeometry,
  indexForX,
  xForIndex,
  yForValue,
  type TurnoverInsightLayout,
} from "./turnoverInsightGeometry";

interface TurnoverInsightChartProps {
  points: readonly TurnoverInsightChartPoint[];
  upperAxis: TurnoverInsightAxisViewModel;
  deltaAxis: TurnoverInsightAxisViewModel | null;
  avg5d: TurnoverInsightAverageViewModel;
  avg20d: TurnoverInsightAverageViewModel;
  layout?: TurnoverInsightLayout;
}

const COLORS = {
  current: "#ff4d5a",
  previous: "#e7edf8",
  down: "#14c98b",
  grid: "rgba(135, 151, 177, 0.18)",
  axis: "#8391a9",
  crosshair: "rgba(226, 232, 240, 0.62)",
};

const AVERAGE_COLOR_TOKENS = {
  avg5d: { property: "--cs-color-brand", fallback: "#f7c76b" },
  avg20d: { property: "--cs-color-purple", fallback: "#a78bfa" },
};

export type AverageLabelPlacement = "above" | "below";

export interface AverageReferenceRenderItem {
  key: "avg5d" | "avg20d";
  average: TurnoverInsightAverageViewModel;
  color: string;
  labelPlacement: AverageLabelPlacement;
}

export function resolveAverageReferenceRenderItems(
  avg5d: TurnoverInsightAverageViewModel,
  avg20d: TurnoverInsightAverageViewModel,
  colors: Readonly<Record<AverageReferenceRenderItem["key"], string>>,
): readonly AverageReferenceRenderItem[] {
  const avg5dAmount = avg5d.amountYi;
  const avg20dAmount = avg20d.amountYi;
  const hasAvg5d = avg5dAmount !== null;
  const hasAvg20d = avg20dAmount !== null;

  if (hasAvg5d && hasAvg20d) {
    const avg5dAbove = avg5dAmount >= avg20dAmount;
    return [
      {
        key: "avg5d",
        average: avg5d,
        color: colors.avg5d,
        labelPlacement: avg5dAbove ? "above" : "below",
      },
      {
        key: "avg20d",
        average: avg20d,
        color: colors.avg20d,
        labelPlacement: avg5dAbove ? "below" : "above",
      },
    ];
  }

  if (hasAvg5d) {
    return [{ key: "avg5d", average: avg5d, color: colors.avg5d, labelPlacement: "above" }];
  }
  if (hasAvg20d) {
    return [{ key: "avg20d", average: avg20d, color: colors.avg20d, labelPlacement: "above" }];
  }
  return [];
}

const COMPACT_AXIS_LABELS = new Set([
  "09:30", "10:00", "10:30", "11:00", "11:30", "13:15", "14:00", "14:30", "15:00",
]);

export function shouldShowTurnoverAxisLabel(
  point: Pick<TurnoverInsightChartPoint, "time" | "showAxisLabel">,
  layout: TurnoverInsightLayout,
): boolean {
  return layout === "compact" ? COMPACT_AXIS_LABELS.has(point.time) : point.showAxisLabel;
}

export function TurnoverInsightChart({
  points,
  upperAxis,
  deltaAxis,
  avg5d,
  avg20d,
  layout = "full",
}: TurnoverInsightChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(1330);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const geometry = useMemo(() => buildTurnoverInsightGeometry(width, layout), [layout, width]);
  const averageColors = useMemo(resolveAverageColors, []);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const updateWidth = () => setWidth(Math.max(360, element.getBoundingClientRect().width));
    updateWidth();
    const observer = new ResizeObserver((entries) => {
      const nextWidth = entries[0]?.contentRect.width;
      if (nextWidth) setWidth(Math.max(360, nextWidth));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(geometry.width * ratio);
    canvas.height = Math.round(geometry.height * ratio);
    canvas.style.width = `${geometry.width}px`;
    canvas.style.height = `${geometry.height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    drawChart(context, {
      geometry,
      points,
      upperAxis,
      deltaAxis,
      avg5d,
      avg20d,
      averageColors,
      hoverIndex,
    });
  }, [averageColors, avg20d, avg5d, deltaAxis, geometry, hoverIndex, points, upperAxis]);

  const hoveredPoint = hoverIndex === null ? null : points[hoverIndex] ?? null;
  const hoverX = hoverIndex === null ? 0 : xForIndex(geometry, hoverIndex, points.length);
  const tooltipLeft = Math.max(8, Math.min(geometry.width - 214, hoverX > geometry.width * 0.72 ? hoverX - 202 : hoverX + 12));

  return (
    <div
      className={`turnover-insight-chart turnover-insight-chart--${layout}`}
      ref={containerRef}
      onPointerLeave={() => setHoverIndex(null)}
      onPointerMove={(event) => {
        const bounds = event.currentTarget.getBoundingClientRect();
        const x = event.clientX - bounds.left;
        const y = event.clientY - bounds.top;
        const withinPlot = x >= geometry.plotLeft
          && x <= geometry.plotRight
          && y >= geometry.upperTop
          && y <= geometry.lowerBottom;
        setHoverIndex(withinPlot ? indexForX(geometry, x, points.length) : null);
      }}
    >
      <canvas aria-label="当日与昨日累计成交额及累计差值图" ref={canvasRef} />
      {hoveredPoint ? (
        <TurnoverInsightTooltip left={tooltipLeft} point={hoveredPoint} top={geometry.upperTop + 10} />
      ) : null}
    </div>
  );
}

interface DrawChartInput extends TurnoverInsightChartProps {
  geometry: ReturnType<typeof buildTurnoverInsightGeometry>;
  averageColors: { avg5d: string; avg20d: string };
  hoverIndex: number | null;
}

function drawChart(context: CanvasRenderingContext2D, input: DrawChartInput) {
  const {
    geometry,
    points,
    upperAxis,
    deltaAxis,
    avg5d,
    avg20d,
      averageColors,
      hoverIndex,
      layout,
  } = input;
  const averageRenderItems = resolveAverageReferenceRenderItems(avg5d, avg20d, averageColors);
  context.clearRect(0, 0, geometry.width, geometry.height);
  context.font = "12px var(--cs-font-family-number, monospace)";
  context.lineWidth = 1;

  drawHorizontalAxis(context, geometry, upperAxis, geometry.upperTop, geometry.upperBottom);
  if (deltaAxis) drawHorizontalAxis(context, geometry, deltaAxis, geometry.lowerTop, geometry.lowerBottom);

  context.strokeStyle = COLORS.grid;
  context.fillStyle = COLORS.axis;
  points.forEach((point, index) => {
    const showLabel = shouldShowTurnoverAxisLabel(point, input.layout ?? "full");
    if (!showLabel) return;
    const x = xForIndex(geometry, index, points.length);
    context.beginPath();
    context.moveTo(x, geometry.upperTop);
    context.lineTo(x, deltaAxis ? geometry.lowerBottom : geometry.upperBottom);
    context.stroke();
    context.textAlign = index === 0 ? "left" : index === points.length - 1 ? "right" : "center";
    context.fillText(point.time, x, geometry.timeLabelY);
  });

  if (deltaAxis) {
    const zeroY = yForValue(0, deltaAxis, geometry.lowerTop, geometry.lowerBottom);
    const barWidth = Math.max(1, (geometry.plotRight - geometry.plotLeft) / points.length - 1);
    points.forEach((point, index) => {
      if (point.deltaAmountYi === null) return;
      const x = xForIndex(geometry, index, points.length);
      const y = yForValue(point.deltaAmountYi, deltaAxis, geometry.lowerTop, geometry.lowerBottom);
      context.fillStyle = point.deltaDirection === "down" ? COLORS.down : COLORS.current;
      context.globalAlpha = hoverIndex === index ? 1 : 0.74;
      context.fillRect(x - barWidth / 2, Math.min(y, zeroY), barWidth, Math.max(1, Math.abs(zeroY - y)));
    });
    context.globalAlpha = 1;
  }

  averageRenderItems.forEach((item) => {
    drawAverageReferenceLine(context, geometry, upperAxis, item.average, item.color);
  });
  drawLine(context, geometry, points, upperAxis, "previousAmountYi", COLORS.previous);
  drawLine(context, geometry, points, upperAxis, "currentAmountYi", COLORS.current);
  averageRenderItems.forEach((item) => {
    drawAverageReferenceLabel(
      context,
      geometry,
      upperAxis,
      item.average,
      item.color,
      item.labelPlacement,
    );
  });

  if (hoverIndex !== null) {
    const point = points[hoverIndex];
    if (!point) return;
    const x = xForIndex(geometry, hoverIndex, points.length);
    context.save();
    context.strokeStyle = COLORS.crosshair;
    context.setLineDash([4, 4]);
    context.beginPath();
    context.moveTo(x, geometry.upperTop);
    context.lineTo(x, deltaAxis ? geometry.lowerBottom : geometry.upperBottom);
    context.stroke();
    context.restore();
    drawHoverPoint(context, x, point.previousAmountYi, upperAxis, geometry, COLORS.previous);
    drawHoverPoint(context, x, point.currentAmountYi, upperAxis, geometry, COLORS.current);
  }
}

export function drawAverageReferenceLine(
  context: CanvasRenderingContext2D,
  geometry: ReturnType<typeof buildTurnoverInsightGeometry>,
  upperAxis: TurnoverInsightAxisViewModel,
  average: TurnoverInsightAverageViewModel,
  color: string,
) {
  if (average.amountYi === null) return;
  const y = yForValue(average.amountYi, upperAxis, geometry.upperTop, geometry.upperBottom);
  context.save();
  context.strokeStyle = color;
  context.lineWidth = 1;
  context.setLineDash([4, 4]);
  context.beginPath();
  context.moveTo(geometry.plotLeft, y);
  context.lineTo(geometry.plotRight, y);
  context.stroke();
  context.restore();
}

export function drawAverageReferenceLabel(
  context: CanvasRenderingContext2D,
  geometry: ReturnType<typeof buildTurnoverInsightGeometry>,
  upperAxis: TurnoverInsightAxisViewModel,
  average: TurnoverInsightAverageViewModel,
  color: string,
  placement: AverageLabelPlacement,
) {
  if (average.amountYi === null) return;
  const y = yForValue(average.amountYi, upperAxis, geometry.upperTop, geometry.upperBottom);
  context.save();
  context.fillStyle = color;
  context.textAlign = "right";
  context.textBaseline = placement === "above" ? "bottom" : "top";
  context.fillText(average.referenceLabel, geometry.plotRight, placement === "above" ? y - 2 : y + 2);
  context.restore();
}

function resolveAverageColors(): { avg5d: string; avg20d: string } {
  if (typeof window === "undefined") {
    return {
      avg5d: AVERAGE_COLOR_TOKENS.avg5d.fallback,
      avg20d: AVERAGE_COLOR_TOKENS.avg20d.fallback,
    };
  }
  const styles = window.getComputedStyle(document.documentElement);
  return {
    avg5d: styles.getPropertyValue(AVERAGE_COLOR_TOKENS.avg5d.property).trim()
      || AVERAGE_COLOR_TOKENS.avg5d.fallback,
    avg20d: styles.getPropertyValue(AVERAGE_COLOR_TOKENS.avg20d.property).trim()
      || AVERAGE_COLOR_TOKENS.avg20d.fallback,
  };
}

function drawHorizontalAxis(
  context: CanvasRenderingContext2D,
  geometry: ReturnType<typeof buildTurnoverInsightGeometry>,
  axis: TurnoverInsightAxisViewModel,
  top: number,
  bottom: number,
) {
  axis.ticks.forEach((tick) => {
    const y = yForValue(tick.valueYi, axis, top, bottom);
    context.strokeStyle = COLORS.grid;
    context.beginPath();
    context.moveTo(geometry.plotLeft, y);
    context.lineTo(geometry.plotRight, y);
    context.stroke();
    context.fillStyle = COLORS.axis;
    context.textAlign = "right";
    context.fillText(tick.displayText, geometry.plotLeft - 8, y + 4);
  });
}

function drawLine(
  context: CanvasRenderingContext2D,
  geometry: ReturnType<typeof buildTurnoverInsightGeometry>,
  points: readonly TurnoverInsightChartPoint[],
  axis: TurnoverInsightAxisViewModel,
  field: "currentAmountYi" | "previousAmountYi",
  color: string,
) {
  let drawing = false;
  context.strokeStyle = color;
  context.lineWidth = 2;
  context.beginPath();
  points.forEach((point, index) => {
    const value = point[field];
    if (value === null) {
      drawing = false;
      return;
    }
    const x = xForIndex(geometry, index, points.length);
    const y = yForValue(value, axis, geometry.upperTop, geometry.upperBottom);
    if (!drawing) {
      context.moveTo(x, y);
      drawing = true;
    } else {
      context.lineTo(x, y);
    }
  });
  context.stroke();
  context.lineWidth = 1;
}

function drawHoverPoint(
  context: CanvasRenderingContext2D,
  x: number,
  value: number | null,
  axis: TurnoverInsightAxisViewModel,
  geometry: ReturnType<typeof buildTurnoverInsightGeometry>,
  color: string,
) {
  if (value === null) return;
  const y = yForValue(value, axis, geometry.upperTop, geometry.upperBottom);
  context.fillStyle = color;
  context.beginPath();
  context.arc(x, y, 3, 0, Math.PI * 2);
  context.fill();
}
