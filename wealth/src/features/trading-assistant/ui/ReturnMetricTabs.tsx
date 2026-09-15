import type { ReturnMetric } from "../model/returnSelection";
export function ReturnMetricTabs({ value, onChange }: { value: ReturnMetric; onChange: (value: ReturnMetric) => void }) {
  return <div className="ta-return-metric-tabs" role="group" aria-label="收益指标">{(["AMOUNT", "RATE"] as const).map(metric =>
    <button key={metric} type="button" aria-pressed={value === metric} onClick={() => onChange(metric)}>{metric === "AMOUNT" ? "收益金额" : "收益率"}</button>)}</div>;
}
