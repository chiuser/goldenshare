import { XXM_ALGORITHM_VERSION, XXM_SPEC_HASH } from "./types";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { GoldXxmResponse, XxmEvent, XxmPeriod, XxmHistoryResponse, XxmViewModel } from "./types";
export function assert(value: unknown): asserts value { if (!value)
    throw new Error("顶底识别数据与合同不一致"); }
export const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
export const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
export function keys(v: unknown, expected: string): asserts v is Record<string, unknown> {
    const names = expected.split(" ");
    assert(record(v) && Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k)));
}
export function timeKey(stamp: unknown, period: XxmPeriod): string {
    assert(typeof stamp === "string");
    assert(/^\d{4}-\d{2}-\d{2}$/.test(stamp.slice(0, 10)) && new Date(stamp.slice(0, 10) + "T00:00:00Z").toISOString().slice(0, 10) === stamp.slice(0, 10));
    if (period === "day") {
        assert(stamp.length === 10);
        return stamp;
    }
    const endpoints = {
        m30: ["10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"],
        m60: ["10:30", "11:30", "14:00", "15:00"],
        m90: ["11:00", "14:00", "15:00"],
        m120: ["11:30", "15:00"],
    }[period];
    assert(endpoints);
    assert(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+08:00$/.test(stamp) && endpoints.includes(stamp.slice(11, 16)));
    const value = Date.parse(stamp) / 1000;
    assert(Number.isFinite(value));
    return String(value);
}
export type XxmDecodeOptions = { tsCode: string; period: XxmPeriod; check: () => void };

export function decodeXxmResponse(raw: unknown, { tsCode, period, check }: XxmDecodeOptions): GoldXxmResponse {
    check();
    keys(raw, "tsCode period algorithmVersion specHash points events meta dataStatus");
    assert(raw.tsCode === tsCode && raw.period === period && raw.algorithmVersion === XXM_ALGORITHM_VERSION && raw.specHash === XXM_SPEC_HASH);
    const { meta, dataStatus, points, events } = raw;
    keys(meta, "count responseStart responseEnd");
    keys(dataStatus, "status message asOf");
    assert(Array.isArray(points) && Array.isArray(events));
    let previous = "";
    const times = new Set<string>();
    for (const point of points) {
        check();
        keys(point, "time close dif dea hist ordinaryState ordinaryDirection");
        timeKey(point.time, period);
        assert(typeof point.time === "string" && point.time > previous && finite(point.close) && point.close > 0
            && [point.dif, point.dea, point.hist].every(finite) && point.ordinaryState === null && point.ordinaryDirection === null);
        previous = point.time;
        times.add(point.time);
    }
    const through = points.at(-1)?.time ?? null;
    assert(meta.count === points.length && meta.responseStart === (points[0]?.time ?? null) && meta.responseEnd === through);
    assert(["READY", "DELAYED", "EMPTY"].includes(String(dataStatus.status)) && dataStatus.asOf === through
        && (dataStatus.message === null || typeof dataStatus.message === "string") && (dataStatus.status === "EMPTY") === !points.length);
    const ids = new Set<string>();
    previous = "";
    for (const event of events) {
        check();
        keys(event, "id time type direction displayOnChart");
        assert(typeof event.id === "string" && !!event.id && !ids.has(event.id) && typeof event.time === "string"
            && times.has(event.time) && event.time >= previous && ["DULL", "STRUCTURE", "CANCEL"].includes(String(event.type))
            && ["TOP", "BOTTOM"].includes(String(event.direction)) && typeof event.displayOnChart === "boolean");
        ids.add(event.id);
        previous = event.time;
    }
    return raw as unknown as GoldXxmResponse;
}

export function buildXxmViewModel(response: XxmHistoryResponse, points: DetailChartPoint[], period: XxmPeriod,
    tsCode: string, _indicatorVersion: number | null = null, check: () => void = () => {}): XxmViewModel {
    assert(response.period === period && response.tsCode === tsCode);
    const source = new Map(response.points.map(point => [timeKey(point.time, period), point]));
    const chart = new Map(points.map(point => [String(point.time), point]));
    const start = response.meta.responseStart && timeKey(response.meta.responseStart, period);
    const end = response.meta.responseEnd && timeKey(response.meta.responseEnd, period);
    if (start !== null && end !== null) {
        for (const [key, point] of chart) {
            check();
            if (period === "day" ? start <= key && key <= end : Number(start) <= Number(key) && Number(key) <= Number(end)) {
                assert(point.close === source.get(key)?.close && source.has(key));
            }
        }
    }
    const byTime: XxmViewModel["byTime"] = new Map();
    const markers: XxmViewModel["markers"] = [];
    for (const [key, point] of source) {
        check();
        const chartPoint = chart.get(key);
        if (!chartPoint) continue;
        const events = response.events.filter(event => event.time === point.time);
        const displayEvents = events.filter(event => event.displayOnChart);
        byTime.set(key, { point, events, displayEvents, debugDetail: null });
        for (const event of displayEvents) markers.push({ time: chartPoint.time, dif: point.dif, event });
    }
    return { response, markers, byTime };
}

export function eventLabel(event: Pick<XxmEvent, "type" | "direction">): string {
    if (event.type === "CANCEL")
        return event.direction === "TOP" ? "顶消失" : "底取消";
    const side = event.direction === "TOP" ? "顶" : "底";
    return side + ({ DULL: "钝化", STRUCTURE: "结构", CANCEL: "消失" }[event.type]);
}
export function eventMarkerLabel(event: Pick<XxmEvent, "type" | "direction">): string { return eventLabel(event).replace(/^[顶底]/u, ""); }
