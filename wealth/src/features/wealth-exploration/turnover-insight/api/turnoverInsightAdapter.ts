import type { TurnoverInsightResponse } from "./turnoverInsightApi";
import type { TurnoverInsightViewModel } from "../model/turnoverInsightTypes";

export function buildTurnoverInsightViewModelFromApi(
  payload: TurnoverInsightResponse,
): TurnoverInsightViewModel {
  return {
    status: payload.status,
    tradingDay: {
      expectedTradeDate: payload.tradingDay.expectedTradeDate,
      observedTradeDate: payload.tradingDay.observedTradeDate ?? null,
      previousObservedTradeDate: payload.tradingDay.previousObservedTradeDate ?? null,
    },
    asOf: payload.asOf ?? null,
    summary: {
      current: { ...payload.summary.current },
      previous: { ...payload.summary.previous },
      delta: { ...payload.summary.delta },
      avg5d: { ...payload.summary.avg5d },
      avg20d: { ...payload.summary.avg20d },
    },
    upperAxis: payload.upperAxis
      ? { ...payload.upperAxis, ticks: payload.upperAxis.ticks.map((tick) => ({ ...tick })) }
      : null,
    deltaAxis: payload.deltaAxis
      ? { ...payload.deltaAxis, ticks: payload.deltaAxis.ticks.map((tick) => ({ ...tick })) }
      : null,
    points: payload.series.map((point) => ({ ...point })),
    message: payload.message ?? null,
    exceptionCode: payload.exceptionCode ?? null,
  };
}
