import type { ShortcutItem } from "../../../shared/ui/shortcut-bar/shortcutBarTypes";

export type ExplorationShortcutKey = "turnover-insight" | "sector-analysis";

export const EXPLORATION_TURNOVER_PATH = "/wealth/exploration/turnover-insight";
export const EXPLORATION_SECTOR_MOMENTUM_PATH = "/wealth/exploration/sector-analysis/momentum-ranking";

export const explorationShortcutItems: readonly ShortcutItem[] = [
  {
    key: "turnover-insight",
    path: EXPLORATION_TURNOVER_PATH,
    title: "成交额洞察",
    description: "查看全市场成交额、日内节奏与历史对比。",
  },
  {
    key: "sector-analysis",
    path: EXPLORATION_SECTOR_MOMENTUM_PATH,
    title: "板块分析",
    description: "查看行业强弱排名与历史变化。",
  },
];
