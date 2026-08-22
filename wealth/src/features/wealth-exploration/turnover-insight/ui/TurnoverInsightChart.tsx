import { useEffect, useMemo, useRef, useState } from "react";

import type {
  TurnoverInsightAxisViewModel,
  TurnoverInsightChartPoint,
} from "../model/turnoverInsightTypes";
import { TurnoverInsightTooltip } from "./TurnoverInsightTooltip";
import {
  buildTurnoverInsightGeometry,
  indexForX,
  xForIndex,
  yForValue,
} from "./turnoverInsightGeometry";

interface TurnoverInsightChartProps {
  points: readonly TurnoverInsightChartPoint[];
  upperAxis: TurnoverInsightAxisViewModel;
  deltaAxis: TurnoverInsightAxisViewModel | null;
}

const COLORS = {
  current: "#ff4d5a",
  previous: "#e7edf8",
  down: "#14c98b",
  grid: "rgba(135, 151, 177, 0.18)",
  axis: "#8391a9",
  crosshair: "rgba(226, 232, 240, 0.62)",
};

export function TurnoverInsightChart({ points, upperAxis, deltaAxis }: TurnoverInsightChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(1330);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const geometry = useMemo(() => buildTurnoverInsightGeometry(width), [width]);

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
    drawChart(context, { geometry, points, upperAxis, deltaAxis, hoverIndex });
  }, [deltaAxis, geometry, hoverIndex, points, upperAxis]);

  const hoveredPoint = hoverIndex === null ? null : points[hoverIndex] ?? null;
  const hoverX = hoverIndex === null ? 0 : xForIndex(geometry, hoverIndex, points.length);
  const tooltipLeft = Math.max(8, Math.min(geometry.width - 214, hoverX > geometry.width * 0.72 ? hoverX - 202 : hoverX + 12));

  return (
    <div
      className="turnover-insight-chart"
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
  hoverIndex: number | null;
}

function drawChart(context: CanvasRenderingContext2D, input: DrawChartInput) {
  const { geometry, points, upperAxis, deltaAxis, hoverIndex } = input;
  context.clearRect(0, 0, geometry.width, geometry.height);
  context.font = "12px var(--cs-font-family-number, monospace)";
  context.lineWidth = 1;

  drawHorizontalAxis(context, geometry, upperAxis, geometry.upperTop, geometry.upperBottom);
  if (deltaAxis) drawHorizontalAxis(context, geometry, deltaAxis, geometry.lowerTop, geometry.lowerBottom);

  context.strokeStyle = COLORS.grid;
  context.fillStyle = COLORS.axis;
  points.forEach((point, index) => {
    if (!point.showAxisLabel) return;
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

  drawLine(context, geometry, points, upperAxis, "previousAmountYi", COLORS.previous);
  drawLine(context, geometry, points, upperAxis, "currentAmountYi", COLORS.current);

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
