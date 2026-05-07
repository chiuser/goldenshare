import { useEffect, useRef, useState } from "react";
import type { MultiTrendPoint } from "../model/market";

interface Series {
  key: string;
  name: string;
  color: string;
  dots?: boolean;
  valueFormatter?: (value: number) => string;
  width?: number;
}

interface MiniLineChartProps {
  data: MultiTrendPoint[];
  series: Series[];
  height?: number;
  valueClassBySign?: boolean;
  zeroCenter?: boolean;
  yFormatter?: (value: number) => string;
}

interface CanvasMetrics {
  height: number;
  pad: { b: number; l: number; r: number; t: number };
  width: number;
  x: (index: number) => number;
  y: (value: number) => number;
}

function niceRange(values: number[], zeroCenter: boolean) {
  if (zeroCenter) {
    const abs = Math.max(...values.map((value) => Math.abs(value)), 1) * 1.18;
    return { min: -abs, max: abs };
  }

  let min = Math.min(...values);
  let max = Math.max(...values);

  if (min === max) {
    min -= 1;
    max += 1;
  }

  const padding = (max - min) * 0.12;
  return { min: min - padding, max: max + padding };
}

function signedClass(value: number) {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}

function defaultYFormatter(value: number) {
  return String(Math.round(value));
}

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function setupCanvas(canvas: HTMLCanvasElement) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, height: rect.height, width: rect.width };
}

function drawAxes(
  ctx: CanvasRenderingContext2D,
  metrics: CanvasMetrics,
  labels: Array<{ label: string; x: number }>,
  yTicks: Array<{ label: string; y: number }>,
) {
  const gridColor = cssVar("--cs-color-chart-grid-primary");
  const axisColor = cssVar("--cs-color-chart-axis-line");
  const labelColor = cssVar("--cs-color-chart-axis-label");
  const numberFont = cssVar("--cs-font-family-number");

  ctx.strokeStyle = gridColor;
  ctx.lineWidth = 1;
  ctx.font = `11px ${numberFont}`;
  ctx.fillStyle = labelColor;
  ctx.textAlign = "right";
  yTicks.forEach((tick) => {
    ctx.beginPath();
    ctx.moveTo(metrics.pad.l, tick.y);
    ctx.lineTo(metrics.width - metrics.pad.r, tick.y);
    ctx.stroke();
    ctx.fillText(tick.label, metrics.pad.l - 7, tick.y + 4);
  });

  ctx.strokeStyle = axisColor;
  ctx.beginPath();
  ctx.moveTo(metrics.pad.l, metrics.pad.t);
  ctx.lineTo(metrics.pad.l, metrics.height - metrics.pad.b);
  ctx.lineTo(metrics.width - metrics.pad.r, metrics.height - metrics.pad.b);
  ctx.stroke();

  ctx.textAlign = "center";
  labels.forEach((label) => ctx.fillText(label.label, label.x, metrics.height - 8));
}

export function MiniLineChart({
  data,
  series,
  height = 178,
  valueClassBySign = false,
  yFormatter = defaultYFormatter,
  zeroCenter = false,
}: MiniLineChartProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const hover = hoverIndex == null ? null : data[hoverIndex];
  const values = data.flatMap((item) => series.map((serie) => Number(item[serie.key])));
  const range = niceRange(values, zeroCenter);

  function buildMetrics(width: number, canvasHeight: number): CanvasMetrics {
    const pad = { l: 48, r: 16, t: 16, b: 32 };
    const span = range.max - range.min || 1;
    const x = (index: number) => pad.l + (width - pad.l - pad.r) * (index / Math.max(1, data.length - 1));
    const y = (value: number) => pad.t + ((range.max - value) / span) * (canvasHeight - pad.t - pad.b);
    return { height: canvasHeight, pad, width, x, y };
  }

  function draw(focusIndex: number | null) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const setup = setupCanvas(canvas);
    if (!setup) return;
    const { ctx, height: canvasHeight, width } = setup;
    const metrics = buildMetrics(width, canvasHeight);
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const value = range.max - (range.max - range.min) * ratio;
      return {
        label: yFormatter(value),
        y: metrics.pad.t + (metrics.height - metrics.pad.t - metrics.pad.b) * ratio,
      };
    });
    const xLabelIndices = [0, Math.floor((data.length - 1) / 2), data.length - 1];
    const xLabels = xLabelIndices.map((index) => ({ label: String(data[index]?.label ?? ""), x: metrics.x(index) }));
    const sampledDotStep = Math.ceil(data.length / 8);

    ctx.clearRect(0, 0, width, canvasHeight);
    drawAxes(ctx, metrics, xLabels, yTicks);

    if (zeroCenter) {
      ctx.strokeStyle = cssVar("--cs-color-chart-zero-line");
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(metrics.pad.l, metrics.y(0));
      ctx.lineTo(width - metrics.pad.r, metrics.y(0));
      ctx.stroke();
    }

    series.forEach((serie) => {
      ctx.strokeStyle = cssVar(serie.color.replace(/^var\((.*)\)$/, "$1")) || serie.color;
      ctx.lineWidth = serie.width || 2;
      ctx.beginPath();
      data.forEach((item, index) => {
        const px = metrics.x(index);
        const py = metrics.y(Number(item[serie.key]));
        if (index === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.stroke();

      if (serie.dots) {
        ctx.fillStyle = ctx.strokeStyle;
        data.forEach((item, index) => {
          if (index % sampledDotStep === 0 || index === data.length - 1) {
            ctx.beginPath();
            ctx.arc(metrics.x(index), metrics.y(Number(item[serie.key])), 2.2, 0, Math.PI * 2);
            ctx.fill();
          }
        });
      }
    });

    if (focusIndex != null) {
      ctx.strokeStyle = cssVar("--cs-color-chart-crosshair-line");
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(metrics.x(focusIndex), metrics.pad.t);
      ctx.lineTo(metrics.x(focusIndex), metrics.height - metrics.pad.b);
      ctx.stroke();
      ctx.setLineDash([]);

      series.forEach((serie) => {
        ctx.fillStyle = cssVar(serie.color.replace(/^var\((.*)\)$/, "$1")) || serie.color;
        ctx.beginPath();
        ctx.arc(metrics.x(focusIndex), metrics.y(Number(data[focusIndex][serie.key])), 3, 0, Math.PI * 2);
        ctx.fill();
      });
    }
  }

  useEffect(() => {
    draw(hoverIndex);
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => draw(hoverIndex));
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [data, hoverIndex, range.max, range.min, series, yFormatter, zeroCenter]);

  function locateIndex(clientX: number) {
    const canvas = canvasRef.current;
    if (!canvas) return 0;
    const rect = canvas.getBoundingClientRect();
    const metrics = buildMetrics(rect.width, rect.height);
    const relativeX = clientX - rect.left;
    const raw = (relativeX - metrics.pad.l) / (metrics.width - metrics.pad.l - metrics.pad.r);
    return Math.max(0, Math.min(data.length - 1, Math.round(raw * (data.length - 1))));
  }

  const tooltipLeft =
    hoverIndex == null
      ? "8px"
      : (() => {
          const canvas = canvasRef.current;
          if (!canvas) return "8px";
          const rect = canvas.getBoundingClientRect();
          const metrics = buildMetrics(rect.width, rect.height);
          return `${Math.min(rect.width - 170, Math.max(8, metrics.x(hoverIndex) + 8))}px`;
        })();

  return (
    <div className={`chart-box ${height >= 230 ? "tall" : "compact"}`}>
      <canvas
        aria-label="历史趋势图"
        height={height}
        ref={canvasRef}
        onMouseLeave={() => setHoverIndex(null)}
        onMouseMove={(event) => setHoverIndex(locateIndex(event.clientX))}
      />
      {hover ? (
        <div className="chart-tooltip visible" style={{ left: tooltipLeft, top: 22 }}>
          <div className="tooltip-title">{hover.label}</div>
          {series.map((serie) => (
            <div className="tooltip-row" key={serie.key}>
              <span style={{ color: serie.color }}>{serie.name}</span>
              <span className={`num ${valueClassBySign ? signedClass(Number(hover[serie.key])) : ""}`}>
                {serie.valueFormatter?.(Number(hover[serie.key])) ?? hover[serie.key]}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
