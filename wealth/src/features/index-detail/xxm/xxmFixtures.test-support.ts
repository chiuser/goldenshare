import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { XXM_ALGORITHM_VERSION, XXM_SPEC_HASH } from "./types";
import type { UTCTimestamp } from "lightweight-charts";
import type { GoldXxmResponse, XxmResponse, XxmDebugResponse, XxmPeriod } from "./types";
// Public fields follow src/biz/schemas/wealth/market/index_detail_xxm.py.
// The independent literal r4 facts below stay unchanged. Each minute table places
// them on seven consecutive completed bars: originWave.count=3 and the final
// nextSameColorCount=2. No production endpoint/time helper generates these inputs.
const minuteStamps = {
    m30: { "2023-01-03": "2023-01-12T10:00:00+08:00", "2023-01-05": "2023-01-12T10:30:00+08:00", "2023-01-09": "2023-01-12T11:30:00+08:00", "2023-01-10": "2023-01-12T13:30:00+08:00", "2023-01-11": "2023-01-12T14:00:00+08:00", "2023-01-12": "2023-01-12T14:30:00+08:00" },
    m60: { "2023-01-03": "2023-01-11T10:30:00+08:00", "2023-01-05": "2023-01-11T11:30:00+08:00", "2023-01-09": "2023-01-11T15:00:00+08:00", "2023-01-10": "2023-01-12T10:30:00+08:00", "2023-01-11": "2023-01-12T11:30:00+08:00", "2023-01-12": "2023-01-12T14:00:00+08:00" },
    m90: { "2023-01-03": "2023-01-10T11:00:00+08:00", "2023-01-05": "2023-01-10T14:00:00+08:00", "2023-01-09": "2023-01-11T11:00:00+08:00", "2023-01-10": "2023-01-11T14:00:00+08:00", "2023-01-11": "2023-01-11T15:00:00+08:00", "2023-01-12": "2023-01-12T11:00:00+08:00" },
    m120: { "2023-01-03": "2023-01-09T11:30:00+08:00", "2023-01-05": "2023-01-09T15:00:00+08:00", "2023-01-09": "2023-01-10T15:00:00+08:00", "2023-01-10": "2023-01-11T11:30:00+08:00", "2023-01-11": "2023-01-11T15:00:00+08:00", "2023-01-12": "2023-01-12T11:30:00+08:00" },
} as const;
// A500 starts after the original sample: day 2024-09-23, minute 2024-10-22.
// Keep the weekday pattern and completed endpoints with independent later dates.
const a500Dates: Record<string, string> = {
    "2023-01-03": "2025-11-04", "2023-01-05": "2025-11-06", "2023-01-09": "2025-11-10",
    "2023-01-10": "2025-11-11", "2023-01-11": "2025-11-12", "2023-01-12": "2025-11-13",
};
const stamp = (day: keyof typeof minuteStamps.m30, period: XxmPeriod, tsCode: string) => {
    const value = period === "day" ? day : minuteStamps[period][day];
    return tsCode === "000510.SH" ? a500Dates[value.slice(0, 10)] + value.slice(10) : value;
};
/** Handwritten public contract: two independent directions on one real time. */
export function xxmFixture(tsCode: string, period: XxmPeriod = "day") {
    const point = { time: stamp("2023-01-12", period, tsCode), close: 106, dif: -16, dea: -15, hist: -2, ordinaryState: "DULL" as const, ordinaryDirection: "BOTTOM" as const };
    const response: XxmResponse = { tsCode, period, algorithmVersion: XXM_ALGORITHM_VERSION, specHash: XXM_SPEC_HASH, source: { kind: period === "day" ? "daily_factor" : "minute_gold", startTime: stamp("2023-01-03", period, tsCode), computedThrough: point.time, initialHistoryIncomplete: true, indicatorVersion: period === "day" ? null : 1 }, points: [point], events: [{ id: "new-bottom", time: point.time, direction: "BOTTOM", type: "DULL", displayOnChart: true }, { id: "old-top", time: point.time, direction: "TOP", type: "CANCEL", displayOnChart: true }], meta: { count: 1, responseStart: point.time, responseEnd: point.time }, dataStatus: { status: "READY", message: null, asOf: point.time } };
    return { response, points: [chartPoint(point)] };
}
function chartPoint(p: XxmResponse['points'][number]): DetailChartPoint { return { time: p.time.length === 10 ? p.time : (Date.parse(p.time) / 1000) as UTCTimestamp, fullDate: p.time, close: p.close, dif: p.dif, dea: p.dea, macd: p.hist, open: p.close, high: p.close + 1, low: p.close - 1, preClose: p.close - 1, changePct: 1, amplitude: 2, volume: 100, volumeDisplay: "100", amount: 1000, turnoverRate: null, k: 1, d: 1, j: 1, overlays: {} }; }
/** RC77/93's independent literal facts: old cancellation plus new activation. */
export function xxmDebugFixture(tsCode: string, period: XxmPeriod = "day") {
    const { response } = xxmFixture(tsCode, period);
    response.points = [{ time: stamp("2023-01-12", period, tsCode), close: 104, dif: 96, dea: 95, hist: 2, ordinaryState: "DULL", ordinaryDirection: "TOP" }];
    response.events = [{ id: "cancel-old", time: stamp("2023-01-12", period, tsCode), direction: "TOP", type: "CANCEL", displayOnChart: false }, { id: "activate-new", time: stamp("2023-01-12", period, tsCode), direction: "TOP", type: "DULL", displayOnChart: true }];
    const old = { startTime: stamp("2023-01-03", period, tsCode), endTime: stamp("2023-01-03", period, tsCode), price: 100, dif: 200, priceAt: stamp("2023-01-03", period, tsCode), difAt: stamp("2023-01-03", period, tsCode) };
    const next = { startTime: stamp("2023-01-05", period, tsCode), endTime: stamp("2023-01-09", period, tsCode), price: 103, dif: 100, priceAt: stamp("2023-01-09", period, tsCode), difAt: stamp("2023-01-05", period, tsCode) };
    const value: XxmDebugResponse = { ...response, debug: { sourceInputId: "b".repeat(64), points: [{ time: stamp("2023-01-12", period, tsCode), activeReference: next, activeStructureId: null }], events: [{ id: "cancel-old", route: "structure_price_break", fromState: "STRUCTURE", eventReference: old, relatedStructureId: "old-structure" }, { id: "activate-new", route: "activation", fromState: "NONE", eventReference: next, relatedStructureId: null }], structures: [{ id: "old-structure", structureEventId: "formation-outside-window", direction: "TOP", formedAt: stamp("2023-01-09", period, tsCode), formationRoute: "dif_turn", originSegmentStart: stamp("2023-01-05", period, tsCode), originalReference: old, priceExtreme: 103, priceExtremeAt: stamp("2023-01-09", period, tsCode), status: "DISAPPEARED", originWave: { sign: 1, start: stamp("2023-01-05", period, tsCode), end: stamp("2023-01-09", period, tsCode), count: 3, price: 103, dif: 100, priceAt: stamp("2023-01-09", period, tsCode), difAt: stamp("2023-01-05", period, tsCode) }, firstOppositeAt: stamp("2023-01-10", period, tsCode), nextSameColorStart: stamp("2023-01-11", period, tsCode), nextSameColorCount: 2, trackingPriceExtreme: 104, trackingPriceExtremeAt: stamp("2023-01-12", period, tsCode), trackingEndedAt: stamp("2023-01-12", period, tsCode), disappearedAt: stamp("2023-01-12", period, tsCode), disappearanceReason: "structure_price_break" }] } };
    return { response: value, points: [chartPoint(value.points[0]!)] };
}

/** Gold keeps the observed curve and events, without live recognition state or a calculation prefix. */
export function goldXxmFixture(tsCode: string, period: XxmPeriod = "day") {
    const { response, points } = xxmFixture(tsCode, period);
    return { response: goldResponse(response), points };
}

export function goldResponse(response: XxmResponse | XxmDebugResponse): GoldXxmResponse {
    const { tsCode, period, algorithmVersion, specHash, points, events, meta, dataStatus } = response;
    return { tsCode, period, algorithmVersion, specHash, events, meta, dataStatus,
        points: points.map(point => ({ ...point, ordinaryState: null, ordinaryDirection: null })) };
}
