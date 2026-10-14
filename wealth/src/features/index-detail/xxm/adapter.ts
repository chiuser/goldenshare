import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { Time } from "lightweight-charts";
import type { XxmEvent, XxmPeriod, XxmReference, XxmResponse, XxmViewModel } from "./types";

function assert(condition: unknown): asserts condition {
  if (!condition) throw new Error("研究指标与当前价格或指标数据不一致");
}
function timeKey(time: string, period: XxmPeriod): string {
  if (period === "day") {
    assert(/^\d{4}-\d{2}-\d{2}$/.test(time) && new Date(`${time}T00:00:00Z`).toISOString().slice(0, 10) === time);
    return time;
  }
  assert(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$/.test(time));
  const value = Date.parse(time) / 1000;
  assert(Number.isFinite(value));
  return String(value);
}
function validateReference(reference: XxmReference | null, period: XxmPeriod) {
  if (!reference) return;
  assert(Number.isFinite(reference.price) && reference.price > 0 && Number.isFinite(reference.dif));
  timeKey(reference.startTime, period); timeKey(reference.endTime, period);
  assert(reference.startTime <= reference.endTime);
}

export function buildXxmViewModel(response: XxmResponse, points: DetailChartPoint[], period: XxmPeriod, tsCode: string,
  indicatorVersion: number | null = null): XxmViewModel {
  assert(response.tsCode === tsCode && tsCode === "000001.SH" && response.period === period);
  assert(response.algorithmVersion === "xxm-direction-v0.1" && /^[a-f0-9]{64}$/.test(response.specHash));
  assert(/^[a-f0-9]{64}$/.test(response.source.inputId));
  assert(response.source.kind === (period === "day" ? "daily_factor" : "minute_gold"));
  assert(response.source.indicatorVersion === (period === "day" ? null : indicatorVersion));
  assert(["READY", "DELAYED", "EMPTY"].includes(response.dataStatus.status));
  const sourceByTime = new Map<string, typeof response.points[number]>();
  let previous = "";
  for (const point of response.points) {
    const key = timeKey(point.time, period);
    assert(point.time > previous && !sourceByTime.has(key)); previous = point.time;
    assert([point.close, point.dif, point.dea, point.hist].every(Number.isFinite) && point.close > 0);
    assert(["NONE", "DULL", "STRUCTURE"].includes(point.ordinaryState));
    assert(point.ordinaryState === "NONE"
      ? point.ordinaryDirection === null && point.activeReference === null
      : ["TOP", "BOTTOM"].includes(point.ordinaryDirection ?? "") && point.activeReference !== null);
    validateReference(point.activeReference, period);
    sourceByTime.set(key, point);
  }
  assert(response.meta.count === response.points.length);
  assert(response.meta.responseStart === (response.points[0]?.time ?? null) && response.meta.responseEnd === (response.points.at(-1)?.time ?? null));
  assert(response.dataStatus.asOf === response.source.computedThrough);
  if (response.dataStatus.status === "EMPTY") {
    assert(response.points.length === 0 && response.events.length === 0 && response.topHistories.length === 0 && response.source.computedThrough === null);
    return { response, markers: [], byTime: new Map() };
  }
  assert(response.source.computedThrough !== null && response.source.startTime !== null);
  timeKey(response.source.computedThrough, period); timeKey(response.source.startTime, period);
  assert(response.points.every(point => point.time >= response.source.startTime! && point.time <= response.source.computedThrough!));
  const chartByTime = new Map(points.map(point => [String(point.time), point]));
  const through = timeKey(response.source.computedThrough, period);
  const comparable = (key: string) => period === "day" ? key : Number(key);
  for (const chart of points) {
    if (comparable(String(chart.time)) > comparable(through)) continue;
    const source = sourceByTime.get(String(chart.time));
    assert(source && [chart.close, chart.dif, chart.dea, chart.macd].every(Number.isFinite));
    assert(chart.close === source.close && chart.dif === source.dif && chart.dea === source.dea && chart.macd === source.hist);
  }
  const histories = new Map(response.topHistories.map(history => [history.id, history]));
  assert(histories.size === response.topHistories.length);
  for (const history of histories.values()) {
    timeKey(history.confirmedAt, period); timeKey(history.pricePeakAt, period); timeKey(history.observedThrough, period);
    validateReference(history.originalReference, period);
    assert(history.confirmedAt <= history.observedThrough && history.observedThrough <= response.source.computedThrough);
    assert(Number.isFinite(history.pricePeak) && Number.isInteger(history.ageBars) && history.ageBars >= 0);
    assert(history.status === "PENDING" ? history.endedAt === null && history.endReason === null
      : history.status === "ENDED" && history.endedAt !== null && history.endReason !== null && history.endedAt <= response.source.computedThrough);
  }
  const byTime: XxmViewModel["byTime"] = new Map();
  for (const [key, point] of sourceByTime) {
    if (!chartByTime.has(key)) continue; // date-level API window may start before a loaded minute endpoint
    assert(!point.pendingTopHistoryId || histories.has(point.pendingTopHistoryId));
    byTime.set(key, { point, events: [], histories: point.pendingTopHistoryId ? [histories.get(point.pendingTopHistoryId)!] : [] });
  }
  for (const history of histories.values()) {
    if (history.endedAt) timeKey(history.endedAt, period);
    const endedDetail = history.endedAt ? byTime.get(timeKey(history.endedAt, period)) : undefined;
    if (endedDetail && !endedDetail.histories.some(existing => existing.id === history.id)) endedDetail.histories.push(history);
  }
  const eventIds = new Set<string>();
  const markers: XxmViewModel["markers"] = [];
  for (const event of response.events) {
    assert(!eventIds.has(event.id)); eventIds.add(event.id);
    const key = timeKey(event.time, period); const source = sourceByTime.get(key);
    assert(source && ["TOP", "BOTTOM"].includes(event.direction));
    assert(["activation", "dif_turn", "dif_return", "color_flip", "dif_break", "dif_break_on_flip", "historical_price_break"].includes(event.route));
    assert(["NONE", "DULL", "STRUCTURE"].includes(event.fromState));
    assert(event.type !== "RESEARCH_HISTORICAL_WITHDRAWAL" || (event.relatedTopHistoryId !== null && event.route === "historical_price_break"));
    eventLabel(event);
    validateReference(event.eventReference, period);
    assert(!event.relatedTopHistoryId || histories.has(event.relatedTopHistoryId));
    const detail = byTime.get(key);
    if (!detail) {
      const first = points[0]; assert(first && comparable(key) < comparable(String(first.time)));
      continue;
    }
    detail.events.push(event);
    if (event.relatedTopHistoryId && !detail.histories.some(history => history.id === event.relatedTopHistoryId)) {
      detail.histories.push(histories.get(event.relatedTopHistoryId)!);
    }
    markers.push({ time: chartByTime.get(key)!.time as Time, dif: source.dif, event });
  }
  return { response, markers, byTime };
}

export function eventLabel(event: Pick<XxmEvent, "type" | "direction">): string {
  if (event.type === "RESEARCH_HISTORICAL_WITHDRAWAL") {
    assert(event.direction === "TOP"); return "顶结构消失";
  }
  const side = event.direction === "TOP" ? "顶" : "底";
  if (event.type === "DULL") return `${side}钝化`;
  if (event.type === "STRUCTURE") return `${side}结构`;
  if (event.type === "CANCEL") return event.direction === "TOP" ? "顶消失" : "底取消";
  throw new Error("研究事件类型未识别");
}

export function eventMarkerLabel(event: Pick<XxmEvent, "type" | "direction">): string {
  return eventLabel(event).replace(/^[顶底]/u, "");
}
