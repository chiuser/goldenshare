import type { HoldingContributions, PositionsAnalysis, PositionsResponse } from "../api/generatedContracts";
import { fixedUnits, geometryFraction, positionNumber as number, positionPercent as percent, profitTone } from "./positionPresentation";

export function contributionPresentation(value: HoldingContributions, daily: boolean) {
  const known = value.positiveCount + value.negativeCount + value.flatCount;
  const incomplete = value.unknownCount > 0;
  const names = daily ? ["上涨贡献", "下跌贡献"] : ["盈利", "亏损"];
  const extreme = (side: "maxPositive" | "maxNegative") => {
    const item = value[side];
    return { name: item ? `${item.stockRef.name} · ${item.stockRef.tsCode}` : incomplete ? "待计算" : "暂无",
      amount: item ? number(item.profitAmount, true) : "—", tone: profitTone(item?.profitAmount ?? null) };
  };
  return {
    positive: extreme("maxPositive"), negative: extreme("maxNegative"), reason: value.reason,
    structure: `${incomplete ? "已知部分：" : ""}${names[0]} ${value.positiveCount} 只 · ${names[1]} ${value.negativeCount} 只 · 持平 ${value.flatCount} 只${incomplete ? ` · 待计算 ${value.unknownCount} 只` : ""}`,
    positiveTotal: number(incomplete && !known ? null : value.positiveAmount, true),
    negativeTotal: number(incomplete && !known ? null : value.negativeAmount, true),
    totalLabel: incomplete ? "已知部分" : "",
  };
}

export function holdingAnalysisPresentation(data: PositionsAnalysis, parent: PositionsResponse) {
  const dates = [...new Set(parent.items.map(row => row.valuationDate).filter(Boolean))].sort();
  const datesText = dates.length ? dates.join(" / ") : "估值日期待确认";
  const status = { Ready: "数据完整", Empty: "暂无持仓", Partial: "部分数据", Delayed: "数据延迟", Error: "结果不可用", Recalculating: "重算中" }[data.coverage.dataStatus];
  const max = data.industries.reduce((largest, row) => row.weightPct === null ? largest :
    fixedUnits(row.weightPct) > largest ? fixedUnits(row.weightPct) : largest, 0n);
  return {
    basis: `${data.scope.accounts.map(account => account.name).join("、") || "暂无账户"} · ${datesText} · ${status} · 仅分析当前持仓；现金只参与总资产占比`,
    stockValue: number(parent.summary.stockMarketValue),
    metrics: [
      { title: "最大单股占比", value: percent(data.largestPosition?.weightPct ?? null), note: data.largestPosition?.stockRef.name ?? "—" },
      { title: "前3持仓占比", value: percent(data.top3WeightPct), note: "按持仓市值排名" },
      { title: "前5持仓占比", value: percent(data.top5WeightPct), note: "不含现金" },
      { title: "现金占总资产", value: percent(data.cashWeightPct), note: number(data.cashAmount) },
    ],
    industries: data.industries.map(row => ({ key: row.industryCode ?? "UNCLASSIFIED", name: row.industryName,
      money: number(row.marketValue), percentage: percent(row.weightPct), classified: row.classificationStatus === "CLASSIFIED",
      width: row.weightPct === null ? null : geometryFraction(fixedUnits(row.weightPct), max) * 100 })),
  };
}
