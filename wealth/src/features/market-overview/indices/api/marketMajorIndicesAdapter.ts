import type { MarketDirection } from "../../../../shared/model/market";
import type { QuoteItem } from "../../api/marketOverviewTypes";
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

export function buildMajorIndicesViewModelFromApi(payload: MarketMajorIndicesResponse): MarketMajorIndicesViewModel {
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

