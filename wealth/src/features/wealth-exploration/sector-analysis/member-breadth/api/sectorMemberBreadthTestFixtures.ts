export function breadthMetaPayload(options: { delayed?: boolean; empty?: boolean } = {}) {
  const dates = options.empty ? [
    { tradeDate: "2026-08-26", availability: "MISSING", expectedSectorCount: 4, validSectorCount: 0 },
    { tradeDate: "2026-08-27", availability: "MISSING", expectedSectorCount: 4, validSectorCount: 0 },
  ] : [
    { tradeDate: "2026-08-26", availability: "COMPLETE", expectedSectorCount: 4, validSectorCount: 4 },
    { tradeDate: "2026-08-27", availability: options.delayed ? "PARTIAL" : "COMPLETE", expectedSectorCount: 4, validSectorCount: options.delayed ? 3 : 4 },
  ];
  return {
    formulaKey: "sector-member-breadth", formulaVersion: 1, dateCoverageBasis: "INDUSTRY_DAILY",
    dateContext: { expectedTradeDate: "2026-08-27", defaultTradeDate: options.empty ? null : options.delayed ? "2026-08-26" : "2026-08-27", defaultStatus: options.empty ? "EMPTY" : options.delayed ? "DELAYED" : "READY", displayText: options.empty ? "暂无可用盘后数据" : options.delayed ? "数据更新中" : "2026-08-27 盘后数据" },
    hierarchy: { hierarchyVersion: "dc-industry-v1", publishedAt: "2026-08-27T20:00:00+08:00", nodes: hierarchyNodes() },
    coverageStartDate: "2026-08-26", coverageEndDate: "2026-08-27", tradeDates: dates,
    scopes: ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"], directions: ["UP", "DOWN"], metrics: ["MEMBER_COUNT", "TURNOVER", "MA_POSITION"], maPeriods: [5, 10, 15, 20, 30, 60], historyRanges: [20, 30, 60], minimumCalculableCount: 5, minimumCoveragePct: 80,
    defaults: { scope: "LEVEL_1", direction: "UP", metric: "MEMBER_COUNT", maPeriod: 20, historyRange: 20 },
  };
}

export function breadthRankingsPayload(url: URL, options: { allIneligible?: boolean; partial?: boolean } = {}) {
  const scope = url.searchParams.get("scope") ?? "LEVEL_1"; const metric = url.searchParams.get("metric") ?? "MEMBER_COUNT"; const tradeDate = url.searchParams.get("tradeDate") ?? "2026-08-27"; const maPeriod = Number(url.searchParams.get("maPeriod") ?? 20);
  const pool = scope === "LEVEL_2" ? hierarchyNodes().filter((node) => node.industryLevel === 2) : scope === "LEVEL_3" ? hierarchyNodes().filter((node) => node.industryLevel === 3) : scope === "LEVEL_1_CHILDREN" ? hierarchyNodes().filter((node) => node.parentSectorCode === url.searchParams.get("level1Code")) : scope === "LEVEL_2_CHILDREN" ? hierarchyNodes().filter((node) => node.parentSectorCode === url.searchParams.get("level2Code")) : hierarchyNodes().filter((node) => node.industryLevel === 1);
  const rows = pool.map((node, index) => {
    const eligible = !options.allIneligible && index === 0; const value = eligible ? 72.5 : null;
    const sourceMemberCount = options.allIneligible || index === 1 ? 4 : 10; const calculableCount = options.allIneligible || index === 1 ? 3 : 9;
    return { listPosition: index + 1, rank: eligible ? 1 : null, rankTotal: eligible ? 1 : null, sectorCode: node.sectorCode, sectorName: node.sectorName, industryLevel: node.industryLevel, hierarchyPath: node.hierarchyPath, sourceMemberCount, calculableCount, coveragePct: calculableCount / sourceMemberCount * 100, metricValuePct: value, qualificationStatus: eligible ? "ELIGIBLE" : "INELIGIBLE", reasonCodes: eligible ? [] : ["MINIMUM_COUNT_NOT_MET"] };
  });
  return { status: "READY", message: null, exceptionCode: null, tradeDate, hierarchyVersion: "dc-industry-v1", formulaKey: "sector-member-breadth", formulaVersion: 1, scope, parentSelection: parentSelection(scope, url), direction: url.searchParams.get("direction") ?? "UP", metric, maPeriod, totalSectorCount: rows.length, eligibleSectorCount: rows.filter((row) => row.qualificationStatus === "ELIGIBLE").length, ineligibleSectorCount: rows.filter((row) => row.qualificationStatus === "INELIGIBLE").length, availability: { metric, calculableSectorCount: options.partial ? Math.max(1, rows.length - 1) : rows.length, eligibleSectorCount: rows.filter((row) => row.qualificationStatus === "ELIGIBLE").length, status: options.partial ? "PARTIAL" : "AVAILABLE", reasonCodes: options.partial ? ["MARKET_ROW_MISSING"] : [] }, defaultSelectedSectorCode: rows.find((row) => row.qualificationStatus === "ELIGIBLE")?.sectorCode ?? null, rows };
}

export function breadthDetailsPayload(url: URL, options: { maUnavailable?: boolean; nullMiddle?: boolean } = {}) {
  const sectorCode = url.searchParams.get("sectorCode") ?? "BK1001.DC"; const node = hierarchyNodes().find((item) => item.sectorCode === sectorCode) ?? hierarchyNodes()[0]!; const direction = url.searchParams.get("direction") ?? "UP"; const maPeriod = Number(url.searchParams.get("maPeriod") ?? 20); const historyRange = Number(url.searchParams.get("historyRange") ?? 20); const tradeDate = url.searchParams.get("tradeDate") ?? "2026-08-27";
  return { status: "READY", message: null, exceptionCode: null, tradeDate, hierarchyVersion: "dc-industry-v1", formulaKey: "sector-member-breadth", formulaVersion: 1, sectorCode, sectorName: node.sectorName, industryLevel: node.industryLevel, hierarchyPath: node.hierarchyPath, direction, maPeriod, historyRange,
    compositions: [composition("MEMBER_COUNT", 72, 20), composition("TURNOVER", 68, 20), options.maUnavailable ? composition("MA_POSITION", null, 3) : composition("MA_POSITION", 65, 20)],
    trend: [
      { tradeDate: tradeDate === "2026-08-26" ? "2026-08-25" : "2026-08-26", memberPct: 60, turnoverPct: 58, maPositionPct: options.maUnavailable || options.nullMiddle ? null : 55, memberReasonCodes: [], turnoverReasonCodes: [], maPositionReasonCodes: options.maUnavailable || options.nullMiddle ? ["ADJ_FACTOR_MISSING"] : [] },
      { tradeDate, memberPct: 72, turnoverPct: 68, maPositionPct: options.maUnavailable ? null : 65, memberReasonCodes: [], turnoverReasonCodes: [], maPositionReasonCodes: options.maUnavailable ? ["ADJ_FACTOR_MISSING"] : [] },
    ],
    members: [
      { stockName: "股票甲", stockCode: "000001.SZ", dailyPctChg: direction === "UP" ? 2.5 : -2.5, amountThousandYuan: 123456, amountContributionPct: 36.5, maRelation: options.maUnavailable ? null : direction === "UP" ? "ABOVE" : "BELOW", maDistancePct: options.maUnavailable ? null : direction === "UP" ? 3.2 : -3.2, reasonCodes: options.maUnavailable ? ["ADJ_FACTOR_MISSING"] : [] },
      { stockName: "股票乙名称很长用于省略测试", stockCode: "000002.SZ", dailyPctChg: null, amountThousandYuan: null, amountContributionPct: null, maRelation: null, maDistancePct: null, reasonCodes: ["MARKET_ROW_MISSING"] },
    ],
  };
}

function hierarchyNodes() { return [
  { sectorCode: "BK1001.DC", sectorName: "电子", industryLevel: 1, parentSectorCode: null, parentSectorName: null, rootSectorCode: "BK1001.DC", rootSectorName: "电子", hierarchyPath: "电子", displayOrder: 1, isLeaf: false },
  { sectorCode: "BK1002.DC", sectorName: "通信", industryLevel: 1, parentSectorCode: null, parentSectorName: null, rootSectorCode: "BK1002.DC", rootSectorName: "通信", hierarchyPath: "通信", displayOrder: 2, isLeaf: false },
  { sectorCode: "BK1101.DC", sectorName: "半导体", industryLevel: 2, parentSectorCode: "BK1001.DC", parentSectorName: "电子", rootSectorCode: "BK1001.DC", rootSectorName: "电子", hierarchyPath: "电子 > 半导体", displayOrder: 3, isLeaf: false },
  { sectorCode: "BK1102.DC", sectorName: "消费电子", industryLevel: 2, parentSectorCode: "BK1001.DC", parentSectorName: "电子", rootSectorCode: "BK1001.DC", rootSectorName: "电子", hierarchyPath: "电子 > 消费电子", displayOrder: 4, isLeaf: false },
  { sectorCode: "BK1201.DC", sectorName: "集成电路", industryLevel: 3, parentSectorCode: "BK1101.DC", parentSectorName: "半导体", rootSectorCode: "BK1001.DC", rootSectorName: "电子", hierarchyPath: "电子 > 半导体 > 集成电路", displayOrder: 5, isLeaf: true },
]; }
function parentSelection(scope: string, url: URL) { const level1Code = scope === "LEVEL_1_CHILDREN" || scope === "LEVEL_2_CHILDREN" ? url.searchParams.get("level1Code") : null; const level2Code = scope === "LEVEL_2_CHILDREN" ? url.searchParams.get("level2Code") : null; const level1 = hierarchyNodes().find((node) => node.sectorCode === level1Code); const level2 = hierarchyNodes().find((node) => node.sectorCode === level2Code); return { level1Code, level1Name: level1?.sectorName ?? null, level2Code, level2Name: level2?.sectorName ?? null }; }
function composition(metric: string, positive: number | null, calculableCount: number) { return { metric, sourceCount: 20, calculableCount, coveragePct: calculableCount / 20 * 100, eligible: calculableCount >= 16, positiveCount: positive === null ? 0 : 12, neutralCount: positive === null ? 0 : 2, negativeCount: positive === null ? 3 : 6, positivePct: positive, neutralPct: positive === null ? null : 8, negativePct: positive === null ? null : 100 - positive - 8, reasonCodes: positive === null ? ["COVERAGE_NOT_MET"] : [] }; }
