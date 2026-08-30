import type {
  PriceVolumeAvailability,
  PriceVolumeDetailsAdapterResult,
  PriceVolumeDetailsRequest,
  PriceVolumeDetailsViewModel,
  PriceVolumeHierarchyNode,
  PriceVolumeHistoryPointViewModel,
  PriceVolumeMetaViewModel,
  PriceVolumeMissingReason,
  PriceVolumePeriod,
  PriceVolumeScope,
  PriceVolumeSnapshotAdapterResult,
  PriceVolumeSnapshotRequest,
  PriceVolumeSnapshotRowViewModel,
  PriceVolumeSnapshotViewModel,
  PriceVolumeState,
  PriceVolumeTradeDateAvailability,
} from "./sectorPriceVolumeTypes";

const SCOPES: PriceVolumeScope[] = ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"];
const PERIODS: PriceVolumePeriod[] = [1, 5, 10, 20, 30];
const HISTORY_RANGES = [20, 30, 60] as const;
const STATES: PriceVolumeState[] = ["JOINT", "PRICE_ONLY", "AMOUNT_ONLY", "NEUTRAL"];
const AVAILABILITIES: PriceVolumeAvailability[] = ["COMPLETE", "PARTIAL", "MISSING"];
const MISSING_REASONS: PriceVolumeMissingReason[] = [
  "HISTORY_INSUFFICIENT", "DATE_MISSING", "PCT_CHANGE_MISSING", "CLOSE_MISSING", "CLOSE_NON_POSITIVE",
  "AMOUNT_MISSING", "AMOUNT_NON_FINITE", "AMOUNT_NEGATIVE", "PRIOR_AMOUNT_AVERAGE_NON_POSITIVE",
];
const CODE_PATTERN = /^BK[0-9]{4}\.DC$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export class SectorPriceVolumeContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SectorPriceVolumeContractError";
  }
}

export function buildSectorPriceVolumeMetaViewModel(payload: unknown): PriceVolumeMetaViewModel {
  const root = exactRecord(payload, [
    "formulaKey", "formulaVersion", "market", "periods", "historyRanges", "scopes", "states", "defaults",
    "dateCoverageBasis", "dateContext", "hierarchy", "coverageStartDate", "coverageEndDate", "tradeDates",
  ], "量价分布 Meta");
  literal(root.formulaKey, "sector-price-volume-distribution", "formulaKey");
  literal(root.formulaVersion, 1, "formulaVersion");
  literal(root.market, "CN_A", "market");
  exactArray(root.periods, PERIODS, "periods");
  exactArray(root.historyRanges, HISTORY_RANGES, "historyRanges");
  exactArray(root.scopes, SCOPES, "scopes");
  exactArray(root.states, STATES, "states");
  literal(root.dateCoverageBasis, "INDUSTRY_PRICE_AMOUNT_DAILY", "dateCoverageBasis");

  const defaults = exactRecord(root.defaults, ["scope", "period", "stateFilter", "sortBy", "sortDirection", "historyRange"], "默认值");
  literal(defaults.scope, "LEVEL_1", "defaults.scope");
  literal(defaults.period, 20, "defaults.period");
  literal(defaults.stateFilter, "ALL", "defaults.stateFilter");
  literal(defaults.sortBy, "PRICE_MOMENTUM", "defaults.sortBy");
  literal(defaults.sortDirection, "DESC", "defaults.sortDirection");
  literal(defaults.historyRange, 20, "defaults.historyRange");

  const dateContext = exactRecord(root.dateContext, ["expectedTradeDate", "defaultTradeDate", "defaultStatus", "displayText"], "日期上下文");
  const expectedTradeDate = isoDate(dateContext.expectedTradeDate, "expectedTradeDate");
  const defaultTradeDate = nullableIsoDate(dateContext.defaultTradeDate, "defaultTradeDate");
  const defaultStatus = enumValue(dateContext.defaultStatus, ["READY", "DELAYED", "EMPTY"] as const, "defaultStatus");
  const displayText = nonEmptyString(dateContext.displayText, "displayText");
  if (defaultStatus === "EMPTY" && defaultTradeDate !== null) fail("EMPTY 不能携带默认日期。");
  if (defaultStatus !== "EMPTY" && defaultTradeDate === null) fail("内容态必须携带默认日期。");
  if (defaultStatus === "READY" && defaultTradeDate !== expectedTradeDate) fail("READY 默认日期必须等于期望日期。");
  if (defaultStatus === "DELAYED" && (defaultTradeDate === null || defaultTradeDate >= expectedTradeDate)) fail("DELAYED 必须使用较早交易日。");

  const hierarchy = exactRecord(root.hierarchy, ["hierarchyVersion", "publishedAt", "nodes"], "行业层级");
  const hierarchyVersion = nonEmptyString(hierarchy.hierarchyVersion, "hierarchyVersion");
  const publishedAt = nonEmptyString(hierarchy.publishedAt, "publishedAt");
  const nodes = arrayValue(hierarchy.nodes, "hierarchy.nodes").map(parseHierarchyNode);
  if (new Set(nodes.map((node) => node.sectorCode)).size !== nodes.length) fail("行业层级代码重复。");
  validateHierarchy(nodes);

  const coverageStartDate = isoDate(root.coverageStartDate, "coverageStartDate");
  const coverageEndDate = isoDate(root.coverageEndDate, "coverageEndDate");
  const tradeDates = arrayValue(root.tradeDates, "tradeDates").map(parseTradeDate);
  const dates = tradeDates.map((item) => item.tradeDate);
  if (dates.length === 0 || !strictlyAscending(dates)) fail("交易日必须唯一且升序。");
  if (dates[0] !== coverageStartDate || dates.at(-1) !== coverageEndDate) fail("交易日未覆盖声明范围。");
  if (expectedTradeDate !== coverageEndDate) fail("期望日期必须等于覆盖结束日。");
  if (defaultTradeDate) {
    const match = tradeDates.find((item) => item.tradeDate === defaultTradeDate);
    if (match?.availability !== "COMPLETE") fail("默认日期必须是完整交易日。");
  }
  return {
    formulaKey: "sector-price-volume-distribution", formulaVersion: 1, market: "CN_A",
    periods: [...PERIODS], historyRanges: [...HISTORY_RANGES], scopes: [...SCOPES], states: [...STATES],
    defaults: { scope: "LEVEL_1", period: 20, stateFilter: "ALL", sortBy: "PRICE_MOMENTUM", sortDirection: "DESC", historyRange: 20 },
    dateCoverageBasis: "INDUSTRY_PRICE_AMOUNT_DAILY",
    dateContext: { expectedTradeDate, defaultTradeDate, defaultStatus, displayText },
    hierarchy: { hierarchyVersion, publishedAt, nodes }, coverageStartDate, coverageEndDate, tradeDates,
    level1Nodes: nodes.filter((node) => node.industryLevel === 1),
    level2Nodes: nodes.filter((node) => node.industryLevel === 2),
    level3Nodes: nodes.filter((node) => node.industryLevel === 3),
  };
}

export function buildSectorPriceVolumeSnapshotViewModel(payload: unknown, request: PriceVolumeSnapshotRequest): PriceVolumeSnapshotAdapterResult {
  const root = exactRecord(payload, ["status", "snapshot", "message", "exceptionCode", "debugInfo"], "量价分布 Snapshot");
  const status = enumValue(root.status, ["READY", "EMPTY", "ERROR"] as const, "status");
  const message = nullableString(root.message, "message");
  const exceptionCode = nullableString(root.exceptionCode, "exceptionCode");
  parseDebugInfo(root.debugInfo);
  if (status === "ERROR") {
    if (root.snapshot !== null || !["SA_HIERARCHY_UNAVAILABLE", "SA_QUERY_FAILED"].includes(exceptionCode ?? "")) fail("ERROR 外壳不符合合同。");
    return { kind: "error", message: message ?? "量价分布数据读取失败，请稍后重试。", retryable: true };
  }
  if (exceptionCode !== null) fail("内容态不能携带技术异常码。");
  const snapshot = parseSnapshot(root.snapshot);
  validateSnapshotRequest(snapshot, request);
  if (status === "READY") {
    if (snapshot.coordinateCount <= 0) fail("READY 必须包含完整二维坐标。");
    return { kind: "ready", data: snapshot };
  }
  if (snapshot.coordinateCount !== 0) fail("EMPTY 不能包含完整二维坐标。");
  return { kind: "empty", data: snapshot, message: message ?? "当前范围暂无完整量价坐标。" };
}

export function buildSectorPriceVolumeDetailsViewModel(payload: unknown, request: PriceVolumeDetailsRequest): PriceVolumeDetailsAdapterResult {
  const root = exactRecord(payload, ["status", "details", "message", "exceptionCode", "debugInfo"], "量价分布 Details");
  const status = enumValue(root.status, ["READY", "EMPTY", "ERROR"] as const, "status");
  const message = nullableString(root.message, "message");
  const exceptionCode = nullableString(root.exceptionCode, "exceptionCode");
  parseDebugInfo(root.debugInfo);
  if (status === "ERROR") {
    if (root.details !== null || !["SA_HIERARCHY_UNAVAILABLE", "SA_QUERY_FAILED"].includes(exceptionCode ?? "")) fail("Details ERROR 外壳不符合合同。");
    return { kind: "error", message: message ?? "历史变化读取失败，请稍后重试。", retryable: true };
  }
  if (exceptionCode !== null) fail("Details 内容态不能携带技术异常码。");
  const details = parseDetails(root.details);
  validateDetailsRequest(details, request);
  const hasValue = details.history.some((point) => point.priceMomentumPct !== null || point.amountActivityPct !== null);
  if (status === "READY") {
    if (!hasValue) fail("READY Details 必须包含历史事实。");
    return { kind: "ready", data: details };
  }
  if (hasValue) fail("EMPTY Details 不能包含历史事实。");
  return { kind: "empty", data: details, message: message ?? "当前行业暂无可展示的历史变化。" };
}

function parseSnapshot(value: unknown): PriceVolumeSnapshotViewModel {
  const item = exactRecord(value, [
    "formulaKey", "formulaVersion", "hierarchyVersion", "observedTradeDate", "availability", "scope", "level1Code", "level2Code",
    "period", "totalCount", "coordinateCount", "missingCoordinateCount", "rows",
  ], "Snapshot事实");
  literal(item.formulaKey, "sector-price-volume-distribution", "formulaKey");
  literal(item.formulaVersion, 1, "formulaVersion");
  const rows = arrayValue(item.rows, "rows").map(parseSnapshotRow);
  const totalCount = nonNegativeInteger(item.totalCount, "totalCount");
  const coordinateCount = nonNegativeInteger(item.coordinateCount, "coordinateCount");
  const missingCoordinateCount = nonNegativeInteger(item.missingCoordinateCount, "missingCoordinateCount");
  if (rows.length !== totalCount || coordinateCount + missingCoordinateCount !== totalCount) fail("Snapshot 计数不闭合。");
  if (rows.filter((row) => row.state !== null).length !== coordinateCount) fail("坐标计数与行业行不一致。");
  if (new Set(rows.map((row) => row.sectorCode)).size !== rows.length) fail("Snapshot 行业代码重复。");
  if (rows.length && (new Set(rows.map((row) => row.priceRankableCount)).size !== 1 || new Set(rows.map((row) => row.amountRankableCount)).size !== 1)) fail("可排名数量必须全行一致。");
  if (!isCanonicalPriceOrder(rows)) fail("Snapshot 未遵循冻结的价格默认排序。");
  return {
    formulaKey: "sector-price-volume-distribution", formulaVersion: 1,
    hierarchyVersion: nonEmptyString(item.hierarchyVersion, "hierarchyVersion"),
    observedTradeDate: isoDate(item.observedTradeDate, "observedTradeDate"),
    availability: enumValue(item.availability, AVAILABILITIES, "availability"),
    scope: enumValue(item.scope, SCOPES, "scope"),
    level1Code: nullableSectorCode(item.level1Code, "level1Code"), level2Code: nullableSectorCode(item.level2Code, "level2Code"),
    period: enumValue(item.period, PERIODS, "period"), totalCount, coordinateCount, missingCoordinateCount, rows,
  };
}

function parseSnapshotRow(value: unknown): PriceVolumeSnapshotRowViewModel {
  const row = exactRecord(value, [
    "sectorCode", "sectorName", "industryLevel", "hierarchyPath", "parentSectorCode", "parentSectorName", "rootSectorCode", "rootSectorName",
    "priceMomentumPct", "amountActivityPct", "priceRank", "priceRankableCount", "amountRank", "amountRankableCount", "state",
    "priceMissingReason", "amountMissingReason",
  ], "Snapshot行业行");
  const priceMomentumPct = nullableFiniteNumber(row.priceMomentumPct, "priceMomentumPct");
  const amountActivityPct = nullableFiniteNumber(row.amountActivityPct, "amountActivityPct");
  const priceRank = nullablePositiveInteger(row.priceRank, "priceRank");
  const amountRank = nullablePositiveInteger(row.amountRank, "amountRank");
  const priceRankableCount = nonNegativeInteger(row.priceRankableCount, "priceRankableCount");
  const amountRankableCount = nonNegativeInteger(row.amountRankableCount, "amountRankableCount");
  const priceMissingReason = nullableMissingReason(row.priceMissingReason, "priceMissingReason");
  const amountMissingReason = nullableMissingReason(row.amountMissingReason, "amountMissingReason");
  validateMetric(priceMomentumPct, priceMissingReason, priceRank, priceRankableCount, "价格");
  validateMetric(amountActivityPct, amountMissingReason, amountRank, amountRankableCount, "成交");
  const state = row.state === null ? null : enumValue(row.state, STATES, "state");
  if ((priceMomentumPct !== null && amountActivityPct !== null) !== (state !== null)) fail("量价状态与坐标完整性不一致。");
  if (state !== null && state !== expectedState(priceMomentumPct!, amountActivityPct!)) fail("量价状态与坐标符号不一致。");
  const industryLevel = enumValue(row.industryLevel, [1, 2, 3] as const, "industryLevel");
  return {
    sectorCode: sectorCode(row.sectorCode, "sectorCode"), sectorName: nonEmptyString(row.sectorName, "sectorName"), industryLevel,
    hierarchyPath: nonEmptyString(row.hierarchyPath, "hierarchyPath"), parentSectorCode: nullableSectorCode(row.parentSectorCode, "parentSectorCode"),
    parentSectorName: nullableString(row.parentSectorName, "parentSectorName"), rootSectorCode: sectorCode(row.rootSectorCode, "rootSectorCode"),
    rootSectorName: nonEmptyString(row.rootSectorName, "rootSectorName"), priceMomentumPct, amountActivityPct, priceRank, priceRankableCount,
    amountRank, amountRankableCount, state, priceMissingReason, amountMissingReason,
    priceText: formatSignedPercent(priceMomentumPct), amountText: formatSignedPercent(amountActivityPct),
    stateText: stateText(state), stateClass: state?.toLowerCase().replaceAll("_", "-") ?? "missing", canDrillDown: industryLevel < 3,
  };
}

function parseDetails(value: unknown): PriceVolumeDetailsViewModel {
  const item = exactRecord(value, [
    "formulaKey", "formulaVersion", "hierarchyVersion", "observedTradeDate", "availability", "scope", "level1Code", "level2Code",
    "period", "historyRange", "selected", "history",
  ], "Details事实");
  literal(item.formulaKey, "sector-price-volume-distribution", "formulaKey");
  literal(item.formulaVersion, 1, "formulaVersion");
  const historyRange = enumValue(item.historyRange, HISTORY_RANGES, "historyRange");
  const history = arrayValue(item.history, "history").map(parseHistoryPoint);
  const dates = history.map((point) => point.tradeDate);
  if (!strictlyAscending(dates) || history.length > historyRange) fail("历史日期槽必须唯一升序且不超过请求范围。");
  const observedTradeDate = isoDate(item.observedTradeDate, "observedTradeDate");
  if (dates.length && dates.at(-1) !== observedTradeDate) fail("历史序列必须结束于实际交易日。");
  const selected = exactRecord(item.selected, ["sectorCode", "sectorName", "industryLevel", "hierarchyPath", "parentSectorCode", "rootSectorCode"], "选中行业");
  return {
    formulaKey: "sector-price-volume-distribution", formulaVersion: 1,
    hierarchyVersion: nonEmptyString(item.hierarchyVersion, "hierarchyVersion"), observedTradeDate,
    availability: enumValue(item.availability, AVAILABILITIES, "availability"), scope: enumValue(item.scope, SCOPES, "scope"),
    level1Code: nullableSectorCode(item.level1Code, "level1Code"), level2Code: nullableSectorCode(item.level2Code, "level2Code"),
    period: enumValue(item.period, PERIODS, "period"), historyRange,
    selected: {
      sectorCode: sectorCode(selected.sectorCode, "selected.sectorCode"), sectorName: nonEmptyString(selected.sectorName, "selected.sectorName"),
      industryLevel: enumValue(selected.industryLevel, [1, 2, 3] as const, "selected.industryLevel"),
      hierarchyPath: nonEmptyString(selected.hierarchyPath, "selected.hierarchyPath"),
      parentSectorCode: nullableSectorCode(selected.parentSectorCode, "selected.parentSectorCode"), rootSectorCode: sectorCode(selected.rootSectorCode, "selected.rootSectorCode"),
    }, history,
  };
}

function parseHistoryPoint(value: unknown): PriceVolumeHistoryPointViewModel {
  const point = exactRecord(value, ["tradeDate", "priceMomentumPct", "amountActivityPct", "priceMissingReason", "amountMissingReason"], "历史日期槽");
  const priceMomentumPct = nullableFiniteNumber(point.priceMomentumPct, "priceMomentumPct");
  const amountActivityPct = nullableFiniteNumber(point.amountActivityPct, "amountActivityPct");
  const priceMissingReason = nullableMissingReason(point.priceMissingReason, "priceMissingReason");
  const amountMissingReason = nullableMissingReason(point.amountMissingReason, "amountMissingReason");
  validateValueReason(priceMomentumPct, priceMissingReason, "价格历史");
  validateValueReason(amountActivityPct, amountMissingReason, "成交历史");
  return { tradeDate: isoDate(point.tradeDate, "tradeDate"), priceMomentumPct, amountActivityPct, priceMissingReason, amountMissingReason };
}

function parseHierarchyNode(value: unknown): PriceVolumeHierarchyNode {
  const node = exactRecord(value, ["sectorCode", "sectorName", "industryLevel", "parentSectorCode", "parentSectorName", "rootSectorCode", "rootSectorName", "hierarchyPath", "displayOrder", "isLeaf"], "行业层级节点");
  return {
    sectorCode: sectorCode(node.sectorCode, "sectorCode"), sectorName: nonEmptyString(node.sectorName, "sectorName"),
    industryLevel: enumValue(node.industryLevel, [1, 2, 3] as const, "industryLevel"),
    parentSectorCode: nullableSectorCode(node.parentSectorCode, "parentSectorCode"), parentSectorName: nullableString(node.parentSectorName, "parentSectorName"),
    rootSectorCode: sectorCode(node.rootSectorCode, "rootSectorCode"), rootSectorName: nonEmptyString(node.rootSectorName, "rootSectorName"),
    hierarchyPath: nonEmptyString(node.hierarchyPath, "hierarchyPath"), displayOrder: nonNegativeInteger(node.displayOrder, "displayOrder"), isLeaf: booleanValue(node.isLeaf, "isLeaf"),
  };
}

function parseTradeDate(value: unknown): PriceVolumeTradeDateAvailability {
  const item = exactRecord(value, ["tradeDate", "availability", "expectedSectorCount", "validSectorCount"], "交易日覆盖");
  const expectedSectorCount = positiveInteger(item.expectedSectorCount, "expectedSectorCount");
  const validSectorCount = nonNegativeInteger(item.validSectorCount, "validSectorCount");
  const availability = enumValue(item.availability, AVAILABILITIES, "availability");
  if (validSectorCount > expectedSectorCount) fail("有效行业数不能超过预期行业数。");
  if (availability === "COMPLETE" && validSectorCount !== expectedSectorCount) fail("COMPLETE 覆盖数量不完整。");
  if (availability === "PARTIAL" && !(validSectorCount > 0 && validSectorCount < expectedSectorCount)) fail("PARTIAL 覆盖数量非法。");
  if (availability === "MISSING" && validSectorCount !== 0) fail("MISSING 覆盖数量非法。");
  return { tradeDate: isoDate(item.tradeDate, "tradeDate"), availability, expectedSectorCount, validSectorCount };
}

function parseDebugInfo(value: unknown) {
  if (value === null) return;
  const debug = exactRecord(value, ["expectedTradeDate", "observedTradeDate", "scope", "poolSize", "requestedOpenDateCount", "loadedOpenDateCount", "reasonCounts"], "debugInfo");
  isoDate(debug.expectedTradeDate, "debugInfo.expectedTradeDate"); nullableIsoDate(debug.observedTradeDate, "debugInfo.observedTradeDate");
  if (debug.scope !== null) enumValue(debug.scope, SCOPES, "debugInfo.scope");
  nonNegativeInteger(debug.poolSize, "debugInfo.poolSize"); nonNegativeInteger(debug.requestedOpenDateCount, "debugInfo.requestedOpenDateCount"); nonNegativeInteger(debug.loadedOpenDateCount, "debugInfo.loadedOpenDateCount");
  const reasons = recordValue(debug.reasonCounts, "debugInfo.reasonCounts");
  Object.entries(reasons).forEach(([reason, count]) => { enumValue(reason, MISSING_REASONS, "debug reason"); nonNegativeInteger(count, "debug reason count"); });
}

function validateHierarchy(nodes: PriceVolumeHierarchyNode[]) {
  const byCode = new Map(nodes.map((node) => [node.sectorCode, node]));
  nodes.forEach((node) => {
    if (node.industryLevel === 1) {
      if (node.parentSectorCode !== null || node.rootSectorCode !== node.sectorCode) fail("一级行业层级闭包非法。");
      return;
    }
    const parent = node.parentSectorCode ? byCode.get(node.parentSectorCode) : undefined;
    const root = byCode.get(node.rootSectorCode);
    if (!parent || parent.industryLevel !== node.industryLevel - 1 || !root || root.industryLevel !== 1) fail("行业父子闭包非法。");
    if (node.industryLevel === 2 && parent.sectorCode !== root.sectorCode) fail("二级行业根节点非法。");
    if (node.industryLevel === 3 && parent.rootSectorCode !== root.sectorCode) fail("三级行业根节点非法。");
  });
}

function validateSnapshotRequest(data: PriceVolumeSnapshotViewModel, request: PriceVolumeSnapshotRequest) {
  if (data.hierarchyVersion !== request.hierarchyVersion || data.observedTradeDate !== request.tradeDate || data.scope !== request.scope || data.period !== request.period) fail("Snapshot 响应事实与请求不一致。");
  if (data.level1Code !== (request.level1Code ?? null) || data.level2Code !== (request.level2Code ?? null)) fail("Snapshot 父级选择与请求不一致。");
}

function validateDetailsRequest(data: PriceVolumeDetailsViewModel, request: PriceVolumeDetailsRequest) {
  if (data.hierarchyVersion !== request.hierarchyVersion || data.observedTradeDate !== request.tradeDate || data.scope !== request.scope || data.period !== request.period || data.historyRange !== request.historyRange) fail("Details 响应事实与请求不一致。");
  if (data.level1Code !== (request.level1Code ?? null) || data.level2Code !== (request.level2Code ?? null) || data.selected.sectorCode !== request.sectorCode) fail("Details 选择与请求不一致。");
}

function validateMetric(value: number | null, reason: PriceVolumeMissingReason | null, rank: number | null, count: number, label: string) {
  validateValueReason(value, reason, label);
  if (value === null && rank !== null) fail(`${label}缺失时不能携带名次。`);
  if (value !== null && (rank === null || rank > count)) fail(`${label}存在时必须携带有效名次。`);
}
function validateValueReason(value: number | null, reason: PriceVolumeMissingReason | null, label: string) { if ((value === null) === (reason === null)) fail(`${label}数值与缺失原因必须互补。`); }
function expectedState(price: number, amount: number): PriceVolumeState { if (price > 0 && amount > 0) return "JOINT"; if (price > 0) return "PRICE_ONLY"; if (amount > 0) return "AMOUNT_ONLY"; return "NEUTRAL"; }
function stateText(state: PriceVolumeState | null) { if (state === "JOINT") return "量价共同增强"; if (state === "PRICE_ONLY") return "价格增强"; if (state === "AMOUNT_ONLY") return "成交增强"; if (state === "NEUTRAL") return "量价均不明显"; return "坐标不完整"; }
function formatSignedPercent(value: number | null) { if (value === null) return "--"; if (value > 0) return `+${value.toFixed(2)}%`; return `${value.toFixed(2)}%`; }
function isCanonicalPriceOrder(rows: PriceVolumeSnapshotRowViewModel[]) { return rows.every((row, index) => index === 0 || compareCanonical(rows[index - 1]!, row) <= 0); }
function compareCanonical(left: PriceVolumeSnapshotRowViewModel, right: PriceVolumeSnapshotRowViewModel) { if (left.priceMomentumPct === null && right.priceMomentumPct !== null) return 1; if (left.priceMomentumPct !== null && right.priceMomentumPct === null) return -1; if (left.priceMomentumPct !== null && right.priceMomentumPct !== null && left.priceMomentumPct !== right.priceMomentumPct) return right.priceMomentumPct - left.priceMomentumPct; return left.sectorCode.localeCompare(right.sectorCode); }
function exactRecord(value: unknown, keys: readonly string[], label: string): Record<string, unknown> { const record = recordValue(value, label); const actual = Object.keys(record).sort(); const expected = [...keys].sort(); if (actual.join("|") !== expected.join("|")) fail(`${label}字段不符合冻结合同。`); return record; }
function recordValue(value: unknown, label: string): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${label}必须是对象。`); return value as Record<string, unknown>; }
function arrayValue(value: unknown, label: string): unknown[] { if (!Array.isArray(value)) fail(`${label}必须是数组。`); return value; }
function exactArray(value: unknown, expected: readonly unknown[], label: string) { const actual = arrayValue(value, label); if (actual.length !== expected.length || actual.some((item, index) => item !== expected[index])) fail(`${label}顺序不符合冻结合同。`); }
function enumValue<T extends string | number>(value: unknown, allowed: readonly T[], label: string): T { if (!allowed.includes(value as T)) fail(`${label}枚举值非法。`); return value as T; }
function literal<T>(value: unknown, expected: T, label: string): asserts value is T { if (value !== expected) fail(`${label}不符合冻结合同。`); }
function nonEmptyString(value: unknown, label: string): string { if (typeof value !== "string" || value.trim() === "") fail(`${label}必须是非空文本。`); return value; }
function nullableString(value: unknown, label: string): string | null { if (value === null) return null; return nonEmptyString(value, label); }
function booleanValue(value: unknown, label: string): boolean { if (typeof value !== "boolean") fail(`${label}必须是布尔值。`); return value; }
function nonNegativeInteger(value: unknown, label: string): number { if (!Number.isInteger(value) || (value as number) < 0) fail(`${label}必须是非负整数。`); return value as number; }
function positiveInteger(value: unknown, label: string): number { const result = nonNegativeInteger(value, label); if (result <= 0) fail(`${label}必须大于0。`); return result; }
function nullablePositiveInteger(value: unknown, label: string): number | null { if (value === null) return null; const result = positiveInteger(value, label); return result; }
function nullableFiniteNumber(value: unknown, label: string): number | null { if (value === null) return null; if (typeof value !== "number" || !Number.isFinite(value)) fail(`${label}必须是有限数值。`); return value; }
function sectorCode(value: unknown, label: string): string { const result = nonEmptyString(value, label); if (!CODE_PATTERN.test(result)) fail(`${label}代码格式非法。`); return result; }
function nullableSectorCode(value: unknown, label: string): string | null { if (value === null) return null; return sectorCode(value, label); }
function nullableMissingReason(value: unknown, label: string): PriceVolumeMissingReason | null { if (value === null) return null; return enumValue(value, MISSING_REASONS, label); }
function isoDate(value: unknown, label: string): string { const result = nonEmptyString(value, label); if (!DATE_PATTERN.test(result)) fail(`${label}日期格式非法。`); const parsed = new Date(`${result}T00:00:00Z`); if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== result) fail(`${label}不是真实日期。`); return result; }
function nullableIsoDate(value: unknown, label: string): string | null { if (value === null) return null; return isoDate(value, label); }
function strictlyAscending(values: string[]) { return values.every((value, index) => index === 0 || values[index - 1]! < value); }
function fail(message: string): never { throw new SectorPriceVolumeContractError(message); }
