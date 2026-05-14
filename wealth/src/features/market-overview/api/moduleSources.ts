export type ModuleSource = "mock" | "real";

export interface MarketOverviewModuleSources {
  summary: ModuleSource;
  majorIndices: ModuleSource;
  breadth: ModuleSource;
  style: ModuleSource;
  turnover: ModuleSource;
  moneyFlow: ModuleSource;
  leaderboards: ModuleSource;
  news: ModuleSource;
  limitUp: ModuleSource;
  streakLadder: ModuleSource;
  sectors: ModuleSource;
}

export const marketOverviewModuleSources: MarketOverviewModuleSources = {
  summary: "real",
  majorIndices: "real",
  breadth: "real",
  style: "real",
  turnover: "real",
  moneyFlow: "real",
  leaderboards: "real",
  news: "real",
  limitUp: "real",
  streakLadder: "real",
  sectors: "real",
};
