export type ModuleSource = "mock" | "real";

export interface MarketOverviewModuleSources {
  summary: ModuleSource;
  majorIndices: ModuleSource;
  breadth: ModuleSource;
  style: ModuleSource;
  turnover: ModuleSource;
  moneyFlow: ModuleSource;
  leaderboards: ModuleSource;
  limitUp: ModuleSource;
  sectors: ModuleSource;
}

export const marketOverviewModuleSources: MarketOverviewModuleSources = {
  summary: "real",
  majorIndices: "real",
  breadth: "real",
  style: "real",
  turnover: "real",
  moneyFlow: "mock",
  leaderboards: "mock",
  limitUp: "mock",
  sectors: "mock",
};
