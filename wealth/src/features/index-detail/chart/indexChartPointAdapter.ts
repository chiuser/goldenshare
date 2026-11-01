import type { IndexCandlePoint } from "../model/indexDetailTypes";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";

export function toDetailChartPoint(point: IndexCandlePoint): DetailChartPoint {
  return {
    time: point.time,
    fullDate: point.fullDate,
    open: point.open,
    high: point.high,
    low: point.low,
    close: point.close,
    preClose: point.preClose,
    changePct: point.changePct,
    amplitude: point.amplitude,
    volume: point.volume,
    volumeDisplay: point.volumeDisplay,
    amount: point.amount,
    turnoverRate: null,
    macd: point.macd,
    dif: point.dif,
    dea: point.dea,
    k: point.k,
    d: point.d,
    j: point.j,
    overlays: {
      ma5: point.ma5, ma10: point.ma10, ma20: point.ma20, ma30: point.ma30,
      ma60: point.ma60, ma90: point.ma90, ma250: point.ma250,
      bollUpper: point.bollUpper, bollMiddle: point.bollMiddle, bollLower: point.bollLower,
    },
  };
}
