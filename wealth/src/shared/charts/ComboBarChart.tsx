import { useEffect, useRef, useState } from "react";
import type { MultiTrendPoint } from "../model/market";

interface ComboBarChartProps {
  data: MultiTrendPoint[];
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

export function ComboBarChart({ data }: ComboBarChartProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const hover = hoverIndex == null ? null : data[hoverIndex];
  const pad = { l: 48, r: 16, t: 18, b: 32 };
  const maxValue = Math.max(...data.flatMap((item) => [Number(item.up), Number(item.down)]), 1) * 1.2;

  function draw(focusIndex: number | null) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const setup = setupCanvas(canvas);
    if (!setup) return;
    const { ctx, height, width } = setup;
    const step = (width - pad.l - pad.r) / data.length;
    const y = (value: number) => height - pad.b - (value / maxValue) * (height - pad.t - pad.b);
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
      label: String(Math.round(maxValue * (1 - ratio))),
      y: pad.t + (height - pad.t - pad.b) * ratio,
    }));
    const xLabelIndices = [0, Math.floor((data.length - 1) / 2), data.length - 1];

    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = cssVar("--cs-color-chart-grid-primary");
    ctx.lineWidth = 1;
    ctx.font = `11px ${cssVar("--cs-font-family-number")}`;
    ctx.fillStyle = cssVar("--cs-color-chart-axis-label");
    ctx.textAlign = "right";
    yTicks.forEach((tick) => {
      ctx.beginPath();
      ctx.moveTo(pad.l, tick.y);
      ctx.lineTo(width - pad.r, tick.y);
      ctx.stroke();
      ctx.fillText(tick.label, pad.l - 7, tick.y + 4);
    });

    ctx.strokeStyle = cssVar("--cs-color-chart-axis-line");
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, height - pad.b);
    ctx.lineTo(width - pad.r, height - pad.b);
    ctx.stroke();

    ctx.textAlign = "center";
    xLabelIndices.forEach((index) => {
      ctx.fillText(String(data[index]?.label ?? ""), pad.l + step * index + step / 2, height - 8);
    });

    data.forEach((item, index) => {
      const x = pad.l + step * index + step * 0.18;
      const barWidth = Math.max(2, step * 0.24);
      ctx.fillStyle = cssVar("--cs-color-market-up");
      ctx.fillRect(x, y(Number(item.up)), barWidth, height - pad.b - y(Number(item.up)));
      ctx.fillStyle = cssVar("--cs-color-market-down");
      ctx.fillRect(x + barWidth + 2, y(Number(item.down)), barWidth, height - pad.b - y(Number(item.down)));
    });

    if (focusIndex != null) {
      const x = pad.l + step * focusIndex + step / 2;
      ctx.strokeStyle = cssVar("--cs-color-chart-crosshair-line");
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, height - pad.b);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  useEffect(() => {
    draw(hoverIndex);
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => draw(hoverIndex));
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [data, hoverIndex, maxValue]);

  function locateIndex(clientX: number) {
    const canvas = canvasRef.current;
    if (!canvas) return 0;
    const rect = canvas.getBoundingClientRect();
    const step = (rect.width - pad.l - pad.r) / data.length;
    const relativeX = clientX - rect.left;
    return Math.max(0, Math.min(data.length - 1, Math.floor((relativeX - pad.l) / step)));
  }

  const tooltipLeft =
    hoverIndex == null
      ? "8px"
      : (() => {
          const rect = canvasRef.current?.getBoundingClientRect();
          if (!rect) return "8px";
          const step = (rect.width - pad.l - pad.r) / data.length;
          return `${Math.min(rect.width - 170, Math.max(8, pad.l + step * hoverIndex + step / 2 + 8))}px`;
        })();

  return (
    <div className="chart-box compact">
      <canvas
        aria-label="历史涨跌停组合柱图"
        ref={canvasRef}
        onMouseLeave={() => setHoverIndex(null)}
        onMouseMove={(event) => setHoverIndex(locateIndex(event.clientX))}
      />
      {hover ? (
        <div className="chart-tooltip visible" style={{ left: tooltipLeft, top: 22 }}>
          <div className="tooltip-title">{hover.label}</div>
          <div className="tooltip-row">
            <span className="up">涨停数</span>
            <span className="num up">{hover.up}</span>
          </div>
          <div className="tooltip-row">
            <span className="down">跌停数</span>
            <span className="num down">{hover.down}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
