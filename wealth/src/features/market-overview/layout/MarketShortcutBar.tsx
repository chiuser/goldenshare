import { ShortcutBar } from "../../../shared/ui/shortcut-bar/ShortcutBar";
import type { ShortcutItem } from "../../../shared/ui/shortcut-bar/shortcutBarTypes";
import { WEALTH_WATCHLIST_PATH } from "../../../app/routes/routerState";

interface MarketShortcutBarProps {
  onAction: (message: string) => void;
  onNavigate: (path: string) => void;
  watchlistCount: number | null;
}

const entries: readonly ShortcutItem[] = [
  { key: "emotion", title: "市场温度与情绪", badge: "新", badgeTone: "neutral", description: "进入分析页查看温度、情绪、资金与风险，不在本页展示分数。", path: "/market/emotion" },
  { key: "opportunity", title: "机会雷达", badge: "3", badgeTone: "alert", description: "查看板块轮动、资金回流与机会线索。", path: "/opportunity/radar" },
  { key: "watchlist", title: "我的自选", badge: "--", badgeTone: "neutral", description: "查看关注股票的行情，添加或移除自选。", path: WEALTH_WATCHLIST_PATH },
  { key: "positions", title: "我的持仓", badge: "5", badgeTone: "neutral", description: "查看手工登记持仓和当日波动。", path: "/positions" },
  { key: "alerts", title: "提醒中心", badge: "2", badgeTone: "alert", description: "管理价格、资金、技术和计划提醒。", path: "/alerts" },
  { key: "settings", title: "用户设置", badge: "--", badgeTone: "neutral", description: "管理账户、偏好和展示设置。", path: "/settings" },
];

export function MarketShortcutBar({ onAction, onNavigate, watchlistCount }: MarketShortcutBarProps) {
  return (
    <ShortcutBar
      activeKey="emotion"
      items={entries.map((entry) => entry.key === "watchlist" ? { ...entry, badge: watchlistCount === null ? "--" : String(watchlistCount) } : entry)}
      onNavigate={(path) => path === WEALTH_WATCHLIST_PATH ? onNavigate(path) : onAction(`跳转：${path}`)}
    />
  );
}
