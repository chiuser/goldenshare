import type {
  SectorHistoryRange,
  SectorMomentumPeriod,
  SectorMomentumUrlDirection,
  SectorMomentumUrlScope,
  SectorMomentumUrlState,
} from "./sectorMomentumTypes";

const DEFAULT_STATE: SectorMomentumUrlState = {
  market: "CN_A",
  debug: false,
  tradeDate: null,
  scope: "level1",
  level1Code: null,
  level2Code: null,
  period: 1,
  direction: "gainers",
  range: 20,
  sectorCode: null,
};

const ALLOWED_KEYS = new Set([
  "market",
  "debug",
  "tradeDate",
  "scope",
  "level1Code",
  "level2Code",
  "period",
  "direction",
  "range",
  "sectorCode",
]);
const SCOPES = new Set<SectorMomentumUrlScope>([
  "level1",
  "level2",
  "level3",
  "level1-children",
  "level2-children",
]);
const PERIODS = new Set<SectorMomentumPeriod>([1, 5, 10, 20, 30]);
const DIRECTIONS = new Set<SectorMomentumUrlDirection>(["gainers", "losers"]);
const RANGES = new Set<SectorHistoryRange>([20, 30, 60]);
const SECTOR_CODE_PATTERN = /^BK[0-9]{4}\.DC$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export type SectorMomentumUrlParseResult =
  | { ok: true; value: SectorMomentumUrlState }
  | { ok: false; message: string };

export function parseSectorMomentumUrlState(search: string): SectorMomentumUrlParseResult {
  const params = new URLSearchParams(search);
  for (const key of new Set(params.keys())) {
    if (!ALLOWED_KEYS.has(key)) return { ok: false, message: `不支持的页面参数：${key}` };
    if (params.getAll(key).length > 1) return { ok: false, message: `页面参数不能重复：${key}` };
  }

  const market = params.get("market");
  if (market !== null && market !== "CN_A") return { ok: false, message: "当前只支持 A 股市场。" };
  const debug = params.get("debug");
  if (debug !== null && debug !== "0" && debug !== "1") {
    return { ok: false, message: "debug 只允许 0 或 1。" };
  }

  const tradeDate = params.get("tradeDate");
  if (tradeDate !== null && !isIsoDate(tradeDate)) {
    return { ok: false, message: "交易日必须使用 YYYY-MM-DD 格式。" };
  }
  const scope = params.get("scope") ?? DEFAULT_STATE.scope;
  if (!SCOPES.has(scope as SectorMomentumUrlScope)) return { ok: false, message: "比较范围参数无效。" };
  const period = readInteger(params.get("period"), DEFAULT_STATE.period);
  if (!PERIODS.has(period as SectorMomentumPeriod)) return { ok: false, message: "统计周期参数无效。" };
  const direction = params.get("direction") ?? DEFAULT_STATE.direction;
  if (!DIRECTIONS.has(direction as SectorMomentumUrlDirection)) return { ok: false, message: "排行方向参数无效。" };
  const range = readInteger(params.get("range"), DEFAULT_STATE.range);
  if (!RANGES.has(range as SectorHistoryRange)) return { ok: false, message: "趋势范围参数无效。" };

  const level1Code = params.get("level1Code");
  const level2Code = params.get("level2Code");
  const sectorCode = params.get("sectorCode");
  for (const [label, code] of [["一级行业", level1Code], ["二级行业", level2Code], ["选中行业", sectorCode]] as const) {
    if (code !== null && !SECTOR_CODE_PATTERN.test(code)) {
      return { ok: false, message: `${label}代码必须使用 BKxxxx.DC 格式。` };
    }
  }

  return {
    ok: true,
    value: {
      market: "CN_A",
      debug: debug === "1",
      tradeDate,
      scope: scope as SectorMomentumUrlScope,
      level1Code,
      level2Code,
      period: period as SectorMomentumPeriod,
      direction: direction as SectorMomentumUrlDirection,
      range: range as SectorHistoryRange,
      sectorCode,
    },
  };
}

export function buildSectorMomentumSearch(state: SectorMomentumUrlState): string {
  const params = new URLSearchParams();
  if (state.debug) params.set("debug", "1");
  if (state.tradeDate) params.set("tradeDate", state.tradeDate);
  if (state.scope !== DEFAULT_STATE.scope) params.set("scope", state.scope);
  if (state.level1Code) params.set("level1Code", state.level1Code);
  if (state.level2Code) params.set("level2Code", state.level2Code);
  if (state.period !== DEFAULT_STATE.period) params.set("period", String(state.period));
  if (state.direction !== DEFAULT_STATE.direction) params.set("direction", state.direction);
  if (state.range !== DEFAULT_STATE.range) params.set("range", String(state.range));
  if (state.sectorCode) params.set("sectorCode", state.sectorCode);
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
