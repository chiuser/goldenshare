import type { QuoteItem } from "../../api/marketOverviewTypes";
import type { MarketMajorIndicesViewModel } from "../../../major-indices/api/marketMajorIndicesAdapter";

export function buildMajorIndicesViewModelFromMock(indices: QuoteItem[]): MarketMajorIndicesViewModel {
  return {
    indices: indices.map((row) => ({
      code: row.code,
      name: row.name,
      point: row.point,
      change: row.change,
      pct: row.pct,
      direction: row.direction,
    })),
    statusLabel: "事实聚合已就绪",
    statusTone: "ready",
    source: "mock",
  };
}
