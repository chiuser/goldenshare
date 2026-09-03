import type { WatchlistItemDto } from "../api/watchlistApiTypes";
import type { WatchlistRowViewModel } from "./watchlistTypes";

function number(value: number | null, divisor = 1, signed = false): string {
  if (value === null || !Number.isFinite(value)) return "--";
  const text = (value / divisor).toFixed(2);
  return signed && value > 0 ? `+${text}` : text;
}

export function buildWatchlistRow(
  item: WatchlistItemDto,
): WatchlistRowViewModel {
  return {
    id: item.id,
    tsCode: item.stock.tsCode,
    name: item.stock.name,
    industry: item.stock.industry ?? "--",
    price: number(item.quote.price),
    changePct: number(item.quote.changePct, 1, true),
    vol: number(item.quote.vol, 10000),
    peTtm:
      item.valuation.peTtm !== null && item.valuation.peTtm > 0
        ? number(item.valuation.peTtm)
        : "--",
    pb:
      item.valuation.pb !== null && item.valuation.pb > 0
        ? number(item.valuation.pb)
        : "--",
    volumeRatio: number(item.activity.volumeRatio),
    turnoverRate: number(item.activity.turnoverRate),
    netAmount: number(item.moneyFlow.netAmount, 1, true),
    priceDirection: item.quote.direction,
    moneyFlowDirection: item.moneyFlow.direction,
    missingFields: item.missingFields,
  };
}
