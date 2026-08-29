import type {
  SectorMemberBreadthHistoryRange,
  SectorMemberBreadthMaPeriod,
  SectorMemberBreadthUrlDirection,
  SectorMemberBreadthUrlMetric,
  SectorMemberBreadthUrlScope,
  SectorMemberBreadthUrlState,
} from "./sectorMemberBreadthTypes";

export const DEFAULT_SECTOR_MEMBER_BREADTH_URL_STATE: SectorMemberBreadthUrlState = {
  market: "CN_A",
  tradeDate: null,
  scope: "level1",
  level1Code: null,
  level2Code: null,
  direction: "up",
  metric: "member-count",
  maPeriod: 20,
  historyRange: 20,
  sectorCode: null,
};

const ALLOWED_KEYS = new Set(["market", "tradeDate", "scope", "level1Code", "level2Code", "direction", "metric", "maPeriod", "historyRange", "sectorCode"]);
const SCOPES = new Set<SectorMemberBreadthUrlScope>(["level1", "level2", "level3", "level1-children", "level2-children"]);
const DIRECTIONS = new Set<SectorMemberBreadthUrlDirection>(["up", "down"]);
const METRICS = new Set<SectorMemberBreadthUrlMetric>(["member-count", "turnover", "ma-position"]);
const MA_PERIODS = new Set<SectorMemberBreadthMaPeriod>([5, 10, 15, 20, 30, 60]);
const HISTORY_RANGES = new Set<SectorMemberBreadthHistoryRange>([20, 30, 60]);
const CODE_PATTERN = /^BK[0-9]{4}\.DC$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export type SectorMemberBreadthUrlParseResult =
  | { ok: true; value: SectorMemberBreadthUrlState }
  | { ok: false; message: string };

export function parseSectorMemberBreadthUrlState(search: string): SectorMemberBreadthUrlParseResult {
  const params = new URLSearchParams(search);
  for (const key of new Set(params.keys())) {
    if (!ALLOWED_KEYS.has(key)) return { ok: false, message: `不支持的页面参数：${key}` };
    if (params.getAll(key).length > 1) return { ok: false, message: `页面参数不能重复：${key}` };
  }
  if (params.get("market") !== null && params.get("market") !== "CN_A") return { ok: false, message: "当前只支持 A 股市场。" };
  const tradeDate = params.get("tradeDate");
  if (tradeDate !== null && !isIsoDate(tradeDate)) return { ok: false, message: "交易日必须使用 YYYY-MM-DD 格式。" };
  const scope = params.get("scope") ?? DEFAULT_SECTOR_MEMBER_BREADTH_URL_STATE.scope;
  const direction = params.get("direction") ?? DEFAULT_SECTOR_MEMBER_BREADTH_URL_STATE.direction;
  const metric = params.get("metric") ?? DEFAULT_SECTOR_MEMBER_BREADTH_URL_STATE.metric;
  const maPeriod = readInteger(params.get("maPeriod"), DEFAULT_SECTOR_MEMBER_BREADTH_URL_STATE.maPeriod);
  const historyRange = readInteger(params.get("historyRange"), DEFAULT_SECTOR_MEMBER_BREADTH_URL_STATE.historyRange);
  if (!SCOPES.has(scope as SectorMemberBreadthUrlScope)) return { ok: false, message: "比较范围参数无效。" };
  if (!DIRECTIONS.has(direction as SectorMemberBreadthUrlDirection)) return { ok: false, message: "广度方向参数无效。" };
  if (!METRICS.has(metric as SectorMemberBreadthUrlMetric)) return { ok: false, message: "排名指标参数无效。" };
  if (!MA_PERIODS.has(maPeriod as SectorMemberBreadthMaPeriod)) return { ok: false, message: "均线周期参数无效。" };
  if (!HISTORY_RANGES.has(historyRange as SectorMemberBreadthHistoryRange)) return { ok: false, message: "历史范围参数无效。" };
  const level1Code = params.get("level1Code");
  const level2Code = params.get("level2Code");
  const sectorCode = params.get("sectorCode");
  for (const [label, code] of [["一级行业", level1Code], ["二级行业", level2Code], ["选中行业", sectorCode]] as const) {
    if (code !== null && !CODE_PATTERN.test(code)) return { ok: false, message: `${label}代码必须使用 BKxxxx.DC 格式。` };
  }
  if (scope === "level1-children" && !level1Code) return { ok: false, message: "一级内二级必须选择一级行业。" };
  if (scope === "level2-children" && (!level1Code || !level2Code)) return { ok: false, message: "二级内三级必须同时选择一级和二级行业。" };
  if (["level1", "level2", "level3"].includes(scope) && (level1Code || level2Code)) return { ok: false, message: "总榜不能携带父级行业参数。" };
  if (scope === "level1-children" && level2Code) return { ok: false, message: "一级内二级不能携带二级父行业参数。" };
  return { ok: true, value: { market: "CN_A", tradeDate, scope: scope as SectorMemberBreadthUrlScope, level1Code, level2Code, direction: direction as SectorMemberBreadthUrlDirection, metric: metric as SectorMemberBreadthUrlMetric, maPeriod: maPeriod as SectorMemberBreadthMaPeriod, historyRange: historyRange as SectorMemberBreadthHistoryRange, sectorCode } };
}

export function buildSectorMemberBreadthSearch(state: SectorMemberBreadthUrlState): string {
  const params = new URLSearchParams();
  if (state.tradeDate) params.set("tradeDate", state.tradeDate);
  if (state.scope !== "level1") params.set("scope", state.scope);
  if (state.level1Code) params.set("level1Code", state.level1Code);
  if (state.level2Code) params.set("level2Code", state.level2Code);
  if (state.direction !== "up") params.set("direction", state.direction);
  if (state.metric !== "member-count") params.set("metric", state.metric);
  if (state.maPeriod !== 20) params.set("maPeriod", String(state.maPeriod));
  if (state.historyRange !== 20) params.set("historyRange", String(state.historyRange));
  if (state.sectorCode) params.set("sectorCode", state.sectorCode);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function readInteger(value: string | null, fallback: number): number { return value === null ? fallback : /^\d+$/.test(value) ? Number(value) : Number.NaN; }
function isIsoDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}
