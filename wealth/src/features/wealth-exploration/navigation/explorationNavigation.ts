import type { ShortcutItem } from "../../../shared/ui/shortcut-bar/shortcutBarTypes";

export type ExplorationShortcutKey = "turnover-insight" | "sector-analysis";

export const EXPLORATION_TURNOVER_PATH = "/wealth/exploration/turnover-insight";
export const EXPLORATION_SECTOR_DAILY_INSIGHT_PATH = "/wealth/exploration/sector-analysis/daily-insight";
export const EXPLORATION_SECTOR_MOMENTUM_PATH = "/wealth/exploration/sector-analysis/momentum-ranking";
export const EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH = "/wealth/exploration/sector-analysis/dual-momentum";
export const EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH = "/wealth/exploration/sector-analysis/relative-rotation";

export const explorationShortcutItems: readonly ShortcutItem[] = [
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
