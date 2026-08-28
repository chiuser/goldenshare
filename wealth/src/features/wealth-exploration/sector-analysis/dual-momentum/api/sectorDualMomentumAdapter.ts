import type {
  DualMomentumAbsoluteStatus,
  DualMomentumCoordinateStatus,
  DualMomentumDisplayStatus,
  DualMomentumMissingReason,
  DualMomentumQualificationStatus,
  DualMomentumRelativeStatus,
  SectorAvailability,
  SectorDualMomentumMetaViewModel,
  SectorDualMomentumPeriod,
  SectorDualMomentumResultsAdapterResult,
  SectorDualMomentumResultsRequest,
  SectorDualMomentumResultsViewModel,
  SectorDualMomentumRowViewModel,
  SectorDualMomentumScope,
  SectorDualMomentumStatus,
  SectorDualMomentumThreshold,
  SectorHierarchyNodeResponse,
  SectorPageStatusResponse,
  SectorTradingDayResponse,
  SectorTradeDateAvailabilityResponse,
} from "../model/sectorDualMomentumTypes";

const SCOPES: SectorDualMomentumScope[] = [
  "LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN",
];
const PERIODS: SectorDualMomentumPeriod[] = [5, 10, 20, 30];
const THRESHOLDS: SectorDualMomentumThreshold[] = [70, 80, 90];
const AVAILABILITIES: SectorAvailability[] = ["COMPLETE", "PARTIAL", "MISSING"];
const STATUSES: SectorDualMomentumStatus[] = ["READY", "DELAYED", "EMPTY", "ERROR"];
const ABSOLUTE_STATUSES: DualMomentumAbsoluteStatus[] = ["POSITIVE", "NOT_POSITIVE", "UNAVAILABLE"];
const RELATIVE_STATUSES: DualMomentumRelativeStatus[] = ["LEADING", "NOT_LEADING", "SAMPLE_INSUFFICIENT", "UNAVAILABLE"];
const QUALIFICATION_STATUSES: DualMomentumQualificationStatus[] = ["QUALIFIED", "NOT_QUALIFIED", "NOT_EVALUATED"];
const COORDINATE_STATUSES: DualMomentumCoordinateStatus[] = ["PLOTTABLE", "UNAVAILABLE"];
const DISPLAY_STATUSES: DualMomentumDisplayStatus[] = [
  "QUALIFIED", "UP_NOT_LEADING", "NOT_UP_LEADING", "NOT_UP_NOT_LEADING", "SAMPLE_INSUFFICIENT", "DATA_INSUFFICIENT",
];
const MISSING_REASONS: DualMomentumMissingReason[] = [
  "HISTORY_INSUFFICIENT", "DATE_MISSING", "CLOSE_MISSING", "CLOSE_NON_POSITIVE", "PCT_CHANGE_MISSING",
];
const CODE_PATTERN = /^BK[0-9]{4}\.DC$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export class SectorDualMomentumContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SectorDualMomentumContractError";
  }
}

export function buildSectorDualMomentumMetaViewModel(payload: unknown): SectorDualMomentumMetaViewModel {
  const root = exactRecord(payload, [
    "status", "tradingDay", "pageStatus", "message", "exceptionCode", "debugInfo",
    "formula", "defaults", "hierarchy", "coverageStartDate", "coverageEndDate", "tradeDates",
  ], "双动量 Meta");
  const status = enumValue(root.status, ["READY", "DELAYED"] as const, "Meta status");
  const tradingDay = parseTradingDay(root.tradingDay);
  const pageStatus = parsePageStatus(root.pageStatus);
  nullableString(root.message, "Meta message");
  const exceptionCode = nullableString(root.exceptionCode, "Meta exceptionCode");
  parseDebugInfo(root.debugInfo);
  validateStatusContract(status, tradingDay, pageStatus, exceptionCode);

  const formula = exactRecord(root.formula, [
    "formulaKey", "formulaVersion", "basisFormulaKey", "basisFormulaVersion",
    "periods", "leadingThresholds", "minimumGroupSize", "scopes",
  ], "双动量公式");
  literal(formula.formulaKey, "sector-dual-momentum", "formulaKey");
  literal(formula.formulaVersion, 1, "formulaVersion");
  literal(formula.basisFormulaKey, "sector-cross-sectional-momentum", "basisFormulaKey");
  literal(formula.basisFormulaVersion, 1, "basisFormulaVersion");
  exactArray(formula.periods, PERIODS, "periods");
  exactArray(formula.leadingThresholds, THRESHOLDS, "leadingThresholds");
  literal(formula.minimumGroupSize, 3, "minimumGroupSize");
  exactArray(formula.scopes, SCOPES, "scopes");

  const defaults = exactRecord(root.defaults, ["scope", "period", "leadingThreshold", "resultView"], "双动量默认值");
  literal(defaults.scope, "LEVEL_1", "defaults.scope");
  literal(defaults.period, 20, "defaults.period");
  literal(defaults.leadingThreshold, 80, "defaults.leadingThreshold");
  literal(defaults.resultView, "QUALIFIED", "defaults.resultView");

  const hierarchy = exactRecord(root.hierarchy, ["hierarchyVersion", "publishedAt", "nodes"], "行业层级");
  const hierarchyVersion = nonEmptyString(hierarchy.hierarchyVersion, "hierarchyVersion");
  const publishedAt = nonEmptyString(hierarchy.publishedAt, "publishedAt");
  const nodes = arrayValue(hierarchy.nodes, "hierarchy.nodes").map(parseHierarchyNode);
  if (new Set(nodes.map((node) => node.sectorCode)).size !== nodes.length) fail("行业层级代码重复。");

  const coverageStartDate = isoDate(root.coverageStartDate, "coverageStartDate");
  const coverageEndDate = isoDate(root.coverageEndDate, "coverageEndDate");
  const tradeDates = arrayValue(root.tradeDates, "tradeDates").map(parseTradeDateAvailability);
  const dateValues = tradeDates.map((item) => item.tradeDate);
  if (dateValues.length === 0 || !strictlyAscending(dateValues)) fail("交易日必须唯一且升序。 ");
  if (dateValues[0] !== coverageStartDate || dateValues.at(-1) !== coverageEndDate) fail("交易日未覆盖 Meta 日期范围。 ");

  return {
    status,
    tradingDay,
    pageStatus,
    message: root.message as string | null,
    formula: {
      formulaKey: "sector-dual-momentum",
      formulaVersion: 1,
      basisFormulaKey: "sector-cross-sectional-momentum",
      basisFormulaVersion: 1,
      periods: [...PERIODS],
      leadingThresholds: [...THRESHOLDS],
      minimumGroupSize: 3,
      scopes: [...SCOPES],
    },
    defaults: { scope: "LEVEL_1", period: 20, leadingThreshold: 80, resultView: "QUALIFIED" },
    hierarchy: { hierarchyVersion, publishedAt, nodes },
    coverageStartDate,
    coverageEndDate,
    tradeDates,
    level1Nodes: nodes.filter((node) => node.industryLevel === 1),
    level2Nodes: nodes.filter((node) => node.industryLevel === 2),
    level3Nodes: nodes.filter((node) => node.industryLevel === 3),
  };
}

export function buildSectorDualMomentumResultsViewModel(
  payload: unknown,
  request: SectorDualMomentumResultsRequest,
): SectorDualMomentumResultsAdapterResult {
  const root = exactRecord(payload, [
    "status", "tradingDay", "pageStatus", "analysis", "message", "exceptionCode", "debugInfo",
  ], "双动量 Results");
  const status = enumValue(root.status, STATUSES, "Results status");
  const tradingDay = parseTradingDay(root.tradingDay);
  const pageStatus = parsePageStatus(root.pageStatus);
  const message = nullableString(root.message, "Results message");
  const exceptionCode = nullableString(root.exceptionCode, "Results exceptionCode");
  parseDebugInfo(root.debugInfo);
  validateStatusContract(status, tradingDay, pageStatus, exceptionCode);

  if (status === "EMPTY" || status === "ERROR") {
    if (root.analysis !== null) fail("EMPTY/ERROR 不能携带分析事实。 ");
    if (status === "EMPTY" && exceptionCode !== "SA_SOURCE_EMPTY") fail("EMPTY 必须使用 SA_SOURCE_EMPTY。 ");
    if (status === "ERROR" && !["SA_HIERARCHY_UNAVAILABLE", "SA_QUERY_FAILED"].includes(exceptionCode ?? "")) fail("ERROR 异常码非法。 ");
    return {
      kind: status === "EMPTY" ? "empty" : "error",
      message: message ?? (status === "EMPTY" ? "当前条件下暂无可计算数据。" : "双动量数据读取失败，请稍后重试。"),
      ...(status === "ERROR" ? { retryable: true } : {}),
    } as SectorDualMomentumResultsAdapterResult;
  }

  const analysis = parseAnalysis(root.analysis);
  validateRequestFacts(request, analysis, tradingDay);
  if (analysis.calculableCount <= 0) fail("READY/DELAYED 必须包含可计算行业。 ");
  const data: SectorDualMomentumResultsViewModel = {
    status,
    tradingDay,
    pageStatus,
    message,
    analysis,
  };
  return { kind: "ready", data };
}

function parseAnalysis(value: unknown): SectorDualMomentumResultsViewModel["analysis"] {
  const item = exactRecord(value, [
    "formulaKey", "formulaVersion", "basisFormulaKey", "basisFormulaVersion", "hierarchyVersion",
    "scope", "period", "leadingThreshold", "minimumGroupSize", "parentSelection", "totalCount",
    "calculableCount", "qualifiedCount", "insufficientCount", "plottableCount", "items",
  ], "双动量分析");
  literal(item.formulaKey, "sector-dual-momentum", "analysis.formulaKey");
  literal(item.formulaVersion, 1, "analysis.formulaVersion");
  literal(item.basisFormulaKey, "sector-cross-sectional-momentum", "analysis.basisFormulaKey");
  literal(item.basisFormulaVersion, 1, "analysis.basisFormulaVersion");
  const parent = exactRecord(item.parentSelection, ["level1Code", "level1Name", "level2Code", "level2Name"], "parentSelection");
  const rows = arrayValue(item.items, "analysis.items").map(parseRow);
  const totalCount = nonNegativeInteger(item.totalCount, "totalCount");
  const calculableCount = nonNegativeInteger(item.calculableCount, "calculableCount");
  const qualifiedCount = nonNegativeInteger(item.qualifiedCount, "qualifiedCount");
  const insufficientCount = nonNegativeInteger(item.insufficientCount, "insufficientCount");
  const plottableCount = nonNegativeInteger(item.plottableCount, "plottableCount");
  if (rows.length !== totalCount) fail("totalCount 与 items 数量不一致。 ");
  if (new Set(rows.map((row) => row.sectorCode)).size !== rows.length) fail("Results 行业代码重复。 ");
  if (rows.filter((row) => row.returnPct !== null).length !== calculableCount) fail("calculableCount 不一致。 ");
  if (rows.filter((row) => row.qualificationStatus === "QUALIFIED").length !== qualifiedCount) fail("qualifiedCount 不一致。 ");
  if (rows.filter((row) => row.qualificationStatus === "NOT_EVALUATED").length !== insufficientCount) fail("insufficientCount 不一致。 ");
  if (rows.filter((row) => row.coordinateStatus === "PLOTTABLE").length !== plottableCount) fail("plottableCount 不一致。 ");
  if (calculableCount < 3 && rows.some((row) => row.returnPct !== null && row.relativeStatus !== "SAMPLE_INSUFFICIENT")) fail("小样本不能生成领先或资格状态。 ");
  if (calculableCount >= 3 && rows.some((row) => row.relativeStatus === "SAMPLE_INSUFFICIENT")) fail("完整样本不能使用小样本状态。 ");
  const expectedOrder = [...rows].sort(canonicalCompare);
  if (rows.some((row, index) => row.sectorCode !== expectedOrder[index]?.sectorCode)) fail("Results 未按规范顺序返回。 ");

  return {
    formulaKey: "sector-dual-momentum",
    formulaVersion: 1,
    basisFormulaKey: "sector-cross-sectional-momentum",
    basisFormulaVersion: 1,
    hierarchyVersion: nonEmptyString(item.hierarchyVersion, "hierarchyVersion"),
    scope: enumValue(item.scope, SCOPES, "scope"),
    period: enumValue(item.period, PERIODS, "period"),
    leadingThreshold: enumValue(item.leadingThreshold, THRESHOLDS, "leadingThreshold"),
    minimumGroupSize: literal(item.minimumGroupSize, 3, "minimumGroupSize"),
    parentSelection: {
      level1Code: nullableSectorCode(parent.level1Code, "parentSelection.level1Code"),
      level1Name: nullableString(parent.level1Name, "parentSelection.level1Name"),
      level2Code: nullableSectorCode(parent.level2Code, "parentSelection.level2Code"),
      level2Name: nullableString(parent.level2Name, "parentSelection.level2Name"),
    },
    totalCount,
    calculableCount,
    qualifiedCount,
    insufficientCount,
    plottableCount,
    items: rows,
  };
}

function parseRow(value: unknown): SectorDualMomentumRowViewModel {
  const row = exactRecord(value, [
    "sectorCode", "sectorName", "industryLevel", "parentSectorCode", "parentSectorName", "hierarchyPath",
    "canDrillDown", "returnPct", "strengthRank", "percentile", "absoluteStatus", "relativeStatus",
    "qualificationStatus", "coordinateStatus", "displayStatus", "missingReason",
  ], "双动量行业行");
  const returnPct = nullableFiniteNumber(row.returnPct, "returnPct");
  const strengthRank = nullablePositiveInteger(row.strengthRank, "strengthRank");
  const percentile = nullableBoundedNumber(row.percentile, 0, 100, "percentile");
  const absoluteStatus = enumValue(row.absoluteStatus, ABSOLUTE_STATUSES, "absoluteStatus");
  const relativeStatus = enumValue(row.relativeStatus, RELATIVE_STATUSES, "relativeStatus");
  const qualificationStatus = enumValue(row.qualificationStatus, QUALIFICATION_STATUSES, "qualificationStatus");
  const coordinateStatus = enumValue(row.coordinateStatus, COORDINATE_STATUSES, "coordinateStatus");
  const displayStatus = enumValue(row.displayStatus, DISPLAY_STATUSES, "displayStatus");
  const missingReason = row.missingReason === null ? null : enumValue(row.missingReason, MISSING_REASONS, "missingReason");
  const facts = [returnPct, strengthRank, percentile];
  if (facts.some((fact) => fact === null) !== facts.every((fact) => fact === null)) fail("收益、排名和百分位只能同有或同空。 ");
  validateRowState({ returnPct, absoluteStatus, relativeStatus, qualificationStatus, coordinateStatus, displayStatus, missingReason });
  return {
    sectorCode: sectorCode(row.sectorCode, "sectorCode"),
    sectorName: nonEmptyString(row.sectorName, "sectorName"),
    industryLevel: enumValue(row.industryLevel, [1, 2, 3] as const, "industryLevel"),
    parentSectorCode: nullableSectorCode(row.parentSectorCode, "parentSectorCode"),
    parentSectorName: nullableString(row.parentSectorName, "parentSectorName"),
    hierarchyPath: nonEmptyString(row.hierarchyPath, "hierarchyPath"),
    canDrillDown: booleanValue(row.canDrillDown, "canDrillDown"),
    returnPct,
    strengthRank,
    percentile,
    absoluteStatus,
    relativeStatus,
    qualificationStatus,
    coordinateStatus,
    displayStatus,
    missingReason,
    returnText: formatReturnPct(returnPct),
    rankText: strengthRank === null ? "--" : String(strengthRank),
    percentileText: formatPercentile(percentile),
    directionClass: returnPct === null ? "muted" : returnPct > 0 ? "up" : returnPct < 0 ? "down" : "flat",
    statusText: displayStatusText(displayStatus),
    statusClass: displayStatus.toLowerCase().replaceAll("_", "-"),
  };
}

function validateRowState(value: {
  returnPct: number | null;
  absoluteStatus: DualMomentumAbsoluteStatus;
  relativeStatus: DualMomentumRelativeStatus;
  qualificationStatus: DualMomentumQualificationStatus;
  coordinateStatus: DualMomentumCoordinateStatus;
  displayStatus: DualMomentumDisplayStatus;
  missingReason: DualMomentumMissingReason | null;
}) {
  if (value.returnPct === null) {
    if (value.absoluteStatus !== "UNAVAILABLE" || value.relativeStatus !== "UNAVAILABLE"
      || value.qualificationStatus !== "NOT_EVALUATED" || value.coordinateStatus !== "UNAVAILABLE"
      || value.displayStatus !== "DATA_INSUFFICIENT" || value.missingReason === null) fail("缺失行业状态组合非法。 ");
    return;
  }
  if (value.coordinateStatus !== "PLOTTABLE" || value.missingReason !== null) fail("可计算行业必须可绘制且没有缺失原因。 ");
  const expected: Record<string, [DualMomentumQualificationStatus, DualMomentumDisplayStatus]> = {
    "POSITIVE|LEADING": ["QUALIFIED", "QUALIFIED"],
    "POSITIVE|NOT_LEADING": ["NOT_QUALIFIED", "UP_NOT_LEADING"],
    "NOT_POSITIVE|LEADING": ["NOT_QUALIFIED", "NOT_UP_LEADING"],
    "NOT_POSITIVE|NOT_LEADING": ["NOT_QUALIFIED", "NOT_UP_NOT_LEADING"],
    "POSITIVE|SAMPLE_INSUFFICIENT": ["NOT_EVALUATED", "SAMPLE_INSUFFICIENT"],
    "NOT_POSITIVE|SAMPLE_INSUFFICIENT": ["NOT_EVALUATED", "SAMPLE_INSUFFICIENT"],
  };
  const pair = expected[`${value.absoluteStatus}|${value.relativeStatus}`];
  if (!pair || pair[0] !== value.qualificationStatus || pair[1] !== value.displayStatus) fail("双动量状态组合非法。 ");
}

function parseHierarchyNode(value: unknown): SectorHierarchyNodeResponse {
  const node = exactRecord(value, [
    "sectorCode", "sectorName", "industryLevel", "parentSectorCode", "parentSectorName",
    "rootSectorCode", "rootSectorName", "hierarchyPath", "displayOrder", "isLeaf",
  ], "行业层级节点");
  return {
    sectorCode: sectorCode(node.sectorCode, "sectorCode"),
    sectorName: nonEmptyString(node.sectorName, "sectorName"),
    industryLevel: enumValue(node.industryLevel, [1, 2, 3] as const, "industryLevel"),
    parentSectorCode: nullableSectorCode(node.parentSectorCode, "parentSectorCode"),
    parentSectorName: nullableString(node.parentSectorName, "parentSectorName"),
    rootSectorCode: sectorCode(node.rootSectorCode, "rootSectorCode"),
    rootSectorName: nonEmptyString(node.rootSectorName, "rootSectorName"),
    hierarchyPath: nonEmptyString(node.hierarchyPath, "hierarchyPath"),
    displayOrder: nonNegativeInteger(node.displayOrder, "displayOrder"),
    isLeaf: booleanValue(node.isLeaf, "isLeaf"),
  };
}

function parseTradeDateAvailability(value: unknown): SectorTradeDateAvailabilityResponse {
  const item = exactRecord(value, ["tradeDate", "availability", "expectedSectorCount", "validSectorCount"], "交易日覆盖");
  const expectedSectorCount = positiveInteger(item.expectedSectorCount, "expectedSectorCount");
  const validSectorCount = nonNegativeInteger(item.validSectorCount, "validSectorCount");
  const availability = enumValue(item.availability, AVAILABILITIES, "availability");
  if (validSectorCount > expectedSectorCount) fail("交易日有效数量不能超过预期数量。 ");
  if (availability === "COMPLETE" && validSectorCount !== expectedSectorCount) fail("COMPLETE 覆盖数量不完整。 ");
  if (availability === "PARTIAL" && !(validSectorCount > 0 && validSectorCount < expectedSectorCount)) fail("PARTIAL 覆盖数量非法。 ");
  if (availability === "MISSING" && validSectorCount !== 0) fail("MISSING 覆盖数量非法。 ");
  return { tradeDate: isoDate(item.tradeDate, "tradeDate"), availability, expectedSectorCount, validSectorCount };
}

function parseTradingDay(value: unknown): SectorTradingDayResponse {
  const day = exactRecord(value, [
    "expectedTradeDate", "observedTradeDate", "expectedAvailability", "expectedSectorCount",
    "expectedValidSectorCount", "observedAvailability", "observedValidSectorCount",
  ], "交易日事实");
  return {
    expectedTradeDate: isoDate(day.expectedTradeDate, "expectedTradeDate"),
    observedTradeDate: nullableIsoDate(day.observedTradeDate, "observedTradeDate"),
    expectedAvailability: enumValue(day.expectedAvailability, AVAILABILITIES, "expectedAvailability"),
    expectedSectorCount: nonNegativeInteger(day.expectedSectorCount, "expectedSectorCount"),
    expectedValidSectorCount: nonNegativeInteger(day.expectedValidSectorCount, "expectedValidSectorCount"),
    observedAvailability: day.observedAvailability === null ? null : enumValue(day.observedAvailability, AVAILABILITIES, "observedAvailability"),
    observedValidSectorCount: nonNegativeInteger(day.observedValidSectorCount, "observedValidSectorCount"),
  };
}

function parsePageStatus(value: unknown): SectorPageStatusResponse {
  const status = exactRecord(value, ["status", "displayText", "asOfTime"], "页面状态");
  return {
    status: enumValue(status.status, STATUSES, "pageStatus.status"),
    displayText: nonEmptyString(status.displayText, "pageStatus.displayText"),
    asOfTime: nonEmptyString(status.asOfTime, "pageStatus.asOfTime"),
  };
}

function parseDebugInfo(value: unknown) {
  if (value === null) return;
  const debug = exactRecord(value, [
    "expectedTradeDate", "observedTradeDate", "scope", "expectedSectorCount", "expectedValidSectorCount",
    "observedValidSectorCount", "sampleSectorCodes",
  ], "debugInfo");
  isoDate(debug.expectedTradeDate, "debugInfo.expectedTradeDate");
  nullableIsoDate(debug.observedTradeDate, "debugInfo.observedTradeDate");
  if (debug.scope !== null) enumValue(debug.scope, SCOPES, "debugInfo.scope");
  nonNegativeInteger(debug.expectedSectorCount, "debugInfo.expectedSectorCount");
  nonNegativeInteger(debug.expectedValidSectorCount, "debugInfo.expectedValidSectorCount");
  nonNegativeInteger(debug.observedValidSectorCount, "debugInfo.observedValidSectorCount");
  const codes = arrayValue(debug.sampleSectorCodes, "debugInfo.sampleSectorCodes");
  if (codes.length > 5) fail("debugInfo 样本行业超过 5 个。 ");
  codes.forEach((code) => sectorCode(code, "debugInfo.sampleSectorCodes"));
}

function validateStatusContract(
  status: SectorDualMomentumStatus,
  day: SectorTradingDayResponse,
  pageStatus: SectorPageStatusResponse,
  exceptionCode: string | null,
) {
  if (pageStatus.status !== status) fail("pageStatus 与响应状态不一致。 ");
  if (status === "READY" && (day.observedTradeDate !== day.expectedTradeDate || exceptionCode !== null)) fail("READY 交易日状态非法。 ");
  if (status === "DELAYED" && (!day.observedTradeDate || day.observedTradeDate >= day.expectedTradeDate || exceptionCode !== "SA_SOURCE_DELAYED")) fail("DELAYED 交易日状态非法。 ");
}

function validateRequestFacts(
  request: SectorDualMomentumResultsRequest,
  analysis: SectorDualMomentumResultsViewModel["analysis"],
  day: SectorTradingDayResponse,
) {
  if (analysis.scope !== request.scope || analysis.period !== request.period || analysis.leadingThreshold !== request.leadingThreshold) fail("Results 与当前范围、周期或阈值不一致。 ");
  if (analysis.hierarchyVersion !== request.hierarchyVersion) fail("Results 层级版本与请求不一致。 ");
  if ((analysis.parentSelection.level1Code ?? undefined) !== request.level1Code
    || (analysis.parentSelection.level2Code ?? undefined) !== request.level2Code) fail("Results 父级范围与请求不一致。 ");
  if (request.tradeDate && day.expectedTradeDate !== request.tradeDate) fail("Results 交易日与请求不一致。 ");
}

function canonicalCompare(left: SectorDualMomentumRowViewModel, right: SectorDualMomentumRowViewModel): number {
  if (left.returnPct === null && right.returnPct !== null) return 1;
  if (left.returnPct !== null && right.returnPct === null) return -1;
  if (left.returnPct === null || right.returnPct === null) return left.sectorCode.localeCompare(right.sectorCode);
  const percentileOrder = (right.percentile ?? 0) - (left.percentile ?? 0);
  if (percentileOrder !== 0) return percentileOrder;
  const returnOrder = right.returnPct - left.returnPct;
  return returnOrder !== 0 ? returnOrder : left.sectorCode.localeCompare(right.sectorCode);
}

export function formatReturnPct(value: number | null): string {
  if (value === null) return "--";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}%`;
}

export function formatPercentile(value: number | null): string {
  return value === null ? "--" : `${value.toFixed(1)}%`;
}

function displayStatusText(value: DualMomentumDisplayStatus): string {
  return {
    QUALIFIED: "符合双动量",
    UP_NOT_LEADING: "上涨未领先",
    NOT_UP_LEADING: "领先未上涨",
    NOT_UP_NOT_LEADING: "均未满足",
    SAMPLE_INSUFFICIENT: "样本不足",
    DATA_INSUFFICIENT: "数据不足",
  }[value];
}

function exactRecord(value: unknown, keys: readonly string[], label: string): Record<string, unknown> {
  if (!isRecord(value)) fail(`${label} 必须是对象。`);
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail(`${label} 字段合同不匹配。`);
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function arrayValue(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) fail(`${label} 必须是数组。`);
  return value;
}

function exactArray<T extends string | number>(value: unknown, expected: readonly T[], label: string) {
  const actual = arrayValue(value, label);
  if (actual.length !== expected.length || actual.some((item, index) => item !== expected[index])) fail(`${label} 必须使用冻结顺序。`);
}

function enumValue<T extends string | number>(value: unknown, values: readonly T[], label: string): T {
  if (!values.includes(value as T)) fail(`${label} 枚举值非法。`);
  return value as T;
}

function literal<T extends string | number>(value: unknown, expected: T, label: string): T {
  if (value !== expected) fail(`${label} 必须为 ${expected}。`);
  return expected;
}

function nonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() === "") fail(`${label} 必须是非空字符串。`);
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  return nonEmptyString(value, label);
}

function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") fail(`${label} 必须是布尔值。`);
  return value;
}

function finiteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(`${label} 必须是有限数值。`);
  return value;
}

function nullableFiniteNumber(value: unknown, label: string): number | null {
  return value === null ? null : finiteNumber(value, label);
}

function nonNegativeInteger(value: unknown, label: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) fail(`${label} 必须是非负整数。`);
  return value as number;
}

function positiveInteger(value: unknown, label: string): number {
  const result = nonNegativeInteger(value, label);
  if (result === 0) fail(`${label} 必须大于 0。`);
  return result;
}

function nullablePositiveInteger(value: unknown, label: string): number | null {
  return value === null ? null : positiveInteger(value, label);
}

function nullableBoundedNumber(value: unknown, minimum: number, maximum: number, label: string): number | null {
  if (value === null) return null;
  const result = finiteNumber(value, label);
  if (result < minimum || result > maximum) fail(`${label} 超出范围。`);
  return result;
}

function sectorCode(value: unknown, label: string): string {
  const result = nonEmptyString(value, label);
  if (!CODE_PATTERN.test(result)) fail(`${label} 格式非法。`);
  return result;
}

function nullableSectorCode(value: unknown, label: string): string | null {
  return value === null ? null : sectorCode(value, label);
}

function isoDate(value: unknown, label: string): string {
  const result = nonEmptyString(value, label);
  if (!DATE_PATTERN.test(result)) fail(`${label} 日期格式非法。`);
  const parsed = new Date(`${result}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== result) fail(`${label} 日期值非法。`);
  return result;
}

function nullableIsoDate(value: unknown, label: string): string | null {
  return value === null ? null : isoDate(value, label);
}

function strictlyAscending(values: string[]): boolean {
  return values.every((value, index) => index === 0 || value > values[index - 1]!);
}

function fail(message: string): never {
  throw new SectorDualMomentumContractError(message);
}
