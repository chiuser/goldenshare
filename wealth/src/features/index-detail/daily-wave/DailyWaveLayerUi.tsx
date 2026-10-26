import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { DailyWaveReadyResponse, DailyWaveReviewState } from "./types";
import type { DailyWaveEndpointFact, DailyWavePresentation, DailyWaveSegment } from "./presentation";
import waveUp from "./assets/wave-up.svg";
import waveDown from "./assets/wave-down.svg";
import "./daily-wave.css";

interface Props { review: DailyWaveReviewState; presentation: DailyWavePresentation | null; }

export function DailyWaveLayerUi({ review, presentation }: Props) {
  const [open, setOpen] = useState(false);
  const [availableHeight, setAvailableHeight] = useState(240);
  const [panelPosition, setPanelPosition] = useState({ width: 640, left: 0 });
  const toggleRef = useRef<HTMLButtonElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const response = review.response;
  useEffect(() => { setOpen(false); }, [review.enabled, review.dataKey]);
  const measurePanel = useCallback(() => {
    const container = containerRef.current;
    const node = container?.closest(".detail-chart-workspace");
    if (!node || !container) return;
    const bounds = node.getBoundingClientRect();
    const controlBounds = container.getBoundingClientRect();
    const anchor = container.querySelector(".daily-wave-state")?.getBoundingClientRect().left ?? controlBounds.left;
    const width = Math.min(640, Math.max(0, bounds.width - 16));
    const left = Math.max(bounds.left + 8, Math.min(anchor, bounds.right - 8 - width)) - controlBounds.left;
    setAvailableHeight(Math.max(0, Math.min(240, controlBounds.top - 8 - bounds.top)));
    setPanelPosition((previous) => previous.width === width && previous.left === left ? previous : { width, left });
  }, []);
  // Sibling indicator buttons can move this anchor without resizing the workspace.
  useLayoutEffect(() => { if (open) measurePanel(); });
  useEffect(() => {
    if (!open || !containerRef.current) return;
    const node = containerRef.current.closest(".detail-chart-workspace");
    const observer = new ResizeObserver(measurePanel);
    if (node) observer.observe(node);
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [open, measurePanel]);
  if (!review.supported) return null;
  const closePanel = () => { setOpen(false); toggleRef.current?.focus(); };
  const count = presentation?.explanations.length ?? 0;
  const canExplain = response?.status === "ready";

  return <div className="daily-wave-controls" ref={containerRef} onKeyDown={(event) => {
    if (event.key === "Escape" && open) { event.stopPropagation(); closePanel(); }
  }}>
    <button aria-pressed={review.enabled} className={`detail-chart-indicator-tab ${review.enabled ? "active" : ""}`}
      onClick={review.toggle} type="button">波段核对</button>
    {review.enabled ? <>
      <span className="daily-wave-state" role="status">
        {review.phase === "loading" ? "正在计算波段划分…" : null}
        {review.phase === "empty" ? `截至${response?.requestedEnd ?? "2026-10-21"}暂无可用日线行情` : null}
        {review.phase === "ready" && response?.status === "ready"
          ? `截至${response.observationEnd} · 待核对${count}段` : null}
        {review.phase === "mismatch" ? "行情与研究结果不一致，暂不显示波段" : null}
        {review.phase === "error" || review.phase === "timeout" ? "波段划分计算失败" : null}
      </span>
      {review.phase === "error" || review.phase === "timeout" || review.phase === "mismatch"
        ? <button className="detail-chart-indicator-tab" onClick={review.retry} type="button">重试</button> : null}
      {canExplain ? <button aria-controls={panelId} aria-expanded={open} className="detail-chart-indicator-tab daily-wave-explain-button"
        onClick={() => setOpen((value) => !value)} ref={toggleRef} type="button">{open ? "收起说明" : "查看说明"}</button> : null}
      {open && canExplain && response?.status === "ready" ? <section aria-label="波段核对说明" className="daily-wave-explanation-panel"
        id={panelId} style={{ maxHeight: availableHeight, width: panelPosition.width, maxWidth: panelPosition.width, left: panelPosition.left }}>
        <div className="daily-wave-explanation-title"><strong>待核对说明 · {count}段</strong>
          <button className="detail-chart-indicator-tab" onClick={closePanel} type="button">收起</button></div>
        <div className="daily-wave-explanation-scroll" tabIndex={0}>
          <p className="daily-wave-range num">实际范围 {response.observationStart} — {response.observationEnd} · {response.sourcePoints.length}根日线</p>
          {review.phase === "mismatch" ? <p className="daily-wave-source-message">{review.errorMessage || "行情与研究结果不一致，暂不显示波段。"}</p> : null}
          {presentation?.spaceUnavailableEndpointCount ? <p>有{presentation.spaceUnavailableEndpointCount}个起止K线空间不足，暂未绘制；日期与计算结果保留。</p> : null}
          {presentation && presentation.unavailableEndpointCount > presentation.spaceUnavailableEndpointCount
            ? <p>有{presentation.unavailableEndpointCount - presentation.spaceUnavailableEndpointCount}个起止K线暂时无法定位，计算结果保留。</p> : null}
          {presentation?.explanations.map(({ segment, colorStart, colorEnd, reasons }) => <article className="daily-wave-explanation-row" key={segment.id}>
            <strong className={segment.direction === "UP" ? "up" : "down"}>{segment.direction === "UP" ? "上涨" : "下降"} · {colorStart} — {colorEnd}</strong>
            <div className="daily-wave-id num">编号 {segment.id}</div>
            <div>起始K线：{endpointLabel(segment.start)} · 终止K线：{endpointLabel(segment.end)}{segment.generated && !segment.isEnded ? "（尚未确认）" : ""}</div>
            {reasons.map((reason) => <div key={reason}>{reason}</div>)}
          </article>)}
        </div>
      </section> : null}
    </> : null}
  </div>;
}

export function DailyWaveLegend({ response }: { response: DailyWaveReadyResponse }) {
  return <span aria-label="波段起止图例" className="daily-wave-legend">
    <span title="上涨开始或下降结束：红色上三角，位于K线下方。"><img alt="" height={6} src={waveUp} width={8} />上涨开始 / 下降结束</span>
    <span title="上涨结束或下降开始：绿色下三角，位于K线上方。"><img alt="" height={6} src={waveDown} width={8} />上涨结束 / 下降开始</span>
    <span className="num">研究截至{response.observationEnd}</span>
  </span>;
}

export function DailyWaveResearchDetails({ response, facts }: { response: DailyWaveReadyResponse; facts: readonly DailyWaveEndpointFact[] }) {
  if (!facts.length) return null;
  return <div aria-label="波段起止详情" className="daily-wave-tooltip-details" data-detail-chart-interactive="true" tabIndex={0}
    onPointerDown={(event) => event.stopPropagation()} onMouseDown={(event) => event.stopPropagation()} onWheel={(event) => event.stopPropagation()}>
    {facts.map(({ segment, role }) => {
      const endpoint = segment[role]!;
      const extrema = segment.extrema;
      const turns = [...response.turns, ...response.pendingTurns].filter((turn) => segment.difTurnIds.includes(turn.id));
      return <section key={`${segment.id}|${role}`}>
        <strong className={segment.direction === "UP" ? "up" : "down"}>{segment.direction === "UP" ? "上涨" : "下降"} · {role === "start" ? "起始" : "终止"}{role === "end" && !segment.isEnded ? "（暂定）" : ""}</strong>
        <div className="daily-wave-id num">{segment.id}</div>
        <div className="num">{endpoint.date} 15:00 · 收盘{endpoint.close}</div>
        {endpoint.tiedDates.length > 1 ? <div>并列日期：{endpoint.tiedDates.join("、")}</div> : null}
        <div>起始K线：{endpointLabel(segment.start)}；终止K线：{endpointLabel(segment.end)}</div>
        <div>起点确认：{timeLabel(segment.startKnownAt)}；结束确认：{timeLabel(segment.endKnownAt)}</div>
        {extrema ? <>{([
          ["最高收盘", extrema.maxClose], ["最低收盘", extrema.minClose],
          ["最高DIF", extrema.maxDif], ["最低DIF", extrema.minDif],
          ["最长红柱", extrema.longestRed], ["最长绿柱", extrema.longestGreen],
        ] as const).map(([label, extreme]) => <div className="num" key={label}>{label}：{extreme ? `${extreme.value}（${extreme.dates.join("、")}）` : "未出现"}</div>)}</> : null}
        {turns.map((turn) => <div className="num" key={turn.id}>DIF{turn.kind === "MAX" ? "峰" : turn.kind === "MIN" ? "谷" : "待确认"} {turn.value} · {turn.plateauDates.join("、")} · 确认{timeLabel(turn.confirmedAt)}</div>)}
        {segment.issues.map((issue, index) => <div key={index}>{issue.message}{issue.dates.length ? `（${issue.dates.join("、")}）` : ""}</div>)}
      </section>;
    })}
  </div>;
}

function endpointLabel(endpoint: DailyWaveSegment["start"]): string {
  return endpoint ? `${endpoint.date} / ${endpoint.close}` : "未确定";
}
function timeLabel(value: string | null): string { return value ? value.replace("T", " ").replace("+08:00", "") : "未确认"; }
