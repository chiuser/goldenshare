import type {
  RelativeCoordinateStatus,
  RelativeMissingReason,
  RelativeRotationStatus,
  SectorAvailability,
  SectorHierarchyNodeResponse,
  SectorPageStatusResponse,
  SectorRelativeRotationAdapterResult,
  SectorRelativeRotationMetaViewModel,
  SectorRelativeRotationPeriod,
  SectorRelativeRotationResultsRequest,
  SectorRelativeRotationResultsViewModel,
  SectorRelativeRotationRowViewModel,
  SectorRelativeRotationScope,
  SectorRelativeRotationStatus,
  SectorRelativeRotationTrailLength,
  SectorRelativeRotationTrailPointViewModel,
  SectorTradingDayResponse,
  SectorTradeDateAvailabilityResponse,
} from "../model/sectorRelativeRotationTypes";

const SCOPES: SectorRelativeRotationScope[] = ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"];
const PERIODS: SectorRelativeRotationPeriod[] = [5, 10, 20, 30];
const TRAIL_LENGTHS: SectorRelativeRotationTrailLength[] = [20, 30, 60];
const AVAILABILITIES: SectorAvailability[] = ["COMPLETE", "PARTIAL", "MISSING"];
const STATUSES: SectorRelativeRotationStatus[] = ["READY", "DELAYED", "EMPTY", "ERROR"];
const ROTATION_STATUSES: RelativeRotationStatus[] = [
  "LEADING_IMPROVING", "WEAK_IMPROVING", "STRONG_NOT_IMPROVING", "WEAK_NOT_IMPROVING", "SAMPLE_INSUFFICIENT", "DATA_INSUFFICIENT",
];
const QUADRANT_STATUSES: RelativeRotationStatus[] = ["LEADING_IMPROVING", "WEAK_IMPROVING", "STRONG_NOT_IMPROVING", "WEAK_NOT_IMPROVING"];
const COORDINATE_STATUSES: RelativeCoordinateStatus[] = ["PLOTTABLE", "UNAVAILABLE"];
const MISSING_REASONS: RelativeMissingReason[] = ["HISTORY_INSUFFICIENT", "DATE_MISSING", "CLOSE_MISSING", "CLOSE_NON_POSITIVE", "PCT_CHANGE_MISSING"];
const CODE_PATTERN = /^BK[0-9]{4}\.DC$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export class SectorRelativeRotationContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SectorRelativeRotationContractError";
  }
}

export function buildSectorRelativeRotationMetaViewModel(payload: unknown): SectorRelativeRotationMetaViewModel {
  const root = exactRecord(payload, [
    "status", "tradingDay", "pageStatus", "message", "exceptionCode", "debugInfo",
    "formula", "defaults", "hierarchy", "coverageStartDate", "coverageEndDate", "tradeDates",
  ], "相对轮动 Meta");
  const status = enumValue(root.status, ["READY", "DELAYED"] as const, "Meta status");
  const tradingDay = parseTradingDay(root.tradingDay);
  const pageStatus = parsePageStatus(root.pageStatus);
  const message = nullableString(root.message, "Meta message");
  const exceptionCode = nullableString(root.exceptionCode, "Meta exceptionCode");
  parseDebugInfo(root.debugInfo);
  validateStatusContract(status, tradingDay, pageStatus, exceptionCode);

  const formula = exactRecord(root.formula, [
    "formulaKey", "formulaVersion", "basisFormulaKey", "basisFormulaVersion", "periods",
    "improvementLookbackDays", "trailLengths", "minimumGroupSize", "scopes", "xDomain", "xSplit", "ySplit",
  ], "相对轮动公式");
  literal(formula.formulaKey, "sector-relative-rotation", "formulaKey");
  literal(formula.formulaVersion, 1, "formulaVersion");
  literal(formula.basisFormulaKey, "sector-cross-sectional-momentum", "basisFormulaKey");
  literal(formula.basisFormulaVersion, 1, "basisFormulaVersion");
  exactArray(formula.periods, PERIODS, "periods");
  literal(formula.improvementLookbackDays, 5, "improvementLookbackDays");
  exactArray(formula.trailLengths, TRAIL_LENGTHS, "trailLengths");
  literal(formula.minimumGroupSize, 3, "minimumGroupSize");
  exactArray(formula.scopes, SCOPES, "scopes");
  exactArray(formula.xDomain, [0, 100], "xDomain");
  literal(formula.xSplit, 50, "xSplit");
  literal(formula.ySplit, 0, "ySplit");

  const defaults = exactRecord(root.defaults, ["scope", "period", "trailLength", "quadrantFilter"], "相对轮动默认值");
  literal(defaults.scope, "LEVEL_1", "defaults.scope");
  literal(defaults.period, 20, "defaults.period");
  literal(defaults.trailLength, 20, "defaults.trailLength");
  literal(defaults.quadrantFilter, "ALL", "defaults.quadrantFilter");

  const hierarchy = exactRecord(root.hierarchy, ["hierarchyVersion", "publishedAt", "nodes"], "行业层级");
  const hierarchyVersion = nonEmptyString(hierarchy.hierarchyVersion, "hierarchyVersion");
  const publishedAt = nonEmptyString(hierarchy.publishedAt, "publishedAt");
  const nodes = arrayValue(hierarchy.nodes, "hierarchy.nodes").map(parseHierarchyNode);
  if (new Set(nodes.map((node) => node.sectorCode)).size !== nodes.length) fail("行业层级代码重复。");
  const coverageStartDate = isoDate(root.coverageStartDate, "coverageStartDate");
  const coverageEndDate = isoDate(root.coverageEndDate, "coverageEndDate");
  const tradeDates = arrayValue(root.tradeDates, "tradeDates").map(parseTradeDateAvailability);
  const dateValues = tradeDates.map((item) => item.tradeDate);
  if (dateValues.length === 0 || !strictlyAscending(dateValues)) fail("交易日必须唯一且升序。");
  if (dateValues[0] !== coverageStartDate || dateValues.at(-1) !== coverageEndDate) fail("交易日未覆盖 Meta 日期范围。");
  return {
    status,
    tradingDay,
    pageStatus,
    message,
    formula: {
      formulaKey: "sector-relative-rotation", formulaVersion: 1,
      basisFormulaKey: "sector-cross-sectional-momentum", basisFormulaVersion: 1,
      periods: [...PERIODS], improvementLookbackDays: 5, trailLengths: [...TRAIL_LENGTHS],
      minimumGroupSize: 3, scopes: [...SCOPES], xDomain: [0, 100], xSplit: 50, ySplit: 0,
    },
    defaults: { scope: "LEVEL_1", period: 20, trailLength: 20, quadrantFilter: "ALL" },
    hierarchy: { hierarchyVersion, publishedAt, nodes },
    coverageStartDate,
    coverageEndDate,
    tradeDates,
    level1Nodes: nodes.filter((node) => node.industryLevel === 1),
    level2Nodes: nodes.filter((node) => node.industryLevel === 2),
    level3Nodes: nodes.filter((node) => node.industryLevel === 3),
  };
}

export function buildSectorRelativeRotationResultsViewModel(
  payload: unknown,
  request: SectorRelativeRotationResultsRequest,
): SectorRelativeRotationAdapterResult {
  const root = exactRecord(payload, ["status", "tradingDay", "pageStatus", "analysis", "message", "exceptionCode", "debugInfo"], "相对轮动 Results");
  const status = enumValue(root.status, STATUSES, "Results status");
  const tradingDay = parseTradingDay(root.tradingDay);
  const pageStatus = parsePageStatus(root.pageStatus);
  const message = nullableString(root.message, "Results message");
  const exceptionCode = nullableString(root.exceptionCode, "Results exceptionCode");
  parseDebugInfo(root.debugInfo);
  validateStatusContract(status, tradingDay, pageStatus, exceptionCode);
  if (status === "EMPTY" || status === "ERROR") {
    if (root.analysis !== null) fail("EMPTY/ERROR 不能携带分析事实。");
    if (status === "EMPTY" && exceptionCode !== "SA_SOURCE_EMPTY") fail("EMPTY 必须使用 SA_SOURCE_EMPTY。");
    if (status === "ERROR" && !["SA_HIERARCHY_UNAVAILABLE", "SA_QUERY_FAILED"].includes(exceptionCode ?? "")) fail("ERROR 异常码非法。");
    return status === "EMPTY"
      ? { kind: "empty", message: message ?? "当前条件下暂无可计算数据。" }
      : { kind: "error", message: message ?? "相对轮动数据读取失败，请稍后重试。", retryable: true };
  }
  const analysis = parseAnalysis(root.analysis);
  validateRequestFacts(request, analysis, tradingDay);
  if (analysis.currentCalculableCount <= 0) fail("READY/DELAYED 必须包含可计算行业。");
  if (analysis.selectedTrail.points.length === 0 || analysis.selectedTrail.points.at(-1)?.tradeDate !== tradingDay.observedTradeDate) {
    fail("选中轨迹必须结束于实际行情日期。");
  }
  return { kind: "ready", data: { status, tradingDay, pageStatus, message, analysis } };
}

function parseAnalysis(value: unknown): SectorRelativeRotationResultsViewModel["analysis"] {
  const item = exactRecord(value, [
    "formulaKey", "formulaVersion", "basisFormulaKey", "basisFormulaVersion", "hierarchyVersion", "scope", "period",
    "improvementLookbackDays", "trailLength", "minimumGroupSize", "parentSelection", "selectedSectorCode",
    "groupInterpretation", "totalCount", "currentCalculableCount", "plottableCount", "missingCoordinateCount",
    "quadrantCounts", "items", "selectedTrail",
  ], "相对轮动分析");
  literal(item.formulaKey, "sector-relative-rotation", "analysis.formulaKey");
  literal(item.formulaVersion, 1, "analysis.formulaVersion");
  literal(item.basisFormulaKey, "sector-cross-sectional-momentum", "analysis.basisFormulaKey");
  literal(item.basisFormulaVersion, 1, "analysis.basisFormulaVersion");
  literal(item.improvementLookbackDays, 5, "analysis.improvementLookbackDays");
  literal(item.minimumGroupSize, 3, "analysis.minimumGroupSize");
  const scope = enumValue(item.scope, SCOPES, "scope");
  const period = enumValue(item.period, PERIODS, "period");
  const trailLength = enumValue(item.trailLength, TRAIL_LENGTHS, "trailLength");
  const parent = exactRecord(item.parentSelection, ["level1Code", "level1Name", "level2Code", "level2Name"], "parentSelection");
  const rows = arrayValue(item.items, "analysis.items").map(parseRow);
  const totalCount = nonNegativeInteger(item.totalCount, "totalCount");
  const currentCalculableCount = nonNegativeInteger(item.currentCalculableCount, "currentCalculableCount");
  const plottableCount = nonNegativeInteger(item.plottableCount, "plottableCount");
  const missingCoordinateCount = nonNegativeInteger(item.missingCoordinateCount, "missingCoordinateCount");
  const groupInterpretation = enumValue(item.groupInterpretation, ["QUADRANT", "SAMPLE_INSUFFICIENT"] as const, "groupInterpretation");
  const quadrantCountsRaw = exactRecord(item.quadrantCounts, ["leadingImproving", "weakImproving", "strongNotImproving", "weakNotImproving"], "quadrantCounts");
  const quadrantCounts = {
    leadingImproving: nonNegativeInteger(quadrantCountsRaw.leadingImproving, "leadingImproving"),
    weakImproving: nonNegativeInteger(quadrantCountsRaw.weakImproving, "weakImproving"),
    strongNotImproving: nonNegativeInteger(quadrantCountsRaw.strongNotImproving, "strongNotImproving"),
    weakNotImproving: nonNegativeInteger(quadrantCountsRaw.weakNotImproving, "weakNotImproving"),
  };
  if (rows.length !== totalCount) fail("totalCount 与 items 数量不一致。");
  if (new Set(rows.map((row) => row.sectorCode)).size !== rows.length) fail("Results 行业代码重复。");
  if (rows.filter((row) => row.percentile !== null).length !== currentCalculableCount) fail("currentCalculableCount 不一致。");
  if (rows.filter((row) => row.coordinateStatus === "PLOTTABLE").length !== plottableCount) fail("plottableCount 不一致。");
  if (missingCoordinateCount !== totalCount - plottableCount) fail("missingCoordinateCount 不一致。");
  const expectedOrder = [...rows].sort(canonicalCompare);
  if (rows.some((row, index) => row.sectorCode !== expectedOrder[index]?.sectorCode)) fail("Results 未按规范顺序返回。");
  const selectedSectorCode = sectorCode(item.selectedSectorCode, "selectedSectorCode");
  if (!rows.some((row) => row.sectorCode === selectedSectorCode)) fail("选中行业不在当前比较池。");
  if (groupInterpretation === "QUADRANT") {
    const expected = countQuadrants(rows);
    if (Object.keys(expected).some((key) => expected[key as keyof typeof expected] !== quadrantCounts[key as keyof typeof quadrantCounts])) fail("象限计数与行业状态不一致。");
    if (Object.values(quadrantCounts).reduce((sum, count) => sum + count, 0) !== plottableCount) fail("象限计数没有覆盖全部可绘制行业。");
    if (rows.some((row) => row.coordinateStatus === "PLOTTABLE" && !QUADRANT_STATUSES.includes(row.rotationStatus))) fail("可绘制行业缺少象限状态。");
  } else {
    if (Object.values(quadrantCounts).some((count) => count !== 0)) fail("小样本不能产生象限计数。");
    if (rows.some((row) => row.coordinateStatus === "PLOTTABLE" && row.rotationStatus !== "SAMPLE_INSUFFICIENT")) fail("小样本可绘制行业必须保持中性状态。");
  }
  const trail = parseTrail(item.selectedTrail, trailLength, selectedSectorCode);
  return {
    formulaKey: "sector-relative-rotation", formulaVersion: 1,
    basisFormulaKey: "sector-cross-sectional-momentum", basisFormulaVersion: 1,
    hierarchyVersion: nonEmptyString(item.hierarchyVersion, "hierarchyVersion"), scope, period,
    improvementLookbackDays: 5, trailLength, minimumGroupSize: 3,
    parentSelection: {
      level1Code: nullableSectorCode(parent.level1Code, "parentSelection.level1Code"),
      level1Name: nullableString(parent.level1Name, "parentSelection.level1Name"),
      level2Code: nullableSectorCode(parent.level2Code, "parentSelection.level2Code"),
      level2Name: nullableString(parent.level2Name, "parentSelection.level2Name"),
    },
    selectedSectorCode, groupInterpretation, totalCount, currentCalculableCount, plottableCount,
    missingCoordinateCount, quadrantCounts, items: rows, selectedTrail: trail,
    scopeTitle: scopeTitle(scope, parent),
  };
}

function parseTrail(value: unknown, trailLength: SectorRelativeRotationTrailLength, selectedCode: string) {
  const trail = exactRecord(value, ["sectorCode", "requestedLength", "dateSlotCount", "points"], "selectedTrail");
  literal(trail.sectorCode, selectedCode, "selectedTrail.sectorCode");
  literal(trail.requestedLength, trailLength, "selectedTrail.requestedLength");
  const points = arrayValue(trail.points, "selectedTrail.points").map(parseTrailPoint);
  const dateSlotCount = nonNegativeInteger(trail.dateSlotCount, "selectedTrail.dateSlotCount");
  if (dateSlotCount !== points.length || dateSlotCount > trailLength) fail("轨迹日期槽数量非法。");
  if (!strictlyAscending(points.map((point) => point.tradeDate))) fail("轨迹日期必须唯一且升序。");
  return { sectorCode: selectedCode, requestedLength: trailLength, dateSlotCount, points };
}

function parseRow(value: unknown): SectorRelativeRotationRowViewModel {
  const row = exactRecord(value, [
    "sectorCode", "sectorName", "industryLevel", "parentSectorCode", "parentSectorName", "hierarchyPath", "canDrillDown",
    "returnPct", "strengthRank", "percentile", "percentileDelta5d", "rotationStatus", "coordinateStatus",
    "currentMissingReason", "comparisonMissingReason",
  ], "相对轮动行业行");
  const parsed = parseCoordinateFact(row, true);
  return {
    sectorCode: sectorCode(row.sectorCode, "sectorCode"),
    sectorName: nonEmptyString(row.sectorName, "sectorName"),
    industryLevel: enumValue(row.industryLevel, [1, 2, 3] as const, "industryLevel"),
    parentSectorCode: nullableSectorCode(row.parentSectorCode, "parentSectorCode"),
    parentSectorName: nullableString(row.parentSectorName, "parentSectorName"),
    hierarchyPath: nonEmptyString(row.hierarchyPath, "hierarchyPath"),
    canDrillDown: booleanValue(row.canDrillDown, "canDrillDown"),
    ...parsed,
    returnText: formatSignedPercent(parsed.returnPct),
    percentileText: parsed.percentile === null ? "--" : `${parsed.percentile.toFixed(1)}%`,
    deltaText: formatSignedPoints(parsed.percentileDelta5d),
    statusText: statusText(parsed.rotationStatus),
    statusClass: parsed.rotationStatus.toLowerCase().replaceAll("_", "-"),
    directionClass: parsed.returnPct === null ? "muted" : parsed.returnPct > 0 ? "up" : parsed.returnPct < 0 ? "down" : "flat",
  };
}

function parseTrailPoint(value: unknown): SectorRelativeRotationTrailPointViewModel {
  const point = exactRecord(value, [
    "tradeDate", "returnPct", "percentile", "percentileDelta5d", "rotationStatus", "coordinateStatus",
    "currentMissingReason", "comparisonMissingReason",
  ], "轨迹日期槽");
  const parsed = parseCoordinateFact(point, false);
  return { tradeDate: isoDate(point.tradeDate, "tradeDate"), returnPct: parsed.returnPct, percentile: parsed.percentile, percentileDelta5d: parsed.percentileDelta5d, rotationStatus: parsed.rotationStatus, coordinateStatus: parsed.coordinateStatus, currentMissingReason: parsed.currentMissingReason, comparisonMissingReason: parsed.comparisonMissingReason };
}

function parseCoordinateFact(value: Record<string, unknown>, includesRank: boolean) {
  const returnPct = nullableFiniteNumber(value.returnPct, "returnPct");
  const strengthRank = includesRank ? nullablePositiveInteger(value.strengthRank, "strengthRank") : null;
  const percentile = nullableBoundedNumber(value.percentile, 0, 100, "percentile");
  const percentileDelta5d = nullableFiniteNumber(value.percentileDelta5d, "percentileDelta5d");
  const rotationStatus = enumValue(value.rotationStatus, ROTATION_STATUSES, "rotationStatus");
  const coordinateStatus = enumValue(value.coordinateStatus, COORDINATE_STATUSES, "coordinateStatus");
  const currentMissingReason = value.currentMissingReason === null ? null : enumValue(value.currentMissingReason, MISSING_REASONS, "currentMissingReason");
  const comparisonMissingReason = value.comparisonMissingReason === null ? null : enumValue(value.comparisonMissingReason, MISSING_REASONS, "comparisonMissingReason");
  const currentFacts = includesRank ? [returnPct, strengthRank, percentile] : [returnPct, percentile];
  if (currentFacts.some((fact) => fact === null) !== currentFacts.every((fact) => fact === null)) fail("当前收益、排名和百分位必须同有或同空。");
  if (percentile === null) {
    if (percentileDelta5d !== null || coordinateStatus !== "UNAVAILABLE" || rotationStatus !== "DATA_INSUFFICIENT" || currentMissingReason === null) fail("当前事实缺失状态非法。");
  } else if (currentMissingReason !== null) fail("可计算当前事实不能携带缺失原因。");
  else if (percentileDelta5d === null) {
    if (coordinateStatus !== "UNAVAILABLE" || rotationStatus !== "DATA_INSUFFICIENT" || comparisonMissingReason === null) fail("比较事实缺失状态非法。");
  } else {
    if (coordinateStatus !== "PLOTTABLE" || rotationStatus === "DATA_INSUFFICIENT" || comparisonMissingReason !== null) fail("完整坐标状态非法。");
    if (rotationStatus !== "SAMPLE_INSUFFICIENT" && rotationStatus !== expectedQuadrant(percentile, percentileDelta5d)) fail("象限状态与坐标不一致。");
  }
  return { returnPct, strengthRank, percentile, percentileDelta5d, rotationStatus, coordinateStatus, currentMissingReason, comparisonMissingReason };
}

function validateRequestFacts(request: SectorRelativeRotationResultsRequest, analysis: SectorRelativeRotationResultsViewModel["analysis"], tradingDay: SectorTradingDayResponse) {
  if (analysis.hierarchyVersion !== request.hierarchyVersion || analysis.scope !== request.scope || analysis.period !== request.period || analysis.trailLength !== request.trailLength) fail("响应事实与请求不一致。");
  if (request.tradeDate && tradingDay.expectedTradeDate !== request.tradeDate) fail("响应交易日与请求不一致。");
  if ((request.level1Code ?? null) !== analysis.parentSelection.level1Code || (request.level2Code ?? null) !== analysis.parentSelection.level2Code) fail("响应父级选择与请求不一致。");
  if (request.sectorCode && request.sectorCode !== analysis.selectedSectorCode) fail("响应选中行业与请求不一致。");
}

function parseHierarchyNode(value: unknown): SectorHierarchyNodeResponse {
  const node = exactRecord(value, ["sectorCode", "sectorName", "industryLevel", "parentSectorCode", "parentSectorName", "rootSectorCode", "rootSectorName", "hierarchyPath", "displayOrder", "isLeaf"], "行业层级节点");
  return {
    sectorCode: sectorCode(node.sectorCode, "sectorCode"), sectorName: nonEmptyString(node.sectorName, "sectorName"),
    industryLevel: enumValue(node.industryLevel, [1, 2, 3] as const, "industryLevel"),
    parentSectorCode: nullableSectorCode(node.parentSectorCode, "parentSectorCode"), parentSectorName: nullableString(node.parentSectorName, "parentSectorName"),
    rootSectorCode: sectorCode(node.rootSectorCode, "rootSectorCode"), rootSectorName: nonEmptyString(node.rootSectorName, "rootSectorName"),
    hierarchyPath: nonEmptyString(node.hierarchyPath, "hierarchyPath"), displayOrder: nonNegativeInteger(node.displayOrder, "displayOrder"), isLeaf: booleanValue(node.isLeaf, "isLeaf"),
  };
}

function parseTradeDateAvailability(value: unknown): SectorTradeDateAvailabilityResponse {
  const item = exactRecord(value, ["tradeDate", "availability", "expectedSectorCount", "validSectorCount"], "交易日覆盖");
  const expectedSectorCount = positiveInteger(item.expectedSectorCount, "expectedSectorCount");
  const validSectorCount = nonNegativeInteger(item.validSectorCount, "validSectorCount");
  const availability = enumValue(item.availability, AVAILABILITIES, "availability");
  if (validSectorCount > expectedSectorCount) fail("交易日有效数量不能超过预期数量。");
  if (availability === "COMPLETE" && validSectorCount !== expectedSectorCount) fail("COMPLETE 覆盖数量不完整。");
  if (availability === "PARTIAL" && !(validSectorCount > 0 && validSectorCount < expectedSectorCount)) fail("PARTIAL 覆盖数量非法。");
  if (availability === "MISSING" && validSectorCount !== 0) fail("MISSING 覆盖数量非法。");
  return { tradeDate: isoDate(item.tradeDate, "tradeDate"), availability, expectedSectorCount, validSectorCount };
}

function parseTradingDay(value: unknown): SectorTradingDayResponse {
  const day = exactRecord(value, ["expectedTradeDate", "observedTradeDate", "expectedAvailability", "expectedSectorCount", "expectedValidSectorCount", "observedAvailability", "observedValidSectorCount"], "交易日事实");
  return {
    expectedTradeDate: isoDate(day.expectedTradeDate, "expectedTradeDate"), observedTradeDate: nullableIsoDate(day.observedTradeDate, "observedTradeDate"),
    expectedAvailability: enumValue(day.expectedAvailability, AVAILABILITIES, "expectedAvailability"), expectedSectorCount: nonNegativeInteger(day.expectedSectorCount, "expectedSectorCount"),
    expectedValidSectorCount: nonNegativeInteger(day.expectedValidSectorCount, "expectedValidSectorCount"),
    observedAvailability: day.observedAvailability === null ? null : enumValue(day.observedAvailability, AVAILABILITIES, "observedAvailability"),
    observedValidSectorCount: nonNegativeInteger(day.observedValidSectorCount, "observedValidSectorCount"),
  };
}

function parsePageStatus(value: unknown): SectorPageStatusResponse {
  const status = exactRecord(value, ["status", "displayText", "asOfTime"], "页面状态");
  return { status: enumValue(status.status, STATUSES, "pageStatus.status"), displayText: nonEmptyString(status.displayText, "pageStatus.displayText"), asOfTime: nonEmptyString(status.asOfTime, "pageStatus.asOfTime") };
}

function parseDebugInfo(value: unknown) {
  if (value === null) return;
  const debug = exactRecord(value, ["expectedTradeDate", "observedTradeDate", "scope", "expectedSectorCount", "expectedValidSectorCount", "observedValidSectorCount", "sampleSectorCodes"], "debugInfo");
  isoDate(debug.expectedTradeDate, "debugInfo.expectedTradeDate");
  nullableIsoDate(debug.observedTradeDate, "debugInfo.observedTradeDate");
  if (debug.scope !== null) enumValue(debug.scope, SCOPES, "debugInfo.scope");
  nonNegativeInteger(debug.expectedSectorCount, "debugInfo.expectedSectorCount");
  nonNegativeInteger(debug.expectedValidSectorCount, "debugInfo.expectedValidSectorCount");
  nonNegativeInteger(debug.observedValidSectorCount, "debugInfo.observedValidSectorCount");
  const codes = arrayValue(debug.sampleSectorCodes, "debugInfo.sampleSectorCodes").map((item) => sectorCode(item, "debugInfo.sampleSectorCodes"));
  if (codes.length > 5) fail("debugInfo 样本代码过多。");
}

function validateStatusContract(status: SectorRelativeRotationStatus, tradingDay: SectorTradingDayResponse, pageStatus: SectorPageStatusResponse, exceptionCode: string | null) {
  if (pageStatus.status !== status) fail("pageStatus 与响应状态不一致。");
  if (status === "READY" && exceptionCode !== null) fail("READY 不能携带异常码。");
  if (status === "DELAYED" && exceptionCode !== "SA_SOURCE_DELAYED") fail("DELAYED 必须使用 SA_SOURCE_DELAYED。");
  if ((status === "READY" || status === "DELAYED") && tradingDay.observedTradeDate === null) fail("内容态必须包含实际行情日期。");
}

function expectedQuadrant(percentile: number, delta: number): RelativeRotationStatus {
  if (percentile >= 50 && delta > 0) return "LEADING_IMPROVING";
  if (percentile < 50 && delta > 0) return "WEAK_IMPROVING";
  if (percentile >= 50) return "STRONG_NOT_IMPROVING";
  return "WEAK_NOT_IMPROVING";
}

function countQuadrants(rows: SectorRelativeRotationRowViewModel[]) {
  return {
    leadingImproving: rows.filter((row) => row.rotationStatus === "LEADING_IMPROVING").length,
    weakImproving: rows.filter((row) => row.rotationStatus === "WEAK_IMPROVING").length,
    strongNotImproving: rows.filter((row) => row.rotationStatus === "STRONG_NOT_IMPROVING").length,
    weakNotImproving: rows.filter((row) => row.rotationStatus === "WEAK_NOT_IMPROVING").length,
  };
}

function canonicalCompare(left: SectorRelativeRotationRowViewModel, right: SectorRelativeRotationRowViewModel) {
  const bucket = (row: SectorRelativeRotationRowViewModel) => row.percentile === null ? 2 : row.percentileDelta5d === null ? 1 : 0;
  const bucketOrder = bucket(left) - bucket(right);
  if (bucketOrder !== 0) return bucketOrder;
  const percentileOrder = (right.percentile ?? 0) - (left.percentile ?? 0);
  if (percentileOrder !== 0) return percentileOrder;
  const deltaOrder = (right.percentileDelta5d ?? 0) - (left.percentileDelta5d ?? 0);
  return deltaOrder !== 0 ? deltaOrder : left.sectorCode.localeCompare(right.sectorCode);
}

function scopeTitle(scope: SectorRelativeRotationScope, parent: Record<string, unknown>): string {
  if (scope === "LEVEL_1") return "一级行业相对轮动";
  if (scope === "LEVEL_2") return "二级行业相对轮动";
  if (scope === "LEVEL_3") return "三级行业相对轮动";
  if (scope === "LEVEL_1_CHILDREN") return `${nullableString(parent.level1Name, "level1Name") ?? "当前一级行业"}内二级行业相对轮动`;
  return `${nullableString(parent.level2Name, "level2Name") ?? "当前二级行业"}内三级行业相对轮动`;
}

export function formatSignedPercent(value: number | null): string {
  if (value === null) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatSignedPoints(value: number | null): string {
  if (value === null) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}

function statusText(value: RelativeRotationStatus): string {
  return {
    LEADING_IMPROVING: "领先且改善",
    WEAK_IMPROVING: "偏弱但改善",
    STRONG_NOT_IMPROVING: "强势但未改善",
    WEAK_NOT_IMPROVING: "偏弱且未改善",
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

function enumValue<const T extends readonly (string | number)[]>(value: unknown, allowed: T, label: string): T[number] {
  if (!allowed.includes(value as T[number])) fail(`${label} 枚举值非法。`);
  return value as T[number];
}
function literal<const T extends string | number>(value: unknown, expected: T, label: string): T { if (value !== expected) fail(`${label} 必须为 ${expected}。`); return expected; }
function exactArray(value: unknown, expected: readonly unknown[], label: string) { const items = arrayValue(value, label); if (items.length !== expected.length || items.some((item, index) => item !== expected[index])) fail(`${label} 固定数组不匹配。`); }
function arrayValue(value: unknown, label: string): unknown[] { if (!Array.isArray(value)) fail(`${label} 必须是数组。`); return value; }
function nonEmptyString(value: unknown, label: string): string { if (typeof value !== "string" || value.trim() === "") fail(`${label} 必须是非空文本。`); return value; }
function nullableString(value: unknown, label: string): string | null { if (value === null) return null; if (typeof value !== "string") fail(`${label} 必须是文本或 null。`); return value; }
function booleanValue(value: unknown, label: string): boolean { if (typeof value !== "boolean") fail(`${label} 必须是布尔值。`); return value; }
function finiteNumber(value: unknown, label: string): number { if (typeof value !== "number" || !Number.isFinite(value)) fail(`${label} 必须是有限数字。`); return value; }
function nullableFiniteNumber(value: unknown, label: string): number | null { return value === null ? null : finiteNumber(value, label); }
function nonNegativeInteger(value: unknown, label: string): number { if (!Number.isInteger(value) || (value as number) < 0) fail(`${label} 必须是非负整数。`); return value as number; }
function positiveInteger(value: unknown, label: string): number { const parsed = nonNegativeInteger(value, label); if (parsed < 1) fail(`${label} 必须是正整数。`); return parsed; }
function nullablePositiveInteger(value: unknown, label: string): number | null { return value === null ? null : positiveInteger(value, label); }
function nullableBoundedNumber(value: unknown, min: number, max: number, label: string): number | null { if (value === null) return null; const parsed = finiteNumber(value, label); if (parsed < min || parsed > max) fail(`${label} 超出范围。`); return parsed; }
function sectorCode(value: unknown, label: string): string { const parsed = nonEmptyString(value, label); if (!CODE_PATTERN.test(parsed)) fail(`${label} 代码格式非法。`); return parsed; }
function nullableSectorCode(value: unknown, label: string): string | null { return value === null ? null : sectorCode(value, label); }
function isoDate(value: unknown, label: string): string { const parsed = nonEmptyString(value, label); if (!DATE_PATTERN.test(parsed) || new Date(`${parsed}T00:00:00Z`).toISOString().slice(0, 10) !== parsed) fail(`${label} 日期非法。`); return parsed; }
function nullableIsoDate(value: unknown, label: string): string | null { return value === null ? null : isoDate(value, label); }
function strictlyAscending(values: string[]): boolean { return values.length > 0 && values.every((value, index) => index === 0 || values[index - 1]! < value); }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function fail(message: string): never { throw new SectorRelativeRotationContractError(message); }
