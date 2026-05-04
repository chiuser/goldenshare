import type { LayerSummary } from "../types";

export function layerDisplayName(layer: LayerSummary): string {
  const labels: Record<string, string> = {
    raw_tushare: "原始数据",
    manifest: "同步用清单",
    derived: "本地计算结果",
    research: "查询优化数据",
  };
  return labels[layer.layer] ?? layer.layer_name;
}

export function layerInitial(layer: LayerSummary): string {
  const labels: Record<string, string> = {
    raw_tushare: "R",
    manifest: "M",
    derived: "D",
    research: "Q",
  };
  return labels[layer.layer] ?? layer.layer.slice(0, 1).toUpperCase();
}

export function humanizeLayerPurpose(layer: LayerSummary): string {
  const descriptions: Record<string, string> = {
    raw_tushare: "从 Tushare 拉取后直接保存的数据。",
    manifest: "给同步任务使用的本地清单，例如股票池、指数池或交易日历。",
    derived: "由本地已有数据计算出来的结果。",
    research: "为了让本地研究和回测查询更快而重新整理的数据。",
  };
  return descriptions[layer.layer] ?? cleanTechnicalCopy(layer.purpose);
}

export function humanizeLayerUsage(layer: LayerSummary): string {
  if (layer.layer === "raw_tushare") {
    return "适合查看原始落盘范围，也可以作为后续计算的数据来源。";
  }
  if (layer.layer === "manifest") {
    return "适合确认同步任务会使用哪些标的、日期或基础清单。";
  }
  if (layer.layer === "derived") {
    return "适合查看本地派生周期或计算结果是否已经生成。";
  }
  if (layer.layer === "research") {
    return "适合单标的长周期查询、回测和相似性分析。";
  }
  return cleanTechnicalCopy(layer.recommended_usage);
}

function cleanTechnicalCopy(value: string): string {
  return value
    .replaceAll("源站事实层", "原始数据")
    .replaceAll("源站事实", "原始数据")
    .replaceAll("执行辅助清单层", "同步用清单")
    .replaceAll("本地派生层", "本地计算结果")
    .replaceAll("研究查询优化层", "查询优化数据")
    .replaceAll("原始落盘层", "直接保存的数据");
}
