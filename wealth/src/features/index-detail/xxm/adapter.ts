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
  assert(response.algorithmVersion === "xxm-direction-v0.1-h1" && /^[a-f0-9]{64}$/.test(response.specHash));
  assert(Array.isArray(response.bottomHistories));
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
    assert(point.pendingBottomHistoryId === null || (typeof point.pendingBottomHistoryId === "string" && point.pendingBottomHistoryId.length > 0));
    validateReference(point.activeReference, period);
    sourceByTime.set(key, point);
  }
  assert(response.meta.count === response.points.length);
  assert(response.meta.responseStart === (response.points[0]?.time ?? null) && response.meta.responseEnd === (response.points.at(-1)?.time ?? null));
  assert(response.dataStatus.asOf === response.source.computedThrough);
  if (response.dataStatus.status === "EMPTY") {
    assert(response.points.length === 0 && response.events.length === 0 && response.topHistories.length === 0 && response.bottomHistories.length === 0 && response.source.computedThrough === null);
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
  const bottomHistories = new Map(response.bottomHistories.map(history => [history.id, history]));
  assert(bottomHistories.size === response.bottomHistories.length);
  assert([...bottomHistories.values()].filter(h => h.status === "PENDING").length <= 1);
  for (const h of bottomHistories.values()) {
    assert(typeof h.id === "string" && h.id.length > 0 && !histories.has(h.id));
    assert(typeof h.structureEventId === "string" && h.structureEventId.length > 0);
    for (const stamp of [h.confirmedAt, h.originSegmentStart, h.priceLowAt, h.observedThrough]) timeKey(stamp, period);
    validateReference(h.originalReference, period);
    assert(h.originalReference && h.originalReference.endTime < h.originSegmentStart);
    assert(["dif_turn", "color_flip"].includes(h.confirmationRoute));
    assert(h.originSegmentStart <= h.priceLowAt && h.priceLowAt <= h.confirmedAt && h.confirmedAt <= h.observedThrough);
    assert(h.observedThrough <= response.source.computedThrough && Number.isFinite(h.priceLow) && h.priceLow > 0);
    assert(Number.isInteger(h.ageBars) && h.ageBars >= 0);
    assert(h.leftOriginAt === null || (typeof h.leftOriginAt === "string" && h.confirmedAt <= h.leftOriginAt && h.leftOriginAt <= h.observedThrough));
    if (h.leftOriginAt !== null) timeKey(h.leftOriginAt, period);
    if (h.status === "PENDING") assert(h.endedAt === null && h.endReason === null && h.observedThrough === response.source.computedThrough);
    else {
      assert(h.status === "ENDED" && typeof h.endedAt === "string" && h.confirmedAt < h.endedAt && h.endedAt === h.observedThrough);
      timeKey(h.endedAt, period);
      assert(["original_reference_break", "new_bottom_DULL", "new_bottom_STRUCTURE", "historical_price_break"].includes(h.endReason ?? ""));
      assert(h.endReason !== "historical_price_break" || h.leftOriginAt !== null);
    }
  }
  // Associations are validated for the complete API window, even before the
  // first loaded minute endpoint. A later ENDED record was pending at old points.
  for (const point of response.points) {
    for (const [id, records] of [[point.pendingTopHistoryId, histories], [point.pendingBottomHistoryId, bottomHistories]] as const) {
      if (id !== null) {
        const h = records.get(id);
        assert(h && h.confirmedAt <= point.time && (h.endedAt === null || point.time < h.endedAt));
      }
    }
  }
  const byTime: XxmViewModel["byTime"] = new Map();
  for (const [key, point] of sourceByTime) {
    if (!chartByTime.has(key)) continue; // date-level API window may start before a loaded minute endpoint
    assert(!point.pendingTopHistoryId || histories.has(point.pendingTopHistoryId));
    byTime.set(key, { point, events: [], histories: point.pendingTopHistoryId ? [histories.get(point.pendingTopHistoryId)!] : [],
      bottomHistories: point.pendingBottomHistoryId ? [bottomHistories.get(point.pendingBottomHistoryId)!] : [] });
  }
  for (const history of histories.values()) {
    if (history.endedAt) timeKey(history.endedAt, period);
    const endedDetail = history.endedAt ? byTime.get(timeKey(history.endedAt, period)) : undefined;
    if (endedDetail && !endedDetail.histories.some(existing => existing.id === history.id)) endedDetail.histories.push(history);
  }
  for (const h of bottomHistories.values()) {
    const detail = h.endedAt ? byTime.get(timeKey(h.endedAt, period)) : undefined;
    if (detail && !detail.bottomHistories.some(existing => existing.id === h.id)) detail.bottomHistories.push(h);
  }
  const eventIds = new Set<string>();
  const markers: XxmViewModel["markers"] = [];
  for (const event of response.events) {
    assert(typeof event.id === "string" && event.id.length > 0 && !eventIds.has(event.id)); eventIds.add(event.id);
    const key = timeKey(event.time, period); const source = sourceByTime.get(key);
    assert(source && ["TOP", "BOTTOM"].includes(event.direction));
    assert(["activation", "dif_turn", "dif_return", "color_flip", "dif_break", "dif_break_on_flip", "historical_price_break"].includes(event.route));
    assert(["NONE", "DULL", "STRUCTURE"].includes(event.fromState));
    assert(event.relatedBottomHistoryId === null || (typeof event.relatedBottomHistoryId === "string" && event.relatedBottomHistoryId.length > 0));
    const historical = event.type === "RESEARCH_HISTORICAL_WITHDRAWAL";
    assert(historical === (event.route === "historical_price_break"));
    const associated = historical || event.type === "STRUCTURE";
    const ownId = event.direction === "TOP" ? event.relatedTopHistoryId : event.relatedBottomHistoryId;
    const otherId = event.direction === "TOP" ? event.relatedBottomHistoryId : event.relatedTopHistoryId;
    assert(otherId === null);
    if (associated) {
      const h = event.direction === "TOP" ? histories.get(ownId!) : bottomHistories.get(ownId!);
      assert(ownId && h);
      if (historical) {
        assert(event.route === "historical_price_break" && h.status === "ENDED" && h.endReason === "historical_price_break" && h.endedAt === event.time);
        assert(event.eventReference && ["startTime", "endTime", "price", "dif"].every(k => h.originalReference[k as keyof XxmReference] === event.eventReference![k as keyof XxmReference]));
      } else {
        assert(h.confirmedAt === event.time && h.confirmationRoute === event.route);
        if (event.direction === "BOTTOM") assert(bottomHistories.get(ownId!)!.structureEventId === event.id);
      }
    } else assert(ownId === null);
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
    if (event.relatedBottomHistoryId && !detail.bottomHistories.some(h => h.id === event.relatedBottomHistoryId)) {
      detail.bottomHistories.push(bottomHistories.get(event.relatedBottomHistoryId)!);
    }
    markers.push({ time: chartByTime.get(key)!.time as Time, dif: source.dif, event });
  }
  const eventsById = new Map(response.events.map(e => [e.id, e]));
  for (const h of bottomHistories.values()) {
    const event = eventsById.get(h.structureEventId);
    if (event) assert(event.direction === "BOTTOM" && event.type === "STRUCTURE" && event.relatedBottomHistoryId === h.id
      && event.time === h.confirmedAt && event.route === h.confirmationRoute);
  }
  return { response, markers, byTime };
}

export function eventLabel(event: Pick<XxmEvent, "type" | "direction">): string {
  if (event.type === "RESEARCH_HISTORICAL_WITHDRAWAL") {
    return event.direction === "TOP" ? "顶结构消失" : "底部结构消失";
  }
  const side = event.direction === "TOP" ? "顶" : "底";
  if (event.type === "DULL") return `${side}钝化`;
  if (event.type === "STRUCTURE") return `${side}结构`;
  if (event.type === "CANCEL") return event.direction === "TOP" ? "顶消失" : "底取消";
  throw new Error("研究事件类型未识别");
}

export function eventMarkerLabel(event: Pick<XxmEvent, "type" | "direction">): string {
  if (event.type === "RESEARCH_HISTORICAL_WITHDRAWAL" && event.direction === "BOTTOM") return "消失";
  return eventLabel(event).replace(/^[顶底]/u, "");
}
