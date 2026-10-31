import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { XXM_ALGORITHM_VERSION, XXM_SPEC_HASH } from "./types";
import type { XxmResponse, XxmDebugResponse } from "./types";
/** Handwritten public contract: two independent directions on one real time. */
export function xxmFixture() {
    const point = { time: "2023-01-12", close: 106, dif: -16, dea: -15, hist: -2, ordinaryState: "DULL" as const, ordinaryDirection: "BOTTOM" as const };
    const response: XxmResponse = { tsCode: "000001.SH", period: "day", algorithmVersion: XXM_ALGORITHM_VERSION, specHash: XXM_SPEC_HASH, source: { kind: "daily_factor", startTime: "2023-01-03", computedThrough: point.time, initialHistoryIncomplete: true, indicatorVersion: null }, points: [point], events: [{ id: "new-bottom", time: point.time, direction: "BOTTOM", type: "DULL", displayOnChart: true }, { id: "old-top", time: point.time, direction: "TOP", type: "CANCEL", displayOnChart: true }], meta: { count: 1, responseStart: point.time, responseEnd: point.time }, dataStatus: { status: "READY", message: null, asOf: point.time } };
    return { response, points: [chartPoint(point)] };
}
function chartPoint(p: XxmResponse['points'][number]): DetailChartPoint { return { time: p.time, fullDate: p.time, close: p.close, dif: p.dif, dea: p.dea, macd: p.hist, open: p.close, high: p.close + 1, low: p.close - 1, preClose: p.close - 1, changePct: 1, amplitude: 2, volume: 100, volumeDisplay: "100", amount: 1000, turnoverRate: null, k: 1, d: 1, j: 1, overlays: {} }; }
/** RC77/93's independent literal facts: old cancellation plus new activation. */
export function xxmDebugFixture() {
    const { response } = xxmFixture();
    response.points = [{ time: "2023-01-12", close: 104, dif: 96, dea: 95, hist: 2, ordinaryState: "DULL", ordinaryDirection: "TOP" }];
    response.events = [{ id: "cancel-old", time: "2023-01-12", direction: "TOP", type: "CANCEL", displayOnChart: false }, { id: "activate-new", time: "2023-01-12", direction: "TOP", type: "DULL", displayOnChart: true }];
    const old = { startTime: "2023-01-03", endTime: "2023-01-03", price: 100, dif: 200, priceAt: "2023-01-03", difAt: "2023-01-03" };
    const next = { startTime: "2023-01-05", endTime: "2023-01-09", price: 103, dif: 100, priceAt: "2023-01-09", difAt: "2023-01-05" };
    const value: XxmDebugResponse = { ...response, debug: { sourceInputId: "b".repeat(64), points: [{ time: "2023-01-12", activeReference: next, activeStructureId: null }], events: [{ id: "cancel-old", route: "structure_price_break", fromState: "STRUCTURE", eventReference: old, relatedStructureId: "old-structure" }, { id: "activate-new", route: "activation", fromState: "NONE", eventReference: next, relatedStructureId: null }], structures: [{ id: "old-structure", structureEventId: "formation-outside-window", direction: "TOP", formedAt: "2023-01-09", formationRoute: "dif_turn", originSegmentStart: "2023-01-05", originalReference: old, priceExtreme: 103, priceExtremeAt: "2023-01-09", status: "DISAPPEARED", originWave: { sign: 1, start: "2023-01-05", end: "2023-01-09", count: 3, price: 103, dif: 100, priceAt: "2023-01-09", difAt: "2023-01-05" }, firstOppositeAt: "2023-01-10", nextSameColorStart: "2023-01-11", nextSameColorCount: 2, trackingPriceExtreme: 104, trackingPriceExtremeAt: "2023-01-12", trackingEndedAt: "2023-01-12", disappearedAt: "2023-01-12", disappearanceReason: "structure_price_break" }] } };
    return { response: value, points: [chartPoint(value.points[0]!)] };
}
