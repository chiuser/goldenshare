import type { IndexTurnoverInsightResponse } from "./indexTurnoverInsightApi";
import type { IndexTurnoverInsightViewModel } from "../model/indexTurnoverInsightTypes";

export function buildIndexTurnoverInsightViewModelFromApi(
  payload: IndexTurnoverInsightResponse,
): IndexTurnoverInsightViewModel {
  if (payload.indices.length !== 10) {
    throw new Error("指数成交额响应必须包含固定 10 项。");
  }
  const identities = new Set(payload.indices.map((item) => `${item.tsCode}:${item.indexName}`));
  if (identities.size !== 10) {
    throw new Error("指数成交额响应身份重复。");
  }
  return {
    status: payload.status,
    tradingDay: {
      expectedTradeDate: payload.tradingDay.expectedTradeDate,
      observedTradeDate: payload.tradingDay.observedTradeDate ?? null,
      previousObservedTradeDate: payload.tradingDay.previousObservedTradeDate ?? null,
    },
    asOf: payload.asOf ?? null,
    indices: payload.indices.map((item) => ({
      tsCode: item.tsCode,
      indexName: item.indexName,
      status: item.status,
      summary: {
        current: { ...item.summary.current },
        previous: { ...item.summary.previous },
        delta: { ...item.summary.delta },
        avg5d: { ...item.summary.avg5d },
        avg20d: { ...item.summary.avg20d },
      },
      upperAxis: item.upperAxis
        ? { ...item.upperAxis, ticks: item.upperAxis.ticks.map((tick) => ({ ...tick })) }
        : null,
      deltaAxis: item.deltaAxis
        ? { ...item.deltaAxis, ticks: item.deltaAxis.ticks.map((tick) => ({ ...tick })) }
        : null,
      points: item.series.map((point) => ({ ...point })),
      message: item.message ?? null,
      exceptionCode: item.exceptionCode ?? null,
    })),
    message: payload.message ?? null,
    exceptionCode: payload.exceptionCode ?? null,
  };
}
