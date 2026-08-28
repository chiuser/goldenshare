export function relativeMetaPayload() {
  return {
    status: "READY", tradingDay: tradingDay(), pageStatus: pageStatus(), message: null, exceptionCode: null, debugInfo: null,
    formula: { formulaKey: "sector-relative-rotation", formulaVersion: 1, basisFormulaKey: "sector-cross-sectional-momentum", basisFormulaVersion: 1, periods: [5, 10, 20, 30], improvementLookbackDays: 5, trailLengths: [20, 30, 60], minimumGroupSize: 3, scopes: ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"], xDomain: [0, 100], xSplit: 50, ySplit: 0 },
    defaults: { scope: "LEVEL_1", period: 20, trailLength: 20, quadrantFilter: "ALL" },
    hierarchy: { hierarchyVersion: "dc-industry-v1", publishedAt: "2026-08-27T20:30:00+08:00", nodes: hierarchyNodes() },
    coverageStartDate: "2026-08-26", coverageEndDate: "2026-08-27",
    tradeDates: [
      { tradeDate: "2026-08-26", availability: "PARTIAL", expectedSectorCount: 4, validSectorCount: 3 },
      { tradeDate: "2026-08-27", availability: "COMPLETE", expectedSectorCount: 4, validSectorCount: 4 },
    ],
  };
}

export function relativeResultsPayload(url?: URL): any {
  const scope = url?.searchParams.get("scope") ?? "LEVEL_1";
  const period = Number(url?.searchParams.get("period") ?? 20);
  const trailLength = Number(url?.searchParams.get("trailLength") ?? 20);
  const selectedSectorCode = url?.searchParams.get("sectorCode") ?? "BK1001.DC";
  const level1Code = url?.searchParams.get("level1Code");
  const level2Code = url?.searchParams.get("level2Code");
  const rows = levelRows(scope);
  const selected = rows.some((row) => row.sectorCode === selectedSectorCode) ? selectedSectorCode : rows[0].sectorCode;
  const selectedRow = rows.find((row) => row.sectorCode === selected)!;
  const groupInterpretation = rows.filter((row) => row.percentile !== null).length < 3 ? "SAMPLE_INSUFFICIENT" : "QUADRANT";
  if (groupInterpretation === "SAMPLE_INSUFFICIENT") rows.forEach((row) => { if (row.coordinateStatus === "PLOTTABLE") row.rotationStatus = "SAMPLE_INSUFFICIENT"; });
  const points = [trail("2026-08-26", selectedRow, selectedRow.percentileDelta5d === null ? null : selectedRow.percentileDelta5d - 1), trail("2026-08-27", selectedRow, selectedRow.percentileDelta5d)];
  const counts = groupInterpretation === "SAMPLE_INSUFFICIENT" ? [0, 0, 0, 0] : [
    rows.filter((row) => row.rotationStatus === "LEADING_IMPROVING").length,
    rows.filter((row) => row.rotationStatus === "WEAK_IMPROVING").length,
    rows.filter((row) => row.rotationStatus === "STRONG_NOT_IMPROVING").length,
    rows.filter((row) => row.rotationStatus === "WEAK_NOT_IMPROVING").length,
  ];
  return {
    status: "READY", tradingDay: tradingDay(), pageStatus: pageStatus(), message: null, exceptionCode: null, debugInfo: null,
    analysis: {
      formulaKey: "sector-relative-rotation", formulaVersion: 1, basisFormulaKey: "sector-cross-sectional-momentum", basisFormulaVersion: 1,
      hierarchyVersion: url?.searchParams.get("hierarchyVersion") ?? "dc-industry-v1", scope, period, improvementLookbackDays: 5, trailLength, minimumGroupSize: 3,
      parentSelection: { level1Code: scope === "LEVEL_1_CHILDREN" || scope === "LEVEL_2_CHILDREN" ? level1Code : null, level1Name: scope === "LEVEL_1_CHILDREN" || scope === "LEVEL_2_CHILDREN" ? "电子" : null, level2Code: scope === "LEVEL_2_CHILDREN" ? level2Code : null, level2Name: scope === "LEVEL_2_CHILDREN" ? "电子设备" : null },
      selectedSectorCode: selected, groupInterpretation, totalCount: rows.length,
      currentCalculableCount: rows.filter((row) => row.percentile !== null).length, plottableCount: rows.filter((row) => row.coordinateStatus === "PLOTTABLE").length, missingCoordinateCount: rows.filter((row) => row.coordinateStatus !== "PLOTTABLE").length,
      quadrantCounts: { leadingImproving: counts[0], weakImproving: counts[1], strongNotImproving: counts[2], weakNotImproving: counts[3] }, items: rows,
      selectedTrail: { sectorCode: selected, requestedLength: trailLength, dateSlotCount: points.length, points },
    },
  };
}

export function relativeContextPayload(tradeDate = "2026-08-27") { return { pageContext: { market: "CN_A", tradeDate, prevTradeDate: "2026-08-26", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai", generatedAt: "2026-08-28T09:15:00+08:00", source: "explicit" } }; }
export function relativeMajorIndicesPayload() { return { tradingDay: { tradeDate: "2026-08-27", market: "CN_A", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai" }, pageStatus: { status: "READY", displayText: "已就绪" }, majorIndices: { definition: { definitionKey: "major", version: "1", fixedCount: 10 }, rows: [] } }; }

function levelRows(scope: string): any[] {
  if (scope === "LEVEL_2" || scope === "LEVEL_1_CHILDREN") return [rotationRow("BK1101.DC", "电子设备", 2, "BK1001.DC", 2.5, 1, 100, 4, "LEADING_IMPROVING", true), rotationRow("BK1102.DC", "通信设备", 2, "BK1002.DC", 1.5, 2, 0, -1, "WEAK_NOT_IMPROVING", true)];
  if (scope === "LEVEL_3" || scope === "LEVEL_2_CHILDREN") return [rotationRow("BK1201.DC", "通信网络设备及器件", 3, "BK1101.DC", 1.8, 1, 100, 3, "LEADING_IMPROVING", false), rotationRow("BK1202.DC", "通信线缆及配套", 3, "BK1101.DC", 0.8, 2, 0, -2, "WEAK_NOT_IMPROVING", false)];
  return [
    rotationRow("BK1001.DC", "电子", 1, null, 3.97, 1, 100, 10, "LEADING_IMPROVING", true),
    rotationRow("BK1002.DC", "通信", 1, null, 2.1, 2, 66.7, -2, "STRONG_NOT_IMPROVING", true),
    rotationRow("BK1003.DC", "煤炭", 1, null, -0.5, 3, 33.3, 5, "WEAK_IMPROVING", true),
    { sectorCode: "BK1004.DC", sectorName: "房地产", industryLevel: 1, parentSectorCode: null, parentSectorName: null, hierarchyPath: "房地产", canDrillDown: true, returnPct: null, strengthRank: null, percentile: null, percentileDelta5d: null, rotationStatus: "DATA_INSUFFICIENT", coordinateStatus: "UNAVAILABLE", currentMissingReason: "HISTORY_INSUFFICIENT", comparisonMissingReason: null },
  ];
}
function rotationRow(sectorCode: string, sectorName: string, industryLevel: number, parentSectorCode: string | null, returnPct: number, strengthRank: number, percentile: number, percentileDelta5d: number, rotationStatus: string, canDrillDown: boolean) { return { sectorCode, sectorName, industryLevel, parentSectorCode, parentSectorName: hierarchyName(parentSectorCode), hierarchyPath: sectorName, canDrillDown, returnPct, strengthRank, percentile, percentileDelta5d, rotationStatus, coordinateStatus: "PLOTTABLE", currentMissingReason: null, comparisonMissingReason: null }; }
function trail(tradeDate: string, row: any, delta: number | null) { if (row.percentile === null) return { tradeDate, returnPct: null, percentile: null, percentileDelta5d: null, rotationStatus: "DATA_INSUFFICIENT", coordinateStatus: "UNAVAILABLE", currentMissingReason: "HISTORY_INSUFFICIENT", comparisonMissingReason: null }; if (delta === null) return { tradeDate, returnPct: row.returnPct, percentile: row.percentile, percentileDelta5d: null, rotationStatus: "DATA_INSUFFICIENT", coordinateStatus: "UNAVAILABLE", currentMissingReason: null, comparisonMissingReason: "DATE_MISSING" }; const rotationStatus = row.rotationStatus === "SAMPLE_INSUFFICIENT" ? "SAMPLE_INSUFFICIENT" : expectedStatus(row.percentile, delta); return { tradeDate, returnPct: row.returnPct, percentile: row.percentile, percentileDelta5d: delta, rotationStatus, coordinateStatus: "PLOTTABLE", currentMissingReason: null, comparisonMissingReason: null }; }
function expectedStatus(percentile: number, delta: number) { if (percentile >= 50 && delta > 0) return "LEADING_IMPROVING"; if (percentile < 50 && delta > 0) return "WEAK_IMPROVING"; if (percentile >= 50) return "STRONG_NOT_IMPROVING"; return "WEAK_NOT_IMPROVING"; }
function hierarchyNodes() { return [node("BK1001.DC", "电子", 1, null, "BK1001.DC", false), node("BK1002.DC", "通信", 1, null, "BK1002.DC", false), node("BK1003.DC", "煤炭", 1, null, "BK1003.DC", false), node("BK1004.DC", "房地产", 1, null, "BK1004.DC", false), node("BK1101.DC", "电子设备", 2, "BK1001.DC", "BK1001.DC", false), node("BK1102.DC", "通信设备", 2, "BK1002.DC", "BK1002.DC", false), node("BK1201.DC", "通信网络设备及器件", 3, "BK1101.DC", "BK1001.DC", true), node("BK1202.DC", "通信线缆及配套", 3, "BK1101.DC", "BK1001.DC", true)]; }
function node(sectorCode: string, sectorName: string, industryLevel: number, parentSectorCode: string | null, rootSectorCode: string, isLeaf: boolean) { const parentSectorName = hierarchyName(parentSectorCode); const rootSectorName = hierarchyName(rootSectorCode) ?? sectorName; return { sectorCode, sectorName, industryLevel, parentSectorCode, parentSectorName, rootSectorCode, rootSectorName, hierarchyPath: parentSectorName ? `${rootSectorName} > ${parentSectorName} > ${sectorName}`.replace(` > ${rootSectorName} >`, " >") : sectorName, displayOrder: Number(sectorCode.slice(2, 6)), isLeaf }; }
function hierarchyName(code: string | null) { return { "BK1001.DC": "电子", "BK1002.DC": "通信", "BK1003.DC": "煤炭", "BK1004.DC": "房地产", "BK1101.DC": "电子设备", "BK1102.DC": "通信设备" }[code ?? ""] ?? null; }
function tradingDay() { return { expectedTradeDate: "2026-08-27", observedTradeDate: "2026-08-27", expectedAvailability: "COMPLETE", expectedSectorCount: 4, expectedValidSectorCount: 4, observedAvailability: "COMPLETE", observedValidSectorCount: 4 }; }
function pageStatus() { return { status: "READY", displayText: "2026-08-27 盘后数据", asOfTime: "2026-08-27T20:31:00+08:00" }; }
