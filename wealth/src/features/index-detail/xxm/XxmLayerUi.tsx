import { Fragment } from "react";
import { eventLabel } from "./adapter";
import type { XxmBottomHistory, XxmHistory, XxmLayerState, XxmReference } from "./types";
import "./xxm-layer.css";

export function XxmLayerStatus({ layer, onRetry }: { layer: XxmLayerState; onRetry: () => void }) {
  if (layer.phase === "unsupported") return null;
  const status = layer.phase === "loading" ? "正在加载研究指标" : layer.phase === "empty" ? "研究指标暂无数据"
    : layer.phase === "error" ? "研究指标加载失败" : layer.phase === "delayed" ? layer.data?.response.dataStatus.message : "";
  return <span className={`xxm-layer-status ${layer.phase}`} role="status" title={layer.errorMessage || status || undefined}>
    <span>徐小明 V0.1 · 研究</span>{status ? <span className="xxm-status-message">{status}</span> : null}
    {layer.phase === "error" ? <button aria-label="重试研究指标" onClick={onRetry} type="button">重试</button> : null}
  </span>;
}

const timeText = (value: string) => value.replace("T", " ").replace(":00+08:00", "");
function referenceText(reference: XxmReference) {
  return `${timeText(reference.startTime)} → ${timeText(reference.endTime)}；价 ${reference.price}，DIF ${reference.dif}`;
}
function historyStatus(history: XxmHistory): string {
  if (history.status === "PENDING") return "仍在跟踪";
  const reason = { original_reference_break: "原 DIF 目标突破", new_top_DULL: "新顶部钝化", new_top_STRUCTURE: "新顶部结构", historical_price_break: "价格突破" };
  return `已结束 · ${history.endReason ? reason[history.endReason] : ""}`;
}

function bottomHistoryStatus(history: XxmBottomHistory): string {
  if (history.status === "PENDING") return "仍在跟踪";
  const reason = { original_reference_break: "原DIF参照失效", new_bottom_DULL: "新底部钝化接替",
    new_bottom_STRUCTURE: "新底部结构接替", historical_price_break: "收盘跌破原低点" };
  return `已结束 · ${history.endReason ? reason[history.endReason] : ""}`;
}

export function XxmResearchDetails({ layer, time }: { layer: XxmLayerState; time: string }) {
  const detail = layer.data?.byTime.get(time);
  if (!detail) return null;
  const { point, events, histories, bottomHistories } = detail;
  const state = point.ordinaryState === "NONE" ? "无钝化或结构" : `${point.ordinaryDirection === "TOP" ? "顶" : "底"}${point.ordinaryState === "DULL" ? "钝化" : "结构"}`;
  return <div className="xxm-tooltip" aria-label="徐小明研究指标详情">
    <div className="xxm-tooltip-title">徐小明 V0.1 · 研究</div>
    <Row label="普通状态" value={state} />
    <Row label="当柱事件" value={events.length ? events.map(eventLabel).join(" / ") : "无新事件"} />
    <Row label="收盘价" value={String(point.close)} />
    <Row label="DIF / DEA" value={`${point.dif} / ${point.dea}`} />
    <Row label="MACD 柱值" value={String(point.hist)} />
    {point.activeReference ? <Row label="活动参照" value={referenceText(point.activeReference)} /> : null}
    {events.map(event => <Fragment key={event.id}>
      {event.eventReference ? <Row label={`${eventLabel(event)}参照`} value={referenceText(event.eventReference)} /> : null}
    </Fragment>)}
    {histories.map(history => <Fragment key={history.id}>
      <Row label="关联顶结构" value={timeText(history.confirmedAt)} />
      <Row label="保存价格峰" value={`${history.pricePeak} · ${timeText(history.pricePeakAt)}`} />
      <Row label="历史跟踪" value={historyStatus(history)} />
      {history.endedAt ? <Row label="结束时间" value={timeText(history.endedAt)} /> : null}
      <Row label="记录截至" value={`${timeText(history.observedThrough)} · ${history.ageBars} 根`} />
    </Fragment>)}
    {bottomHistories.map(history => <Fragment key={history.id}>
      <Row label="关联底部结构" value={timeText(history.confirmedAt)} />
      <Row label="保存收盘低点" value={`${history.priceLow} · ${timeText(history.priceLowAt)}`} />
      {history.leftOriginAt ? <Row label="离开原负柱段" value={timeText(history.leftOriginAt)} /> : null}
      <Row label="底部历史跟踪" value={bottomHistoryStatus(history)} />
      {history.endedAt ? <Row label="结束时间" value={timeText(history.endedAt)} /> : null}
      <Row label="记录截至" value={`${timeText(history.observedThrough)} · ${history.ageBars} 根`} />
    </Fragment>)}
    <div className="xxm-tooltip-note">研究判断，历史寿命尚未验证</div>
  </div>;
}
function Row({ label, value }: { label: string; value: string }) {
  return <div className="xxm-tooltip-row"><span>{label}</span><b className="num" title={value}>{value}</b></div>;
}
