import type {
  SectorAnalysisMetaResponse,
  SectorAnalysisStatus,
  SectorAnalysisTradingDayResponse,
  SectorHierarchyNodeResponse,
  SectorMomentumHistoryResponse,
  SectorMomentumHistoryViewModel,
  SectorMomentumMetaViewModel,
  SectorMomentumRankingViewModel,
  SectorMomentumRankingsResponse,
  SectorRankingRowResponse,
  SectorRankingRowViewModel,
} from "../model/sectorMomentumTypes";
import { SectorMomentumApiError } from "./sectorMomentumApi";

export function buildSectorMomentumMetaViewModel(payload: unknown): SectorMomentumMetaViewModel {
  const response = requireRecord(payload, "Meta");
  const hierarchy = requireRecord(response.hierarchy, "hierarchy");
  const formula = requireRecord(response.formula, "formula");
  const nodes = requireArray(hierarchy.nodes, "hierarchy.nodes").map(readHierarchyNode);
  const tradeDates = requireArray(response.tradeDates, "tradeDates").map((item) => {
    const row = requireRecord(item, "tradeDates item");
    return {
      tradeDate: requireDate(row.tradeDate, "tradeDate"),
      availability: requireChoice(row.availability, ["COMPLETE", "PARTIAL", "MISSING"], "availability"),
      expectedSectorCount: requireNonNegativeInteger(row.expectedSectorCount, "expectedSectorCount"),
      validSectorCount: requireNonNegativeInteger(row.validSectorCount, "validSectorCount"),
    };
  });
  const coverageStartDate = requireDate(response.coverageStartDate, "coverageStartDate");
  const coverageEndDate = requireDate(response.coverageEndDate, "coverageEndDate");
  if (!tradeDates.length || tradeDates[0]?.tradeDate !== coverageStartDate
      || tradeDates.at(-1)?.tradeDate !== coverageEndDate) {
    throw contractError("交易日覆盖区间与日期列表不一致");
  }
  ensureAscendingUnique(tradeDates.map((item) => item.tradeDate), "tradeDates");

  const typed: SectorAnalysisMetaResponse = {
    formula: {
      formulaKey: requireLiteral(formula.formulaKey, "sector-cross-sectional-momentum", "formulaKey"),
      formulaVersion: requireLiteral(formula.formulaVersion, 1, "formulaVersion"),
      periods: readExactNumberChoices(formula.periods, [1, 5, 10, 20, 30], "periods"),
      historyRanges: readExactNumberChoices(formula.historyRanges, [20, 30, 60], "historyRanges"),
      scopes: readExactStringChoices(
        formula.scopes,
        ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"],
        "scopes",
      ),
      directions: readExactStringChoices(formula.directions, ["GAINERS", "LOSERS"], "directions"),
    },
    hierarchy: {
      hierarchyVersion: requireString(hierarchy.hierarchyVersion, "hierarchyVersion"),
      publishedAt: requireString(hierarchy.publishedAt, "publishedAt"),
      nodes,
    },
    coverageStartDate,
    coverageEndDate,
    tradeDates,
  };
  return {
    ...typed,
    level1Nodes: nodes.filter((node) => node.industryLevel === 1),
    level2Nodes: nodes.filter((node) => node.industryLevel === 2),
    level3Nodes: nodes.filter((node) => node.industryLevel === 3),
  };
}

export function buildSectorMomentumRankingViewModel(payload: unknown):
  | SectorMomentumRankingViewModel
  | { status: "EMPTY"; message: string; tradingDay: SectorAnalysisTradingDayResponse }
  | { status: "ERROR"; message: string; tradingDay: SectorAnalysisTradingDayResponse } {
  const response = readRankingsResponse(payload);
  if (response.status === "EMPTY" || response.status === "ERROR") {
    return {
      status: response.status,
      message: response.message ?? (response.status === "EMPTY" ? "当前条件下暂无可计算数据。" : "板块分析加载失败。"),
      tradingDay: response.tradingDay,
    };
  }
  if (!response.ranking) throw contractError("READY/DELAYED 缺少 ranking");
  const maxAbs = response.ranking.rows.reduce(
    (maximum, row) => Math.max(maximum, Math.abs(row.returnPct ?? 0)),
    0,
  );
  return {
    ...response.ranking,
    rows: response.ranking.rows.map((row) => buildRankingRowViewModel(row, maxAbs)),
    tradingDay: response.tradingDay,
    pageStatus: response.pageStatus,
    status: response.status,
  };
}

export function buildSectorMomentumHistoryViewModel(payload: unknown):
  | SectorMomentumHistoryViewModel
  | { status: "EMPTY"; message: string; tradingDay: SectorAnalysisTradingDayResponse }
  | { status: "ERROR"; message: string; tradingDay: SectorAnalysisTradingDayResponse } {
  const response = readHistoryResponse(payload);
  if (response.status === "EMPTY" || response.status === "ERROR") {
    return {
      status: response.status,
      message: response.message ?? (response.status === "EMPTY" ? "当前行业暂无历史数据。" : "历史趋势加载失败。"),
      tradingDay: response.tradingDay,
    };
  }
  if (!response.detail) throw contractError("READY/DELAYED 缺少 detail");
  const returnDates = response.rollingReturns.map((point) => point.tradeDate);
  const rankDates = response.historicalRanks.map((point) => point.tradeDate);
  if (returnDates.join("|") !== rankDates.join("|")) throw contractError("两条历史序列日期不一致");
  ensureAscendingUnique(returnDates, "history dates");
  return {
    detail: response.detail,
    points: response.rollingReturns.map((point, index) => {
      const rank = response.historicalRanks[index]!;
      return {
        tradeDate: point.tradeDate,
        returnPct: point.returnPct,
        strengthRank: rank.strengthRank,
        calculableCount: rank.calculableCount,
        totalCount: rank.totalCount,
        percentile: rank.percentile,
      };
    }),
    tradingDay: response.tradingDay,
    pageStatus: response.pageStatus,
    status: response.status,
  };
}

export function formatReturnPct(value: number | null): string {
  if (value === null) return "--";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}%`;
}

export function formatPercentile(value: number | null): string {
  return value === null ? "--" : `${value.toFixed(1)}%`;
}

export function formatRank(rank: number | null, count: number): string {
  return rank === null ? "--" : `${rank} / ${count}`;
}

function buildRankingRowViewModel(row: SectorRankingRowResponse, maxAbs: number): SectorRankingRowViewModel {
  return {
    ...row,
    returnText: formatReturnPct(row.returnPct),
    returnBarWidthPct: row.returnPct === null || maxAbs === 0
      ? 0
      : Math.min(50, Math.abs(row.returnPct) / maxAbs * 50),
    percentileText: formatPercentile(row.percentile),
    strengthRankText: row.strengthRank === null ? "--" : String(row.strengthRank),
    directionClass: row.returnPct === null ? "muted" : row.returnPct > 0 ? "up" : row.returnPct < 0 ? "down" : "flat",
  };
}

function readRankingsResponse(payload: unknown): SectorMomentumRankingsResponse {
  const row = requireRecord(payload, "rankings response");
  const status = readStatus(row.status);
  const tradingDay = readTradingDay(row.tradingDay);
  const pageStatus = readPageStatus(row.pageStatus, status);
  const rankingValue = row.ranking;
  let ranking: SectorMomentumRankingsResponse["ranking"] = null;
  if (rankingValue !== null) {
    const source = requireRecord(rankingValue, "ranking");
    const rows = requireArray(source.rows, "ranking.rows").map(readRankingRow);
    const totalCount = requireNonNegativeInteger(source.totalCount, "totalCount");
    const calculableCount = requireNonNegativeInteger(source.calculableCount, "calculableCount");
    if (rows.length !== totalCount || rows.filter((item) => item.returnPct !== null).length !== calculableCount) {
      throw contractError("榜单计数与行不一致");
    }
    if (rows.some((item, index) => item.listPosition !== index + 1)) throw contractError("榜单序号不连续");
    ranking = {
      formulaKey: requireLiteral(source.formulaKey, "sector-cross-sectional-momentum", "formulaKey"),
      formulaVersion: requireLiteral(source.formulaVersion, 1, "formulaVersion"),
      hierarchyVersion: requireString(source.hierarchyVersion, "hierarchyVersion"),
      scope: requireChoice(source.scope, ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"], "scope"),
      period: requireChoice(source.period, [1, 5, 10, 20, 30], "period"),
      direction: requireChoice(source.direction, ["GAINERS", "LOSERS"], "direction"),
      parentSelection: readParentSelection(source.parentSelection),
      totalCount,
      calculableCount,
      rows,
    };
  }
  if ((status === "READY" || status === "DELAYED") && (!ranking || ranking.calculableCount === 0)) {
    throw contractError("正常状态缺少可计算榜单");
  }
  if ((status === "EMPTY" || status === "ERROR") && ranking !== null) throw contractError("异常状态携带榜单数据");
  return {
    status,
    tradingDay,
    pageStatus,
    ranking,
    message: readNullableString(row.message, "message"),
    exceptionCode: readNullableString(row.exceptionCode, "exceptionCode"),
  };
}

function readHistoryResponse(payload: unknown): SectorMomentumHistoryResponse {
  const row = requireRecord(payload, "history response");
  const status = readStatus(row.status);
  const tradingDay = readTradingDay(row.tradingDay);
  const pageStatus = readPageStatus(row.pageStatus, status);
  const detail = row.detail === null ? null : readDetail(row.detail);
  const rollingReturns = requireArray(row.rollingReturns, "rollingReturns").map((item) => {
    const point = requireRecord(item, "rollingReturns item");
    return { tradeDate: requireDate(point.tradeDate, "tradeDate"), returnPct: readNullableFinite(point.returnPct, "returnPct") };
  });
  const historicalRanks = requireArray(row.historicalRanks, "historicalRanks").map((item) => {
    const point = requireRecord(item, "historicalRanks item");
    return {
      tradeDate: requireDate(point.tradeDate, "tradeDate"),
      strengthRank: readNullablePositiveInteger(point.strengthRank, "strengthRank"),
      calculableCount: requireNonNegativeInteger(point.calculableCount, "calculableCount"),
      totalCount: requireNonNegativeInteger(point.totalCount, "totalCount"),
      percentile: readNullableFinite(point.percentile, "percentile"),
    };
  });
  if ((status === "READY" || status === "DELAYED") && (!detail || rollingReturns.length === 0)) {
    throw contractError("正常状态缺少历史详情");
  }
  if ((status === "EMPTY" || status === "ERROR") && (detail || rollingReturns.length || historicalRanks.length)) {
    throw contractError("异常状态携带历史数据");
  }
  return {
    status,
    tradingDay,
    pageStatus,
    detail,
    rollingReturns,
    historicalRanks,
    message: readNullableString(row.message, "message"),
    exceptionCode: readNullableString(row.exceptionCode, "exceptionCode"),
  };
}

function readHierarchyNode(value: unknown): SectorHierarchyNodeResponse {
  const row = requireRecord(value, "hierarchy node");
  return {
    sectorCode: requireSectorCode(row.sectorCode, "sectorCode"),
    sectorName: requireString(row.sectorName, "sectorName"),
    industryLevel: requireChoice(row.industryLevel, [1, 2, 3], "industryLevel"),
    parentSectorCode: readNullableSectorCode(row.parentSectorCode, "parentSectorCode"),
    parentSectorName: readNullableString(row.parentSectorName, "parentSectorName"),
    rootSectorCode: requireSectorCode(row.rootSectorCode, "rootSectorCode"),
    rootSectorName: requireString(row.rootSectorName, "rootSectorName"),
    hierarchyPath: requireString(row.hierarchyPath, "hierarchyPath"),
    displayOrder: requireNonNegativeInteger(row.displayOrder, "displayOrder"),
    isLeaf: requireBoolean(row.isLeaf, "isLeaf"),
  };
}

function readRankingRow(value: unknown): SectorRankingRowResponse {
  const row = requireRecord(value, "ranking row");
  const returnPct = readNullableFinite(row.returnPct, "returnPct");
  const strengthRank = readNullablePositiveInteger(row.strengthRank, "strengthRank");
  const percentile = readNullableFinite(row.percentile, "percentile");
  if ([returnPct, strengthRank, percentile].some((item) => item === null)
      && ![returnPct, strengthRank, percentile].every((item) => item === null)) {
    throw contractError("收益、排名和百分位必须同时存在或同时缺失");
  }
  return {
    listPosition: requirePositiveInteger(row.listPosition, "listPosition"),
    strengthRank,
    sectorCode: requireSectorCode(row.sectorCode, "sectorCode"),
    sectorName: requireString(row.sectorName, "sectorName"),
    industryLevel: requireChoice(row.industryLevel, [1, 2, 3], "industryLevel"),
    parentSectorCode: readNullableSectorCode(row.parentSectorCode, "parentSectorCode"),
    parentSectorName: readNullableString(row.parentSectorName, "parentSectorName"),
    hierarchyPath: requireString(row.hierarchyPath, "hierarchyPath"),
    returnPct,
    percentile,
    canDrillDown: requireBoolean(row.canDrillDown, "canDrillDown"),
  };
}

function readDetail(value: unknown): SectorMomentumHistoryResponse["detail"] {
  const row = requireRecord(value, "detail");
  return {
    sectorCode: requireSectorCode(row.sectorCode, "sectorCode"),
    sectorName: requireString(row.sectorName, "sectorName"),
    industryLevel: requireChoice(row.industryLevel, [1, 2, 3], "industryLevel"),
    hierarchyPath: requireString(row.hierarchyPath, "hierarchyPath"),
    scopeTitle: requireString(row.scopeTitle, "scopeTitle"),
    returnPct: readNullableFinite(row.returnPct, "returnPct"),
    percentile: readNullableFinite(row.percentile, "percentile"),
    currentScopeStrengthRank: readNullablePositiveInteger(row.currentScopeStrengthRank, "currentScopeStrengthRank"),
    currentScopeCalculableCount: requireNonNegativeInteger(row.currentScopeCalculableCount, "currentScopeCalculableCount"),
    currentScopeTotalCount: requireNonNegativeInteger(row.currentScopeTotalCount, "currentScopeTotalCount"),
    globalLevelStrengthRank: readNullablePositiveInteger(row.globalLevelStrengthRank, "globalLevelStrengthRank"),
    globalLevelCalculableCount: requireNonNegativeInteger(row.globalLevelCalculableCount, "globalLevelCalculableCount"),
    globalLevelTotalCount: requireNonNegativeInteger(row.globalLevelTotalCount, "globalLevelTotalCount"),
    parentStrengthRank: readNullablePositiveInteger(row.parentStrengthRank, "parentStrengthRank"),
    parentCalculableCount: readNullableNonNegativeInteger(row.parentCalculableCount, "parentCalculableCount"),
    parentTotalCount: readNullableNonNegativeInteger(row.parentTotalCount, "parentTotalCount"),
    formulaKey: requireLiteral(row.formulaKey, "sector-cross-sectional-momentum", "formulaKey"),
    formulaVersion: requireLiteral(row.formulaVersion, 1, "formulaVersion"),
    hierarchyVersion: requireString(row.hierarchyVersion, "hierarchyVersion"),
  };
}

function readTradingDay(value: unknown): SectorAnalysisTradingDayResponse {
  const row = requireRecord(value, "tradingDay");
  return {
    expectedTradeDate: requireDate(row.expectedTradeDate, "expectedTradeDate"),
    observedTradeDate: readNullableDate(row.observedTradeDate, "observedTradeDate"),
    expectedAvailability: requireChoice(row.expectedAvailability, ["COMPLETE", "PARTIAL", "MISSING"], "expectedAvailability"),
    expectedSectorCount: requireNonNegativeInteger(row.expectedSectorCount, "expectedSectorCount"),
    expectedValidSectorCount: requireNonNegativeInteger(row.expectedValidSectorCount, "expectedValidSectorCount"),
    observedAvailability: row.observedAvailability === null
      ? null
      : requireChoice(row.observedAvailability, ["COMPLETE", "PARTIAL", "MISSING"] as const, "observedAvailability"),
    observedValidSectorCount: requireNonNegativeInteger(row.observedValidSectorCount, "observedValidSectorCount"),
  };
}

function readPageStatus(value: unknown, expected: SectorAnalysisStatus) {
  const row = requireRecord(value, "pageStatus");
  const status = readStatus(row.status);
  if (status !== expected) throw contractError("pageStatus 与响应状态不一致");
  return {
    status,
    displayText: requireString(row.displayText, "displayText"),
    asOfTime: requireString(row.asOfTime, "asOfTime"),
  };
}

function readParentSelection(value: unknown) {
  const row = requireRecord(value, "parentSelection");
  return {
    level1Code: readNullableSectorCode(row.level1Code, "level1Code"),
    level1Name: readNullableString(row.level1Name, "level1Name"),
    level2Code: readNullableSectorCode(row.level2Code, "level2Code"),
    level2Name: readNullableString(row.level2Name, "level2Name"),
  };
}

function readStatus(value: unknown): SectorAnalysisStatus {
  return requireChoice(value, ["READY", "DELAYED", "EMPTY", "ERROR"], "status");
}

function requireRecord(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw contractError(`${field} 必须是对象`);
  return value as Record<string, unknown>;
}

function requireArray(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw contractError(`${field} 必须是数组`);
  return value;
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string" || !value) throw contractError(`${field} 必须是非空字符串`);
  return value;
}

function requireBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw contractError(`${field} 必须是布尔值`);
  return value;
}

function requireFinite(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw contractError(`${field} 必须是有限数值`);
  return value;
}

function readNullableFinite(value: unknown, field: string): number | null {
  return value === null ? null : requireFinite(value, field);
}

function requireNonNegativeInteger(value: unknown, field: string): number {
  const number = requireFinite(value, field);
  if (!Number.isInteger(number) || number < 0) throw contractError(`${field} 必须是非负整数`);
  return number;
}

function requirePositiveInteger(value: unknown, field: string): number {
  const number = requireNonNegativeInteger(value, field);
  if (number < 1) throw contractError(`${field} 必须是正整数`);
  return number;
}

function readNullablePositiveInteger(value: unknown, field: string): number | null {
  return value === null ? null : requirePositiveInteger(value, field);
}

function readNullableNonNegativeInteger(value: unknown, field: string): number | null {
  return value === null ? null : requireNonNegativeInteger(value, field);
}

function requireDate(value: unknown, field: string): string {
  const date = requireString(value, field);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw contractError(`${field} 必须是日期`);
  return date;
}

function readNullableDate(value: unknown, field: string): string | null {
  return value === null ? null : requireDate(value, field);
}

function requireSectorCode(value: unknown, field: string): string {
  const code = requireString(value, field);
  if (!/^BK[0-9]{4}\.DC$/.test(code)) throw contractError(`${field} 不是合法行业代码`);
  return code;
}

function readNullableSectorCode(value: unknown, field: string): string | null {
  return value === null ? null : requireSectorCode(value, field);
}

function readNullableString(value: unknown, field: string): string | null {
  return value === null ? null : requireString(value, field);
}

function requireChoice<T extends string | number>(value: unknown, allowed: readonly T[], field: string): T {
  if (!allowed.includes(value as T)) throw contractError(`${field} 使用了未批准的枚举`);
  return value as T;
}

function requireLiteral<T extends string | number>(value: unknown, expected: T, field: string): T {
  if (value !== expected) throw contractError(`${field} 版本不匹配`);
  return expected;
}

function readExactNumberChoices<T extends number>(value: unknown, expected: readonly T[], field: string): T[] {
  const actual = requireArray(value, field).map((item) => requireChoice(item, expected, field));
  if (actual.join("|") !== expected.join("|")) throw contractError(`${field} 合同不完整`);
  return actual;
}

function readExactStringChoices<T extends string>(value: unknown, expected: readonly T[], field: string): T[] {
  const actual = requireArray(value, field).map((item) => requireChoice(item, expected, field));
  if (actual.join("|") !== expected.join("|")) throw contractError(`${field} 合同不完整`);
  return actual;
}

function ensureAscendingUnique(values: string[], field: string) {
  if (values.join("|") !== [...new Set(values)].sort().join("|")) throw contractError(`${field} 必须严格升序且唯一`);
}

function contractError(message: string): SectorMomentumApiError {
  return new SectorMomentumApiError(`板块分析数据合同无效：${message}`, "SA_QUERY_FAILED", 502);
}
