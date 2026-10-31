import { XXM_ALGORITHM_VERSION, XXM_SPEC_HASH } from "./types";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { DecodeXxmDebug } from "../debug/types";
import type { XxmEvent, XxmPeriod, XxmResponse, XxmDebugResponse, XxmViewModel } from "./types";
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
    const endpoints = period === "m60" ? ["10:30", "11:30", "14:00", "15:00"] : period === "m90" ? ["11:00", "14:00", "15:00"] : ["11:30", "15:00"];
    assert(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+08:00$/.test(stamp) && endpoints.includes(stamp.slice(11, 16)));
    const value = Date.parse(stamp) / 1000;
    assert(Number.isFinite(value));
    return String(value);
}
export function decodeXxmResponse(raw: unknown, options: {
    tsCode: string;
    period: XxmPeriod;
    debug: 0 | 1;
    decodeDebug?: DecodeXxmDebug;
    check: () => void;
}): XxmResponse | XxmDebugResponse {
    const { period, check } = options;
    check();
    const names = "tsCode period algorithmVersion specHash source points events meta dataStatus";
    keys(raw, names + (options.debug ? " debug" : ""));
    assert(raw.tsCode === options.tsCode && raw.tsCode === "000001.SH" && raw.period === period && raw.algorithmVersion === XXM_ALGORITHM_VERSION && raw.specHash === XXM_SPEC_HASH);
    keys(raw.source, "kind startTime computedThrough initialHistoryIncomplete indicatorVersion");
    keys(raw.meta, "count responseStart responseEnd");
    keys(raw.dataStatus, "status message asOf");
    const source = raw.source, meta = raw.meta, status = raw.dataStatus;
    assert(source.kind === (period === "day" ? "daily_factor" : "minute_gold") && typeof source.initialHistoryIncomplete === "boolean" && (period === "day" ? source.indicatorVersion === null : Number.isInteger(source.indicatorVersion)));
    assert(["READY", "DELAYED", "EMPTY"].includes(String(status.status)) && (status.message === null || typeof status.message === "string") && status.asOf === source.computedThrough);
    assert(Array.isArray(raw.points) && Array.isArray(raw.events));
    let previous = "";
    const times = new Set<string>();
    for (const [i, p] of raw.points.entries()) {
        if (i % 128 === 0)
            check();
        keys(p, "time close dif dea hist ordinaryState ordinaryDirection");
        timeKey(p.time, period);
        assert(typeof p.time === "string" && p.time > previous && finite(p.close) && p.close > 0 && [p.dif, p.dea, p.hist].every(finite));
        assert(["NONE", "DULL", "STRUCTURE"].includes(String(p.ordinaryState)) && (p.ordinaryState === "NONE" ? p.ordinaryDirection === null : ["TOP", "BOTTOM"].includes(String(p.ordinaryDirection))));
        previous = p.time;
        times.add(p.time);
    }
    assert(Number.isInteger(meta.count) && meta.count === raw.points.length && meta.responseStart === (raw.points[0]?.time ?? null) && meta.responseEnd === (raw.points.at(-1)?.time ?? null));
    if (status.status === "EMPTY")
        assert(raw.points.length === 0 && raw.events.length === 0 && source.startTime === null && source.computedThrough === null);
    else {
        timeKey(source.startTime, period);
        timeKey(source.computedThrough, period);
        assert(String(source.startTime) <= String(source.computedThrough));
        for (const p of raw.points)
            assert(p.time >= String(source.startTime) && p.time <= String(source.computedThrough));
    }
    const ids = new Set<string>();
    previous = "";
    for (const e of raw.events) {
        check();
        keys(e, "id time direction type displayOnChart");
        assert(typeof e.id === "string" && !!e.id && !ids.has(e.id) && typeof e.time === "string" && times.has(e.time) && e.time >= previous && ["DULL", "STRUCTURE", "CANCEL"].includes(String(e.type)) && ["TOP", "BOTTOM"].includes(String(e.direction)) && typeof e.displayOnChart === "boolean");
        if (!e.displayOnChart)
            assert(e.type === "CANCEL" && raw.events.some(v => record(v) && v.time === e.time && v.direction === e.direction && v.type === "DULL" && v.displayOnChart === true));
        ids.add(e.id);
        previous = e.time;
    }
    const response = Object.fromEntries(names.split(" ").map(k => [k, raw[k]])) as unknown as XxmResponse;
    if (options.debug) {
        assert(options.decodeDebug);
        const debug = options.decodeDebug(raw.debug, { response, tsCode: options.tsCode, period, check });
        check();
        return { ...response, debug };
    }
    check();
    return response;
}
export function buildXxmViewModel(response: XxmResponse | XxmDebugResponse, points: DetailChartPoint[], period: XxmPeriod, tsCode: string, indicatorVersion: number | null = null, check: () => void = () => { }): XxmViewModel {
    check();
    assert(response.algorithmVersion === XXM_ALGORITHM_VERSION && response.specHash === XXM_SPEC_HASH);
    assert(response.period === period && response.tsCode === tsCode && response.source.indicatorVersion === (period === "day" ? null : indicatorVersion));
    const source = new Map(response.points.map(p => [timeKey(p.time, period), p]));
    const chart = new Map(points.map(p => [String(p.time), p]));
    const through = response.source.computedThrough === null ? null : timeKey(response.source.computedThrough, period);
    for (const [i, p] of points.entries()) {
        if (i % 128 === 0)
            check();
        if (through === null || (period === "day" ? String(p.time) > through : Number(p.time) > Number(through)))
            continue;
        const s = source.get(String(p.time));
        assert(s && [p.close, p.dif, p.dea, p.macd].every(finite) && p.close === s.close && p.dif === s.dif && p.dea === s.dea && p.macd === s.hist);
    }
    const byTime: XxmViewModel["byTime"] = new Map();
    const markers: XxmViewModel["markers"] = [];
    const debug = "debug" in response ? response.debug : null;
    for (const [i, [key, p]] of [...source].entries()) {
        if (i % 128 === 0)
            check();
        if (!chart.has(key))
            continue;
        const events = response.events.filter(e => e.time === p.time), displayEvents = events.filter(e => e.displayOnChart);
        let debugDetail = null;
        if (debug) {
            const point = debug.points.find(v => v.time === p.time)!;
            const eventsDebug = debug.events.filter(e => events.some(v => v.id === e.id));
            const ids = new Set([point.activeStructureId, ...eventsDebug.map(e => e.relatedStructureId)]);
            debugDetail = { point, events: eventsDebug, structures: debug.structures.filter(s => ids.has(s.id) || (s.formedAt <= p.time && (s.trackingEndedAt === null || s.trackingEndedAt >= p.time))) };
        }
        byTime.set(key, { point: p, events, displayEvents, debugDetail });
        for (const event of displayEvents)
            markers.push({ time: chart.get(key)!.time, dif: p.dif, event });
    }
    check();
    return { response, markers, byTime };
}
export function eventLabel(event: Pick<XxmEvent, "type" | "direction">): string {
    if (event.type === "CANCEL")
        return event.direction === "TOP" ? "顶消失" : "底取消";
    const side = event.direction === "TOP" ? "顶" : "底";
    return side + ({ DULL: "钝化", STRUCTURE: "结构", CANCEL: "消失" }[event.type]);
}
export function eventMarkerLabel(event: Pick<XxmEvent, "type" | "direction">): string { return eventLabel(event).replace(/^[顶底]/u, ""); }
