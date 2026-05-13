import type { MarketDirection } from "../../../../shared/model/market";
import type { MarketOverview } from "../../api/marketOverviewTypes";
import type { MarketSectorOverviewResponse } from "./marketSectorOverviewApi";

export interface SectorOverviewRankRowViewModel {
  name: string;
  text: string;
  value: number;
}

export interface SectorOverviewColumnViewModel {
  key: string;
  title: string;
  tone: "up" | "down";
  valueLabel: string;
  rows: SectorOverviewRankRowViewModel[];
}

export interface SectorOverviewHeatmapItemViewModel {
  name: string;
  pct: number;
}

export interface MarketSectorOverviewViewModel {
  columns: SectorOverviewColumnViewModel[];
  heatmap: SectorOverviewHeatmapItemViewModel[];
  statusLabel: string;
  statusTone: "ready" | "delayed";
  source: "mock" | "real";
}

function toneFromApi(value: "UP" | "DOWN" | "NEUTRAL"): SectorOverviewColumnViewModel["tone"] {
  return value === "DOWN" ? "down" : "up";
}

function statusTone(status: string): MarketSectorOverviewViewModel["statusTone"] {
  return status === "READY" ? "ready" : "delayed";
}

function subjectName(subject: { subjectCode: string; subjectName?: string | null }): string {
  return subject.subjectName || subject.subjectCode;
}

function metricValue(value: number | null | undefined, direction: MarketDirection): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (direction === "DOWN") return -0;
  return 0;
}

export function buildSectorOverviewViewModelFromMock(overview: MarketOverview): MarketSectorOverviewViewModel {
  return {
    columns: overview.sectors.columns,
    heatmap: overview.sectors.heatmap,
    statusLabel: "mock ready",
    statusTone: "ready",
    source: "mock",
  };
}

export function buildSectorOverviewViewModelFromApi(payload: MarketSectorOverviewResponse): MarketSectorOverviewViewModel {
  return {
    columns: payload.sectorOverview.columns.map((column) => ({
      key: column.columnKey,
      title: column.title,
      tone: toneFromApi(column.tone),
      valueLabel: column.metricLabel,
      rows: column.rows.map((row) => ({
        name: subjectName(row.subject),
        text: row.metric.displayText,
        value: metricValue(row.metric.value, row.metric.direction),
      })),
    })),
    heatmap: payload.sectorOverview.heatMapItems.map((item) => ({
      name: subjectName(item.subject),
      pct: item.changePct ?? 0,
    })),
    statusLabel: payload.pageStatus.displayText,
    statusTone: statusTone(payload.pageStatus.status),
    source: "real",
  };
}
