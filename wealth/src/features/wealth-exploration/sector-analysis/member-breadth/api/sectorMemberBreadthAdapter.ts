import type {
  SectorHierarchyNode,
  SectorMemberBreadthComposition,
  SectorMemberBreadthDetailsAdapterResult,
  SectorMemberBreadthDetailsRequest,
  SectorMemberBreadthDetailsViewModel,
  SectorMemberBreadthHistoryRange,
  SectorMemberBreadthMaPeriod,
  SectorMemberBreadthMetaViewModel,
  SectorMemberBreadthMetric,
  SectorMemberBreadthRankingRow,
  SectorMemberBreadthRankingsAdapterResult,
  SectorMemberBreadthRankingsRequest,
  SectorMemberBreadthRankingsViewModel,
  SectorMemberBreadthReason,
  SectorMemberBreadthScope,
  SectorTradeDateAvailability,
} from "../model/sectorMemberBreadthTypes";

const SCOPES: SectorMemberBreadthScope[] = ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"];
const METRICS: SectorMemberBreadthMetric[] = ["MEMBER_COUNT", "TURNOVER", "MA_POSITION"];
const MA_PERIODS: SectorMemberBreadthMaPeriod[] = [5, 10, 15, 20, 30, 60];
const HISTORY_RANGES: SectorMemberBreadthHistoryRange[] = [20, 30, 60];
const REASONS: SectorMemberBreadthReason[] = ["SOURCE_MEMBER_EMPTY", "MARKET_ROW_MISSING", "PCT_CHANGE_MISSING", "AMOUNT_MISSING", "AMOUNT_NON_POSITIVE", "ADJ_FACTOR_MISSING", "ADJ_FACTOR_NON_POSITIVE", "MA_HISTORY_INSUFFICIENT", "MINIMUM_COUNT_NOT_MET", "COVERAGE_NOT_MET"];
const CODE_PATTERN = /^BK[0-9]{4}\.DC$/;
const STOCK_CODE_PATTERN = /^[0-9]{6}\.(?:SH|SZ|BJ)$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
// Four-decimal percentages: half a final digit per value, plus float noise.
const COMPOSITION_SUM_TOLERANCE = 3 * 0.00005 + 1e-12;
const COVERAGE_ROUNDING_TOLERANCE = 0.00005 + 1e-12;

export class SectorMemberBreadthContractError extends Error {
  constructor(message: string) { super(message); this.name = "SectorMemberBreadthContractError"; }
}

export function buildSectorMemberBreadthMetaViewModel(payload: unknown): SectorMemberBreadthMetaViewModel {
  const root = exactRecord(payload, ["formulaKey", "formulaVersion", "dateCoverageBasis", "dateContext", "hierarchy", "coverageStartDate", "coverageEndDate", "tradeDates", "scopes", "directions", "metrics", "maPeriods", "historyRanges", "minimumCalculableCount", "minimumCoveragePct", "defaults"], "成员广度 Meta");
  literal(root.formulaKey, "sector-member-breadth", "formulaKey"); literal(root.formulaVersion, 1, "formulaVersion"); literal(root.dateCoverageBasis, "INDUSTRY_DAILY", "dateCoverageBasis");
  const dateContext = exactRecord(root.dateContext, ["expectedTradeDate", "defaultTradeDate", "defaultStatus", "displayText"], "dateContext");
  const hierarchy = exactRecord(root.hierarchy, ["hierarchyVersion", "publishedAt", "nodes"], "hierarchy");
  const nodes = arrayValue(hierarchy.nodes, "hierarchy.nodes").map(parseHierarchyNode);
  const coverageStartDate = isoDate(root.coverageStartDate, "coverageStartDate");
  const coverageEndDate = isoDate(root.coverageEndDate, "coverageEndDate");
  const tradeDates = arrayValue(root.tradeDates, "tradeDates").map(parseTradeDate);
  if (tradeDates.length === 0 || tradeDates[0]?.tradeDate !== coverageStartDate || tradeDates.at(-1)?.tradeDate !== coverageEndDate || !strictAscending(tradeDates.map((item) => item.tradeDate))) fail("Meta 交易日覆盖不连续。 ");
  const expectedTradeDate = isoDate(dateContext.expectedTradeDate, "dateContext.expectedTradeDate");
  if (expectedTradeDate !== coverageEndDate) fail("Meta 预期日期必须等于覆盖结束日。 ");
  const defaultTradeDate = dateContext.defaultTradeDate === null ? null : isoDate(dateContext.defaultTradeDate, "dateContext.defaultTradeDate");
  const defaultStatus = enumValue(dateContext.defaultStatus, ["READY", "DELAYED", "EMPTY"] as const, "dateContext.defaultStatus");
  validateDefaultDate(tradeDates, defaultTradeDate, defaultStatus);
  exactArray(root.scopes, SCOPES, "scopes"); exactArray(root.directions, ["UP", "DOWN"], "directions"); exactArray(root.metrics, METRICS, "metrics"); exactArray(root.maPeriods, MA_PERIODS, "maPeriods"); exactArray(root.historyRanges, HISTORY_RANGES, "historyRanges");
  const defaults = exactRecord(root.defaults, ["scope", "direction", "metric", "maPeriod", "historyRange"], "defaults");
  literal(defaults.scope, "LEVEL_1", "defaults.scope"); literal(defaults.direction, "UP", "defaults.direction"); literal(defaults.metric, "MEMBER_COUNT", "defaults.metric"); literal(defaults.maPeriod, 20, "defaults.maPeriod"); literal(defaults.historyRange, 20, "defaults.historyRange");
  return {
    formulaKey: "sector-member-breadth", formulaVersion: 1, dateCoverageBasis: "INDUSTRY_DAILY",
    dateContext: { expectedTradeDate, defaultTradeDate, defaultStatus, displayText: nonEmptyString(dateContext.displayText, "dateContext.displayText") },
    hierarchy: { hierarchyVersion: nonEmptyString(hierarchy.hierarchyVersion, "hierarchyVersion"), publishedAt: dateTime(hierarchy.publishedAt, "publishedAt"), nodes },
    coverageStartDate, coverageEndDate, tradeDates, scopes: [...SCOPES], directions: ["UP", "DOWN"], metrics: [...METRICS], maPeriods: [...MA_PERIODS], historyRanges: [...HISTORY_RANGES],
    minimumCalculableCount: literal(root.minimumCalculableCount, 5, "minimumCalculableCount"), minimumCoveragePct: literal(root.minimumCoveragePct, 80, "minimumCoveragePct"),
    defaults: { scope: "LEVEL_1", direction: "UP", metric: "MEMBER_COUNT", maPeriod: 20, historyRange: 20 },
    level1Nodes: nodes.filter((node) => node.industryLevel === 1), level2Nodes: nodes.filter((node) => node.industryLevel === 2),
  };
}

export function buildSectorMemberBreadthRankingsViewModel(payload: unknown, request: SectorMemberBreadthRankingsRequest): SectorMemberBreadthRankingsAdapterResult {
  const root = exactRecord(payload, ["status", "message", "exceptionCode", "tradeDate", "hierarchyVersion", "formulaKey", "formulaVersion", "scope", "parentSelection", "direction", "metric", "maPeriod", "totalSectorCount", "eligibleSectorCount", "ineligibleSectorCount", "availability", "defaultSelectedSectorCode", "rows"], "成员广度 Rankings");
  const status = enumValue(root.status, ["READY", "EMPTY", "ERROR"] as const, "status");
  const message = nullableString(root.message, "message"); const exceptionCode = nullableString(root.exceptionCode, "exceptionCode");
  validateResponseIdentity(root, request);
  literal(root.scope, request.scope, "scope"); literal(root.direction, request.direction, "direction"); literal(root.metric, request.metric, "metric"); literal(root.maPeriod, request.maPeriod, "maPeriod");
  const parent = parseParentSelection(root.parentSelection);
  validateParentSelection(parent, request);
  const rows = arrayValue(root.rows, "rows").map(parseRankingRow);
  const totalSectorCount = nonNegativeInteger(root.totalSectorCount, "totalSectorCount");
  const eligibleSectorCount = nonNegativeInteger(root.eligibleSectorCount, "eligibleSectorCount");
  const ineligibleSectorCount = nonNegativeInteger(root.ineligibleSectorCount, "ineligibleSectorCount");
  if (rows.length !== totalSectorCount || eligibleSectorCount + ineligibleSectorCount !== totalSectorCount) fail("Rankings 行业计数不平衡。 ");
  if (new Set(rows.map((row) => row.sectorCode)).size !== rows.length || rows.some((row, index) => row.listPosition !== index + 1)) fail("Rankings 行业代码或列表位置不合法。 ");
  if (rows.filter((row) => row.qualificationStatus === "ELIGIBLE").length !== eligibleSectorCount) fail("Rankings 资格计数不一致。 ");
  validateRankingOrder(rows);
  const availability = parseAvailability(root.availability, request.metric, totalSectorCount, eligibleSectorCount);
  const defaultSelectedSectorCode = nullableSectorCode(root.defaultSelectedSectorCode, "defaultSelectedSectorCode");
  const firstEligible = rows.find((row) => row.qualificationStatus === "ELIGIBLE")?.sectorCode ?? null;
  if (defaultSelectedSectorCode !== firstEligible) fail("默认行业必须是第一只有资格行业。 ");
  if (status === "READY" && (exceptionCode !== null || availability.calculableSectorCount === 0)) fail("READY Rankings 必须包含可计算行业且不能携带异常码。 ");
  if (status === "EMPTY" && (exceptionCode !== "SA_SOURCE_EMPTY" || availability.calculableSectorCount !== 0 || rows.length !== 0)) fail("EMPTY Rankings 必须使用空来源事实壳。 ");
  if (status === "ERROR" && (!new Set(["SA_HIERARCHY_UNAVAILABLE", "SA_BREADTH_QUERY_FAILED"]).has(exceptionCode ?? "") || rows.length !== 0)) fail("ERROR Rankings 必须使用批准的安全空壳。 ");
  if (status !== "READY") return status === "EMPTY" ? { kind: "empty", message: message ?? "当前比较范围暂无可计算的成员广度数据。" } : { kind: "error", message: message ?? "成员广度榜单读取失败，请稍后重试。", retryable: true };
  const data: SectorMemberBreadthRankingsViewModel = { status: "READY", message, tradeDate: request.tradeDate, hierarchyVersion: request.hierarchyVersion, scope: request.scope, parentSelection: parent, direction: request.direction, metric: request.metric, maPeriod: request.maPeriod, totalSectorCount, eligibleSectorCount, ineligibleSectorCount, availability, defaultSelectedSectorCode, rows };
  return { kind: "ready", data };
}

export function buildSectorMemberBreadthDetailsViewModel(payload: unknown, request: SectorMemberBreadthDetailsRequest): SectorMemberBreadthDetailsAdapterResult {
  const root = exactRecord(payload, ["status", "message", "exceptionCode", "tradeDate", "hierarchyVersion", "formulaKey", "formulaVersion", "sectorCode", "sectorName", "industryLevel", "hierarchyPath", "direction", "maPeriod", "historyRange", "compositions", "trend", "members"], "成员广度 Details");
  const status = enumValue(root.status, ["READY", "EMPTY", "ERROR"] as const, "status");
  const message = nullableString(root.message, "message"); const exceptionCode = nullableString(root.exceptionCode, "exceptionCode");
  validateResponseIdentity(root, request); literal(root.sectorCode, request.sectorCode, "sectorCode"); literal(root.direction, request.direction, "direction"); literal(root.maPeriod, request.maPeriod, "maPeriod"); literal(root.historyRange, request.historyRange, "historyRange");
  const sectorName = nonEmptyString(root.sectorName, "sectorName"); const industryLevel = enumValue(root.industryLevel, [1, 2, 3] as const, "industryLevel"); const hierarchyPath = nonEmptyString(root.hierarchyPath, "hierarchyPath");
  if (status !== "READY") {
    if (arrayValue(root.compositions, "compositions").length || arrayValue(root.trend, "trend").length || arrayValue(root.members, "members").length) fail("EMPTY/ERROR Details 不能携带事实。 ");
    if (status === "EMPTY" && exceptionCode !== "SA_BREADTH_SOURCE_EMPTY") fail("EMPTY Details 必须使用来源为空异常码。 ");
    if (status === "ERROR" && !new Set(["SA_HIERARCHY_UNAVAILABLE", "SA_BREADTH_QUERY_FAILED"]).has(exceptionCode ?? "")) fail("ERROR Details 必须使用批准的安全异常码。 ");
    return status === "EMPTY" ? { kind: "empty", message: message ?? "当前行业暂无来源成分股数据。" } : { kind: "error", message: message ?? "成员广度详情读取失败，请稍后重试。", retryable: true };
  }
  if (exceptionCode !== null) fail("READY Details 不能携带异常码。 ");
  const compositions = arrayValue(root.compositions, "compositions").map(parseComposition);
  if (compositions.map((item) => item.metric).join("|") !== METRICS.join("|")) fail("Details 三项组成顺序不合法。 ");
  const trend = arrayValue(root.trend, "trend").map((value) => {
    const row = exactRecord(value, ["tradeDate", "memberPct", "turnoverPct", "maPositionPct", "memberReasonCodes", "turnoverReasonCodes", "maPositionReasonCodes"], "trend");
    return { tradeDate: isoDate(row.tradeDate, "trend.tradeDate"), memberPct: nullableBoundedNumber(row.memberPct, 0, 100, "memberPct"), turnoverPct: nullableBoundedNumber(row.turnoverPct, 0, 100, "turnoverPct"), maPositionPct: nullableBoundedNumber(row.maPositionPct, 0, 100, "maPositionPct"), memberReasonCodes: reasonCodes(row.memberReasonCodes), turnoverReasonCodes: reasonCodes(row.turnoverReasonCodes), maPositionReasonCodes: reasonCodes(row.maPositionReasonCodes) };
  });
  if (trend.length === 0 || trend.length > request.historyRange || trend.at(-1)?.tradeDate !== request.tradeDate || !strictAscending(trend.map((item) => item.tradeDate))) fail("Details 趋势日期槽不合法。 ");
  const members = arrayValue(root.members, "members").map((value) => {
    const row = exactRecord(value, ["stockName", "stockCode", "dailyPctChg", "amountThousandYuan", "amountContributionPct", "maRelation", "maDistancePct", "reasonCodes"], "member");
    const maRelation = row.maRelation === null ? null : enumValue(row.maRelation, ["ABOVE", "EQUAL", "BELOW"] as const, "maRelation");
    const maDistancePct = nullableFiniteNumber(row.maDistancePct, "maDistancePct"); if ((maRelation === null) !== (maDistancePct === null)) fail("成员均线关系与距离必须同有同空。 ");
    return { stockName: nullableString(row.stockName, "stockName"), stockCode: patternString(row.stockCode, STOCK_CODE_PATTERN, "stockCode"), dailyPctChg: nullableFiniteNumber(row.dailyPctChg, "dailyPctChg"), amountThousandYuan: nullableNonNegativeNumber(row.amountThousandYuan, "amountThousandYuan"), amountContributionPct: nullableBoundedNumber(row.amountContributionPct, 0, 100, "amountContributionPct"), maRelation, maDistancePct, reasonCodes: reasonCodes(row.reasonCodes) };
  });
  if (new Set(members.map((row) => row.stockCode)).size !== members.length) fail("Details 成员代码重复。 ");
  validateMemberOrder(members, request.direction);
  const data: SectorMemberBreadthDetailsViewModel = { status: "READY", message, tradeDate: request.tradeDate, hierarchyVersion: request.hierarchyVersion, sectorCode: request.sectorCode, sectorName, industryLevel, hierarchyPath, direction: request.direction, maPeriod: request.maPeriod, historyRange: request.historyRange, compositions, trend, members };
  return { kind: "ready", data };
}

function parseHierarchyNode(value: unknown): SectorHierarchyNode {
  const row = exactRecord(value, ["sectorCode", "sectorName", "industryLevel", "parentSectorCode", "parentSectorName", "rootSectorCode", "rootSectorName", "hierarchyPath", "displayOrder", "isLeaf"], "hierarchy node");
  return { sectorCode: sectorCode(row.sectorCode, "sectorCode"), sectorName: nonEmptyString(row.sectorName, "sectorName"), industryLevel: enumValue(row.industryLevel, [1, 2, 3] as const, "industryLevel"), parentSectorCode: nullableSectorCode(row.parentSectorCode, "parentSectorCode"), parentSectorName: nullableString(row.parentSectorName, "parentSectorName"), rootSectorCode: sectorCode(row.rootSectorCode, "rootSectorCode"), rootSectorName: nonEmptyString(row.rootSectorName, "rootSectorName"), hierarchyPath: nonEmptyString(row.hierarchyPath, "hierarchyPath"), displayOrder: nonNegativeInteger(row.displayOrder, "displayOrder"), isLeaf: booleanValue(row.isLeaf, "isLeaf") };
}
function parseTradeDate(value: unknown): SectorTradeDateAvailability {
  const row = exactRecord(value, ["tradeDate", "availability", "expectedSectorCount", "validSectorCount"], "tradeDate");
  const expectedSectorCount = positiveInteger(row.expectedSectorCount, "expectedSectorCount"); const validSectorCount = nonNegativeInteger(row.validSectorCount, "validSectorCount"); const availability = enumValue(row.availability, ["COMPLETE", "PARTIAL", "MISSING"] as const, "availability");
  if (validSectorCount > expectedSectorCount || (availability === "COMPLETE" && validSectorCount !== expectedSectorCount) || (availability === "PARTIAL" && !(validSectorCount > 0 && validSectorCount < expectedSectorCount)) || (availability === "MISSING" && validSectorCount !== 0)) fail("交易日覆盖计数不合法。 ");
  return { tradeDate: isoDate(row.tradeDate, "tradeDate"), availability, expectedSectorCount, validSectorCount };
}
function validateDefaultDate(dates: SectorTradeDateAvailability[], selected: string | null, status: "READY" | "DELAYED" | "EMPTY") {
  const latest = dates.at(-1)!; const complete = dates.filter((item) => item.availability === "COMPLETE").at(-1)?.tradeDate ?? null;
  if (latest.availability === "COMPLETE" && (selected !== latest.tradeDate || status !== "READY")) fail("完整预期日必须作为 READY 默认日。 ");
  if (latest.availability !== "COMPLETE" && complete && (selected !== complete || status !== "DELAYED")) fail("不完整预期日必须回退最近完整日。 ");
  if (!complete && (selected !== null || status !== "EMPTY")) fail("无完整日期必须返回 EMPTY 默认日。 ");
}
function validateResponseIdentity(root: Record<string, unknown>, request: { tradeDate: string; hierarchyVersion: string }) {
  literal(root.tradeDate, request.tradeDate, "tradeDate"); literal(root.hierarchyVersion, request.hierarchyVersion, "hierarchyVersion"); literal(root.formulaKey, "sector-member-breadth", "formulaKey"); literal(root.formulaVersion, 1, "formulaVersion");
}
function parseParentSelection(value: unknown) { const row = exactRecord(value, ["level1Code", "level1Name", "level2Code", "level2Name"], "parentSelection"); return { level1Code: nullableSectorCode(row.level1Code, "level1Code"), level1Name: nullableString(row.level1Name, "level1Name"), level2Code: nullableSectorCode(row.level2Code, "level2Code"), level2Name: nullableString(row.level2Name, "level2Name") }; }
function validateParentSelection(parent: ReturnType<typeof parseParentSelection>, request: SectorMemberBreadthRankingsRequest) { if (parent.level1Code !== (request.level1Code ?? null) || parent.level2Code !== (request.level2Code ?? null)) fail("响应父级选择与请求不一致。 "); if ((parent.level1Code === null) !== (parent.level1Name === null) || (parent.level2Code === null) !== (parent.level2Name === null)) fail("响应父级代码与名称必须同有同空。 "); }
function parseRankingRow(value: unknown): SectorMemberBreadthRankingRow {
  const row = exactRecord(value, ["listPosition", "rank", "rankTotal", "sectorCode", "sectorName", "industryLevel", "hierarchyPath", "sourceMemberCount", "calculableCount", "coveragePct", "metricValuePct", "qualificationStatus", "reasonCodes"], "ranking row");
  const sourceMemberCount = nonNegativeInteger(row.sourceMemberCount, "sourceMemberCount"); const calculableCount = nonNegativeInteger(row.calculableCount, "calculableCount"); if (calculableCount > sourceMemberCount) fail("可计算数不能超过来源成员数。 ");
  const rank = nullablePositiveInteger(row.rank, "rank"); const rankTotal = nullablePositiveInteger(row.rankTotal, "rankTotal"); const metricValuePct = nullableBoundedNumber(row.metricValuePct, 0, 100, "metricValuePct"); const qualificationStatus = enumValue(row.qualificationStatus, ["ELIGIBLE", "INELIGIBLE"] as const, "qualificationStatus");
  if ([rank, rankTotal, metricValuePct].some((item) => item === null) !== [rank, rankTotal, metricValuePct].every((item) => item === null)) fail("排名、排名总数和指标值必须同有同空。 ");
  if ((qualificationStatus === "ELIGIBLE") !== (rank !== null)) fail("资格与排名事实不一致。 ");
  const coveragePct = boundedNumber(row.coveragePct, 0, 100, "coveragePct");
  validateCoverage(sourceMemberCount, calculableCount, coveragePct, "ranking row");
  if ((calculableCount >= 5 && coveragePct >= 80) !== (qualificationStatus === "ELIGIBLE")) fail("排名资格与5+80%门禁不一致。 ");
  return { listPosition: positiveInteger(row.listPosition, "listPosition"), rank, rankTotal, sectorCode: sectorCode(row.sectorCode, "sectorCode"), sectorName: nonEmptyString(row.sectorName, "sectorName"), industryLevel: enumValue(row.industryLevel, [1, 2, 3] as const, "industryLevel"), hierarchyPath: nonEmptyString(row.hierarchyPath, "hierarchyPath"), sourceMemberCount, calculableCount, coveragePct, metricValuePct, qualificationStatus, reasonCodes: reasonCodes(row.reasonCodes), rankText: rank === null ? "--" : `${rank} / ${rankTotal}`, metricText: formatPct(metricValuePct), coverageText: `${calculableCount} / ${sourceMemberCount} · ${coveragePct.toFixed(1)}%` };
}
function validateRankingOrder(rows: SectorMemberBreadthRankingRow[]) {
  const eligible = rows.filter((row) => row.qualificationStatus === "ELIGIBLE");
  for (let index = 0; index < eligible.length; index += 1) { const row = eligible[index]!; const previous = eligible[index - 1]; if (row.rankTotal !== eligible.length) fail("rankTotal 必须等于有资格行业数。 "); if (previous && (previous.metricValuePct ?? 0) < (row.metricValuePct ?? 0)) fail("有资格行业未按指标降序。 "); if (previous?.metricValuePct === row.metricValuePct && previous.sectorCode > row.sectorCode) fail("并列行业未按代码稳定排序。 "); const expected = previous?.metricValuePct === row.metricValuePct ? previous.rank : index + 1; if (row.rank !== expected) fail("行业排名不是标准竞争排名。 "); }
  const ineligible = rows.slice(eligible.length); if (ineligible.some((row) => row.qualificationStatus !== "INELIGIBLE")) fail("无资格行业必须位于有资格行业之后。 "); if (ineligible.some((row, index) => index > 0 && ineligible[index - 1]!.sectorCode > row.sectorCode)) fail("无资格行业未按代码稳定排序。 ");
}
function parseAvailability(value: unknown, metric: SectorMemberBreadthMetric, total: number, eligible: number) { const row = exactRecord(value, ["metric", "calculableSectorCount", "eligibleSectorCount", "status", "reasonCodes"], "availability"); literal(row.metric, metric, "availability.metric"); const calculableSectorCount = nonNegativeInteger(row.calculableSectorCount, "calculableSectorCount"); const eligibleSectorCount = nonNegativeInteger(row.eligibleSectorCount, "eligibleSectorCount"); if (calculableSectorCount > total || eligibleSectorCount !== eligible) fail("availability 计数不一致。 "); const status = enumValue(row.status, ["AVAILABLE", "PARTIAL", "UNAVAILABLE"] as const, "availability.status"); const expected = calculableSectorCount === 0 ? "UNAVAILABLE" : calculableSectorCount === total ? "AVAILABLE" : "PARTIAL"; if (status !== expected) fail("availability 状态不一致。 "); return { metric, calculableSectorCount, eligibleSectorCount, status, reasonCodes: reasonCodes(row.reasonCodes) }; }
function parseComposition(value: unknown): SectorMemberBreadthComposition { const row = exactRecord(value, ["metric", "sourceCount", "calculableCount", "coveragePct", "eligible", "positiveCount", "neutralCount", "negativeCount", "positivePct", "neutralPct", "negativePct", "reasonCodes"], "composition"); const sourceCount = nonNegativeInteger(row.sourceCount, "sourceCount"); const calculableCount = nonNegativeInteger(row.calculableCount, "calculableCount"); const positiveCount = nonNegativeInteger(row.positiveCount, "positiveCount"); const neutralCount = nonNegativeInteger(row.neutralCount, "neutralCount"); const negativeCount = nonNegativeInteger(row.negativeCount, "negativeCount"); if (calculableCount > sourceCount || positiveCount + neutralCount + negativeCount !== calculableCount) fail("组成数量不平衡。 "); const percentages = [nullableBoundedNumber(row.positivePct, 0, 100, "positivePct"), nullableBoundedNumber(row.neutralPct, 0, 100, "neutralPct"), nullableBoundedNumber(row.negativePct, 0, 100, "negativePct")] as const; if (percentages.some((item) => item === null) !== percentages.every((item) => item === null)) fail("组成百分比必须同有同空。 "); if (percentages[0] !== null && Math.abs(percentages[0] + percentages[1]! + percentages[2]! - 100) > COMPOSITION_SUM_TOLERANCE) fail("组成百分比之和必须等于100。 "); const coveragePct = boundedNumber(row.coveragePct, 0, 100, "coveragePct"); const eligible = booleanValue(row.eligible, "eligible"); validateCoverage(sourceCount, calculableCount, coveragePct, "composition"); if ((calculableCount >= 5 && coveragePct >= 80) !== eligible) fail("组成资格与5+80%门禁不一致。 "); return { metric: enumValue(row.metric, METRICS, "metric"), sourceCount, calculableCount, coveragePct, eligible, positiveCount, neutralCount, negativeCount, positivePct: percentages[0], neutralPct: percentages[1], negativePct: percentages[2], reasonCodes: reasonCodes(row.reasonCodes) }; }

function validateCoverage(sourceCount: number, calculableCount: number, coveragePct: number, label: string) { const expected = sourceCount === 0 ? 0 : calculableCount / sourceCount * 100; if (Math.abs(expected - coveragePct) > COVERAGE_ROUNDING_TOLERANCE) fail(`${label} 覆盖率与数量不一致。 `); }
function validateMemberOrder(rows: SectorMemberBreadthDetailsViewModel["members"], direction: "UP" | "DOWN") { const sorted = [...rows].sort((left, right) => { if (left.dailyPctChg === null || right.dailyPctChg === null) { if (left.dailyPctChg !== right.dailyPctChg) return left.dailyPctChg === null ? 1 : -1; } else if (left.dailyPctChg !== right.dailyPctChg) return direction === "UP" ? right.dailyPctChg - left.dailyPctChg : left.dailyPctChg - right.dailyPctChg; if (left.amountThousandYuan === null || right.amountThousandYuan === null) { if (left.amountThousandYuan !== right.amountThousandYuan) return left.amountThousandYuan === null ? 1 : -1; } else if (left.amountThousandYuan !== right.amountThousandYuan) return right.amountThousandYuan - left.amountThousandYuan; return left.stockCode.localeCompare(right.stockCode); }); if (rows.some((row, index) => row !== sorted[index])) fail("Details 成员未按冻结次序返回。 "); }

function exactRecord(value: unknown, keys: string[], label: string): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${label} 必须是对象。 `); const record = value as Record<string, unknown>; const actual = Object.keys(record).sort(); const expected = [...keys].sort(); if (actual.join("|") !== expected.join("|")) fail(`${label} 字段不符合冻结合同。 `); return record; }
function arrayValue(value: unknown, label: string): unknown[] { if (!Array.isArray(value)) fail(`${label} 必须是数组。 `); return value; }
function exactArray<T extends string | number>(value: unknown, expected: readonly T[], label: string): void { const array = arrayValue(value, label); if (array.length !== expected.length || array.some((item, index) => item !== expected[index])) fail(`${label} 顺序不符合冻结合同。 `); }
function enumValue<T extends string | number>(value: unknown, allowed: readonly T[], label: string): T { if (!allowed.includes(value as T)) fail(`${label} 枚举值非法。 `); return value as T; }
function literal<T extends string | number>(value: unknown, expected: T, label: string): T { if (value !== expected) fail(`${label} 不符合冻结合同。 `); return expected; }
function nonEmptyString(value: unknown, label: string): string { if (typeof value !== "string" || value.trim() === "") fail(`${label} 必须是非空字符串。 `); return value; }
function nullableString(value: unknown, label: string): string | null { return value === null ? null : typeof value === "string" ? value : fail(`${label} 必须是字符串或 null。 `); }
function patternString(value: unknown, pattern: RegExp, label: string): string { const text = nonEmptyString(value, label); if (!pattern.test(text)) fail(`${label} 格式非法。 `); return text; }
function sectorCode(value: unknown, label: string): string { return patternString(value, CODE_PATTERN, label); }
function nullableSectorCode(value: unknown, label: string): string | null { return value === null ? null : sectorCode(value, label); }
function booleanValue(value: unknown, label: string): boolean { if (typeof value !== "boolean") fail(`${label} 必须是布尔值。 `); return value; }
function finiteNumber(value: unknown, label: string): number { if (typeof value !== "number" || !Number.isFinite(value)) fail(`${label} 必须是有限数值。 `); return value; }
function nullableFiniteNumber(value: unknown, label: string): number | null { return value === null ? null : finiteNumber(value, label); }
function boundedNumber(value: unknown, min: number, max: number, label: string): number { const number = finiteNumber(value, label); if (number < min || number > max) fail(`${label} 超出允许范围。 `); return number; }
function nullableBoundedNumber(value: unknown, min: number, max: number, label: string): number | null { return value === null ? null : boundedNumber(value, min, max, label); }
function nullableNonNegativeNumber(value: unknown, label: string): number | null { const number = nullableFiniteNumber(value, label); if (number !== null && number < 0) fail(`${label} 不能为负数。 `); return number; }
function nonNegativeInteger(value: unknown, label: string): number { const number = finiteNumber(value, label); if (!Number.isInteger(number) || number < 0) fail(`${label} 必须是非负整数。 `); return number; }
function positiveInteger(value: unknown, label: string): number { const number = nonNegativeInteger(value, label); if (number < 1) fail(`${label} 必须是正整数。 `); return number; }
function nullablePositiveInteger(value: unknown, label: string): number | null { return value === null ? null : positiveInteger(value, label); }
function isoDate(value: unknown, label: string): string { const text = nonEmptyString(value, label); if (!DATE_PATTERN.test(text) || new Date(`${text}T00:00:00Z`).toISOString().slice(0, 10) !== text) fail(`${label} 日期格式非法。 `); return text; }
function dateTime(value: unknown, label: string): string { const text = nonEmptyString(value, label); if (Number.isNaN(Date.parse(text))) fail(`${label} 时间格式非法。 `); return text; }
function strictAscending(values: string[]): boolean { return values.length === new Set(values).size && values.every((value, index) => index === 0 || values[index - 1]! < value); }
function reasonCodes(value: unknown): SectorMemberBreadthReason[] { const reasons = arrayValue(value, "reasonCodes").map((item) => enumValue(item, REASONS, "reasonCode")); if (new Set(reasons).size !== reasons.length) fail("reasonCodes 不能重复。 "); return reasons; }
function formatPct(value: number | null): string { return value === null ? "--" : `${value.toFixed(1)}%`; }
function fail(message: string): never { throw new SectorMemberBreadthContractError(message.trim()); }
