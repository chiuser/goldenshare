const HIERARCHY_VERSION = "dc-industry-v1";

export function priceVolumeHierarchyNodes() {
  return [
    node("BK1001.DC", "电子", 1, null, null, "BK1001.DC", "电子", "电子", 1, false),
    node("BK1002.DC", "通信", 1, null, null, "BK1002.DC", "通信", "通信", 2, false),
    node("BK1101.DC", "半导体", 2, "BK1001.DC", "电子", "BK1001.DC", "电子", "电子 > 半导体", 3, false),
    node("BK1102.DC", "消费电子", 2, "BK1001.DC", "电子", "BK1001.DC", "电子", "电子 > 消费电子", 4, false),
    node("BK1201.DC", "集成电路", 3, "BK1101.DC", "半导体", "BK1001.DC", "电子", "电子 > 半导体 > 集成电路", 5, true),
    node("BK1202.DC", "模拟芯片", 3, "BK1101.DC", "半导体", "BK1001.DC", "电子", "电子 > 半导体 > 模拟芯片", 6, true),
  ];
}

export function priceVolumeMetaPayload(options: { delayed?: boolean; empty?: boolean } = {}) {
  const defaultTradeDate = options.empty ? null : options.delayed ? "2026-08-26" : "2026-08-27";
  return {
    formulaKey: "sector-price-volume-distribution",
    formulaVersion: 1,
    market: "CN_A",
    periods: [1, 5, 10, 20, 30],
    historyRanges: [20, 30, 60],
    scopes: ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"],
    states: ["JOINT", "PRICE_ONLY", "AMOUNT_ONLY", "NEUTRAL"],
    defaults: { scope: "LEVEL_1", period: 20, stateFilter: "ALL", sortBy: "PRICE_MOMENTUM", sortDirection: "DESC", historyRange: 20 },
    dateCoverageBasis: "INDUSTRY_PRICE_AMOUNT_DAILY",
    dateContext: {
      expectedTradeDate: "2026-08-27",
      defaultTradeDate,
      defaultStatus: options.empty ? "EMPTY" : options.delayed ? "DELAYED" : "READY",
      displayText: options.empty ? "暂无可用盘后数据" : options.delayed ? "数据更新中" : "2026-08-27 盘后数据",
    },
    hierarchy: { hierarchyVersion: HIERARCHY_VERSION, publishedAt: "2026-08-27T20:00:00+08:00", nodes: priceVolumeHierarchyNodes() },
    coverageStartDate: "2026-08-25",
    coverageEndDate: "2026-08-27",
    tradeDates: [
      { tradeDate: "2026-08-25", availability: options.empty ? "MISSING" : "COMPLETE", expectedSectorCount: 6, validSectorCount: options.empty ? 0 : 6 },
      { tradeDate: "2026-08-26", availability: options.empty ? "MISSING" : "COMPLETE", expectedSectorCount: 6, validSectorCount: options.empty ? 0 : 6 },
      { tradeDate: "2026-08-27", availability: options.empty ? "MISSING" : options.delayed ? "PARTIAL" : "COMPLETE", expectedSectorCount: 6, validSectorCount: options.empty ? 0 : options.delayed ? 5 : 6 },
    ],
  };
}

export function priceVolumeSnapshotPayload(url: URL, options: { empty?: boolean } = {}) {
  const scope = url.searchParams.get("scope") ?? "LEVEL_1";
  const tradeDate = url.searchParams.get("tradeDate") ?? "2026-08-27";
  const period = Number(url.searchParams.get("period") ?? 20);
  const level1Code = url.searchParams.get("level1Code");
  const level2Code = url.searchParams.get("level2Code");
  const pool = rowsForScope(scope, level1Code, level2Code);
  const rows = options.empty ? pool.map((item) => missingRow(item)) : pool.map((item, index) => metricRow(item, index, pool.length));
  const coordinateCount = rows.filter((row) => row.state !== null).length;
  return {
    status: coordinateCount > 0 ? "READY" : "EMPTY",
    snapshot: {
      formulaKey: "sector-price-volume-distribution", formulaVersion: 1, hierarchyVersion: HIERARCHY_VERSION,
      observedTradeDate: tradeDate, availability: coordinateCount === rows.length ? "COMPLETE" : coordinateCount === 0 ? "MISSING" : "PARTIAL",
      scope, level1Code, level2Code, period, totalCount: rows.length, coordinateCount, missingCoordinateCount: rows.length - coordinateCount, rows,
    },
    message: coordinateCount > 0 ? null : "当前范围暂无完整量价坐标。",
    exceptionCode: null,
    debugInfo: null,
  };
}

export function priceVolumeDetailsPayload(url: URL, options: { empty?: boolean } = {}) {
  const sectorCode = url.searchParams.get("sectorCode") ?? "BK1001.DC";
  const selected = priceVolumeHierarchyNodes().find((item) => item.sectorCode === sectorCode) ?? priceVolumeHierarchyNodes()[0]!;
  const tradeDate = url.searchParams.get("tradeDate") ?? "2026-08-27";
  const emptyPoint = { priceMomentumPct: null, amountActivityPct: null, priceMissingReason: "HISTORY_INSUFFICIENT", amountMissingReason: "HISTORY_INSUFFICIENT" };
  const history = options.empty ? [
    { tradeDate: "2026-08-26", ...emptyPoint }, { tradeDate, ...emptyPoint },
  ] : [
    { tradeDate: "2026-08-25", priceMomentumPct: 1.2, amountActivityPct: -4.5, priceMissingReason: null, amountMissingReason: null },
    { tradeDate: "2026-08-26", priceMomentumPct: null, amountActivityPct: 6.5, priceMissingReason: "DATE_MISSING", amountMissingReason: null },
    { tradeDate, priceMomentumPct: 8.62, amountActivityPct: 24.8, priceMissingReason: null, amountMissingReason: null },
  ];
  return {
    status: options.empty ? "EMPTY" : "READY",
    details: {
      formulaKey: "sector-price-volume-distribution", formulaVersion: 1, hierarchyVersion: HIERARCHY_VERSION,
      observedTradeDate: tradeDate, availability: options.empty ? "MISSING" : "COMPLETE", scope: url.searchParams.get("scope") ?? "LEVEL_1",
      level1Code: url.searchParams.get("level1Code"), level2Code: url.searchParams.get("level2Code"), period: Number(url.searchParams.get("period") ?? 20),
      historyRange: Number(url.searchParams.get("historyRange") ?? 20),
      selected: { sectorCode: selected.sectorCode, sectorName: selected.sectorName, industryLevel: selected.industryLevel, hierarchyPath: selected.hierarchyPath, parentSectorCode: selected.parentSectorCode, rootSectorCode: selected.rootSectorCode },
      history,
    },
    message: options.empty ? "当前行业暂无可展示的历史变化。" : null,
    exceptionCode: null,
    debugInfo: null,
  };
}

function rowsForScope(scope: string, level1Code: string | null, level2Code: string | null) {
  const nodes = priceVolumeHierarchyNodes();
  if (scope === "LEVEL_1") return nodes.filter((item) => item.industryLevel === 1);
  if (scope === "LEVEL_2") return nodes.filter((item) => item.industryLevel === 2);
  if (scope === "LEVEL_3") return nodes.filter((item) => item.industryLevel === 3);
  if (scope === "LEVEL_1_CHILDREN") return nodes.filter((item) => item.parentSectorCode === level1Code);
  return nodes.filter((item) => item.parentSectorCode === level2Code);
}

function metricRow(item: ReturnType<typeof priceVolumeHierarchyNodes>[number], index: number, total: number) {
  if (index === total - 1 && total > 1) return {
    ...rowIdentity(item), priceMomentumPct: -2.18, amountActivityPct: null, priceRank: index + 1, priceRankableCount: total,
    amountRank: null, amountRankableCount: total - 1, state: null, priceMissingReason: null, amountMissingReason: "AMOUNT_MISSING",
  };
  const price = 8.62 - index * 3.1;
  const amount = 24.8 - index * 8.2;
  return {
    ...rowIdentity(item), priceMomentumPct: price, amountActivityPct: amount, priceRank: index + 1, priceRankableCount: total,
    amountRank: index + 1, amountRankableCount: total - (total > 1 ? 1 : 0), state: price > 0 && amount > 0 ? "JOINT" : price > 0 ? "PRICE_ONLY" : amount > 0 ? "AMOUNT_ONLY" : "NEUTRAL",
    priceMissingReason: null, amountMissingReason: null,
  };
}

function missingRow(item: ReturnType<typeof priceVolumeHierarchyNodes>[number]) {
  return { ...rowIdentity(item), priceMomentumPct: null, amountActivityPct: null, priceRank: null, priceRankableCount: 0, amountRank: null, amountRankableCount: 0, state: null, priceMissingReason: "DATE_MISSING", amountMissingReason: "DATE_MISSING" };
}

function rowIdentity(item: ReturnType<typeof priceVolumeHierarchyNodes>[number]) {
  return { sectorCode: item.sectorCode, sectorName: item.sectorName, industryLevel: item.industryLevel, hierarchyPath: item.hierarchyPath, parentSectorCode: item.parentSectorCode, parentSectorName: item.parentSectorName, rootSectorCode: item.rootSectorCode, rootSectorName: item.rootSectorName };
}

function node(sectorCode: string, sectorName: string, industryLevel: 1 | 2 | 3, parentSectorCode: string | null, parentSectorName: string | null, rootSectorCode: string, rootSectorName: string, hierarchyPath: string, displayOrder: number, isLeaf: boolean) {
  return { sectorCode, sectorName, industryLevel, parentSectorCode, parentSectorName, rootSectorCode, rootSectorName, hierarchyPath, displayOrder, isLeaf };
}
