import { fetchIndexDetailKline } from "../index-detail/api/indexDetailApiClient";
import { fetchStockDetailKline } from "../stock-detail/api/stockDetailApiClient";
import { selectPriceTargetQuote, type PriceTargetAsset } from "./singleCandlePriceTarget";

export async function loadSingleCandlePriceTargetQuote(asset: PriceTargetAsset, endDate: string, signal: AbortSignal) {
  const params = { tsCode: asset.tsCode, period: "day" as const, endDate, limit: 2 };
  if (asset.kind === "stock") {
    const response = await fetchStockDetailKline({ ...params, adjustment: "forward" }, { signal });
    if (response.stockRef.tsCode !== asset.tsCode || response.period !== "day"
      || response.adjustment !== "forward" || response.sourceAdjustment !== "qfq") {
      throw new Error("股票日线行情与测算请求不匹配");
    }
    return selectPriceTargetQuote(response.bars, endDate);
  }

  const response = await fetchIndexDetailKline(params, { signal });
  if (response.indexRef.tsCode !== asset.tsCode || response.period !== "day") {
    throw new Error("指数日线行情与测算请求不匹配");
  }
  return selectPriceTargetQuote(response.bars, endDate);
}
