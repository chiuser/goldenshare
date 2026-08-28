import type {
  SectorDualMomentumPeriod,
  SectorDualMomentumResultView,
  SectorDualMomentumThreshold,
  SectorDualMomentumUrlScope,
  SectorDualMomentumUrlState,
} from "./sectorDualMomentumTypes";

export const DEFAULT_DUAL_MOMENTUM_URL_STATE: SectorDualMomentumUrlState = {
  market: "CN_A",
  debug: false,
  tradeDate: null,
  scope: "level1",
  level1Code: null,
  level2Code: null,
  period: 20,
  threshold: 80,
  resultView: "qualified",
  sectorCode: null,
};

const ALLOWED_KEYS = new Set([
  "market", "debug", "tradeDate", "scope", "level1Code",
  "level2Code", "period", "threshold", "resultView", "sectorCode",
]);
const SCOPES = new Set<SectorDualMomentumUrlScope>([
  "level1", "level2", "level3", "level1-children", "level2-children",
]);
const PERIODS = new Set<SectorDualMomentumPeriod>([5, 10, 20, 30]);
const THRESHOLDS = new Set<SectorDualMomentumThreshold>([70, 80, 90]);
const RESULT_VIEWS = new Set<SectorDualMomentumResultView>(["qualified", "all"]);
const SECTOR_CODE_PATTERN = /^BK[0-9]{4}\.DC$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export type SectorDualMomentumUrlParseResult =
  | { ok: true; value: SectorDualMomentumUrlState }
  | { ok: false; message: string };

export function parseSectorDualMomentumUrlState(search: string): SectorDualMomentumUrlParseResult {
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
  if (tradeDate !== null && !isIsoDate(tradeDate)) return { ok: false, message: "交易日必须使用 YYYY-MM-DD 格式。" };
  const scope = params.get("scope") ?? DEFAULT_DUAL_MOMENTUM_URL_STATE.scope;
  if (!SCOPES.has(scope as SectorDualMomentumUrlScope)) return { ok: false, message: "比较范围参数无效。" };
  const period = readInteger(params.get("period"), DEFAULT_DUAL_MOMENTUM_URL_STATE.period);
  if (!PERIODS.has(period as SectorDualMomentumPeriod)) return { ok: false, message: "观察周期参数无效。" };
  const threshold = readInteger(params.get("threshold"), DEFAULT_DUAL_MOMENTUM_URL_STATE.threshold);
  if (!THRESHOLDS.has(threshold as SectorDualMomentumThreshold)) return { ok: false, message: "领先阈值参数无效。" };
  const resultView = params.get("resultView") ?? DEFAULT_DUAL_MOMENTUM_URL_STATE.resultView;
  if (!RESULT_VIEWS.has(resultView as SectorDualMomentumResultView)) return { ok: false, message: "结果视图参数无效。" };

  const level1Code = params.get("level1Code");
  const level2Code = params.get("level2Code");
  const sectorCode = params.get("sectorCode");
  for (const [label, code] of [["一级行业", level1Code], ["二级行业", level2Code], ["选中行业", sectorCode]] as const) {
    if (code !== null && !SECTOR_CODE_PATTERN.test(code)) return { ok: false, message: `${label}代码必须使用 BKxxxx.DC 格式。` };
  }
  return {
    ok: true,
    value: {
      market: "CN_A",
      debug: debug === "1",
      tradeDate,
      scope: scope as SectorDualMomentumUrlScope,
      level1Code,
      level2Code,
      period: period as SectorDualMomentumPeriod,
      threshold: threshold as SectorDualMomentumThreshold,
      resultView: resultView as SectorDualMomentumResultView,
      sectorCode,
    },
  };
}

export function buildSectorDualMomentumSearch(state: SectorDualMomentumUrlState): string {
  const params = new URLSearchParams();
  if (state.debug) params.set("debug", "1");
  if (state.tradeDate) params.set("tradeDate", state.tradeDate);
  if (state.scope !== DEFAULT_DUAL_MOMENTUM_URL_STATE.scope) params.set("scope", state.scope);
  if (state.level1Code) params.set("level1Code", state.level1Code);
  if (state.level2Code) params.set("level2Code", state.level2Code);
  if (state.period !== DEFAULT_DUAL_MOMENTUM_URL_STATE.period) params.set("period", String(state.period));
  if (state.threshold !== DEFAULT_DUAL_MOMENTUM_URL_STATE.threshold) params.set("threshold", String(state.threshold));
  if (state.resultView !== DEFAULT_DUAL_MOMENTUM_URL_STATE.resultView) params.set("resultView", state.resultView);
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
