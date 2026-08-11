import type { IndexDetailKlineResponseDto, IndexDetailPageInitResponseDto } from "../api/indexDetailApiTypes";
import { buildBasicMetrics } from "../api/indexDetailViewModelAdapter";
import { INDEX_PERIOD_OPTIONS } from "./indexDetailConstants";
import type { IndexDataPagePhase, IndexDetailViewModel, IndexPeriodOption } from "./indexDetailTypes";

const INDEX_NAMES: Record<string, string> = {
  "000001.SH": "上证指数",
  "399001.SZ": "深证成指",
  "399006.SZ": "创业板指",
  "000688.SH": "科创50",
  "000300.SH": "沪深300",
  "000905.SH": "中证500",
  "000852.SH": "中证1000",
  "899050.BJ": "北证50",
  "000510.SH": "中证A500",
  "000016.SH": "上证50",
};

export function normalizeIndexTsCode(tsCode: string): string {
  return tsCode.trim().toUpperCase();
}

export function getIndexShellIdentity(tsCode: string): IndexDetailViewModel["identity"] {
  const normalized = normalizeIndexTsCode(tsCode);
  return {
    tsCode: normalized,
    name: INDEX_NAMES[normalized] ?? "指数详情",
    market: null,
    category: null,
    publisher: null,
    tags: [],
  };
}

export function getIndexShellPeriods(): IndexPeriodOption[] {
  return INDEX_PERIOD_OPTIONS.map((period) => ({ ...period, supported: period.key === "day" }));
}

export function resolveIndexDataPagePhase(
  pageInit: IndexDetailPageInitResponseDto,
  kline: IndexDetailKlineResponseDto,
): IndexDataPagePhase {
  if (pageInit.dataStatus.status === "PARTIAL" || kline.dataStatus.status === "PARTIAL") return "partial";
  if (pageInit.dataStatus.status === "DELAYED" || kline.dataStatus.status === "DELAYED") return "delayed";
  return "ready";
}

export function collectIndexPartialReasons(
  pageInit: IndexDetailPageInitResponseDto,
  kline: IndexDetailKlineResponseDto,
): string[] {
  const reasons = buildBasicMetrics(pageInit)
    .filter((metric) => metric.value === "--")
    .map((metric) => metric.label);

  if (pageInit.constituentBreadth && pageInit.constituentBreadth.missingCount > 0) {
    reasons.push(`成分涨跌统计（缺少 ${pageInit.constituentBreadth.missingCount} 个成分行情）`);
  }
  if (kline.dataStatus.status === "PARTIAL") reasons.push("部分日线技术指标");
  if (reasons.length === 0 && pageInit.dataStatus.status === "PARTIAL") reasons.push("部分基本行情");
  return [...new Set(reasons)];
}
