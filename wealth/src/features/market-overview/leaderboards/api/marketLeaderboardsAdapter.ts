import type { MarketOverview } from "../../api/marketOverviewTypes";
import type { MarketLeaderboardsResponse } from "./marketLeaderboardsApi";

export interface LeaderboardViewRow {
  rank: number;
  name: string;
  code: string;
  latestPrice: number | null;
  changePct: number | null;
  turnoverRate: number | null;
  volumeRatio: number | null;
  volumeText: string;
  amountText: string;
}

export interface LeaderboardViewTab {
  key: string;
  label: string;
  rows: LeaderboardViewRow[];
}

export interface MarketLeaderboardsViewModel {
  tabs: LeaderboardViewTab[];
  statusLabel: string;
  statusTone: "ready" | "delayed";
  source: "mock" | "real";
}

export function buildLeaderboardsViewModelFromMock(overview: MarketOverview): MarketLeaderboardsViewModel {
  return {
    tabs: overview.leaderboards.map((tab) => ({
      key: tab.key,
      label: tab.label,
      rows: tab.rows.map((row, index) => ({
        rank: index + 1,
        name: row.name,
        code: row.code,
        latestPrice: row.latestPrice,
        changePct: row.changePct,
        turnoverRate: row.turnoverRate,
        volumeRatio: row.volumeRatio,
        volumeText: row.volume,
        amountText: row.amount,
      })),
    })),
    statusLabel: "事实聚合已就绪",
    statusTone: "ready",
    source: "mock",
  };
}

export function buildLeaderboardsViewModelFromApi(payload: MarketLeaderboardsResponse): MarketLeaderboardsViewModel {
  const rowsByBoard = new Map(payload.boards.map((board) => [board.boardKey, board.rows]));
  return {
    tabs: payload.definitions.map((definition) => {
      const rows = rowsByBoard.get(definition.boardKey) ?? [];
      return {
        key: definition.boardKey,
        label: definition.boardLabel,
        rows: rows.map((row, index) => ({
          rank: row.rank ?? index + 1,
          name: row.subject.subjectName?.trim() || row.subject.subjectCode,
          code: row.subject.subjectCode,
          latestPrice: row.metrics.latestPrice ?? null,
          changePct: row.metrics.changePct ?? null,
          turnoverRate: row.metrics.turnoverRate ?? null,
          volumeRatio: row.metrics.volumeRatio ?? null,
          volumeText: formatVolume(row.metrics.volume ?? null),
          amountText: formatAmount(row.metrics.amount ?? null),
        })),
      };
    }),
    statusLabel: payload.pageStatus.displayText,
    statusTone: payload.pageStatus.status === "READY" ? "ready" : "delayed",
    source: "real",
  };
}

function formatVolume(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "--";
  const abs = Math.abs(value);
  if (abs >= 10000) {
    return `${(value / 10000).toFixed(1)}万手`;
  }
  return `${Math.round(value)}手`;
}

function formatAmount(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "--";
  const amountYi = value / 100000;
  if (Math.abs(amountYi) >= 1000) {
    return `${amountYi.toFixed(0)}亿`;
  }
  return `${amountYi.toFixed(1)}亿`;
}

