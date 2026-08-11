import { useLayoutEffect, useMemo, useRef } from "react";

import type { IndexDetailWeightsResponseDto } from "../api/indexDetailApiTypes";

const ROW_HEIGHT = 40;
const VIEWPORT_HEIGHT = 400;
const OVERSCAN = 2;

interface IndexWeightsTabProps {
  data: IndexDetailWeightsResponseDto | null;
  errorMessage: string;
  onRetry: () => void;
  onScrollTopChange: (value: number) => void;
  phase: "idle" | "loading" | "ready" | "empty" | "error";
  scrollTop: number;
}

export function IndexWeightsTab({ data, errorMessage, onRetry, onScrollTopChange, phase, scrollTop }: IndexWeightsTabProps) {
  const rows = data?.rows ?? [];
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const visible = useMemo(() => {
    const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
    const count = Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT) + OVERSCAN * 2;
    return { rows: rows.slice(start, start + count), start };
  }, [rows, scrollTop]);

  useLayoutEffect(() => {
    if (viewportRef.current && viewportRef.current.scrollTop !== scrollTop) {
      viewportRef.current.scrollTop = scrollTop;
    }
  }, [scrollTop]);

  return (
    <section className="index-weights-module" aria-label="权重股贡献">
      <div className="index-tab-section-title"><strong>权重股贡献</strong><span>{data?.weightTradeDate ?? "--"}</span></div>
      <div className="index-weight-header" role="row"><span>序号 / 成分股</span><span>权重</span><span>贡献点</span></div>
      {phase === "loading" || phase === "idle" ? <IndexWeightState text="正在加载权重股…" /> : null}
      {phase === "error" ? <div className="index-weight-state"><span>{errorMessage}</span><button type="button" onClick={onRetry}>重试</button></div> : null}
      {phase === "empty" ? <IndexWeightState text="暂无权重股数据" /> : null}
      {phase === "ready" ? (
        <div
          aria-label="权重股滚动列表"
          className="index-weight-viewport"
          data-total-rows={rows.length}
          onScroll={(event) => onScrollTopChange(event.currentTarget.scrollTop)}
          ref={viewportRef}
          style={{ height: VIEWPORT_HEIGHT }}
          tabIndex={0}
        >
          <div className="index-weight-spacer" style={{ height: rows.length * ROW_HEIGHT }}>
            {visible.rows.map((row, offset) => {
              const index = visible.start + offset;
              return (
                <div className="index-weight-row" key={row.conCode} role="row" style={{ height: ROW_HEIGHT, transform: `translateY(${index * ROW_HEIGHT}px)` }}>
                  <span className="index-weight-name"><em>{index + 1}</em><span><b>{row.name ?? row.conCode}</b><small>{row.conCode}</small></span></span>
                  <span>{formatPercent(row.weight)}</span>
                  <span className={row.direction === "UP" ? "up" : row.direction === "DOWN" ? "down" : "secondary"}>{formatContribution(row.contributionPoint)}</span>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
      <p className="index-weight-note">{data?.note ?? "基于最新月度权重估算，非指数公司官方归因"}</p>
    </section>
  );
}

function IndexWeightState({ text }: { text: string }) { return <div className="index-weight-state"><span>{text}</span></div>; }
function formatPercent(value: number): string { return Number.isFinite(value) ? `${value.toFixed(2)}%` : "--"; }
function formatContribution(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}
