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
  { key: "VOL", label: "VOL", active: false, supported: true },
  { key: "MA", label: "均线", active: true, supported: true, overlay: "MA" },
  { key: "MACD", label: "MACD", active: true, supported: true },
  { key: "KDJ", label: "KDJ", active: true, supported: true },
  { key: "BOLL", label: "BOLL", active: false, supported: true, overlay: "BOLL" },
];
