import type { IndexIndicatorTab, IndexPeriodKey } from "./indexDetailTypes";

export const INDEX_PERIOD_OPTIONS: Array<{ key: IndexPeriodKey; label: string }> = [
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

export const INDEX_INDICATOR_TABS: Omit<IndexIndicatorTab, "supported">[] = [
  { key: "VOL", label: "VOL" },
  { key: "amount", label: "成交额" },
  { key: "MA", label: "均线", overlay: "MA" },
  { key: "MACD", label: "MACD" },
  { key: "KDJ", label: "KDJ" },
  { key: "BOLL", label: "BOLL", overlay: "BOLL" },
];
