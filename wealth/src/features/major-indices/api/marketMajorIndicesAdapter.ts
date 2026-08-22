import type { MarketDirection } from "../../../shared/model/market";
import type { TopMarketTicker } from "../../../shared/ui/top-market-bar/topMarketBarTypes";
import type { MarketMajorIndicesResponse } from "./marketMajorIndicesApi";

export interface MajorIndexViewItem {
  code: string;
  name: string;
  point: number | null;
  change: number | null;
  pct: number | null;
  direction: MarketDirection;
}

export interface MarketMajorIndicesViewModel {
  indices: MajorIndexViewItem[];
  statusLabel: string;
  statusTone: "ready" | "delayed";
  source: "mock" | "real";
}

export function buildMajorIndicesViewModelFromApi(
  payload: MarketMajorIndicesResponse,
): MarketMajorIndicesViewModel {
  return {
    indices: payload.majorIndices.rows.map((row) => ({
      code: row.subject.subjectCode,
      name: row.subject.subjectName ?? row.subject.subjectCode,
      point: row.point ?? null,
      change: row.change ?? null,
      pct: row.changePct ?? null,
      direction: row.direction,
    })),
    statusLabel: payload.pageStatus.displayText,
    statusTone: payload.pageStatus.status === "READY" ? "ready" : "delayed",
    source: "real",
  };
}

export function buildTopMarketTickersFromMajorIndices(
  model: MarketMajorIndicesViewModel,
): readonly TopMarketTicker[] {
  return model.indices.flatMap<TopMarketTicker>((row) => {
    if (!Number.isFinite(row.point) || !Number.isFinite(row.change) || !Number.isFinite(row.pct)) return [];
    return [{
      code: row.code,
      name: row.name,
      point: row.point as number,
      change: row.change as number,
      pct: row.pct as number,
      direction: row.direction,
    }];
  });
}
