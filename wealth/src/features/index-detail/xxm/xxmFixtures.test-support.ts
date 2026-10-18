import { XXM_ALGORITHM_VERSION, XXM_SPEC_HASH } from "./types";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { XxmResponse } from "./types";

export function xxmFixture(): { response: XxmResponse; points: DetailChartPoint[] } {
  const reference = { startTime: "2026-03-01", endTime: "2026-03-10", price: 120, dif: -2 };
  const topReference = { startTime: "2026-02-01", endTime: "2026-02-10", price: 100, dif: 3 };
  const point = { time: "2026-10-09", close: 106, dif: -1, dea: -0.5, hist: -1,
    ordinaryState: "DULL" as const, ordinaryDirection: "BOTTOM" as const, activeReference: reference, pendingTopHistoryId: null, pendingBottomHistoryId: null, pendingRearmId: null };
  const response: XxmResponse = {
    tsCode: "000001.SH", period: "day", algorithmVersion: XXM_ALGORITHM_VERSION, specHash: XXM_SPEC_HASH,
    source: { kind: "daily_factor", inputId: "b".repeat(64), startTime: "2023-01-03", computedThrough: point.time, initialHistoryIncomplete: true, indicatorVersion: null },
    points: [point], events: [
      { id: "e1", time: point.time, direction: "BOTTOM", type: "DULL", route: "activation", fromState: "NONE", eventReference: reference, relatedTopHistoryId: null, relatedBottomHistoryId: null, relatedRearmId: null },
      { id: "e2", time: point.time, direction: "TOP", type: "RESEARCH_HISTORICAL_WITHDRAWAL", route: "historical_price_break", fromState: "DULL", eventReference: topReference, relatedTopHistoryId: "h1", relatedBottomHistoryId: null, relatedRearmId: null },
    ],
    topHistories: [{ id: "h1", confirmedAt: "2026-09-15", confirmationRoute: "color_flip", pricePeak: 105,
      pricePeakAt: "2026-09-14", originalReference: topReference, status: "ENDED", endedAt: point.time,
      endReason: "historical_price_break", observedThrough: point.time, ageBars: 17 }],
    bottomHistories: [], rearmRecords: [],
    meta: { count: 1, responseStart: point.time, responseEnd: point.time },
    dataStatus: { status: "READY", message: null, asOf: point.time },
  };
  const chart: DetailChartPoint = { time: point.time, fullDate: point.time, close: point.close, dif: point.dif, dea: point.dea,
    macd: point.hist, open: 106, high: 107, low: 105, preClose: 105, changePct: 1, amplitude: 2,
    volume: 100, volumeDisplay: "100", amount: 1000, turnoverRate: null, k: 1, d: 1, j: 1, overlays: {} };
  return { response, points: [chart] };
}
