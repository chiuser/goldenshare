import type { OpsCatalogResponse } from "./api/types";

type CatalogActionParameter = NonNullable<OpsCatalogResponse["actions"][number]["parameters"]>[number];

export type TimeGranularity = "day" | "week" | "month";
export type TimeMode = "single_point" | "time_range";

export type TimeCapability = {
  hasTimeInput: boolean;
  supportsPoint: boolean;
  supportsRange: boolean;
  pointGranularity: TimeGranularity | null;
  rangeGranularity: TimeGranularity | null;
  pointKey: string | null;
  rangeStartKey: string | null;
  rangeEndKey: string | null;
};

const TIME_POINT_KEYS: Array<{ key: string; granularity: TimeGranularity }> = [
  { key: "trade_date", granularity: "day" },
  { key: "week", granularity: "week" },
  { key: "month", granularity: "month" },
];

const TIME_RANGE_KEYS: Array<{ start: string; end: string; granularity: TimeGranularity }> = [
  { start: "start_date", end: "end_date", granularity: "day" },
  { start: "start_week", end: "end_week", granularity: "week" },
  { start: "start_month", end: "end_month", granularity: "month" },
];

export const TIME_PARAM_KEYS = new Set([
  "trade_date",
  "start_date",
  "end_date",
  "week",
  "start_week",
  "end_week",
  "month",
  "start_month",
  "end_month",
]);

export function inferTimeCapability(params: CatalogActionParameter[] | undefined): TimeCapability {
  const keys = new Set((params || []).map((param) => param.key));

  const point = TIME_POINT_KEYS.find((item) => keys.has(item.key)) || null;
  const range = TIME_RANGE_KEYS.find((item) => keys.has(item.start) && keys.has(item.end)) || null;

  return {
    hasTimeInput: Boolean(point || range),
    supportsPoint: Boolean(point),
    supportsRange: Boolean(range),
    pointGranularity: point?.granularity || null,
    rangeGranularity: range?.granularity || null,
    pointKey: point?.key || null,
    rangeStartKey: range?.start || null,
    rangeEndKey: range?.end || null,
  };
}

export function filterNonTimeParams(params: CatalogActionParameter[] | undefined): CatalogActionParameter[] {
  return (params || []).filter((param) => !TIME_PARAM_KEYS.has(param.key));
}

export function getTimeModeLabels(capability: TimeCapability): { point: string; range: string } {
  const granularity = capability.pointGranularity || capability.rangeGranularity || "day";
  if (granularity === "month") {
    return {
      point: "只处理一个月",
      range: "处理一个月份区间",
    };
  }
  if (granularity === "week") {
    return {
      point: "只处理一周",
      range: "处理一个周区间",
    };
  }
  return {
    point: "只处理一天",
    range: "处理一个时间区间",
  };
}
