import type { StockIndicatorTab, StockPeriodOption } from "./stockDetailTypes";

export const STOCK_PERIOD_OPTIONS: StockPeriodOption[] = [
  { key: "timeShare", label: "分时" },
  { key: "day", label: "日K" },
  { key: "week", label: "周K" },
  { key: "month", label: "月K" },
  { key: "m120", label: "120分" },
  { key: "m90", label: "90分" },
  { key: "m60", label: "60分" },
  { key: "m30", label: "30分" },
  { key: "m15", label: "15分" },
  { key: "m5", label: "5分" },
  { key: "m1", label: "1分" },
];

export const STOCK_INDICATOR_TABS: StockIndicatorTab[] = [
  { key: "VOL", label: "VOL", active: false, supported: false },
  { key: "AMOUNT", label: "成交额", active: false, supported: false },
  { key: "MA", label: "均线", active: true, supported: true, overlay: "MA" },
  { key: "BIG_ORDER", label: "大单净量", active: false, supported: false },
  { key: "MACD", label: "MACD", active: true, supported: true },
  { key: "KDJ", label: "KDJ", active: true, supported: true },
  { key: "MAIN_PASSWORD", label: "主力密码", active: false, supported: false },
  { key: "MARGIN", label: "融资融券", active: false, supported: false },
  { key: "NORTHBOUND_FLOW", label: "陆股通资金", active: false, supported: false },
  { key: "NORTHBOUND_HOLDING", label: "陆股通持股", active: false, supported: false },
  { key: "AI_INSTITUTION", label: "AI机构活跃度", active: false, supported: false },
  { key: "BOTTOM_FISHING", label: "资金抄底", active: false, supported: false },
  { key: "POSITION", label: "资金仓位", active: false, supported: false },
  { key: "BOLL", label: "BOLL", active: false, supported: true, overlay: "BOLL" },
  { key: "MORE", label: "更多", active: false, supported: false },
];
