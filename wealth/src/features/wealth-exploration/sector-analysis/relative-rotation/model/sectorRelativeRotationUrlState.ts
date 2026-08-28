import type {
  SectorRelativeRotationPeriod,
  SectorRelativeRotationQuadrantFilter,
  SectorRelativeRotationTrailLength,
  SectorRelativeRotationUrlScope,
  SectorRelativeRotationUrlState,
} from "./sectorRelativeRotationTypes";

export const DEFAULT_RELATIVE_ROTATION_URL_STATE: SectorRelativeRotationUrlState = {
  market: "CN_A",
  debug: false,
  tradeDate: null,
  scope: "level1",
  level1Code: null,
  level2Code: null,
  period: 20,
  trailLength: 20,
  sectorCode: null,
  quadrant: "all",
  search: "",
};

const ALLOWED_KEYS = new Set([
  "market", "debug", "tradeDate", "scope", "level1Code", "level2Code",
  "period", "trailLength", "sectorCode", "quadrant", "search",
]);
const SCOPES = new Set<SectorRelativeRotationUrlScope>(["level1", "level2", "level3", "level1-children", "level2-children"]);
const PERIODS = new Set<SectorRelativeRotationPeriod>([5, 10, 20, 30]);
const TRAIL_LENGTHS = new Set<SectorRelativeRotationTrailLength>([20, 30, 60]);
const QUADRANTS = new Set<SectorRelativeRotationQuadrantFilter>([
  "all", "leading-improving", "weak-improving", "strong-not-improving", "weak-not-improving",
]);
const CODE_PATTERN = /^BK[0-9]{4}\.DC$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export type SectorRelativeRotationUrlParseResult =
  | { ok: true; value: SectorRelativeRotationUrlState }
  | { ok: false; message: string };

export function parseSectorRelativeRotationUrlState(search: string): SectorRelativeRotationUrlParseResult {
  const params = new URLSearchParams(search);
  for (const key of new Set(params.keys())) {
    if (!ALLOWED_KEYS.has(key)) return { ok: false, message: `不支持的页面参数：${key}` };
    if (params.getAll(key).length > 1) return { ok: false, message: `页面参数不能重复：${key}` };
  }
  const market = params.get("market");
  if (market !== null && market !== "CN_A") return { ok: false, message: "当前只支持 A 股市场。" };
  const debug = params.get("debug");
  if (debug !== null && debug !== "0" && debug !== "1") return { ok: false, message: "debug 只允许 0 或 1。" };
  const tradeDate = params.get("tradeDate");
  if (tradeDate !== null && !isIsoDate(tradeDate)) return { ok: false, message: "交易日必须使用真实的 YYYY-MM-DD 日期。" };
  const scope = params.get("scope") ?? DEFAULT_RELATIVE_ROTATION_URL_STATE.scope;
  if (!SCOPES.has(scope as SectorRelativeRotationUrlScope)) return { ok: false, message: "比较范围参数无效。" };
  const period = readInteger(params.get("period"), DEFAULT_RELATIVE_ROTATION_URL_STATE.period);
  if (!PERIODS.has(period as SectorRelativeRotationPeriod)) return { ok: false, message: "强度周期参数无效。" };
  const trailLength = readInteger(params.get("trailLength"), DEFAULT_RELATIVE_ROTATION_URL_STATE.trailLength);
  if (!TRAIL_LENGTHS.has(trailLength as SectorRelativeRotationTrailLength)) return { ok: false, message: "轨迹长度参数无效。" };
  const quadrant = params.get("quadrant") ?? DEFAULT_RELATIVE_ROTATION_URL_STATE.quadrant;
  if (!QUADRANTS.has(quadrant as SectorRelativeRotationQuadrantFilter)) return { ok: false, message: "象限筛选参数无效。" };
  const searchValue = (params.get("search") ?? "").trim();
  if ([...searchValue].length > 64) return { ok: false, message: "行业搜索最多允许 64 个字符。" };
  const level1Code = params.get("level1Code");
  const level2Code = params.get("level2Code");
  const sectorCode = params.get("sectorCode");
  for (const [label, code] of [["一级行业", level1Code], ["二级行业", level2Code], ["选中行业", sectorCode]] as const) {
    if (code !== null && !CODE_PATTERN.test(code)) return { ok: false, message: `${label}代码必须使用 BKxxxx.DC 格式。` };
  }
  if (["level1", "level2", "level3"].includes(scope) && (level1Code || level2Code)) {
    return { ok: false, message: "同级总榜不能携带父级行业参数。" };
  }
  if (scope === "level1-children" && (!level1Code || level2Code)) {
    return { ok: false, message: "一级内二级必须且只能选择一级行业。" };
  }
  if (scope === "level2-children" && (!level1Code || !level2Code)) {
    return { ok: false, message: "二级内三级必须同时选择一级和二级行业。" };
  }
  return {
    ok: true,
    value: {
      market: "CN_A",
      debug: debug === "1",
      tradeDate,
      scope: scope as SectorRelativeRotationUrlScope,
      level1Code,
      level2Code,
      period: period as SectorRelativeRotationPeriod,
      trailLength: trailLength as SectorRelativeRotationTrailLength,
      sectorCode,
      quadrant: quadrant as SectorRelativeRotationQuadrantFilter,
      search: searchValue,
    },
  };
}
export function buildSectorRelativeRotationSearch(state: SectorRelativeRotationUrlState): string {
  const params = new URLSearchParams();
  if (state.debug) params.set("debug", "1");
  if (state.tradeDate) params.set("tradeDate", state.tradeDate);
  if (state.scope !== DEFAULT_RELATIVE_ROTATION_URL_STATE.scope) params.set("scope", state.scope);
  if (state.level1Code) params.set("level1Code", state.level1Code);
  if (state.level2Code) params.set("level2Code", state.level2Code);
  if (state.period !== DEFAULT_RELATIVE_ROTATION_URL_STATE.period) params.set("period", String(state.period));
  if (state.trailLength !== DEFAULT_RELATIVE_ROTATION_URL_STATE.trailLength) params.set("trailLength", String(state.trailLength));
  if (state.sectorCode) params.set("sectorCode", state.sectorCode);
  if (state.quadrant !== DEFAULT_RELATIVE_ROTATION_URL_STATE.quadrant) params.set("quadrant", state.quadrant);
  if (state.search) params.set("search", state.search);
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
