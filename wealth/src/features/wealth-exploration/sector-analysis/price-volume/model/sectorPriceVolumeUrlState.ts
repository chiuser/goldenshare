import type {
  PriceVolumeHistoryRange,
  PriceVolumePeriod,
  PriceVolumeSortBy,
  PriceVolumeSortDirection,
  PriceVolumeStateFilter,
  PriceVolumeUrlScope,
  PriceVolumeUrlState,
} from "../api/sectorPriceVolumeTypes";

export const DEFAULT_PRICE_VOLUME_URL_STATE: PriceVolumeUrlState = {
  tradeDate: null,
  scope: "level1",
  level1Code: null,
  level2Code: null,
  period: 20,
  stateFilter: "all",
  sortBy: "price-momentum",
  sortDirection: "desc",
  sectorCode: null,
  historyRange: 20,
};

const ALLOWED_KEYS = new Set([
  "tradeDate", "scope", "level1Code", "level2Code", "period",
  "stateFilter", "sortBy", "sortDirection", "sectorCode", "historyRange",
]);
const SCOPES = new Set<PriceVolumeUrlScope>(["level1", "level2", "level3", "level1-children", "level2-children"]);
const PERIODS = new Set<PriceVolumePeriod>([1, 5, 10, 20, 30]);
const FILTERS = new Set<PriceVolumeStateFilter>(["all", "joint", "price", "amount", "neutral"]);
const SORT_FIELDS = new Set<PriceVolumeSortBy>(["price-momentum", "amount-activity"]);
const SORT_DIRECTIONS = new Set<PriceVolumeSortDirection>(["desc", "asc"]);
const HISTORY_RANGES = new Set<PriceVolumeHistoryRange>([20, 30, 60]);
const CODE_PATTERN = /^BK[0-9]{4}\.DC$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export type PriceVolumeUrlParseResult =
  | { ok: true; value: PriceVolumeUrlState }
  | { ok: false; message: string };

export function parseSectorPriceVolumeUrlState(search: string): PriceVolumeUrlParseResult {
  const params = new URLSearchParams(search);
  for (const key of new Set(params.keys())) {
    if (!ALLOWED_KEYS.has(key)) return { ok: false, message: `不支持的页面参数：${key}` };
    if (params.getAll(key).length > 1) return { ok: false, message: `页面参数不能重复：${key}` };
  }
  const tradeDate = params.get("tradeDate");
  if (tradeDate !== null && !isIsoDate(tradeDate)) return { ok: false, message: "交易日必须使用真实的 YYYY-MM-DD 日期。" };
  const scope = params.get("scope") ?? DEFAULT_PRICE_VOLUME_URL_STATE.scope;
  if (!SCOPES.has(scope as PriceVolumeUrlScope)) return { ok: false, message: "比较范围参数无效。" };
  const period = readInteger(params.get("period"), DEFAULT_PRICE_VOLUME_URL_STATE.period);
  if (!PERIODS.has(period as PriceVolumePeriod)) return { ok: false, message: "统计周期参数无效。" };
  const stateFilter = params.get("stateFilter") ?? DEFAULT_PRICE_VOLUME_URL_STATE.stateFilter;
  if (!FILTERS.has(stateFilter as PriceVolumeStateFilter)) return { ok: false, message: "状态筛选参数无效。" };
  const sortBy = params.get("sortBy") ?? DEFAULT_PRICE_VOLUME_URL_STATE.sortBy;
  if (!SORT_FIELDS.has(sortBy as PriceVolumeSortBy)) return { ok: false, message: "排序字段参数无效。" };
  const sortDirection = params.get("sortDirection") ?? DEFAULT_PRICE_VOLUME_URL_STATE.sortDirection;
  if (!SORT_DIRECTIONS.has(sortDirection as PriceVolumeSortDirection)) return { ok: false, message: "排序方向参数无效。" };
  const historyRange = readInteger(params.get("historyRange"), DEFAULT_PRICE_VOLUME_URL_STATE.historyRange);
  if (!HISTORY_RANGES.has(historyRange as PriceVolumeHistoryRange)) return { ok: false, message: "历史范围参数无效。" };
  const level1Code = params.get("level1Code");
  const level2Code = params.get("level2Code");
  const sectorCode = params.get("sectorCode");
  for (const [label, code] of [["一级行业", level1Code], ["二级行业", level2Code], ["选中行业", sectorCode]] as const) {
    if (code !== null && !CODE_PATTERN.test(code)) return { ok: false, message: `${label}代码必须使用 BKxxxx.DC 格式。` };
  }
  if (["level1", "level2", "level3"].includes(scope) && (level1Code || level2Code)) return { ok: false, message: "同级总榜不能携带父级行业参数。" };
  if (scope === "level1-children" && (!level1Code || level2Code)) return { ok: false, message: "一级内二级必须且只能选择一级行业。" };
  if (scope === "level2-children" && (!level1Code || !level2Code)) return { ok: false, message: "二级内三级必须同时选择一级和二级行业。" };
  return {
    ok: true,
    value: {
      tradeDate,
      scope: scope as PriceVolumeUrlScope,
      level1Code,
      level2Code,
      period: period as PriceVolumePeriod,
      stateFilter: stateFilter as PriceVolumeStateFilter,
      sortBy: sortBy as PriceVolumeSortBy,
      sortDirection: sortDirection as PriceVolumeSortDirection,
      sectorCode,
      historyRange: historyRange as PriceVolumeHistoryRange,
    },
  };
}

export function buildSectorPriceVolumeSearch(state: PriceVolumeUrlState): string {
  const params = new URLSearchParams();
  if (state.tradeDate) params.set("tradeDate", state.tradeDate);
  if (state.scope !== DEFAULT_PRICE_VOLUME_URL_STATE.scope) params.set("scope", state.scope);
  if (state.level1Code) params.set("level1Code", state.level1Code);
  if (state.level2Code) params.set("level2Code", state.level2Code);
  if (state.period !== DEFAULT_PRICE_VOLUME_URL_STATE.period) params.set("period", String(state.period));
  if (state.stateFilter !== DEFAULT_PRICE_VOLUME_URL_STATE.stateFilter) params.set("stateFilter", state.stateFilter);
  if (state.sortBy !== DEFAULT_PRICE_VOLUME_URL_STATE.sortBy) params.set("sortBy", state.sortBy);
  if (state.sortDirection !== DEFAULT_PRICE_VOLUME_URL_STATE.sortDirection) params.set("sortDirection", state.sortDirection);
  if (state.sectorCode) params.set("sectorCode", state.sectorCode);
  if (state.historyRange !== DEFAULT_PRICE_VOLUME_URL_STATE.historyRange) params.set("historyRange", String(state.historyRange));
  const query = params.toString();
  return query ? `?${query}` : "";
}

function readInteger(value: string | null, fallback: number): number {
  if (value === null) return fallback;
  if (!/^\d+$/.test(value)) return Number.NaN;
  return Number(value);
}

function isIsoDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}
