import type { TrendChannelPoint } from "../../../../shared/charts/trend-channel/trendChannelGeometry";
import type { StockTrendChannelResponseDto } from "./stockTrendChannelApiTypes";

export interface StockTrendChannelViewModel {
  points: TrendChannelPoint[];
  status: "READY" | "EMPTY";
}

export function buildStockTrendChannelViewModel(
  payload: StockTrendChannelResponseDto,
): StockTrendChannelViewModel {
  const points = payload.bars.map((bar) => ({
    time: bar.tradeDate,
    close: bar.close,
    shortUpper: bar.shortChannel.upper,
    shortLower: bar.shortChannel.lower,
    longUpper: bar.longChannel.upper,
    longLower: bar.longChannel.lower,
  }));
  let previousTime = "";
  points.forEach((point) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(point.time)) {
      throw new Error("股票趋势通道返回了非法交易日。")
    }
    if (previousTime && point.time <= previousTime) {
      throw new Error("股票趋势通道必须严格按交易日升序返回。")
    }
    if (![point.close, point.shortUpper, point.shortLower, point.longUpper, point.longLower].every(Number.isFinite)) {
      throw new Error("股票趋势通道返回了非法数值。")
    }
    if (point.shortUpper < point.shortLower || point.longUpper < point.longLower) {
      throw new Error("股票趋势通道上下轨顺序非法。")
    }
    previousTime = point.time;
  });
  if (payload.meta.count !== points.length) {
    throw new Error("股票趋势通道返回数量与 meta 不一致。")
  }
  if (payload.dataStatus.status === "EMPTY" && points.length > 0) {
    throw new Error("股票趋势通道空态与数据行冲突。")
  }
  return { points, status: points.length === 0 ? "EMPTY" : "READY" };
}
