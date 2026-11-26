import type { ShortcutItem } from "../../../shared/ui/shortcut-bar/shortcutBarTypes";

export type ExplorationShortcutKey = "turnover-insight" | "sector-analysis" | "etf-activity";

export const EXPLORATION_TURNOVER_PATH = "/wealth/exploration/turnover-insight";
export const EXPLORATION_ETF_ACTIVITY_PATH = "/wealth/exploration/etf-activity";
export const EXPLORATION_SECTOR_DAILY_INSIGHT_PATH = "/wealth/exploration/sector-analysis/daily-insight";
export const EXPLORATION_SECTOR_MOMENTUM_PATH = "/wealth/exploration/sector-analysis/momentum-ranking";
export const EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH = "/wealth/exploration/sector-analysis/dual-momentum";
export const EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH = "/wealth/exploration/sector-analysis/relative-rotation";

const explorationShortcutItems: readonly ShortcutItem[] = [
  {
    key: "turnover-insight",
    path: EXPLORATION_TURNOVER_PATH,
    title: "成交额洞察",
    description: "查看全市场成交额、日内节奏与历史对比。",
  },
  {
    key: "sector-analysis",
    path: EXPLORATION_SECTOR_DAILY_INSIGHT_PATH,
    title: "板块分析",
    description: "查看每日行业事实、强弱变化与独立分析。",
  },
];

export function isEtfActivityEnabled(): boolean {
  const mode = import.meta.env.MODE;
  return mode === "local-dg" || (mode === "development" && import.meta.env.DEV);
}

export function getExplorationShortcutItems(): readonly ShortcutItem[] {
  return isEtfActivityEnabled() ? [...explorationShortcutItems, {
    key: "etf-activity",
    path: EXPLORATION_ETF_ACTIVITY_PATH,
    title: "ETF 动态",
    description: "查看 ETF 成交额趋势与每日排行。",
  }] : explorationShortcutItems;
}
