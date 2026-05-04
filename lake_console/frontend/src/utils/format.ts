import type { DatasetSummary, LayerSummary } from "../types";

export function formatBytes(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

export function formatRange(start: string | null, end: string | null): string {
  if (!start && !end) {
    return "-";
  }
  if (start === end) {
    return start ?? "-";
  }
  return `${start ?? "-"} ~ ${end ?? "-"}`;
}

export function formatDateOrMonthRange(dataset: DatasetSummary): string {
  const dateRange = formatRange(dataset.earliest_trade_date, dataset.latest_trade_date);
  if (dateRange !== "-") {
    return dateRange;
  }
  return formatRange(dataset.earliest_trade_month, dataset.latest_trade_month);
}

export function formatLayerDateOrMonthRange(layer: LayerSummary): string {
  const dateRange = formatRange(layer.earliest_trade_date, layer.latest_trade_date);
  if (dateRange !== "-") {
    return dateRange;
  }
  return formatRange(layer.earliest_trade_month, layer.latest_trade_month);
}

export function formatRowCount(value: number | null): string {
  return value === null ? "未计算" : value.toLocaleString("zh-CN");
}

export function formatDateTime(value: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}
